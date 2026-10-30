import io
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
import httpx
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

from minio_storage import minio_storage
from nllb_translator import translate_sop_sections_from_english
from skill_manager import skill_manager
from sop_evaluator import (
    LLMServiceError,
    evaluate_sop_with_llm,
    format_llm_unavailable_message,
)
from kenvue_guidelines import (
    enforce_kenvue_template_standards,
    compare_sop_evaluations,
    audit_sop_deterministically,
)
from validation_agent import validation_agent, generate_japanese_sop_title

logger = logging.getLogger(__name__)

# Register built-in Unicode CID Fonts for Japanese, Chinese, and Korean (CJK)
try:
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiMin-W3'))
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    pdfmetrics.registerFont(UnicodeCIDFont('HYSMyeongJo-Medium'))
    pdfmetrics.registerFontFamily(
        'HeiseiKakuGo-W5',
        normal='HeiseiKakuGo-W5',
        bold='HeiseiKakuGo-W5',
        italic='HeiseiMin-W3',
        boldItalic='HeiseiKakuGo-W5',
    )
    pdfmetrics.registerFontFamily(
        'STSong-Light',
        normal='STSong-Light',
        bold='STSong-Light',
        italic='STSong-Light',
        boldItalic='STSong-Light',
    )
    pdfmetrics.registerFontFamily(
        'HYSMyeongJo-Medium',
        normal='HYSMyeongJo-Medium',
        bold='HYSMyeongJo-Medium',
        italic='HYSMyeongJo-Medium',
        boldItalic='HYSMyeongJo-Medium',
    )
except Exception as e:
    logger.warning("Could not register CJK Unicode CID fonts: %s", e)


def contains_cjk(text: str) -> bool:
    """Checks if text contains Japanese (Hiragana/Katakana/Kanji), Chinese, or Korean Unicode characters."""
    if not text:
        return False
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af]", text))


def select_pdf_fonts(text: str, output_language: str = "English") -> Tuple[str, str, str]:
    """
    Selects the appropriate ReportLab font family (bold, regular, oblique) based on
    output_language and character script so Japanese, Chinese, Korean, and Latin
    scripts all render cleanly without black-box missing glyphs.
    """
    lang_norm = (output_language or "").strip().lower()
    has_hangul = bool(re.search(r"[\uac00-\ud7af]", text or ""))
    has_kana = bool(re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text or ""))
    has_han = bool(re.search(r"[\u4e00-\u9fff]", text or ""))

    if "korean" in lang_norm or lang_norm == "kor_hang" or has_hangul:
        return ("HYSMyeongJo-Medium", "HYSMyeongJo-Medium", "HYSMyeongJo-Medium")
    if "chinese" in lang_norm or lang_norm.startswith("zho_") or (has_han and not has_kana and "japanese" not in lang_norm):
        return ("STSong-Light", "STSong-Light", "STSong-Light")
    if "japanese" in lang_norm or lang_norm == "jpn_jpan" or has_kana or has_han:
        return ("HeiseiKakuGo-W5", "HeiseiKakuGo-W5", "HeiseiMin-W3")
    return ("Helvetica-Bold", "Helvetica", "Helvetica-Oblique")

# =====================================================================
# REPORTLAB SOP GENERATOR & ASSET RE-INTEGRATION
# Generates a clean, professional Kenvue-standard PDF incorporating all
# checked suggestions, custom instructions, and re-inserting original
# images and tables from MinIO as-is into their original positions.
# =====================================================================


def sanitize_reportlab_text(text: str) -> str:
    """
    Cleans and normalizes text for ReportLab Platypus Paragraphs.
    Eliminates missing glyphs that render as black boxes (em-dashes, narrow spaces,
    unsupported Unicode bullets, emojis, smart quotes) and ensures safe XML escaping
    for &, <, and > without stripping mathematical inequalities (e.g., < 25°C, > 7.0).
    Idempotent when called multiple times.
    """
    if not text:
        return ""

    # Unescape basic XML entities first so repeated calls are 100% idempotent
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )

    # Normalize fullwidth CJK Celsius / symbols
    text = text.replace("℃", "°C").replace("℉", "°F")

    # Replace narrow spaces, zero-width spaces, non-breaking spaces with standard space
    text = re.sub(r"[\u202f\u00a0\u200b\u200e\u200f\ufeff\ufe00-\ufe0f]", " ", text)

    # Replace em-dashes and en-dashes with safe ASCII hyphens
    text = text.replace("—", " - ").replace("–", "-").replace("―", " - ").replace("−", "-")

    # Normalize Unicode bullets, squares, checkboxes to safe ASCII hyphens/brackets
    text = text.replace("•", "- ").replace("▪", "- ").replace("▫", "- ")
    text = text.replace("&bull;", "- ")
    text = text.replace("■", "- ").replace("□", "[ ]").replace("☑", "[x]").replace("✔", "[x]")

    # Normalize smart quotes and apostrophes
    text = text.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    text = text.replace("…", "...")

    # Normalize non-standard citation brackets
    text = text.replace("【", "[").replace("】", "]")

    # Normalize math comparison symbols to prevent unmapped font glyphs
    text = text.replace("≤", "<=").replace("≥", ">=")

    # Remove emojis (which Helvetica cannot render and draws as black boxes)
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"[\u2600-\u26ff\u2700-\u27bf]", "", text)

    # Replace <br> or <br/> with standard space
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)

    # Strip only genuine HTML tags (e.g., <b>, </div>, <span class="...">) while preserving "< 25°C"
    text = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*\b[^>]*>", "", text)

    # Escape XML special characters (&, <, >) for ReportLab Paragraph parser
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Clean multiple spaces while preserving newlines
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def format_paragraph_for_reportlab(text: str) -> str:
    """
    Sanitizes and safely formats a paragraph for ReportLab Platypus Paragraph.
    Strips inline [IMAGE_ARTIFACT: ...] / [TABLE_ARTIFACT: ...] markers (since assets
    are embedded as flowables) and formats line breaks as <br/>.
    """
    if not text:
        return ""
    stripped_tags = re.sub(r"\[(?:IMAGE|TABLE)_ARTIFACT:[^\]]+\]", "", text)
    cleaned = sanitize_reportlab_text(stripped_tags)
    if not cleaned:
        return ""
    # Normalize bullet prefix
    lines = cleaned.split("\n")
    formatted_lines = []
    for l in lines:
        l_str = l.strip()
        if not l_str:
            continue
        if l_str.startswith(("- ", "* ")):
            l_str = "- " + l_str[2:].strip()
        formatted_lines.append(l_str)
    return "<br/>".join(formatted_lines)


def is_markdown_table_separator(cells: List[str]) -> bool:
    """Checks if a row consists purely of Markdown table column separator delimiters."""
    if not cells:
        return False
    return all(re.match(r"^:?-{2,}:?$", c.strip()) for c in cells if c.strip())


def parse_markdown_table_lines(lines: List[str]) -> Optional[Dict[str, Any]]:
    """
    Parses consecutive pipe-delimited lines into a structured dictionary with
    'header' (List[str]) and 'rows' (List[List[str]]), safely handling optional
    separator rows, missing cells, and varied column counts.
    """
    raw_rows = []
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("|"):
            line_str = line_str[1:]
        if line_str.endswith("|"):
            line_str = line_str[:-1]
        cells = [c.strip() for c in line_str.split("|")]
        raw_rows.append(cells)

    if len(raw_rows) < 2:
        return None

    if len(raw_rows) >= 2 and is_markdown_table_separator(raw_rows[1]):
        header = raw_rows[0]
        data_rows = raw_rows[2:]
    else:
        header = raw_rows[0]
        data_rows = raw_rows[1:]

    num_cols = len(header)
    if num_cols == 0:
        return None

    normalized_data_rows = []
    for row in data_rows:
        if len(row) < num_cols:
            row = row + [""] * (num_cols - len(row))
        elif len(row) > num_cols:
            row = row[: num_cols - 1] + [" | ".join(row[num_cols - 1 :])]
        normalized_data_rows.append(row)

    return {"header": header, "rows": normalized_data_rows}


def split_content_into_flowable_blocks(content: str) -> List[Dict[str, Any]]:
    """
    Splits section content into alternating blocks of normal prose and structured markdown tables.
    Ensures that tables in Section 3.0 (Key Terms), Section 4.0 (Roles and Responsibilities),
    Section 6.0 (Process Flow), or any other section are rendered as native ReportLab Tables.
    """
    if not content:
        return []

    lines = content.split("\n")
    blocks = []
    current_prose_lines = []
    current_table_lines = []

    def flush_prose():
        if current_prose_lines:
            text = "\n".join(current_prose_lines).strip()
            if text:
                blocks.append({"type": "prose", "text": text})
            current_prose_lines.clear()

    def flush_table():
        if current_table_lines:
            tbl = parse_markdown_table_lines(current_table_lines)
            if tbl and (tbl["header"] or tbl["rows"]):
                blocks.append({"type": "table", "header": tbl["header"], "rows": tbl["rows"]})
            else:
                fallback_text = "\n".join(current_table_lines).strip()
                if fallback_text:
                    blocks.append({"type": "prose", "text": fallback_text})
            current_table_lines.clear()

    for i, line in enumerate(lines):
        line_str = line.strip()
        has_pipes = "|" in line_str and len([c for c in line_str.strip("|").split("|") if c.strip()]) >= 1
        is_pipe_line = line_str.startswith("|") or (
            has_pipes and ("---" in line_str or (i + 1 < len(lines) and "|" in lines[i + 1]))
        )

        if is_pipe_line:
            flush_prose()
            current_table_lines.append(line)
        else:
            flush_table()
            current_prose_lines.append(line)

    flush_table()
    flush_prose()
    return blocks


def build_reportlab_table_flowable(
    tbl_data: Dict[str, Any],
    output_language: str,
    doc_font_bold: str,
    doc_font_regular: str,
) -> Table:
    """
    Transforms a structured Markdown table block into an authoritative, publication-quality
    ReportLab Platypus Table flowable matching Kenvue corporate QMS styling.
    """
    header = tbl_data["header"]
    rows = tbl_data["rows"]
    num_cols = max(len(header), 1)

    # Total available width between 40pt margins on A4 is 515pt
    if num_cols == 1:
        col_widths = [515]
    elif num_cols == 2:
        # Standard ratio for Key Terms (Term | Definition) and Roles & Responsibilities (Role | Responsibilities)
        col_widths = [140, 375]
    elif num_cols == 3:
        first_h = header[0].lower() if header else ""
        if any(k in first_h for k in ["step", "no", "#", "item", "seq"]):
            col_widths = [55, 230, 230]
        else:
            col_widths = [125, 195, 195]
    elif num_cols == 4:
        first_h = header[0].lower() if header else ""
        if any(k in first_h for k in ["version", "rev", "step", "no", "#"]):
            col_widths = [65, 230, 80, 140]
        else:
            col_widths = [128.75, 128.75, 128.75, 128.75]
    else:
        w = 515.0 / num_cols
        col_widths = [w] * num_cols

    all_table_text = " ".join(header) + " " + " ".join([" ".join(r) for r in rows])
    tbl_font_b, tbl_font_r, _ = select_pdf_fonts(all_table_text, output_language)
    has_cjk = contains_cjk(all_table_text)
    hdr_font = tbl_font_b if has_cjk else doc_font_bold
    body_font = tbl_font_r if has_cjk else doc_font_regular

    th_style = ParagraphStyle(
        "KenvueTableHdr",
        fontName=hdr_font,
        fontSize=9,
        leading=12,
        textColor=colors.white,
    )
    td_style = ParagraphStyle(
        "KenvueTableTd",
        fontName=body_font,
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#1e293b"),
    )

    def clean_cell_text(raw_text: str) -> str:
        stripped = re.sub(r"\[(?:IMAGE|TABLE)_ARTIFACT:[^\]]+\]", "", raw_text)
        cleaned = sanitize_reportlab_text(stripped)
        cleaned = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", cleaned)
        cleaned = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", cleaned)
        cleaned = cleaned.replace("\n", "<br/>")
        return cleaned

    table_matrix = []
    # Header row
    hdr_row = [Paragraph(f"<b>{clean_cell_text(h)}</b>", th_style) for h in header]
    table_matrix.append(hdr_row)

    # Data rows
    for r in rows:
        row_cells = [Paragraph(clean_cell_text(cell), td_style) for cell in r]
        table_matrix.append(row_cells)

    table_style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),  # Kenvue navy
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),  # Light slate border
    ]

    for r_idx in range(1, len(table_matrix)):
        if r_idx % 2 == 0:
            table_style_commands.append(
                ("BACKGROUND", (0, r_idx), (-1, r_idx), colors.HexColor("#f8fafc"))
            )

    rl_table = Table(table_matrix, colWidths=col_widths, repeatRows=1)
    rl_table.setStyle(TableStyle(table_style_commands))
    return rl_table


def chunk_oversized_text(text: str, max_chars: int = 600) -> List[str]:
    """
    Safely splits an excessively long paragraph into smaller sentence-level chunks
    so that no single ReportLab Table row can ever exceed the page frame height.
    """
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current_chunk = []
    current_len = 0
    for s in sentences:
        if current_len + len(s) > max_chars and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [s]
            current_len = len(s)
        else:
            current_chunk.append(s)
            current_len += len(s)
    if current_chunk:
        chunks.append(" ".join(current_chunk))
    return chunks


def render_safety_callout_flowables(
    content: str,
    output_language: str,
    callout_style: ParagraphStyle,
    doc_font_bold: str,
    doc_font_regular: str,
) -> List[Any]:
    """
    Renders safety and PPE precautions as a multi-row, page-splittable callout table.
    Guarantees that long safety sections (even 1000+ points) never crash ReportLab with
    overflow errors by enabling natural page breaks between rows.
    """
    blocks = split_content_into_flowable_blocks(content)
    flowables = []

    all_text = " ".join([b.get("text", "") for b in blocks if b["type"] == "prose"])
    tbl_b, tbl_r, _ = select_pdf_fonts(all_text, output_language)
    has_cjk = contains_cjk(all_text)
    hdr_font = tbl_b if has_cjk else doc_font_bold
    body_font = tbl_r if has_cjk else doc_font_regular

    hdr_style = ParagraphStyle(
        "SafetyCalloutHdr",
        parent=callout_style,
        fontName=hdr_font,
        fontSize=9.5,
        leading=13,
        textColor=colors.white,
    )
    row_style = ParagraphStyle(
        "SafetyCalloutRow",
        parent=callout_style,
        fontName=body_font,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#991b1b"),
    )

    for b in blocks:
        if b["type"] == "table":
            tbl = build_reportlab_table_flowable(b, output_language, hdr_font, body_font)
            flowables.append(tbl)
            flowables.append(Spacer(1, 8))
        else:
            prose_text = b["text"]
            raw_paragraphs = [p.strip() for p in prose_text.split("\n\n") if p.strip()]
            if not raw_paragraphs:
                raw_paragraphs = [p.strip() for p in prose_text.split("\n") if p.strip()]

            if not raw_paragraphs:
                continue

            callout_rows = []
            callout_rows.append([Paragraph("<b>[MANDATORY SAFETY &amp; PPE NOTICE]</b>", hdr_style)])

            for p in raw_paragraphs:
                stripped_p = re.sub(r"\[(?:IMAGE|TABLE)_ARTIFACT:[^\]]+\]", "", p)
                cleaned_p = sanitize_reportlab_text(stripped_p)
                cleaned_p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", cleaned_p)
                cleaned_p = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<i>\1</i>", cleaned_p)
                cleaned_p = cleaned_p.replace("\n", "<br/>")
                chunks = chunk_oversized_text(cleaned_p, max_chars=600)
                for chunk in chunks:
                    callout_rows.append([Paragraph(chunk, row_style)])

            table_style_commands = [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dc2626")),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#fef2f2")),
                ("BOX", (0, 0), (-1, -1), 1.2, colors.HexColor("#ef4444")),
                ("INNERGRID", (0, 1), (-1, -1), 0.5, colors.HexColor("#fee2e2")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
            callout_tbl = Table(callout_rows, colWidths=[515], repeatRows=1)
            callout_tbl.setStyle(TableStyle(table_style_commands))
            flowables.append(callout_tbl)
            flowables.append(Spacer(1, 10))

    return flowables


def assign_artifacts_to_sections(
    sections: List[Dict[str, Any]], artifacts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Intelligently maps every extracted image and table to its semantically
    correct Kenvue SOP section based on table contents, headers, captions,
    and original page context. Guarantees 100% asset preservation with
    proper contextual placement.
    """
    if not artifacts:
        return sections

    new_sections = [dict(s) for s in sections]
    for s in new_sections:
        existing = s.get("artifact_ids") or s.get("asset_ids") or []
        s["artifact_ids"] = list(existing)

    def classify_target_section(art: Dict[str, Any]) -> Tuple[str, str]:
        cap = (art.get("caption") or "").lower()
        md = (art.get("table_markdown") or "").lower()
        combined = f"{cap} {md}"
        page = art.get("page", 1)

        # 1. Revision History & Document Control
        if any(k in combined for k in ["version number", "description of change", "reason for change", "document id", "sop-ex-"]) or ("revision" in combined and "history" in combined):
            return ("9.0 Revision History & Document Control", "normal")

        # 2. Definitions & Terminology
        if ("term" in md and "definition" in md) or any(k in combined for k in ["glossary", "acronyms", "term definition", "terminology"]):
            return ("2.0 Scope, Applicability & Definitions", "normal")

        # 3. Roles & Responsibilities
        if ("role" in md and "responsibilit" in md) or "role responsibilities" in combined:
            return ("3.0 Roles & Responsibilities", "normal")

        # 4. Records & Retention / References
        if any(k in combined for k in ["retention", "retention period", "record minimum", "reference description", "applicable site"]):
            return ("8.0 Documentation, Records Retention & References", "normal")

        # 5. Checklists & Signoff Logsheets / Appendices
        if any(k in combined for k in ["quick check", "checklist", "field entry", "workstation id", "operator signature", "signoff", "sign-off"]):
            return ("10.0 Appendix: Operational Checklists & Logsheets", "normal")

        # 6. Quality Control & Acceptance Criteria
        if any(k in combined for k in ["acceptance criteria", "verification checkpoint", "step check", "tolerance", "inspection checkpoints", "parameter limits"]):
            return ("7.0 Quality Control, Inspection & Acceptance Standards", "normal")

        # 7. Equipment, Materials & Setup / Layout
        if any(k in combined for k in ["arrangement", "staging", "supply staging", "equipment", "materials available", "apparatus", "layout"]):
            return ("5.0 Equipment, Materials & Workstation Setup", "normal")

        # 8. Step-by-Step Procedure & Flowchart
        if any(k in combined for k in ["process flow", "flowchart", "sequence", "cleaning sequence", "procedure", "wipe technique"]):
            return ("6.0 Step-by-Step Operating Procedure", "normal")

        # 9. Safety & PPE
        if any(k in combined for k in ["safety", "ppe", "hazard", "chemical", "first aid", "sds"]):
            return ("4.0 Mandatory Safety, PPE & Hazard Controls", "safety")

        # Fallback by page context
        if page == 1:
            return ("9.0 Revision History & Document Control", "normal")
        elif page == 2:
            return ("2.0 Scope, Applicability & Definitions", "normal")
        elif page == 3:
            return ("5.0 Equipment, Materials & Workstation Setup", "normal")
        elif page == 4:
            return ("6.0 Step-by-Step Operating Procedure", "normal")
        elif page == 5:
            return ("8.0 Documentation, Records Retention & References", "normal")
        elif page >= 6:
            return ("10.0 Appendix: Operational Checklists & Logsheets", "normal")
        return ("6.0 Step-by-Step Operating Procedure", "normal")

    def find_matching_section(target_title: str) -> Optional[Dict[str, Any]]:
        target_num = target_title.split()[0]
        target_keywords = [w.lower() for w in target_title.split()[1:] if len(w) > 3]
        for s in new_sections:
            if s.get("heading", "").startswith(target_num):
                return s
        for s in new_sections:
            h_lower = s.get("heading", "").lower()
            if any(kw in h_lower for kw in target_keywords):
                return s
        return None

    # Track already assigned artifacts to prevent duplication
    for art in artifacts:
        aid = art["id"]
        target_heading, sec_type = classify_target_section(art)

        # Remove aid if mistakenly placed in wrong section
        for s in new_sections:
            if aid in s["artifact_ids"]:
                h = s.get("heading", "")
                target_num = target_heading.split()[0]
                if not (target_num in h or any(kw in h.lower() for kw in target_heading.lower().split()[1:] if len(kw) > 3)):
                    s["artifact_ids"].remove(aid)

        # Place aid in rightful section
        is_already_placed = any(aid in s["artifact_ids"] for s in new_sections)
        if not is_already_placed:
            target_sec = find_matching_section(target_heading)
            if target_sec:
                if aid not in target_sec["artifact_ids"]:
                    target_sec["artifact_ids"].append(aid)
            else:
                default_content = f"Technical documentation and verified criteria for {target_heading}."
                if "10.0" in target_heading or "Appendix" in target_heading:
                    default_content = "The following operational checklist and completion logsheet forms must be executed and retained in the batch record:"
                elif "9.0" in target_heading:
                    default_content = "Document change history and controlled revision status:"

                new_sec = {
                    "heading": target_heading,
                    "content": default_content,
                    "type": sec_type,
                    "artifact_ids": [aid],
                }
                new_sections.append(new_sec)

    def section_sort_key(sec):
        h = sec.get("heading", "")
        m = re.match(r"^(\d+)(?:\.(\d+))?", h)
        if m:
            return (int(m.group(1)), int(m.group(2) or 0))
        return (99, 0)

    new_sections.sort(key=section_sort_key)
    return new_sections


def create_kenvue_pdf(
    title: str,
    sections: List[Dict[str, Any]],
    artifacts: List[Dict[str, Any]],
    output_stream: io.BytesIO,
    output_language: str = "English",
    review_required: bool = False,
):
    """
    Builds a professional Kenvue-standard PDF document using ReportLab Platypus.
    Embeds original images and tables fetched from MinIO as-is without black-box artifacts.
    Supports English, Japanese, Chinese, Korean, and European languages natively.
    """
    # Legacy assignment can manufacture checklist obligations. A gated draft
    # already carries explicit source artifact IDs and must not be mutated.
    if not review_required:
        sections = assign_artifacts_to_sections(sections, artifacts)

    doc = SimpleDocTemplate(
        output_stream,
        pagesize=A4,
        leftMargin=40,
        rightMargin=40,
        topMargin=45,
        bottomMargin=45,
    )

    styles = getSampleStyleSheet()

    # Check if document contains Japanese / Chinese / Korean / CJK text anywhere
    all_doc_text = (title or "") + " " + " ".join([s.get("heading", "") + " " + s.get("content", "") for s in sections])
    doc_font_bold, doc_font_regular, doc_font_oblique = select_pdf_fonts(all_doc_text, output_language)

    # Custom Typography matching Kenvue corporate guidelines
    header_style = ParagraphStyle(
        "KenvueTitle",
        parent=styles["Heading1"],
        fontName=doc_font_bold,
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "KenvueMeta",
        parent=styles["Normal"],
        fontName=doc_font_regular,
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
    )
    sec_heading_style = ParagraphStyle(
        "KenvueSecHeading",
        parent=styles["Heading2"],
        fontName=doc_font_bold,
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1e3a8a"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "KenvueBody",
        parent=styles["Normal"],
        fontName=doc_font_regular,
        fontSize=10,
        leading=14.5,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=6,
    )
    callout_style = ParagraphStyle(
        "KenvueCallout",
        parent=styles["Normal"],
        fontName=doc_font_regular,
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor("#991b1b"),
    )
    caption_style = ParagraphStyle(
        "KenvueCaption",
        parent=styles["Normal"],
        fontName=doc_font_oblique,
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#64748b"),
        alignment=1,  # Centered
        spaceAfter=8,
    )

    story = []

    # 1. Document Header Banner
    safe_title = sanitize_reportlab_text(title)
    safe_lang = sanitize_reportlab_text(output_language or "English")
    status_line = "DRAFT - AUTHOR REVIEW REQUIRED" if review_required else "GENERATED - APPROVAL NOT VERIFIED"
    meta_data = [
        [
            Paragraph(f"<b>{safe_title}</b>", header_style),
            Paragraph(f"<b>KENVUE OPERATIONAL STANDARD</b><br/>Status: {status_line} | Language: {safe_lang}<br/>Version: Generated draft", meta_style),
        ],
        [
            Paragraph("<b>Document ID:</b> Not verified from source", meta_style),
            Paragraph("<b>Approval:</b> Author confirmation required", meta_style),
        ],
    ]
    header_table = Table(meta_data, colWidths=[335, 180])
    header_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#cbd5e1")),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ])
    )
    story.append(header_table)
    story.append(Spacer(1, 12))

    # Pre-index artifacts by page/type for exact re-insertion
    artifact_map = {art["id"]: art for art in artifacts}
    placed_art_ids = set()
    source_table_blocks = [block for section in sections for block in split_content_into_flowable_blocks(section.get("content", ""))
                           if block["type"] == "table"] if review_required else []

    # 2. Render Formatted Sections
    for sec in sections:
        raw_heading = sec.get("heading", "")
        heading = sanitize_reportlab_text(raw_heading)
        content = sec.get("content", "")
        sec_type = sec.get("type", "normal")

        if heading:
            cjk_b, _, _ = select_pdf_fonts(heading, output_language)
            h_style = ParagraphStyle("SecHeadingCJK", parent=sec_heading_style, fontName=cjk_b) if contains_cjk(heading) else sec_heading_style
            story.append(Paragraph(heading, h_style))
            story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#cbd5e1"), spaceAfter=8))

        if sec_type == "safety" or "safety" in heading.lower() or "ppe" in heading.lower():
            # Styled Multi-row Callout Box for Safety & PPE Precautions (safely splits across pages)
            safety_flowables = render_safety_callout_flowables(
                content=content,
                output_language=output_language,
                callout_style=callout_style,
                doc_font_bold=doc_font_bold,
                doc_font_regular=doc_font_regular,
            )
            story.extend(safety_flowables)
        else:
            blocks = split_content_into_flowable_blocks(content)
            for b in blocks:
                if b["type"] == "table":
                    tbl_flowable = build_reportlab_table_flowable(
                        tbl_data=b,
                        output_language=output_language,
                        doc_font_bold=doc_font_bold,
                        doc_font_regular=doc_font_regular,
                    )
                    story.append(tbl_flowable)
                    story.append(Spacer(1, 10))
                    if review_required:
                        # An unchanged source table already rendered in the body
                        # also satisfies its artifact; do not render it twice.
                        for art in artifacts:
                            original_table = parse_markdown_table_lines((art.get("table_markdown") or "").splitlines())
                            parts = (art.get("table_data") or {}).get("source_parts", [])
                            all_parts_present = bool(parts) and all(any(
                                block["header"] == part["headers"] and block["rows"] == part["rows"]
                                for block in source_table_blocks) for part in parts)
                            current_part = any(b["header"] == part["headers"] and b["rows"] == part["rows"] for part in parts)
                            exact_table = original_table and original_table["header"] == b["header"] and original_table["rows"] == b["rows"]
                            if exact_table or (all_parts_present and current_part):
                                placed_art_ids.add(art["id"])
                                story.append(Paragraph("Source table: " + sanitize_reportlab_text(str(art["id"])) +
                                                       f" (Original Page {art.get('page')})", caption_style))
                else:
                    paragraphs = b["text"].split("\n\n")
                    for p in paragraphs:
                        p_clean = format_paragraph_for_reportlab(p)
                        if not p_clean:
                            continue
                        _, cjk_r, _ = select_pdf_fonts(p_clean, output_language)
                        p_style = ParagraphStyle("BodyCJK", parent=body_style, fontName=cjk_r) if contains_cjk(p_clean) else body_style
                        story.append(Paragraph(p_clean, p_style))

        # --- HERE ORIGINAL MINIO IMAGES & TABLES ARE RE-INSERTED AS-IS ---
        inline_art_ids = [
            m.strip()
            for m in re.findall(r"\[(?:IMAGE|TABLE)_ARTIFACT:\s*([^\]]+)\]", content)
            if m.strip()
        ]
        related_art_ids = list(dict.fromkeys(list(sec.get("artifact_ids", [])) + inline_art_ids))
        for art_id in related_art_ids:
            art = artifact_map.get(art_id)
            if not art or art_id in placed_art_ids:
                continue

            # Prioritize structured ReportLab Table flowable for table artifacts
            tbl_headers = art.get("headers")
            tbl_rows = art.get("rows")
            if not tbl_headers and isinstance(art.get("table_data"), dict):
                tbl_headers = art["table_data"].get("headers")
                tbl_rows = art["table_data"].get("rows")
            if not tbl_headers and art.get("table_markdown"):
                parsed_tbl = parse_markdown_table_lines(art["table_markdown"].split("\n"))
                if parsed_tbl:
                    tbl_headers = parsed_tbl.get("header")
                    tbl_rows = parsed_tbl.get("rows")
            is_table = art.get("artifact_type") == "table" or bool(tbl_headers and tbl_rows is not None)

            if is_table and tbl_headers and tbl_rows is not None:
                try:
                    story.append(Spacer(1, 8))
                    tbl_flowable = build_reportlab_table_flowable(
                        tbl_data={"header": tbl_headers, "rows": tbl_rows},
                        output_language=output_language,
                        doc_font_bold=doc_font_bold,
                        doc_font_regular=doc_font_regular,
                    )
                    t_name = art.get("table_name") or art.get("caption") or "Table"
                    safe_cap = sanitize_reportlab_text(t_name)
                    story.append(KeepTogether([
                        tbl_flowable,
                        Spacer(1, 4),
                        Paragraph(f"<b>{safe_cap}</b> (Original Page {art.get('page')})", caption_style),
                    ]))
                    story.append(Spacer(1, 8))
                    placed_art_ids.add(art_id)
                    continue
                except Exception as e:
                    logger.warning("Could not render structured table flowable for %s: %s; falling back to image", art_id, e)
            
            if not art.get("object_name"):
                continue
            raw_data, content_type = minio_storage.get_file_bytes(art["object_name"])
            if not raw_data:
                continue

            try:
                img_stream = io.BytesIO(raw_data)
                w = art.get("width") or 300
                h = art.get("height") or 200
                max_w, max_h = 460, 260
                scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
                disp_w = max(120, int(w * scale))
                disp_h = max(60, int(h * scale))

                story.append(Spacer(1, 8))
                rl_image = Image(img_stream, width=disp_w, height=disp_h)
                asset_label = "Figure" if art.get("artifact_type") == "image" else "Table"
                safe_cap = sanitize_reportlab_text(art.get("caption", f"{asset_label} Asset"))
                story.append(KeepTogether([
                    rl_image,
                    Spacer(1, 4),
                    Paragraph(f"<b>{safe_cap}</b> (Original Page {art.get('page')})", caption_style),
                ]))
                story.append(Spacer(1, 8))
                placed_art_ids.add(art_id)
            except Exception as e:
                logger.warning("Could not re-insert artifact %s: %s", art_id, e)

        story.append(Spacer(1, 8))

    # 3. Ensure NO artifact is missed: Append any remaining unplaced figures/tables
    unplaced_artifacts = [art for art in artifacts if art["id"] not in placed_art_ids]
    if unplaced_artifacts:
        story.append(Spacer(1, 14))
        story.append(Paragraph("Source Asset Review" if review_required else "10.0 Reference Figures, Diagrams & Data Tables (Original Assets)", sec_heading_style))
        story.append(HRFlowable(width="100%", thickness=0.8, color=colors.HexColor("#cbd5e1"), spaceAfter=8))
        story.append(Paragraph(
            "Original source assets require author verification. Unavailable assets are identified below." if review_required else
            "The following verified figures, process flowcharts, and technical data tables from the original SOP document have been preserved as-is in accordance with Kenvue document control requirements:",
            body_style,
        ))
        story.append(Spacer(1, 8))

        for art in unplaced_artifacts:
            # Check structured table first
            tbl_headers = art.get("headers")
            tbl_rows = art.get("rows")
            if not tbl_headers and isinstance(art.get("table_data"), dict):
                tbl_headers = art["table_data"].get("headers")
                tbl_rows = art["table_data"].get("rows")
            if not tbl_headers and art.get("table_markdown"):
                parsed_tbl = parse_markdown_table_lines(art["table_markdown"].split("\n"))
                if parsed_tbl:
                    tbl_headers = parsed_tbl.get("header")
                    tbl_rows = parsed_tbl.get("rows")
            is_table = art.get("artifact_type") == "table" or bool(tbl_headers and tbl_rows is not None)

            if is_table and tbl_headers and tbl_rows is not None:
                try:
                    story.append(Spacer(1, 8))
                    tbl_flowable = build_reportlab_table_flowable(
                        tbl_data={"header": tbl_headers, "rows": tbl_rows},
                        output_language=output_language,
                        doc_font_bold=doc_font_bold,
                        doc_font_regular=doc_font_regular,
                    )
                    t_name = art.get("table_name") or art.get("caption") or "Table"
                    safe_cap = sanitize_reportlab_text(t_name)
                    story.append(KeepTogether([
                        tbl_flowable,
                        Spacer(1, 4),
                        Paragraph(f"<b>{safe_cap}</b> (Original Page {art.get('page')})", caption_style),
                    ]))
                    story.append(Spacer(1, 10))
                    placed_art_ids.add(art["id"])
                    continue
                except Exception as e:
                    logger.warning("Could not render unplaced structured table flowable for %s: %s", art["id"], e)

            if not art.get("object_name"):
                continue
            raw_data, content_type = minio_storage.get_file_bytes(art["object_name"])
            if not raw_data:
                continue
            try:
                img_stream = io.BytesIO(raw_data)
                w = art.get("width") or 300
                h = art.get("height") or 200
                max_w, max_h = 460, 260
                scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
                disp_w = max(120, int(w * scale))
                disp_h = max(60, int(h * scale))

                story.append(Spacer(1, 8))
                rl_image = Image(img_stream, width=disp_w, height=disp_h)
                asset_label = "Figure" if art.get("artifact_type") == "image" else "Table"
                safe_cap = sanitize_reportlab_text(art.get("caption", f"{asset_label} Asset"))
                story.append(KeepTogether([
                    rl_image,
                    Spacer(1, 4),
                    Paragraph(f"<b>{safe_cap}</b> (Original Page {art.get('page')})", caption_style),
                ]))
                story.append(Spacer(1, 10))
                placed_art_ids.add(art["id"])
            except Exception as e:
                logger.warning("Could not append unplaced artifact %s: %s", art["id"], e)

    missing_artifact_ids = [art["id"] for art in artifacts if art["id"] not in placed_art_ids]
    if review_required and missing_artifact_ids:
        story.append(Paragraph("AUTHOR REVIEW REQUIRED: Some original assets could not be rendered: " +
                               sanitize_reportlab_text(", ".join(missing_artifact_ids)), body_style))
    doc.build(story)
    return {"rendered_artifact_ids": sorted(placed_art_ids), "missing_artifact_ids": missing_artifact_ids}


try:
    from validation_agent import TITLE_PATTERNS
except ImportError:
    from services.api.validation_agent import TITLE_PATTERNS



def extract_new_title_request(custom_instructions: str, skill_markdown: str = "") -> Optional[str]:
    """
    Checks if the user explicitly requested a title change/rename in custom instructions or skill.
    Returns the new title string if explicitly requested, otherwise None.
    """
    sources = [custom_instructions or ""]
    if skill_markdown:
        sec3_match = re.search(
            r"## 3\. Custom User Requirements & Overrides\s*\n(.*?)(?:\n---|\Z)",
            skill_markdown,
            re.DOTALL,
        )
        if sec3_match:
            sources.append(sec3_match.group(1))

    for src in sources:
        if not src or "_No additional custom user overrides" in src:
            continue
        for line in src.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue
            is_title_ja = bool(re.search(
                r"(?:heading|title|name)\s+(?:of\s+)?(?:the\s+)?(?:sop|document|report)?(?:\s+(?:should|must|needs\s+to|shall)?\s*be|\s*to\s*be)?\s*(?:in|to|as)\s*(?:japanese|japanse|nihongo)|(?:in\s+)?(?:japanese|japanse|nihongo)\s+(?:heading|title|name)|make\s+(?:the\s+)?(?:heading|title|name)\s+(?:in\s+)?(?:japanese|japanse|nihongo)",
                line_str, re.IGNORECASE
            ))
            if is_title_ja:
                return "JAPANESE_TITLE_REQUESTED"

            for pat in TITLE_PATTERNS:
                m = re.search(pat, line_str, re.IGNORECASE)
                if m:
                    candidate = m.group(1).strip().strip("\"'").strip()
                    if candidate and len(candidate) > 1 and candidate.lower() not in ("sop", "document", "the sop"):
                        return candidate
    return None


def extract_title_override(
    custom_instructions: str,
    skill_markdown: str,
    original_filename: str,
    llm_title: Optional[str] = None,
    existing_title: Optional[str] = None,
) -> str:
    """
    Extracts custom document title/heading overrides specified by the user
    in either their custom instructions or the dynamic skill directive.
    If no new title is explicitly requested, strictly preserves existing_title.
    """
    explicit_new_title = extract_new_title_request(custom_instructions, skill_markdown)
    if explicit_new_title:
        if explicit_new_title == "JAPANESE_TITLE_REQUESTED":
            return generate_japanese_sop_title(original_filename)
        return explicit_new_title

    # If this is an iterative refinement and we already have an established title, STRICTLY PRESERVE IT
    if existing_title and existing_title.strip() and not existing_title.lower().startswith("optimized sop:"):
        return existing_title.strip()

    if llm_title and llm_title.strip() and not llm_title.lower().startswith("optimized sop:"):
        return llm_title.strip()

    clean_base = original_filename.replace(".pdf", "").replace("_", " ").strip()
    return f"Standard Operating Procedure: {clean_base}"


def parse_llm_json_response(content: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """
    Parses LLM output into (document_title, sections_data).
    Tolerates JSON objects, JSON lists, markdown fences, and truncated JSON responses.
    """
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    title = None
    sections = []

    # Attempt 1: Direct JSON parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            title = data.get("document_title") or data.get("title")
            raw_secs = data.get("sections") or []
            if isinstance(raw_secs, list):
                sections = raw_secs
        elif isinstance(data, list):
            sections = data
        if sections:
            return title, sections
    except Exception as e:
        logger.debug("Direct JSON parse failed: %s, attempting recovery", e)

    # Attempt 2: If truncated with missing closing brackets
    for suffix in ['"]}]}', '"}]}', ']}', ']']:
        try:
            data = json.loads(cleaned + suffix)
            if isinstance(data, dict) and "sections" in data:
                return data.get("document_title"), data["sections"]
            elif isinstance(data, list):
                return None, data
        except Exception:
            pass

    # Attempt 3: Flexible regex extraction of completed section blocks regardless of key order
    sec_blocks = re.findall(r"\{[^{}]*\"heading\"[^{}]*\}", cleaned, re.DOTALL)
    for b in sec_blocks:
        h_m = re.search(r'\"heading\"\s*:\s*\"([^\"]+)\"', b)
        c_m = re.search(r'\"content\"\s*:\s*\"((?:\\.|[^\"])*)\"', b)
        t_m = re.search(r'\"type\"\s*:\s*\"([^\"]+)\"', b)
        a_m = re.search(r'\"artifact_ids\"\s*:\s*\[([^\]]*)\]', b)
        if h_m and c_m:
            heading = h_m.group(1)
            raw_content = c_m.group(1).encode().decode("unicode_escape", errors="replace")
            sec_type = t_m.group(1) if t_m else "normal"
            raw_arts = a_m.group(1) if a_m else ""
            art_ids = [a.strip().strip('"\'') for a in raw_arts.split(",") if a.strip().strip('"\'')]
            sections.append({
                "heading": heading,
                "content": raw_content,
                "type": sec_type,
                "artifact_ids": art_ids,
            })

    if sections:
        return title, sections

    return None, []


async def generate_optimized_sop(
    conversation_id: str,
    username: str,
    original_text: str,
    original_filename: str,
    selected_suggestions: List[Dict[str, str]],
    custom_instructions: str,
    artifacts: List[Dict[str, Any]],
    llm_service_url: str,
    provider: str,
    model: str,
    api_key: str,
    existing_sections: Optional[List[Dict[str, Any]]] = None,
    existing_title: Optional[str] = None,
    output_language: str = "English",
    previous_scores: Optional[Dict[str, Any]] = None,
    document_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    # --- HERE SOP OPTIMIZATION & REGENERATION HAPPENS ---
    1. Compiles session-specific optimization skill directive into storage.
    2. Prompts LLM to rewrite text in canonical English adhering to Kenvue guidelines + selected changes.
    3. Enforces authoritative Kenvue Master SOP-WI Template structure (SOP-STD-001) and writing standards.
    4. Evaluates quality scores on the canonical English representation using the authoritative Kenvue rubric.
    5. Calculates before-and-after score comparison and resolved violations.
    6. Translates canonical English sections to the selected output_language via NLLB if output_language != English.
    7. Compiles a high-quality PDF with ReportLab enforcing custom title override & localized fonts.
    8. Re-inserts original images and tables from storage as-is without alteration.
    """
    is_iterative = bool(existing_sections and isinstance(existing_sections, list) and len(existing_sections) >= 3)

    # If title not provided explicitly, try extracting from existing_sections
    if not existing_title and existing_sections:
        for s in existing_sections:
            c_text = s.get("content", "")
            m_dt = re.search(r"Document Title:\s*([^\n\r]+)", c_text, re.IGNORECASE)
            if m_dt:
                existing_title = m_dt.group(1).strip()
                break
            m_p1 = re.search(r"(?:The purpose of this (?:procedure|Standard Operating Procedure)\s*\(([^)]+)\)|本標準作業手順書\s*\(([^)]+)\))", c_text)
            if m_p1:
                cand = (m_p1.group(1) or m_p1.group(2) or "").strip()
                if cand:
                    existing_title = cand
                    break

    # Determine authoritative title from custom instructions or skill directives
    doc_title = extract_title_override(
        custom_instructions=custom_instructions,
        skill_markdown="",
        original_filename=original_filename,
        existing_title=existing_title,
    )
    logger.info("Authoritative SOP Title resolved: '%s'", doc_title)

    # Step 1: Compile dynamic SOP Optimization Directive & Execution Skill
    skill_directive = skill_manager.build_optimization_skill(
        conversation_id=conversation_id,
        username=username,
        original_filename=original_filename,
        selected_suggestions=selected_suggestions,
        custom_instructions=custom_instructions,
        artifacts=artifacts,
        original_text=original_text,
        is_iterative=is_iterative,
        current_title=doc_title,
        document_id=document_id,
    )

    # Source and template have distinct authority. No legacy content injector or
    # requirement-generating remediation may run after evidence reconciliation.
    from source_grounding import inventory_from_pages, grounded_transform, canonical
    import hashlib
    source_inventory = None
    if document_id:
        inventory_bytes, _ = minio_storage.get_file_bytes(
            f"users/{username}/conversations/{conversation_id}/extraction/{document_id}.json")
        if inventory_bytes:
            source_inventory = json.loads(inventory_bytes)
            expected = hashlib.sha256(canonical(original_text).encode()).hexdigest()
            if source_inventory.get("source_text_sha256") != expected or source_inventory.get("document_id") != document_id:
                logger.warning("Source evidence manifest is stale; using complete current canonical source with review flag")
                source_inventory = None
    if source_inventory is None:
        source_inventory = inventory_from_pages(
            [{"page": None, "text": original_text}], document_id or conversation_id,
            original_filename, artifacts, status="legacy_provenance_unavailable")
    # Actual artifact records are authoritative, not model-provided identifiers.
    source_inventory["artifacts"] = artifacts
    if not api_key or not api_key.strip():
        raise LLMServiceError(format_llm_unavailable_message(provider, 400, "API key is not configured"), status_code=503)
    sections_data, val_report = await grounded_transform(
        source_inventory,
        json.dumps({"selected_suggestions": selected_suggestions, "custom_instructions": custom_instructions,
                    "previous_layout": [s.get("heading") for s in existing_sections or []]}, ensure_ascii=False)
        if selected_suggestions or custom_instructions else "",
        {"llm_service_url": llm_service_url, "provider": provider, "model": model, "api_key": api_key})
    # Existing validation remains observable but cannot inject factual content.
    style_report = validation_agent.validate_sections(
        sections=sections_data, selected_suggestions=selected_suggestions,
        custom_instructions=custom_instructions, doc_title=doc_title)
    val_report["style_validation"] = style_report
    if not style_report.get("passed", False):
        val_report.update(passed=False, requires_human_review=True)
    is_full_japanese = False  # Canonical evidence is always reconciled in English.
    if re.search(r"japanese|japanse|nihongo", custom_instructions or "", re.I):
        output_language = "Japanese"
    logger.info("Source reconciliation: document=%s elements=%d human_review=%s rejected=%d",
                document_id, val_report["source_element_count"], val_report["requires_human_review"],
                len(val_report["rejected_candidates"]))

    # Step 2: Evaluate the optimized SOP on the Canonical English representation via the active LLM
    import copy
    english_sections = copy.deepcopy(sections_data)
    english_title = doc_title

    full_new_text = "\n\n".join([f"{s.get('heading')}\n{s.get('content')}" for s in english_sections])
    updated_eval = await evaluate_sop_with_llm(
        sop_text=full_new_text,
        llm_service_url=llm_service_url,
        provider=provider,
        model=model,
        api_key=api_key,
        compact_mode=False,
    )

    val_report["template_violations"] = updated_eval.get("violations", [])
    if val_report["template_violations"]:
        val_report.update(passed=False, requires_human_review=True)
    comparison = compare_sop_evaluations(previous_scores or {}, updated_eval)

    updated_scores = {
        "template_score": updated_eval["template_score"],
        "readability_score": updated_eval["readability_score"],
        "quality_score": updated_eval["quality_score"],
        "average_score": updated_eval["average_score"],
        "overall_score": updated_eval["average_score"],
        "english_title": english_title,
        "summary": updated_eval.get("summary", ""),
        "suggestions": updated_eval.get("suggestions", []),
        "violations": updated_eval.get("violations", []),
        "passed_checks": updated_eval.get("passed_checks", []),
        "score_difference": comparison.get("score_difference", 0),
        "resolved_violations": comparison.get("resolved_violations", []),
        "newly_introduced_violations": comparison.get("newly_introduced_violations", []),
        "outcome": comparison.get("outcome", "MAINTAINED"),
        "before_and_after_comparison": comparison,
    }

    # Step 3: Translate Canonical English SOP to Selected Output Language via NLLB if output_language != English
    target_lang = (output_language or "English").strip()
    if is_full_japanese and target_lang.lower() in ("english", "eng_latn"):
        target_lang = "Japanese"

    translation_meta = {
        "translation_status": "skipped_already_english",
        "translation_model": "facebook/nllb-200-distilled-600M",
        "output_language": target_lang,
        "translation_errors": None,
    }

    if target_lang.lower() not in ("english", "eng_latn", "en") and not is_full_japanese:
        sections_data, doc_title, translation_meta = await translate_sop_sections_from_english(
            sections=english_sections,
            doc_title=english_title,
            target_language=target_lang,
            llm_service_url=llm_service_url,
            provider=provider,
            model=model,
            api_key=api_key,
        )

    if target_lang.lower() not in ("english", "eng_latn", "en"):
        val_report.update(passed=False, requires_human_review=True, localized_text_requires_review=True)

    logger.info(
        "[NLLB-PIPELINE] Single SOP Generation | Selected output language: %s | Translation model: %s | Translation status: %s | Generation status: completed",
        target_lang,
        translation_meta.get("translation_model", "facebook/nllb-200-distilled-600M"),
        translation_meta.get("translation_status", "completed"),
    )

    # Step 4: Build PDF with ReportLab using the authoritative localized doc_title and sections
    pdf_buffer = io.BytesIO()
    rendering_report = create_kenvue_pdf(
        title=doc_title,
        sections=sections_data,
        artifacts=artifacts,
        output_stream=pdf_buffer,
        output_language=target_lang,
        review_required=True,
    )
    pdf_bytes = pdf_buffer.getvalue()
    pdf_buffer.close()
    val_report["artifact_rendering"] = rendering_report
    if rendering_report["missing_artifact_ids"]:
        val_report.update(passed=False, requires_human_review=True)

    # Step 5: Store optimized PDF in storage under users/{username}/...
    safe_doc_id = re.sub(r"[^\w\-]", "_", str(document_id)) if document_id else None
    import uuid
    version_id = uuid.uuid4().hex
    version_prefix = f"users/{username}/conversations/{conversation_id}/optimized/{safe_doc_id or 'document'}/{version_id}"
    object_name = f"{version_prefix}/sop.pdf"
    sections_json_obj = f"{version_prefix}/sections.json"
    english_sections_obj = f"{version_prefix}/english_sections.json"
    # All generation files are immutable and published only with an audit record.
    saved_objects = []
    for destination, data, content_type in [
        (object_name, pdf_bytes, "application/pdf"),
        (f"{version_prefix}/validation.json", json.dumps(val_report, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        (f"{version_prefix}/evidence.json", json.dumps(source_inventory, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        (sections_json_obj, json.dumps(sections_data, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
        (english_sections_obj, json.dumps(english_sections, ensure_ascii=False, indent=2).encode("utf-8"), "application/json"),
    ]:
        if not minio_storage.upload_file_bytes(destination, data, content_type):
            for saved in saved_objects:
                minio_storage.remove_file(saved)
            raise RuntimeError("Could not persist complete optimized artifact and validation record")
        saved_objects.append(destination)

    return {
        "status": "success",
        "document_title": doc_title,
        "english_title": english_title,
        "output_language": target_lang,
        "translation_metadata": translation_meta,
        "object_name": object_name,
        "artifact_version_id": version_id,
        "document_id": document_id,
        "sections_object_name": sections_json_obj,
        "sections": sections_data,
        "english_sections": english_sections,
        "skill_object_name": skill_directive["object_name"],
        "pdf_size_bytes": len(pdf_bytes),
        "updated_scores": updated_scores,
        "before_and_after_comparison": comparison,
        "score_difference": comparison.get("score_difference", 0),
        "resolved_violations": comparison.get("resolved_violations", []),
        "newly_introduced_violations": comparison.get("newly_introduced_violations", []),
        "validation_report": val_report,
        "summary": (
            f"Source-grounded SOP draft generated in {target_lang} as '{doc_title}'. "
            f"Retained {val_report['source_element_count']} source elements. "
            "Author review required before approval; missing information and requested additions remain unresolved."
        ),
    }
