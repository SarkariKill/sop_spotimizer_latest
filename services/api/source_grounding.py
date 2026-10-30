"""Conservative source reconciliation for single-SOP optimization.

Similarity and model-supplied citations are never proof of entailment. Only exact
source passages and a deliberately small, auditable spelling repair set can be
automatically accepted. Other rewrites fall back to source and are recorded.
"""
import hashlib
import json
import re
from typing import Any, Dict, List

from kenvue_guidelines import ALL_CANONICAL_SECTIONS

MISSING = "[AUTHOR REVIEW REQUIRED] Information not provided in the source SOP."
_SPELLING = {"teh": "the", "inpect": "inspect", "chek": "check"}


def canonical(text):
    return re.sub(r"\s+", " ", text or "").strip()


def safe_rewrite(text):
    # No modal replacement: 'should' -> 'must' changes obligation strength.
    return re.sub(r"\b(teh|inpect|chek)\b", lambda m: _SPELLING[m[0].lower()], text, flags=re.I)


def inventory_from_pages(pages, document_id, filename, artifacts=None, status="complete"):
    elements = []
    section = "Document Overview"
    section_id = None
    for page in pages:
        # Keep complete lines/table blocks; do not split on decimal points or units.
        blocks = re.split(r"\n\s*\n", page.get("text", ""))
        for block in blocks:
            for part in re.split(r"(?m)(?=^(?:#{1,6}\s+|\d+(?:\.\d+)*\.?\s+[A-Z]))", block):
                part = part.strip()
                if not part:
                    continue
                first, _, rest = part.partition("\n")
                heading = re.match(r"^(?:#{1,6}\s*)?(\d+(?:\.\d+)*\.?)\s+(.+)$", first)
                # Numbered instructions are evidence too; heading recognition is
                # metadata only and never deletes the line.
                if heading:
                    section_id = heading[1].rstrip(".")
                    section = heading[2]
                eid = hashlib.sha256(f"{document_id}|{page.get('page')}|{len(elements)}|{part}".encode()).hexdigest()[:24]
                elements.append({"source_id": eid, "document_id": document_id,
                                 "filename": filename, "page": page.get("page"),
                                 "page_provenance": page.get("page_provenance", "unavailable"),
                                 "page_start": page.get("page"), "page_end": page.get("page"),
                                 "section_id": section_id, "section_title": section,
                                 "parent_section_id": section_id.rsplit(".", 1)[0] if section_id and "." in section_id else None,
                                 "text": part, "reading_order": len(elements),
                                 "extraction_engine": page.get("extraction_engine", "legacy"),
                                 "extraction_status": page.get("extraction_status", status)})
    source_text = "\n\n".join(p.get("text", "") for p in pages if p.get("text"))
    return {"document_id": document_id, "filename": filename, "elements": elements,
            "source_text_sha256": hashlib.sha256(canonical(source_text).encode()).hexdigest(),
            "artifacts": artifacts or [], "extraction_status": status}


def attach_structure(inventory, structural_elements):
    """Attach Docling hierarchy only to exact native passages; never invent links."""
    by_text = {}
    by_ref = {element["source_ref"]: element for element in structural_elements}
    for element in structural_elements:
        by_text.setdefault(canonical(element["text"]), []).append(element)
    for source in inventory["elements"]:
        matches = by_text.get(canonical(source["text"]), [])
        if len(matches) == 1:
            source["structure"] = matches[0]
            heading = by_ref.get(matches[0].get("section_ref"))
            if heading:
                source["section_title"] = heading["text"]
                source["source_section_ref"] = heading["source_ref"]
    inventory["structural_elements"] = structural_elements
    return inventory


def target_for(element):
    title = element.get("section_title", "").lower()
    for key, number in [("purpose", "1.0"), ("scope", "2.0"), ("term", "3.0"),
                        ("definition", "3.0"), ("responsibil", "4.0"), ("requirement", "5.0"),
                        ("process flow", "6.0"), ("reference", "8.0"), ("appendi", "9.0"),
                        ("revision", "revision_history")]:
        if key in title:
            return number
    return "7.0"


def template_sections():
    # Reuse approved names/order. Include optional sections with disclosures.
    return [{"heading": s,
             "content": MISSING, "type": "normal", "artifact_ids": [], "source_ids": []}
            for s in ALL_CANONICAL_SECTIONS]


def reconcile(inventory, candidates):
    """Reject invented IDs, extra prose, altered units/roles/negations and omissions.

    Every source element is emitted once even if generation omits it. Comparing
    an entire associated passage preserves parameter/context associations, signs,
    ranges, tolerances, tables and numbered cross references without substring
    or numeric-similarity heuristics.
    """
    evidence = {e["source_id"]: e for e in inventory["elements"]}
    accepted = {}
    findings = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            findings.append({"type": "invalid_candidate", "candidate": str(candidate)})
            continue
        ids = candidate.get("source_ids", [])
        if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or ids[0] not in evidence:
            findings.append({"type": "invalid_source_reference", "candidate": candidate})
            continue
        eid = ids[0]
        original = evidence[eid]["text"]
        content = candidate.get("content", "")
        normalize = (lambda value: value.strip()) if "|" in original else canonical
        if not isinstance(content, str) or normalize(content) not in {normalize(original), normalize(safe_rewrite(original))}:
            findings.append({"type": "unsupported_or_unverifiable_rewrite", "source_id": eid,
                             "source_passage": original, "candidate": candidate})
            continue
        if eid in accepted:
            findings.append({"type": "duplicate_candidate", "source_id": eid})
            continue
        accepted[eid] = content

    sections = template_sections()
    for sec in sections:
        key = "revision_history" if "revision" in sec["heading"].lower() else sec["heading"].split()[0]
        selected = [e for e in evidence.values() if target_for(e) == key]
        if selected:
            sec["content"] = "\n\n".join(accepted.get(e["source_id"], safe_rewrite(e["text"])) for e in selected)
            sec["source_ids"] = [e["source_id"] for e in selected]
    # All artifacts remain source assets; do not describe unseen image contents.
    for art in inventory.get("artifacts", []):
        target = next((s for s in sections if s["heading"].startswith("7.0")), sections[-1])
        target["artifact_ids"].append(art["id"])
    missing = [s["heading"] for s in sections if not s["source_ids"]]
    extraction_issues = inventory.get("extraction_status") != "complete" or any(e.get("extraction_status") != "complete" for e in evidence.values())
    unreadable_assets = [a["id"] for a in inventory.get("artifacts", []) if
                         a.get("artifact_type") == "image" or
                         (a.get("artifact_type") == "table" and not
                          (a.get("table_markdown") or a.get("table_data") or a.get("table_data_json") or a.get("headers")))]
    review = bool(missing or extraction_issues or unreadable_assets)
    return sections, {"passed": not review, "source_grounded": True,
                      "requires_human_review": review, "source_coverage_passed": True,
                      "parameter_preservation_passed": True, "source_reference_validity_passed": True,
                      "parameter_preservation_scope": "extracted_text_and_retained_original_assets; unreadable assets require review",
                      "asset_content_requires_review": unreadable_assets,
                      "unsupported_claims_in_final": [], "rejected_candidates": findings,
                      "missing_sections": missing, "extraction_incomplete": extraction_issues,
                      "source_element_count": len(evidence), "retained_source_ids": list(evidence),
                      "artifact_ids": [a["id"] for a in inventory.get("artifacts", [])],
                      "validation_method": "exact_passage_or_allowlisted_spelling_repair",
                      "verified_suggestions": [], "verified_custom": [], "iterations_executed": 1}


async def grounded_transform(inventory, instructions, llm_config):
    """Bound context by complete evidence elements, never by a document digest.

    Oversized elements stay verbatim and are explicitly reported, not truncated.
    One correction request per batch bounds remediation.
    """
    import httpx
    from prompt_loader import format_prompt, load_prompt
    from sop_evaluator import LLMServiceError, format_llm_unavailable_message

    if not inventory["elements"]:
        raise ValueError("Source contains no usable text; extraction/OCR review required.")
    batches, current, size = [], [], 0
    oversized = []
    for e in inventory["elements"]:
        # Use serialized size, including provenance, rather than text size alone.
        item_size = len(json.dumps(e, ensure_ascii=False))
        if current and size + item_size > 8000:
            batches.append(current); current, size = [], 0
        if item_size > 8000:
            oversized.append(e["source_id"])
            continue  # reconciliation retains this complete element verbatim
        current.append(e); size += item_size
    if current:
        batches.append(current)
    candidates, attempts = [], []
    requests_made, max_passes_used = 0, 0
    async with httpx.AsyncClient(timeout=90) as client:
        for batch in batches:
            batch_inventory = {**inventory, "elements": batch}
            local_findings = []
            for attempt in range(2):
                requests_made += 1
                max_passes_used = max(max_passes_used, attempt + 1)
                prompt = format_prompt(load_prompt("single_sop_optimization"), evidence_json=json.dumps(batch, ensure_ascii=False),
                                       requested_changes=instructions, findings_json=json.dumps(local_findings, ensure_ascii=False))
                try:
                    response = await client.post(f"{llm_config['llm_service_url']}/generate", json={
                        "provider": llm_config["provider"], "model": llm_config["model"],
                        "api_key": llm_config["api_key"], "messages": [{"role": "user", "content": prompt}]})
                    if response.status_code != 200:
                        raise LLMServiceError(format_llm_unavailable_message(
                            llm_config["provider"], response.status_code, response.text))
                except httpx.HTTPError as exc:
                    raise LLMServiceError(format_llm_unavailable_message(llm_config["provider"], 503, str(exc))) from exc
                try:
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", response.json().get("content", "").strip())
                    parsed = json.loads(raw)
                    output = parsed.get("statements", []) if isinstance(parsed, dict) else []
                    if not isinstance(output, list):
                        output = []
                except (ValueError, TypeError):
                    output = []
                _, report = reconcile(batch_inventory, output)
                local_findings = report["rejected_candidates"]
                covered = {c["source_ids"][0] for c in output if isinstance(c, dict) and isinstance(c.get("source_ids"), list) and len(c["source_ids"]) == 1 and isinstance(c["source_ids"][0], str)}
                if not output:
                    local_findings = [{"type": "invalid_or_empty_output"}]
                if not local_findings and covered == {e["source_id"] for e in batch}:
                    break
                if not local_findings:
                    local_findings = [{"type": "missing_source_coverage"}]
                attempts.append({"attempt": attempt + 1, "findings": local_findings})
            candidates.extend(output)
    sections, report = reconcile(inventory, candidates)
    report["audit_history"] = attempts
    report["iterations_executed"] = max_passes_used
    report["generation_requests"] = requests_made
    report["oversized_source_ids_retained_verbatim"] = oversized
    report["recommendations_requiring_author_approval"] = instructions
    if instructions:
        report.update(passed=False, requires_human_review=True)
    return sections, report
