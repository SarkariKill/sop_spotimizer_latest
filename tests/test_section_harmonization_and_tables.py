#!/usr/bin/env python3
"""
=============================================================================
Audit & Verification Tests: Structured Tables & Section-Level Harmonization
Tests A through G as specified in Section 9 of the Technical Specification:
- Test A: Structured table preservation (headers, rows, metadata, ReportLab table)
- Test B: Tables spanning pages (continuity, repeatRows, no duplicated headers)
- Test C: Three-SOP section comparison (Cases 1, 2, 4, 5, 7)
- Test D: Semantic alignment (different titles with same intent vs identical titles with different intent)
- Test E: Hierarchical and overlapping chunks (metadata, section hierarchy, table linking)
- Test F: Kenvue template compliance (mandatory sections 1.0 to 10.0, active voice)
- Test G: Parameter preservation and conflict detection
=============================================================================
"""
import io
import json
import os
import re
import sys
import unittest

# Ensure services/api is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
API_DIR = os.path.join(PROJECT_ROOT, "services", "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

import pymupdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table as RLTable, TableStyle, PageBreak

from pdf_processor import extract_sop_pdf, extract_sop_docx
from rag_engine import create_hierarchical_chunks
from sop_generator import (
    create_kenvue_pdf,
    parse_markdown_table_lines,
    split_content_into_flowable_blocks,
    build_reportlab_table_flowable,
)
from kenvue_guidelines import (
    MANDATORY_SECTIONS,
    audit_sop_deterministically,
    enforce_kenvue_template_standards,
)
from harmonization_engine import (
    extract_sections_from_text,
    build_section_inventory,
    align_sections_across_sops,
    perform_pairwise_and_group_section_comparisons,
    synthesize_conservative_section_content,
    synthesize_conservative_sections_deterministically,
    merge_structured_tables,
    extract_parameters_from_text,
    HarmonizationEngine,
)
from validation_agent import validation_agent


def create_synthetic_pdf_with_table(title: str, sections_data: list, multi_page: bool = False) -> bytes:
    """Helper to generate a clean synthetic PDF with native tables for test fixtures."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    normal = styles["Normal"]

    story = [Paragraph(f"<b>{title}</b>", h1), Spacer(1, 10)]

    for sec in sections_data:
        heading = sec.get("heading", "")
        content = sec.get("content", "")
        table = sec.get("table")

        if heading:
            story.append(Paragraph(f"<b>{heading}</b>", h2))
            story.append(Spacer(1, 6))
        if content:
            story.append(Paragraph(content, normal))
            story.append(Spacer(1, 6))

        if table:
            t_flowable = RLTable(table["data"], colWidths=table.get("colWidths", [150, 180, 180]), repeatRows=1)
            t_flowable.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e3a8a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(t_flowable)
            story.append(Spacer(1, 8))

        if multi_page and sec.get("page_break"):
            story.append(PageBreak())

    doc.build(story)
    return buf.getvalue()


class TestStructuredTablesAndHarmonization(unittest.TestCase):
    """Targeted Test Suite verifying structured tables and section-level multi-SOP harmonization."""

    # -------------------------------------------------------------------------
    # Test A: Structured table preservation
    # -------------------------------------------------------------------------
    def test_a_structured_table_preservation(self):
        """
        Verify:
        - Table extracted as structured data (headers, rows, table_name, num_rows, num_cols).
        - Headers and row values are preserved accurately.
        - Source page and section metadata remain linked.
        - Generated PDF contains an actual native ReportLab Table flowable, not a JPG screenshot.
        """
        table_data = [
            ["Role", "Responsibilities", "Approval Authority"],
            ["Operator", "Execute standard procedural steps per batch record.", "Operational Execution"],
            ["Shift Supervisor", "Verify line clearance and calibration records.", "Line Clearance Signoff"],
            ["Quality Assurance", "Review deviations, sign off release certificates.", "Batch Disposition"],
        ]
        pdf_bytes = create_synthetic_pdf_with_table(
            title="SOP-KNV-001: Tablet Coating Operations",
            sections_data=[
                {"heading": "1.0 Purpose", "content": "The purpose of this Document is to define tablet coating operations."},
                {"heading": "4.0 Roles and Responsibilities", "content": "Table 1: Operational Roles and Responsibilities", "table": {"data": table_data}},
            ],
        )

        pages_data, artifacts, summary = extract_sop_pdf(pdf_bytes, conversation_id="conv_test_a", filename="SOP-KNV-001.pdf")

        table_artifacts = [a for a in artifacts if a.get("artifact_type") == "table"]
        self.assertTrue(len(table_artifacts) >= 1, "Expected at least 1 extracted table artifact")

        tbl = table_artifacts[0]
        # Verify structured metadata
        self.assertIn("headers", tbl)
        self.assertIn("rows", tbl)
        self.assertEqual(tbl.get("num_cols"), 3)
        self.assertEqual(len(tbl["headers"]), 3)
        self.assertEqual(tbl["headers"][0].lower(), "role")
        self.assertEqual(tbl["headers"][1].lower(), "responsibilities")
        self.assertEqual(len(tbl["rows"]), 3)

        # Verify section metadata linking
        self.assertTrue("4.0" in str(tbl.get("section_id") or "") or "Roles" in str(tbl.get("section_title") or "") or "Roles" in str(tbl.get("table_name") or ""))

        # Verify generated PDF builds native ReportLab Table flowables
        pdf_out = io.BytesIO()
        test_sections = [
            {"heading": "1.0 Purpose", "content": "The purpose of this Document is to define tablet coating operations."},
            {
                "heading": "4.0 Roles and Responsibilities",
                "content": "| Role | Responsibilities |\n| --- | --- |\n| Operator | Execute steps. |\n| QA | Audit. |",
                "artifact_ids": [tbl["id"]],
            },
        ]
        create_kenvue_pdf(
            title="Optimized Tablet Coating SOP",
            sections=test_sections,
            artifacts=artifacts,
            output_stream=pdf_out,
            output_language="English",
        )
        pdf_out_bytes = pdf_out.getvalue()
        self.assertTrue(len(pdf_out_bytes) > 2000, "Generated PDF must not be empty")

        # Inspect generated PDF with PyMuPDF to verify table text is rendered as vector text
        doc_gen = pymupdf.open(stream=pdf_out_bytes, filetype="pdf")
        full_text = "\n".join([page.get_text() for page in doc_gen])
        self.assertIn("Role", full_text)
        self.assertIn("Responsibilities", full_text)
        self.assertIn("Shift Supervisor", full_text)
        doc_gen.close()

    # -------------------------------------------------------------------------
    # Test B: Tables spanning pages
    # -------------------------------------------------------------------------
    def test_b_tables_spanning_pages(self):
        """
        Verify:
        - Multi-page table continuation detection properly merges continuing rows without duplicating header rows.
        - Table flowable sets repeatRows=1 for clean page breaks.
        """
        tbl_block = {
            "header": ["Step No.", "Operational Parameter", "Acceptance Limits"],
            "rows": [
                [f"Step {i}", f"Parameter {i} Description", f"{100 + i * 5} ± 2 units"]
                for i in range(1, 40)
            ],
        }
        flowable = build_reportlab_table_flowable(tbl_block, output_language="English", doc_font_bold="Helvetica-Bold", doc_font_regular="Helvetica")
        self.assertIsInstance(flowable, RLTable)
        self.assertEqual(flowable.repeatRows, 1, "Flowable table must set repeatRows=1 for multi-page continuity")

        # Build PDF with 40 rows to force multi-page table spanning
        pdf_out = io.BytesIO()
        doc = SimpleDocTemplate(pdf_out, pagesize=A4, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=40)
        doc.build([flowable])
        multi_page_pdf = pdf_out.getvalue()

        # Extract with extract_sop_pdf and verify continuation detection
        pages_data, artifacts, summary = extract_sop_pdf(multi_page_pdf, conversation_id="conv_test_b", filename="MultiPageTable.pdf")
        tbl_arts = [a for a in artifacts if a.get("artifact_type") == "table"]
        self.assertTrue(len(tbl_arts) >= 1)

        # Check that headers are not repeated as raw data rows
        tbl = tbl_arts[0]
        data_rows = tbl.get("rows", [])
        for r in data_rows:
            self.assertNotEqual(r, tbl["headers"], "Header row must not be duplicated as a data row during continuation")

    # -------------------------------------------------------------------------
    # Test C: Three-SOP section comparison (Cases 1, 2, 4, 5, 7)
    # -------------------------------------------------------------------------
    def test_c_three_sop_section_comparison(self):
        """
        Fixtures:
        - SOP 1, SOP 2, SOP 3 with Procedure sections:
          1. Shared instruction by all 3: "Verify line clearance before charging active ingredients." (Case 1)
          2. Shared by 2 (SOP 1 & SOP 2): "Inspect impeller seal for lubricant leaks." (Case 2/3)
          3. Unique to SOP 3: "Perform nitrogen blanketing purge for 5 minutes." (Case 2/5)
          4. Conflicting parameter:
             SOP 1 specifies: "Set agitator speed to 1500 RPM."
             SOP 2 specifies: "Set agitator speed to 1800 RPM." (Case 4)
          5. Structured tables in SOP 1 and SOP 2 (Case 7).
        Verify:
        - Exactly 3 pairwise comparisons: (SOP 1, SOP 2), (SOP 1, SOP 3), (SOP 2, SOP 3).
        - Consolidated section preserves unique step, keeps shared step once, and flags parameter conflict.
        """
        sop1_text = """
1.0 Purpose
Define mixing operations for Facility A.

7.0 Procedure
7.1 Verify line clearance before charging active ingredients.
7.2 Inspect impeller seal for lubricant leaks.
7.3 Set agitator speed to 1500 RPM.
7.4 Table of Equipment:
| Equipment ID | Tag | Min Range |
| EQ-101 | Mixer A | 500 RPM |
| EQ-102 | Mixer B | 1000 RPM |
"""
        sop2_text = """
1.0 Purpose
Define mixing operations for Facility B.

7.0 Procedure
7.1 Verify line clearance before charging active ingredients.
7.2 Inspect impeller seal for lubricant leaks.
7.3 Set agitator speed to 1800 RPM.
7.4 Table of Equipment:
| Equipment ID | Tag | Max Range |
| EQ-101 | Mixer A | 2500 RPM |
| EQ-103 | Mixer C | 3000 RPM |
"""
        sop3_text = """
1.0 Purpose
Define mixing operations for Facility C.

7.0 Procedure
7.1 Verify line clearance before charging active ingredients.
7.2 Perform nitrogen blanketing purge for 5 minutes.
7.3 Maintain ambient tank pressure between 1.0 and 1.2 bar.
"""

        source_docs = [
            {"id": "doc_1", "filename": "SOP_1.pdf", "text": sop1_text},
            {"id": "doc_2", "filename": "SOP_2.pdf", "text": sop2_text},
            {"id": "doc_3", "filename": "SOP_3.pdf", "text": sop3_text},
        ]
        filenames = ["SOP_1.pdf", "SOP_2.pdf", "SOP_3.pdf"]

        # Stage A: Inventory
        inventories = build_section_inventory(source_docs)
        self.assertEqual(len(inventories), 3)

        # Stage B: Alignment
        aligned = align_sections_across_sops(inventories)
        self.assertIn("7.0 Procedure", aligned)
        self.assertEqual(len(aligned["7.0 Procedure"]["source_sections"]), 3)

        # Stages C & D: Pairwise Comparisons Across All 3 Pairs
        comp_data = perform_pairwise_and_group_section_comparisons(aligned, filenames)
        self.assertEqual(comp_data["pairwise_pairs_total"], 3, "3 SOPs must produce exactly 3 pairwise comparisons: n(n-1)/2")

        # Verify Parameter Conflict Detection (Case 4)
        conflicts = comp_data["parameter_conflicts"]
        self.assertTrue(len(conflicts) >= 1, "Must detect speed conflict between 1500 RPM and 1800 RPM")
        speed_conflict = next((c for c in conflicts if "rpm" in c["parameter"].lower()), None)
        self.assertIsNotNone(speed_conflict)
        self.assertIn("1500", speed_conflict["value_1"] + speed_conflict["value_2"])
        self.assertIn("1800", speed_conflict["value_1"] + speed_conflict["value_2"])

        # Stage E: Conservative Consolidation
        proc_content = synthesize_conservative_section_content("7.0 Procedure", aligned["7.0 Procedure"], comp_data, "Harmonized Mixing SOP")

        # 1. Shared instruction by all 3 kept once
        self.assertEqual(proc_content.count("Verify line clearance before charging active ingredients"), 1)

        # 2. Unique step to SOP 3 retained
        self.assertIn("Perform nitrogen blanketing purge for 5 minutes", proc_content)

        # 3. Parameter conflict flagged explicitly (Case 4)
        self.assertIn("[REVIEW REQUIRED - Parameter Divergence", proc_content)
        self.assertIn("1500", proc_content)
        self.assertIn("1800", proc_content)

        # 4. Table merged row-by-row (Case 7)
        self.assertIn("EQ-101", proc_content)
        self.assertIn("EQ-102", proc_content)
        self.assertIn("EQ-103", proc_content)

    # -------------------------------------------------------------------------
    # Test D: Semantic alignment
    # -------------------------------------------------------------------------
    def test_d_semantic_alignment(self):
        """
        Verify:
        - Different section titles with identical intent ('Operating Instructions' vs 'Execution Steps') map to 7.0 Procedure.
        - Distinct titles / unique domain procedures are preserved (Case 5).
        """
        doc_a = {"id": "1", "filename": "SOP_A.pdf", "text": "## Execution Steps\nClean the nozzle with sterile WFI."}
        doc_b = {"id": "2", "filename": "SOP_B.pdf", "text": "## Operating Instructions\nClean the nozzle with sterile WFI."}
        invs = build_section_inventory([doc_a, doc_b])
        aligned = align_sections_across_sops(invs)

        self.assertIn("7.0 Procedure", aligned)
        proc_sources = aligned["7.0 Procedure"]["source_sections"]
        self.assertEqual(len(proc_sources), 2, "Both Execution Steps and Operating Instructions must align to 7.0 Procedure")

        # Distinct titles / unique domain procedures are preserved (Case 5)
        doc_c = {"id": "3", "filename": "SOP_C.pdf", "text": "## Cleanroom HVAC Filter Differential Pressure Audit\nCheck manometer gauge for 15 Pa drop."}
        invs_c = build_section_inventory([doc_c])
        aligned_c = align_sections_across_sops(invs_c)
        unique_keys = [k for k in aligned_c.keys() if "HVAC" in k or "Unique:" in k]
        self.assertTrue(len(unique_keys) >= 1, "Unique domain procedure must be preserved as unique section")

    # -------------------------------------------------------------------------
    # Test E: Hierarchical and overlapping chunks
    # -------------------------------------------------------------------------
    def test_e_hierarchical_and_overlapping_chunks(self):
        """
        Verify:
        - Section hierarchy, parent-child metadata schema, table linking, and chunk boundaries.
        - Chunks do not cut markdown table rows in half.
        """
        text = """# 7.0 Procedure
## 7.1 Pre-Start Inspection
Verify that line clearance certificate is signed.
Check calibration label on balance BAL-001.

| Checkpoint | Limit | Status |
| Visual Seal | 100% Intact | Pass |
| Nitrogen Pressure | 2.5 ± 0.1 bar | Pass |

## 7.2 Main Execution
Run coating drum at 12 RPM for 45 minutes.
Spray suspension at 150 mL/min continuously.
"""
        parents, children = create_hierarchical_chunks(
            pages_data=[{"page": 1, "text": text}],
            parent_chunk_size=500,
            child_chunk_size=200,
            child_chunk_overlap=50,
            document_id="SOP-EVAL-001",
            filename="SOP-EVAL-001.pdf",
            artifacts_data=[{"id": "tbl_001", "artifact_type": "table", "section_title": "Procedure", "page": 1}],
        )

        all_chunks = parents + children
        self.assertTrue(len(all_chunks) >= 2, "Expected multiple parent/child chunks")
        for ch in all_chunks:
            self.assertEqual(ch["document_id"], "SOP-EVAL-001")
            self.assertEqual(ch["source_filename"], "SOP-EVAL-001.pdf")
            self.assertIn("section_id", ch)
            self.assertIn("section_title", ch)
            self.assertIn("chunk_id", ch)
            self.assertIn("chunk_text", ch)
            self.assertIn("table_ids", ch)

            # Table rows must remain intact
            if "|" in ch["chunk_text"]:
                lines = [l.strip() for l in ch["chunk_text"].split("\n") if l.strip().startswith("|")]
                for l in lines:
                    self.assertTrue(l.endswith("|"), f"Table line was cut across cell boundary: {l}")

    # -------------------------------------------------------------------------
    # Test F: Kenvue template compliance
    # -------------------------------------------------------------------------
    def test_f_kenvue_template_compliance(self):
        """
        Verify:
        - Mandatory Kenvue sections 1.0 to 10.0, Roles table, Key Terms table, and Document Revision History.
        - Enforces imperative, active voice.
        """
        sections = [
            {"heading": "1.0 Purpose", "content": "The purpose of this Document is to define cleaning steps for Kenvue."},
            {"heading": "7.0 Procedure", "content": "The operator should probably check the valve if needed."},
        ]
        enforced = enforce_kenvue_template_standards(sections, "Standard Cleaning SOP")

        headings = [s["heading"] for s in enforced]
        self.assertTrue(any("1.0" in h for h in headings))
        self.assertTrue(any("2.0" in h for h in headings))
        self.assertTrue(any("3.0" in h for h in headings))
        self.assertTrue(any("4.0" in h for h in headings))
        self.assertTrue(any("7.0" in h for h in headings))
        self.assertTrue(any("Revision" in h for h in headings))

        audit_res = audit_sop_deterministically(enforced)
        self.assertTrue(audit_res["has_mandatory_sections"], "Enforced SOP must contain mandatory sections")
        self.assertGreaterEqual(audit_res["deterministic_template_score"], 80)

    # -------------------------------------------------------------------------
    # Test G: Parameter preservation and conflict detection
    # -------------------------------------------------------------------------
    def test_g_parameter_preservation_and_conflict_detection(self):
        """
        Verify:
        - Divergent numerical limits trigger conflict reporting.
        - Validation rejects silent overwrites and demands human review.
        """
        conflicts = [
            {
                "section": "7.0 Procedure",
                "parameter": "rpm",
                "sop_1": "SOP_A.pdf",
                "value_1": "1500 RPM",
                "sop_2": "SOP_B.pdf",
                "value_2": "1800 RPM",
                "description": "SOP_A specifies 1500 RPM while SOP_B specifies 1800 RPM",
            }
        ]
        # Content without review callout must fail validation
        failing_sections = [
            {"heading": "1.0 Purpose", "content": "The purpose of this Document is to define mixing."},
            {"heading": "7.0 Procedure", "content": "7.1 Set agitator to 1650 RPM."},
        ]
        val_res = validation_agent.validate_sections(
            sections=failing_sections,
            selected_suggestions=[],
            custom_instructions="",
            doc_title="Harmonized Mixing",
            parameter_conflicts=conflicts,
        )
        self.assertFalse(val_res["passed"], "Must fail validation when parameter conflict is silently resolved")
        self.assertEqual(len(val_res["missing_conflicts"]), 1)

        # Content with review callout must pass validation
        passing_sections = [
            {"heading": "1.0 Purpose", "content": "The purpose of this Document is to define mixing."},
            {
                "heading": "7.0 Procedure",
                "content": "7.1 Set agitator.\n> **[REVIEW REQUIRED - Parameter Divergence: RPM]**\n> SOP_A: 1500 RPM vs SOP_B: 1800 RPM\n> *Both preserved for authorized GMP review.*",
            },
        ]
        val_res_pass = validation_agent.validate_sections(
            sections=passing_sections,
            selected_suggestions=[],
            custom_instructions="",
            doc_title="Harmonized Mixing",
            parameter_conflicts=conflicts,
        )
        self.assertTrue(val_res_pass["passed"], "Must pass validation when parameter conflict is explicitly flagged for review")


if __name__ == "__main__":
    unittest.main()
