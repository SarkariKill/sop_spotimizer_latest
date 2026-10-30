"""Synthetic source/provenance and optimization safety regressions."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))
import pymupdf
from document_ingestion import extract_document
from source_grounding import inventory_from_pages, reconcile, grounded_transform, MISSING
from sop_generator import create_kenvue_pdf, generate_optimized_sop
from local_storage import LocalStorage


def pdf_fixture():
    doc = pymupdf.open()
    for heading, text in [("1.0 Purpose", "Inspect the seal."), ("7.0 Procedure", "Maintain pressure at -5 ± 1 bar.\nInspect at 10 to 15 minutes.")]:
        page = doc.new_page()
        page.insert_text((50, 50), heading)
        page.insert_text((50, 80), text)
    return doc.tobytes()


def docx_fixture():
    import docx
    from PIL import Image
    doc = docx.Document()
    doc.add_heading("7.0 Procedure", level=1)
    doc.add_heading("7.1 Inspection", level=2)
    doc.add_paragraph("Inspect the seal.")
    table = doc.add_table(rows=2, cols=2)
    for row, values in zip(table.rows, [("Parameter", "Value"), ("Pressure", "-5 ± 1 bar")]):
        for cell, value in zip(row.cells, values):
            cell.text = value
    image = io.BytesIO(); Image.new("RGB", (25, 25), "red").save(image, format="PNG"); image.seek(0)
    doc.add_picture(image)
    out = io.BytesIO(); doc.save(out)
    return out.getvalue()


class SourceGroundingTests(unittest.TestCase):
    def inventory(self, text="Inpect teh seal.\n\nPressure: -5 ± 1 bar.\n\nDuration: 10 to 15 minutes."):
        return inventory_from_pages([{"page": 2, "text": text}], "doc-a", "source.pdf")

    def test_reject_invented_temperature_roles_and_citations(self):
        inv = self.inventory()
        bad = [{"source_ids": [inv["elements"][0]["source_id"]], "content": "QA must sample every hour at 45 °C."},
               {"source_ids": ["invented-id"], "content": "Use gloves."}]
        secs, report = reconcile(inv, bad)
        result = "\n".join(s["content"] for s in secs)
        self.assertNotIn("45", result)
        self.assertNotIn("QA must", result)
        self.assertEqual(len(report["rejected_candidates"]), 2)
        self.assertTrue(report["source_coverage_passed"])
        self.assertEqual(report["retained_source_ids"], [e["source_id"] for e in inv["elements"]])

    def test_preserve_context_sign_units_tolerance_and_reference(self):
        inv = self.inventory("Pressure: -5 ± 1 bar.\n\nTemperature: 5 °C.\n\nRefer to step 7.1.2.")
        bad = [{"source_ids": [e["source_id"]], "content": e["text"].replace("-5 ± 1 bar", "5 ± 1 °C")} for e in inv["elements"]]
        secs, report = reconcile(inv, bad)
        result = "\n".join(s["content"] for s in secs)
        self.assertIn("Pressure: -5 ± 1 bar.", result)
        self.assertIn("step 7.1.2", result)
        self.assertEqual(len(report["rejected_candidates"]), 1)

    def test_missing_sections_disclose_without_generic_requirements(self):
        secs, report = reconcile(self.inventory("Inspect the seal."), [])
        result = "\n".join(s["content"] for s in secs)
        self.assertIn(MISSING, result)
        self.assertNotIn("cleanroom", result)
        self.assertNotIn("QA Reviewer", result)
        self.assertNotIn("FRM-0009808", result)
        self.assertTrue(report["requires_human_review"])
        self.assertFalse(report["passed"])

    def test_docling_heading_links_map_unnumbered_native_content(self):
        from source_grounding import attach_structure, target_for
        inv = self.inventory("Purpose\n\nDescribe seal inspection.")
        attach_structure(inv, [
            {"source_ref": "#/texts/0", "text": "Purpose", "section_ref": "#/texts/0", "label": "section_header"},
            {"source_ref": "#/texts/1", "text": "Describe seal inspection.", "section_ref": "#/texts/0", "label": "text"},
        ])
        self.assertTrue(all(target_for(e) == "1.0" for e in inv["elements"]))
        self.assertTrue(all(e["source_section_ref"] == "#/texts/0" for e in inv["elements"]))

    def test_conservative_grammar_and_negations(self):
        inv = self.inventory("Inpect teh seal. Do not open the valve.")
        e = inv["elements"][0]
        secs, report = reconcile(inv, [{"source_ids": [e["source_id"]], "content": "inspect the seal. Do not open the valve."}])
        self.assertFalse(report["rejected_candidates"])
        self.assertIn("Do not open", " ".join(s["content"] for s in secs))
        _, report = reconcile(inv, [{"source_ids": [e["source_id"]], "content": "inspect the seal. Open the valve."}])
        self.assertTrue(report["rejected_candidates"])

    def test_artifact_references_and_tables_retained(self):
        table = "| Parameter | Value |\n| --- | --- |\n| Pressure | -5 ± 1 bar |"
        inv = self.inventory(table)
        inv["artifacts"] = [{"id": "image-a", "artifact_type": "image", "page": 2}]
        secs, report = reconcile(inv, [])
        self.assertIn(table, "\n".join(s["content"] for s in secs))
        self.assertEqual([a for s in secs for a in s["artifact_ids"]], ["image-a"])
        self.assertTrue(report["requires_human_review"])

    def test_bounded_bad_remediation_retains_source(self):
        inv = self.inventory("Inspect the seal.")
        e = inv["elements"][0]
        response = __import__('httpx').Response(200, json={"content": json.dumps({"statements": [{"source_ids": [e["source_id"]], "content": "Heat to 45 °C."}]})}, request=__import__('httpx').Request("POST", "http://test/generate"))
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)) as request:
            secs, report = asyncio.run(grounded_transform(inv, "", {"llm_service_url": "http://test", "provider": "azure_openai", "model": "test", "api_key": "test"}))
        self.assertEqual(request.await_count, 2)
        self.assertNotIn("45", "\n".join(s["content"] for s in secs))
        self.assertTrue(report["audit_history"])

    def test_oversized_element_is_retained_without_truncation(self):
        inv = self.inventory("Inspect " + "seal " * 2000 + "TAIL_SENTINEL")
        secs, report = asyncio.run(grounded_transform(inv, "", {"llm_service_url": "http://test"}))
        self.assertIn("TAIL_SENTINEL", "\n".join(s["content"] for s in secs))
        self.assertTrue(report["oversized_source_ids_retained_verbatim"])

    def test_pdf_does_not_claim_approval_or_fake_id(self):
        secs, _ = reconcile(self.inventory("Inspect the seal."), [])
        out = io.BytesIO(); create_kenvue_pdf("Seal inspection", secs, [], out, review_required=True)
        doc = pymupdf.open(stream=out.getvalue(), filetype="pdf")
        text = "".join(page.get_text() for page in doc)
        self.assertNotIn("APPROVED", text)
        self.assertNotIn("SOP-KNV-2026-OPT", text)
        self.assertIn("AUTHOR REVIEW REQUIRED", text)
        self.assertIn("Inspect the seal", text)

    def test_full_generator_gates_before_render_and_preserves_versions(self):
        import httpx
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalStorage(directory)
            response = httpx.Response(200, json={"content": json.dumps({"statements": [{"source_ids": ["fake"], "content": "QA must heat to 45 °C."}]})})
            evaluation = {"template_score": 20, "readability_score": 20, "quality_score": 20,
                          "average_score": 20, "violations": [], "suggestions": []}
            kwargs = dict(conversation_id="conv", username="admin", original_text="Inspect the seal.",
                          original_filename="seal.pdf", selected_suggestions=[], custom_instructions="",
                          artifacts=[], llm_service_url="http://test", provider="azure_openai", model="test",
                          api_key="test", document_id="doc-a",
                          existing_sections=[{"heading": "7.0 Procedure", "content": "Invented duty"}] * 3)
            with patch("sop_generator.minio_storage", storage), patch("skill_manager.minio_storage", storage), patch("httpx.AsyncClient.post", new=AsyncMock(return_value=response)), patch("sop_generator.evaluate_sop_with_llm", new=AsyncMock(return_value=evaluation)):
                first = asyncio.run(generate_optimized_sop(**kwargs))
                old_bytes, _ = storage.get_file_bytes(first["object_name"])
                second = asyncio.run(generate_optimized_sop(**kwargs))
            self.assertNotEqual(first["object_name"], second["object_name"])
            self.assertEqual(old_bytes, storage.get_file_bytes(first["object_name"])[0])
            text = "\n".join(s["content"] for s in first["english_sections"])
            self.assertNotIn("Invented duty", text)
            self.assertNotIn("45", text)
            self.assertFalse(first["validation_report"]["passed"])
            self.assertTrue(first["validation_report"]["requires_human_review"])
            self.assertTrue(storage.file_exists(first["object_name"].replace("sop.pdf", "validation.json")))

    def test_graph_validation_preserves_review_gate_without_injection(self):
        from agents.validation_node_agent import validation_decision_agent
        from agents.retrieval_agent import retrieval_agent
        from graph.state import create_initial_agent_state
        state = create_initial_agent_state("single_sop_optimization", "conv")
        state["intermediate_results"] = {"optimization_result": {"validation_report": {"source_grounded": True, "passed": False, "requires_human_review": True}}}
        with patch("agents.validation_node_agent.validate_sop_sections_tool") as validator:
            result = validation_decision_agent.execute(state)
        validator.invoke.assert_not_called()
        self.assertFalse(result["validation_report"]["passed"])
        with patch("agents.retrieval_agent.faiss_index_chunks_tool") as indexer:
            result = retrieval_agent.execute(state)
        indexer.invoke.assert_not_called()
        self.assertIn("post_optimization_reindex", result["completed_steps"])

    def test_translation_preserves_tail_and_actual_page_mapping(self):
        from nllb_translator import translate_sop_to_english, translate_pages_to_english
        import httpx
        seen = []
        async def translate(client, url, **kwargs):
            passage = kwargs["json"]["messages"][-1]["content"]
            seen.append(passage)
            return httpx.Response(200, json={"content": passage})
        with patch("httpx.AsyncClient.post", new=translate):
            text = "SOURCE " * 1400 + "TAIL_SENTINEL"
            result, meta = asyncio.run(translate_sop_to_english(text, "German", api_key="test"))
            self.assertIn("TAIL_SENTINEL", result)
            self.assertEqual(len(seen), 2)
            pages, _ = asyncio.run(translate_pages_to_english([
                {"page": 5, "text": "PAGE_FIVE source"}, {"page": 8, "text": "PAGE_EIGHT source"}], "German", api_key="test"))
        self.assertEqual(pages[0]["page"], 5)
        self.assertEqual(pages[1]["page"], 8)
        self.assertNotIn("PAGE_EIGHT", pages[0]["text"])


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.storage = LocalStorage(self.temp.name)
        self.patch = patch("document_ingestion.minio_storage", self.storage)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_text_pdf_pages_and_provenance_compatible_with_chunking(self):
        from rag_engine import create_hierarchical_chunks
        pages, arts, stats = extract_document(pdf_fixture(), "conv", "source.pdf", "doc-a")
        self.assertEqual(len(pages), 2)
        self.assertIn("Inspect the seal", pages[0]["text"])
        self.assertEqual(stats["extraction_engine"], "docling")
        parents, children = create_hierarchical_chunks(pages, document_id="doc-a", filename="source.pdf", artifacts_data=arts)
        self.assertTrue(children)
        self.assertTrue(all(c["document_id"] == "doc-a" and c["page"] in (1, 2) for c in children))

    def test_conversion_failure_is_reported_without_fallback(self):
        from document_ingestion import DocumentExtractionError
        with patch("document_ingestion._convert", side_effect=RuntimeError("test conversion failure")) as convert:
            with self.assertRaisesRegex(DocumentExtractionError, "test conversion failure"):
                extract_document(pdf_fixture(), "conv", "source.pdf", "doc-a")
        self.assertEqual(convert.call_count, 1)
        self.assertFalse(self.storage.list_objects())

    def test_partial_docling_result_is_rejected_before_indexing(self):
        from docling.datamodel.base_models import ConversionStatus
        from unittest.mock import MagicMock
        from document_ingestion import DocumentExtractionError
        result = MagicMock(status=ConversionStatus.PARTIAL_SUCCESS, errors=["incomplete page"])
        from document_ingestion import _convert_in_worker
        with patch("document_ingestion._converter") as converter, patch("document_ingestion._normalize") as normalize:
            converter.return_value.convert.return_value = result
            with self.assertRaisesRegex(DocumentExtractionError, "not complete"):
                _convert_in_worker(pdf_fixture(), "source.pdf")
            normalize.assert_not_called()

    def test_docling_is_required_even_if_obsolete_flag_requests_legacy(self):
        with patch.dict(os.environ, {"SOP_EXTRACTION_ENGINE": "legacy"}):
            pages, artifacts, stats = extract_document(docx_fixture(), "conv", "source.docx", "doc-a")
        self.assertEqual(stats["extraction_engine"], "docling")
        self.assertIn("Inspect the seal", pages[0]["text"])

    def test_missing_dependency_is_an_observable_service_error(self):
        from document_ingestion import DocumentExtractionError
        with patch("document_ingestion._convert", side_effect=ImportError("docling unavailable")):
            with self.assertRaises(DocumentExtractionError) as error:
                extract_document(pdf_fixture(), "conv", "source.pdf", "doc-a")
        self.assertEqual(error.exception.status_code, 503)

    def test_scanned_pdf_requires_ocr_instead_of_empty_indexing(self):
        doc = pymupdf.open(); doc.new_page()
        with self.assertRaisesRegex(ValueError, "OCR"):
            extract_document(doc.tobytes(), "conv", "scan.pdf", "doc-a")

    def test_rejected_scanned_image_exposes_partial_assets_for_cleanup(self):
        from PIL import Image, ImageDraw
        from document_ingestion import DocumentExtractionError
        image = Image.new("RGB", (400, 400), "white")
        ImageDraw.Draw(image).text((30, 30), "Inspect the seal.", fill="black")
        pixels = io.BytesIO(); image.save(pixels, format="PNG")
        document = pymupdf.open(); page = document.new_page()
        page.insert_image(pymupdf.Rect(20, 20, 420, 420), stream=pixels.getvalue())
        with self.assertRaises(DocumentExtractionError) as failure:
            extract_document(document.tobytes(), "conv", "scan.pdf", "doc-a")
        self.assertFalse(self.storage.list_objects(), "Rejected extraction must clean partial binary assets")

    def test_missing_asset_is_explicit_in_rendering_report(self):
        inv = inventory_from_pages([{"page": 1, "text": "Inspect the seal."}], "doc-a", "source.pdf")
        inv["artifacts"] = [{"id": "missing-image", "artifact_type": "image", "page": 1}]
        secs, _ = reconcile(inv, [])
        output = io.BytesIO()
        report = create_kenvue_pdf("Seal inspection", secs, inv["artifacts"], output, review_required=True)
        self.assertEqual(report["missing_artifact_ids"], ["missing-image"])
        document = pymupdf.open(stream=output.getvalue(), filetype="pdf")
        self.assertIn("could not be rendered", "".join(p.get_text() for p in document))

    def test_malformed_and_empty_inputs(self):
        for data, name in [(b"", "empty.pdf"), (b"bad", "bad.pdf"), (b"bad", "bad.docx"), (b"bad", "bad.exe")]:
            with self.subTest(name=name), self.assertRaises(Exception):
                extract_document(data, "conv", name, "doc-a")

    @unittest.skipUnless(__import__('importlib').util.find_spec("docx"), "python-docx fixture dependency unavailable")
    def test_docx_docling_headings_tables_images(self):
        pages, arts, stats = extract_document(docx_fixture(), "conv", "source.docx", "doc-a")
        self.assertIn("7.1 Inspection", "\n".join(p["text"] for p in pages))
        self.assertTrue(any(a["artifact_type"] == "table" for a in arts))
        self.assertTrue(any(a["artifact_type"] == "image" for a in arts))
        self.assertTrue(all(a["document_id"] == "doc-a" for a in arts))
        table = next(a for a in arts if a["artifact_type"] == "table")
        preview, content_type = self.storage.get_file_bytes(table["object_name"])
        self.assertEqual(content_type, "image/svg+xml")
        self.assertIn(b"<svg", preview)
        self.assertIn(b"Pressure", preview)

    @unittest.skipUnless(__import__('importlib').util.find_spec("docx"), "python-docx fixture dependency unavailable")
    def test_docx_assets_render_and_tables_are_not_duplicated(self):
        pages, arts, _ = extract_document(docx_fixture(), "conv", "source.docx", "doc-a")
        inv = inventory_from_pages(pages, "doc-a", "source.docx", arts)
        secs, _ = reconcile(inv, [])
        output = io.BytesIO()
        with patch("sop_generator.minio_storage", self.storage):
            report = create_kenvue_pdf("Inspection", secs, arts, output, review_required=True)
        self.assertEqual(set(report["rendered_artifact_ids"]), {a["id"] for a in arts})
        self.assertFalse(report["missing_artifact_ids"])
        doc = pymupdf.open(stream=output.getvalue(), filetype="pdf")
        self.assertTrue(any(p.get_images() for p in doc))
        self.assertEqual("".join(p.get_text() for p in doc).count("-5 ± 1 bar"), 1)

    @unittest.skipUnless(__import__('importlib').util.find_spec("docling"), "Docling is required")
    def test_pdf_docling_ocr_requires_local_models(self):
        from document_ingestion import _converter
        with patch.dict(os.environ, {"DOCLING_ARTIFACTS_PATH": "/tmp/kenvue-models-do-not-exist", "DOCLING_OCR": "0"}):
            with self.assertRaisesRegex(ValueError, "models are missing"):
                _converter(True)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DOCLING_ARTIFACTS_PATH": directory, "DOCLING_OCR": "1", "DOCLING_OCR_DET_MODEL": ""}):
            with self.assertRaisesRegex(ValueError, "automatic OCR downloads disabled"):
                _converter(True)

    @unittest.skipUnless(__import__('importlib').util.find_spec("docling"), "Docling is required")
    def test_real_docling_docx_structure(self):
        pages, _, _ = extract_document(docx_fixture(), "conv", "source.docx", "doc-a")
        elements = [e for p in pages for e in p["elements"]]
        self.assertTrue(any(e["label"] == "section_header" and "7.1" in e["text"] for e in elements))
        self.assertTrue(any(e["label"] == "table" and "Pressure" in e["text"] for e in elements))
        self.assertTrue(all(e["source_ref"] for e in elements))
        self.assertTrue(any(e["parent_ref"] for e in elements))
        with patch.dict(os.environ, {"SOP_EXTRACTION_ENGINE": "docling"}):
            native_pages, artifacts, stats = extract_document(docx_fixture(), "conv", "source.docx", "doc-a")
        self.assertEqual(stats["extraction_engine"], "docling")
        self.assertFalse(stats["extraction_warnings"])
        self.assertTrue(any(e["label"] == "picture" for e in stats["structural_elements"]))
        self.assertTrue(any(a["artifact_type"] == "image" for a in artifacts))


if __name__ == "__main__":
    unittest.main()
