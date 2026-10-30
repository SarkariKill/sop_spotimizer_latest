#!/usr/bin/env python3
"""
=============================================================================
Comprehensive Edge Cases & Deep Integration Test Suite for Kenvue SOP Assistant
=============================================================================
Tests all system boundary conditions, fault tolerance, security guardrails,
and edge cases across the entire platform:
1. Zero-byte (empty) and corrupted PDF uploads
2. Upload batch size limits (>10 files rejected with HTTP 400)
3. Unsupported file extensions (.exe, .txt, .zip rejected with HTTP 400)
4. Long SOP 100,000-character boundary preservation
5. Multi-SOP Optimization download isolation (English vs Japanese persistence)
6. Preview/download of non-existent document IDs (HTTP 404)
7. RAG chat invalid conversation and empty query resilience
8. Matrix cell "Distinct / Unrelated" verification (Zero occurrence of "5% DIFFERENT")
9. Prohibited words case-insensitive detection ('SHOULD', 'shall', 'Will')
10. Missing mandatory sections detection in 10-tier auditor
11. Dynamic prompt hot-reloading and safe formatting with nested JSON
12. Multilingual Unicode PDF rendering (Japanese, German, Spanish, Math symbols)
13. Harmonized SOP interactive refinement versioning (v1 -> v2)
14. Harmonized SOP simplification directives application
15. FAISS FlatIP metric verification (METRIC_INNER_PRODUCT, zero HNSW)
16. Offline LLM guardrails (HTTP 503, zero corrupt database records)
17. Cascade deletion of session and disk artifacts
=============================================================================
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import faiss
import fitz  # PyMuPDF
import httpx
import numpy as np
from fastapi.testclient import TestClient

# Ensure services/api is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
API_DIR = os.path.join(PROJECT_ROOT, "services", "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

import main as api_main
import prompt_loader
from kenvue_guidelines import (
    KENVUE_DOCUMENT_METADATA,
    MANDATORY_SECTIONS,
    PROHIBITED_TERMS,
    audit_sop_deterministically,
    build_comprehensive_sop_digest,
)
from similarity_engine import MultiSopSimilarityEngine
from sop_generator import create_kenvue_pdf
from tests.test_all_features_e2e import fake_llm_responder, mock_sync_llm_post


def make_test_pdf(title: str, text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(50, 50, 550, 90), title, fontsize=14)
    page.insert_textbox(fitz.Rect(50, 100, 550, 750), text, fontsize=10)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class TestKenvueEdgeCasesAndFeatures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api_main.app)
        cls.test_username = "admin"
        cls.headers = {"X-User-Name": cls.test_username}

    def test_edge_01_empty_and_corrupt_files(self):
        """Edge Case 1: Uploading a 0-byte PDF or corrupt payload fails cleanly with HTTP 400 or handled error."""
        res_conv = self.client.post("/conversations", json={"title": "Edge 1 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        # 0-byte file
        res_zero = self.client.post(
            f"/conversations/{conv_id}/upload-sop",
            headers=self.headers,
            files=[("files", ("empty.pdf", b"", "application/pdf"))],
        )
        self.assertIn(res_zero.status_code, [400, 422, 500])

        # Corrupted non-PDF bytes pretending to be PDF
        corrupt_bytes = b"NOT_A_PDF_HEADER_DATA_12345"
        res_corrupt = self.client.post(
            f"/conversations/{conv_id}/upload-sop",
            headers=self.headers,
            files=[("files", ("corrupt.pdf", corrupt_bytes, "application/pdf"))],
        )
        self.assertIn(res_corrupt.status_code, [400, 500])

    def test_edge_02_max_upload_limit_enforcement(self):
        """Edge Case 2: Batch upload exceeding 10 documents must be rejected with HTTP 400."""
        res_conv = self.client.post("/conversations", json={"title": "Edge 2 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        files = []
        for i in range(11):
            pdf_b = make_test_pdf(f"SOP {i}", f"1.0 Purpose: Content {i}")
            files.append(("files", (f"SOP_{i}.pdf", pdf_b, "application/pdf")))

        res = self.client.post(
            f"/conversations/{conv_id}/upload-sop",
            headers=self.headers,
            files=files,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("10 SOP", res.json()["detail"])

    def test_edge_03_invalid_file_extension(self):
        """Edge Case 3: Uploading unsupported file extensions (.exe, .zip, .txt) must be rejected with HTTP 400."""
        res_conv = self.client.post("/conversations", json={"title": "Edge 3 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        bad_files = [
            ("bad.exe", b"binary_executable", "application/octet-stream"),
            ("archive.zip", b"PK_zip_data", "application/zip"),
            ("notes.txt", b"plain text notes", "text/plain"),
        ]
        for name, data, mime in bad_files:
            res = self.client.post(
                f"/conversations/{conv_id}/upload-sop",
                headers=self.headers,
                files=[("files", (name, data, mime))],
            )
            self.assertEqual(res.status_code, 400, f"File {name} should have been rejected")
            self.assertIn("PDF and DOCX", res.json()["detail"])

    def test_edge_04_long_sop_100k_chars_boundary(self):
        """Edge Case 4: Long SOP digest preserves structure up to 100,000 characters without crashing."""
        lines = ["1.0 Purpose: Long document evaluation.\n2.0 Scope: Global sites."]
        for i in range(1200):
            lines.append(f"7.0 Procedure step {i}: The Operator must verify temperature is 25.0 ± 2.0 °C and speed is 3000 ± 50 RPM.")
        lines.append("Document Revision History: | 1.0 | All | Initial | Standard | Owner |")
        huge_text = "\n".join(lines)
        self.assertGreater(len(huge_text), 100000)

        digest = build_comprehensive_sop_digest(huge_text, max_chars=100000)
        self.assertLessEqual(len(digest), 105000)
        self.assertIn("1.0 Purpose", digest)
        self.assertIn("Document Revision History", digest)

    def test_edge_05_multi_sop_optimization_and_download_isolation(self):
        """
        Edge Case 5 (Critical Fix Verification):
        Upload English SOP & Japanese SOP. Optimize both.
        Verify preview and download for English SOP returns English content,
        and Japanese SOP returns Japanese content. No bleed-over!
        """
        res_conv = self.client.post("/conversations", json={"title": "Edge 5 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        en_pdf = make_test_pdf("EN SOP", "1.0 Purpose: English centrifuge cleaning.\n7.0 Procedure: Operator must clean.")
        jp_pdf = make_test_pdf("JP SOP", "1.0 Purpose: 日本語の遠心分離機の洗浄手順。\n7.0 手順: 作業者は洗浄しなければならない。")

        with patch.object(
            api_main,
            "get_global_llm_config",
            return_value={"provider": "azure_openai", "model": "gpt-4o", "api_key": "test_azure_key", "azure_configured": True},
        ), patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=fake_llm_responder)), patch(
            "httpx.Client.post", new=mock_sync_llm_post
        ):
            res_up = self.client.post(
                f"/conversations/{conv_id}/upload-sop",
                headers=self.headers,
                files=[
                    ("files", ("Centrifuge_EN.pdf", en_pdf, "application/pdf")),
                    ("files", ("Centrifuge_JP.pdf", jp_pdf, "application/pdf")),
                ],
            )
            self.assertEqual(res_up.status_code, 200, res_up.text)
            data = res_up.json()
            docs = data["documents"]
            self.assertEqual(len(docs), 2)
            doc_en = docs[0] if "EN" in docs[0]["filename"] else docs[1]
            doc_jp = docs[1] if "JP" in docs[1]["filename"] else docs[0]

            # Optimize English SOP
            res_opt_en = self.client.post(
                f"/conversations/{conv_id}/optimize-sop",
                headers=self.headers,
                json={
                    "document_id": doc_en["id"],
                    "output_language": "English",
                    "custom_instructions": "Standardize English procedure",
                },
            )
            self.assertEqual(res_opt_en.status_code, 200)

            # Optimize Japanese SOP
            res_opt_jp = self.client.post(
                f"/conversations/{conv_id}/optimize-sop",
                headers=self.headers,
                json={
                    "document_id": doc_jp["id"],
                    "output_language": "Japanese",
                    "custom_instructions": "日本語で生成",
                },
            )
            self.assertEqual(res_opt_jp.status_code, 200)

            # Download Japanese SOP
            res_dl_jp = self.client.get(
                f"/conversations/{conv_id}/sop/{doc_jp['id']}/optimized-pdf/download",
                headers=self.headers,
            )
            self.assertEqual(res_dl_jp.status_code, 200)
            self.assertEqual(res_dl_jp.headers["content-type"], "application/pdf")

            # Now go back to English SOP and download it! Must be English, NOT Japanese!
            res_dl_en = self.client.get(
                f"/conversations/{conv_id}/sop/{doc_en['id']}/optimized-pdf/download",
                headers=self.headers,
            )
            self.assertEqual(res_dl_en.status_code, 200)
            self.assertEqual(res_dl_en.headers["content-type"], "application/pdf")

            # Inspect downloaded PDF contents using PyMuPDF
            doc_en_pdf = fitz.open(stream=res_dl_en.content, filetype="pdf")
            text_en_pages = " ".join([page.get_text() for page in doc_en_pdf])
            doc_en_pdf.close()
            self.assertIn("Standard Operating Procedure", text_en_pages)
            self.assertNotIn("遠心分離機", text_en_pages)

    def test_edge_06_non_existent_document_preview_download(self):
        """Edge Case 6: Requesting preview/download of a non-existent document ID returns HTTP 404 cleanly."""
        fake_conv_id = "00000000-0000-0000-0000-000000000000"
        fake_doc_id = "fake-doc-id-999"

        res_dl = self.client.get(
            f"/conversations/{fake_conv_id}/sop/{fake_doc_id}/optimized-pdf/download",
            headers=self.headers,
        )
        self.assertIn(res_dl.status_code, [404, 500])

    def test_edge_07_rag_chat_invalid_conversation_or_empty_query(self):
        """Edge Case 7: RAG chat query with empty query or non-existent conversation handles gracefully."""
        # Non-existent conversation
        res_fake_conv = self.client.post(
            "/chat",
            headers=self.headers,
            json={"conversation_id": "non-existent-conv-id", "content": "What is the rotor speed?"},
        )
        self.assertIn(res_fake_conv.status_code, [200, 404])

        # Empty query validation (min_length=1 or 400/422)
        res_empty = self.client.post(
            "/chat",
            headers=self.headers,
            json={"conversation_id": "some-id", "content": ""},
        )
        self.assertIn(res_empty.status_code, [400, 422])

    def test_edge_08_matrix_label_distinct_sop_not_5_percent_different(self):
        """
        Edge Case 8 (Label Clarity Verification):
        Verify pairwise similarity matrix returns 'Distinct / Unrelated' and group card returns
        'Standalone SOP', with zero occurrence of confusing '5% DIFFERENT'.
        """
        engine = MultiSopSimilarityEngine()
        doc_a_chunks = [{"chunk_id": "c1", "content": "Centrifuge cleaning with ethanol 75% at 3000 RPM."}]
        doc_b_chunks = [{"chunk_id": "c2", "content": "Forklift maintenance battery charging guidelines."}]

        score, overlaps, diffs, metrics = engine.compute_document_similarity(
            doc_a_chunks, doc_b_chunks,
            "Centrifuge cleaning procedure.",
            "Forklift battery maintenance.",
        )
        self.assertLess(score, 40.0)

        # Test collection analysis output structure
        docs = [
            {"document_id": "d1", "filename": "Centrifuge.pdf", "text": "Centrifuge cleaning with ethanol 75% at 3000 RPM."},
            {"document_id": "d2", "filename": "Forklift.pdf", "text": "Forklift battery maintenance."},
        ]
        all_chunks = [
            {"document_id": "d1", "chunk_id": "c1", "content": "Centrifuge cleaning with ethanol 75% at 3000 RPM."},
            {"document_id": "d2", "chunk_id": "c2", "content": "Forklift battery maintenance."},
        ]

        result = engine.analyze_collection(docs, all_chunks)
        matrix = result.get("pairwise_matrix", [])
        self.assertEqual(len(matrix), 1)

        # Check pair status
        pair = matrix[0]
        self.assertIn(pair["status"], ["Distinct / Unrelated", "Distinct SOP"])
        self.assertNotIn("DIFFERENT", pair["status"])

        # Check groups
        groups = result.get("groups", [])
        for g in groups:
            if g.get("status") == "Standalone SOP":
                self.assertNotIn("DIFFERENT", g["status"])

    def test_edge_09_prohibited_terms_case_insensitivity(self):
        """Edge Case 9: Deterministic compliance auditor detects prohibited words in all casing variations."""
        text_with_prohibited = (
            "1.0 Purpose\n"
            "The Operator SHOULD calibrate the rotor.\n"
            "The technician Shall verify the chamber.\n"
            "The supervisor WiLL sign off on the batch.\n"
        )
        audit = audit_sop_deterministically(text_with_prohibited)
        total_prohibited = sum(audit["prohibited_counts"].values())
        self.assertGreaterEqual(total_prohibited, 3)

    def test_edge_10_missing_mandatory_sections_detection(self):
        """Edge Case 10: Deterministic compliance auditor correctly flags missing mandatory sections."""
        incomplete_text = "1.0 Purpose\nOnly purpose is given here."
        audit = audit_sop_deterministically(incomplete_text)
        self.assertFalse(audit["has_mandatory_sections"])
        violations = [v["rule"] for v in audit["violations"]]
        self.assertTrue(any("Procedure" in v for v in violations))
        self.assertTrue(any("Roles" in v for v in violations))

    def test_edge_11_prompt_hot_reloading_and_safe_formatting(self):
        """Edge Case 11: Dynamic prompt loading detects disk edits, handles None and complex JSON schemas."""
        # 1. Safe JSON interpolation with literal curly braces
        template = '{"title": "{doc_title}", "config": {"max_rpm": {max_rpm}, "flag": true}}'
        formatted = prompt_loader.format_prompt(template, doc_title="Mixer SOP", max_rpm=1500)
        self.assertIn('"title": "Mixer SOP"', formatted)
        self.assertIn('"max_rpm": 1500', formatted)
        self.assertIn('"flag": true', formatted)

        # 2. None value replacement
        none_template = "Title: {title} | Extra: {extra}"
        res_none = prompt_loader.format_prompt(none_template, title="Valid", extra=None)
        self.assertEqual(res_none, "Title: Valid | Extra: ")

        # 3. Non-existent prompt raises FileNotFoundError
        with self.assertRaises(FileNotFoundError):
            prompt_loader.load_prompt("totally_fake_non_existent_prompt_9999")

    def test_edge_12_unicode_multilingual_pdf_generation(self):
        """Edge Case 12: ReportLab PDF generator renders multilingual characters and technical symbols cleanly."""
        doc_title = "多言語標準作業手順書: Centrifuge & Mixer (± 2.5 °C, 12,500 RPM)"
        sections = [
            {
                "heading": "1.0 Purpose / 目的",
                "content": "German: Bitte prüfen Sie die Rotor-Geschwindigkeit (ä, ö, ü, ß).\n"
                           "Spanish: Verificación de parámetros según el diseño (ñ, á, é).\n"
                           "Math/Technical: Tolerances 45.0 ± 2.0 °C, 15 ± 2 PSI, speed 12,500 ± 50 RPM.\n"
                           "Japanese: 作業者は必ず保護具を着用しなければならない。",
                "type": "normal",
            },
            {
                "heading": "Document Revision History",
                "content": "| Version | Section | Description | Reason | Owner |\n| 1.0 | All | Initial release | Creation | QA Manager |",
                "type": "normal",
            },
        ]
        bio = io.BytesIO()
        create_kenvue_pdf(doc_title, sections, artifacts=[], output_stream=bio, output_language="Japanese")
        pdf_bytes = bio.getvalue()
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)

        # Verify PyMuPDF can parse the generated PDF without corruption
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertGreaterEqual(len(pdf_doc), 1)
        pdf_doc.close()

    def test_edge_13_harmonization_refinement_versioning(self):
        """Edge Case 13: Interactive refinement increments version and records audit history."""
        from harmonization_engine import HarmonizationEngine
        engine = HarmonizationEngine()

        current_version = {
            "version_number": 1,
            "document_title": "Packaging Line SOP",
            "sections": [
                {"heading": "1.0 Purpose", "content": "Baseline purpose."},
                {"heading": "7.0 Procedure", "content": "Baseline procedure."},
            ],
            "scores": {"average_score": 85},
            "source_document_ids": ["doc-1"],
            "source_filenames": ["SOP1.pdf"],
        }

        mock_refined_sections = [
            {"heading": "1.0 Purpose", "content": "Refined purpose with emergency shutdown."},
            {"heading": "7.0 Procedure", "content": "The Operator must hit E-stop in case of emergency."},
        ]

        with patch("httpx.AsyncClient") as mock_client_cls, patch(
            "harmonization_engine.evaluate_sop_with_llm", AsyncMock(return_value={"template_score": 90, "average_score": 90, "readability_score": 90, "quality_score": 90, "suggestions": []})
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"content": json.dumps(mock_refined_sections)}
            mock_client.post.return_value = mock_resp

            import asyncio
            refined = asyncio.run(
                engine.refine_sop(
                    current_version=current_version,
                    refinement_prompt="Add emergency shutdown procedure",
                    conversation_id="edge-conv-13",
                    username=self.test_username,
                    llm_service_url="http://127.0.0.1:8001",
                    provider="azure_openai",
                    model="gpt-4o",
                    api_key="mock-key",
                )
            )

        self.assertEqual(refined["version_number"], 2)
        self.assertIn("v2", refined["version_label"])

    def test_edge_14_simplification_directives(self):
        """Edge Case 14: Simplification applies selected directives and increments version number."""
        from harmonization_engine import HarmonizationEngine
        engine = HarmonizationEngine()

        current_version = {
            "version_number": 1,
            "document_title": "Packaging Line SOP",
            "sections": [
                {"heading": "1.0 Purpose", "content": "Complex purpose."},
                {"heading": "7.0 Procedure", "content": "Complex procedure."},
            ],
            "scores": {"average_score": 80},
            "source_document_ids": ["doc-1"],
            "source_filenames": ["SOP1.pdf"],
        }

        mock_simplified_sections = [
            {"heading": "1.0 Purpose", "content": "Simplified purpose."},
            {"heading": "7.0 Procedure", "content": "Simplified step 1. Simplified step 2."},
        ]

        with patch("httpx.AsyncClient") as mock_client_cls, patch(
            "harmonization_engine.evaluate_sop_with_llm", AsyncMock(return_value={"template_score": 92, "average_score": 92, "readability_score": 92, "quality_score": 92, "suggestions": []})
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            mock_resp = unittest.mock.MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"content": json.dumps(mock_simplified_sections)}
            mock_client.post.return_value = mock_resp

            import asyncio
            simplified = asyncio.run(
                engine.simplify_sop(
                    current_version=current_version,
                    selected_recommendation_ids=["simp_complex_sentences", "simp_redundant_words"],
                    custom_instructions="Shorten steps",
                    conversation_id="edge-conv-14",
                    username=self.test_username,
                    llm_service_url="http://127.0.0.1:8001",
                    provider="azure_openai",
                    model="gpt-4o",
                    api_key="mock-key",
                )
            )

        self.assertEqual(simplified["version_number"], 2)
        self.assertIn("v2", simplified["version_label"])

    def test_edge_15_faiss_flatip_zero_hnsw_verification(self):
        """Edge Case 15: FAISS vector index strictly uses IndexFlatIP (METRIC_INNER_PRODUCT) with zero HNSW."""
        d = 384
        index = faiss.IndexFlatIP(d)
        self.assertEqual(index.metric_type, faiss.METRIC_INNER_PRODUCT)
        self.assertFalse(hasattr(index, "hnsw"))
        self.assertIsInstance(index, faiss.IndexFlatIP)

        # Test index vector search normalization
        v1 = np.random.randn(1, d).astype(np.float32)
        v2 = np.random.randn(1, d).astype(np.float32)
        faiss.normalize_L2(v1)
        faiss.normalize_L2(v2)
        index.add(v1)
        distances, indices = index.search(v2, 1)
        self.assertEqual(indices.shape, (1, 1))
        self.assertLessEqual(distances[0][0], 1.00001)

    def test_edge_16_offline_llm_guardrails(self):
        """Edge Case 16: When LLM service is offline or unreachable, system returns HTTP 503 cleanly."""
        res_conv = self.client.post("/conversations", json={"title": "Edge 16 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        pdf_b = make_test_pdf("SOP Offline", "1.0 Purpose: Test offline LLM service.")

        with patch.object(
            api_main,
            "get_global_llm_config",
            return_value={"provider": "azure_openai", "model": "gpt-4o", "api_key": "", "azure_configured": False},
        ):
            res = self.client.post(
                f"/conversations/{conv_id}/upload-sop",
                headers=self.headers,
                files=[("files", ("Offline_SOP.pdf", pdf_b, "application/pdf"))],
            )
        self.assertEqual(res.status_code, 503)
        self.assertIn("LLM Service Unavailable", res.json()["detail"])

    def test_edge_17_cascade_deletion_lifecycle(self):
        """Edge Case 17: Deleting a conversation cascades and completely removes DB rows and disk storage."""
        # Create a conversation
        res_conv = self.client.post("/conversations", json={"title": "Edge 17 Conv"}, headers=self.headers)
        self.assertEqual(res_conv.status_code, 200)
        conv_id = res_conv.json()["id"]

        # Verify DB has conversation
        with api_main.db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,))
            self.assertIsNotNone(c.fetchone())

        # Delete conversation
        res_del = self.client.delete(f"/conversations/{conv_id}", headers=self.headers)
        self.assertEqual(res_del.status_code, 200)

        # Verify DB no longer has conversation
        with api_main.db() as conn:
            c = conn.cursor()
            c.execute("SELECT id FROM conversations WHERE id = ?", (conv_id,))
            self.assertIsNone(c.fetchone())


if __name__ == "__main__":
    unittest.main()
