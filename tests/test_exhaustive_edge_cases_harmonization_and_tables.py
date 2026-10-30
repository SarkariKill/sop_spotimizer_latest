#!/usr/bin/env python3
"""
=============================================================================
Exhaustive Edge Cases & Stress Test Suite:
Structured Tables, Chunking Integrity & Section-to-Section Harmonization
=============================================================================
This test suite covers deep edge cases and stress scenarios:
1. Multi-Page Continuation Table (3+ Pages) with header suppression
2. Multiple Distinct Tables on Same and Adjacent Pages
3. DOCX Table Extraction and Dimension Integrity
4. Markdown Table Row Preservation in Hierarchical Chunking (no mid-row slicing)
5. Multi-SOP Scalability Matrix: N=4 (6 pairs) and N=5 (10 pairs)
6. Multi-Parameter Conflict Detection across 6 Units (RPM, °C, bar, pH, min, mg/mL)
7. Parameter Consensus Verification (Zero false positive conflicts on agreed values)
8. Case 5 Preservation of Unique Domain Procedures across Multiple SOPs
9. Case 7 Structured Table Deduplication & Row Merge
10. Native ReportLab Table Flowable PDF Generation & Text Searchability
11. Full End-to-End Harmonization Pipeline Execution with State Verification
=============================================================================
"""

import asyncio
import io
import json
import os
import re
import sys
import unittest
from typing import Any, Dict, List

import docx
import pymupdf
from fastapi.testclient import TestClient
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table as RLTable,
    TableStyle,
)

# Ensure services/api is on sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
API_DIR = os.path.join(PROJECT_ROOT, "services", "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

import main as api_main
from harmonization_engine import (
    align_sections_across_sops,
    build_section_inventory,
    extract_sections_from_text,
    harmonization_engine,
    perform_pairwise_and_group_section_comparisons,
    synthesize_conservative_section_content,
    synthesize_conservative_sections_deterministically,
)
from kenvue_guidelines import (
    audit_sop_deterministically,
    enforce_kenvue_template_standards,
)
from pdf_processor import extract_sop_docx, extract_sop_pdf
from rag_engine import create_hierarchical_chunks
from sop_generator import (
    build_reportlab_table_flowable,
    create_kenvue_pdf,
    parse_markdown_table_lines,
    split_content_into_flowable_blocks,
)
from validation_agent import validation_agent


class TestExhaustiveHarmonizationAndTables(unittest.TestCase):
    """
    Exhaustive verification suite for table extraction, chunking, and harmonization.
    """

    def setUp(self):
        self.client = TestClient(api_main.app)

    # -------------------------------------------------------------------------
    # Test 1: Multi-Page Continuation Table (3 Pages)
    # -------------------------------------------------------------------------
    def test_multi_page_3_page_table_continuation(self):
        """
        Verify that a table spanning across 3 pages is stitched into a single
        continuous table artifact, with header repeated on each page suppressed.
        """
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        elements.append(Paragraph("7.0 Extended Continuous Procedure", styles["Heading1"]))
        elements.append(Spacer(1, 10))

        headers = ["Step", "Operational Target", "Acceptance Criteria", "Verification Method"]
        t_style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C8102E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])

        # Page 1 table
        p1_rows = [headers] + [[f"Step 1.{i}", f"Target {i}", "Pass", "Visual check"] for i in range(1, 6)]
        elements.append(RLTable(p1_rows, style=t_style))
        elements.append(PageBreak())

        # Page 2 table (repeated headers)
        elements.append(Paragraph("7.0 Extended Continuous Procedure (Cont.)", styles["Heading2"]))
        p2_rows = [headers] + [[f"Step 2.{i}", f"Target {i}", "Pass", "Gauge check"] for i in range(1, 6)]
        elements.append(RLTable(p2_rows, style=t_style))
        elements.append(PageBreak())

        # Page 3 table (repeated headers)
        elements.append(Paragraph("7.0 Extended Continuous Procedure (Cont. 2)", styles["Heading2"]))
        p3_rows = [headers] + [[f"Step 3.{i}", f"Target {i}", "Pass", "QA Sign-off"] for i in range(1, 6)]
        elements.append(RLTable(p3_rows, style=t_style))

        doc.build(elements)
        pdf_bytes = buf.getvalue()

        pages_data, artifacts, summary = extract_sop_pdf(pdf_bytes, conversation_id="conv_test_multi3", filename="3page_table.pdf")
        tables = [a for a in artifacts if a.get("artifact_type") == "table"]
        self.assertGreaterEqual(len(tables), 1, "Should detect at least 1 stitched multi-page table")

        stitched = tables[0]
        # Should start at page 1 and end at page 3
        self.assertEqual(stitched.get("page_start"), 1)
        self.assertEqual(stitched.get("page_end"), 3)
        # Total rows should be 5 + 5 + 5 = 15 data rows
        data_rows = stitched.get("rows", [])
        self.assertEqual(len(data_rows), 15, f"Expected 15 data rows across 3 pages, got {len(data_rows)}")
        # Header should be preserved once
        self.assertEqual(stitched.get("headers"), headers)

    # -------------------------------------------------------------------------
    # Test 2: Multiple Distinct Tables on Same and Adjacent Pages
    # -------------------------------------------------------------------------
    def test_multiple_distinct_tables_on_pages(self):
        """
        Verify that multiple distinct tables on the same page and different pages
        are extracted with their distinct column structures and headers.
        """
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        t_style = TableStyle([
            ("GRID", (0, 0), (-1, -1), 1, colors.HexColor("#000000")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#C8102E")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])

        # Page 1: Table 1 (Roles) and Table 2 (Equipment)
        elements.append(Paragraph("4.0 Roles and Responsibilities", styles["Heading1"]))
        roles_table = [
            ["Role", "Responsibility"],
            ["Operator", "Execute steps according to SOP."],
            ["Supervisor", "Verify line clearance."],
        ]
        elements.append(RLTable(roles_table, style=t_style))
        elements.append(Spacer(1, 15))

        elements.append(Paragraph("5.0 Equipment and Materials", styles["Heading1"]))
        equip_table = [
            ["Equipment ID", "Description", "Calibration Due"],
            ["BAL-001", "Analytical Balance", "2026-12-31"],
            ["PH-002", "Digital pH Meter", "2026-11-15"],
        ]
        elements.append(RLTable(equip_table, style=t_style))
        elements.append(PageBreak())

        # Page 2: Table 3 (Revision History)
        elements.append(Paragraph("Revision History", styles["Heading1"]))
        rev_table = [
            ["Version", "Date", "Description", "Author"],
            ["1.0", "2026-01-01", "Initial draft", "J. Doe"],
        ]
        elements.append(RLTable(rev_table, style=t_style))

        doc.build(elements)
        pages_data, artifacts, summary = extract_sop_pdf(buf.getvalue(), conversation_id="conv_distinct_tbl", filename="distinct_tbl.pdf")

        tables = [a for a in artifacts if a.get("artifact_type") == "table"]
        self.assertGreaterEqual(len(tables), 3, f"Expected 3 distinct tables, extracted {len(tables)}")

        # Verify distinct headers
        extracted_headers = [t.get("headers", []) for t in tables]
        self.assertTrue(any("Role" in h for h in extracted_headers))
        self.assertTrue(any("Equipment ID" in h for h in extracted_headers))
        self.assertTrue(any("Version" in h for h in extracted_headers))

    # -------------------------------------------------------------------------
    # Test 3: DOCX Table Extraction and Dimension Integrity
    # -------------------------------------------------------------------------
    def test_docx_table_extraction(self):
        """
        Verify DOCX table extraction extracts structured headers, rows, and dimensions.
        """
        doc = docx.Document()
        doc.add_heading("7.0 Procedure", level=1)
        doc.add_paragraph("Table 1: Critical Process Parameters")

        table = doc.add_table(rows=3, cols=3)
        headers = ["Parameter", "Target", "Tolerance"]
        for j, text in enumerate(headers):
            table.cell(0, j).text = text

        data = [
            ["Agitation Speed", "1500 RPM", "± 50 RPM"],
            ["Jacket Temperature", "25 °C", "± 2 °C"],
        ]
        for i, row in enumerate(data):
            for j, val in enumerate(row):
                table.cell(i + 1, j).text = val

        buf = io.BytesIO()
        doc.save(buf)

        pages_data, artifacts, summary = extract_sop_docx(buf.getvalue(), conversation_id="conv_docx_test", filename="test.docx")
        tables = [a for a in artifacts if a.get("artifact_type") == "table"]
        self.assertEqual(len(tables), 1)
        tbl = tables[0]
        self.assertEqual(tbl["headers"], headers)
        self.assertEqual(len(tbl["rows"]), 2)
        self.assertEqual(tbl["num_cols"], 3)
        self.assertEqual(tbl["num_rows"], 2)

    # -------------------------------------------------------------------------
    # Test 4: Markdown Table Row Preservation in Chunking
    # -------------------------------------------------------------------------
    def test_markdown_table_row_preservation_in_chunking(self):
        """
        Verify that large Markdown tables in section content are never split mid-row
        across 250-character micro-chunk boundaries.
        """
        table_rows = [
            f"| Step {i} | Add component {i} into vessel | 10.{i} g | Complete |"
            for i in range(1, 30)
        ]
        table_content = (
            "| Step | Action | Amount | Status |\n"
            "| --- | --- | --- | --- |\n"
            + "\n".join(table_rows)
        )
        full_text = (
            "# 7.0 Procedure\n"
            "Follow the compounding instructions detailed below.\n\n"
            + table_content
        )

        pages_data = [{"page": 1, "text": full_text}]
        parent_chunks, child_chunks = create_hierarchical_chunks(
            pages_data=pages_data,
            document_id="SOP-STRESS-001",
            filename="SOP-STRESS-001.pdf",
            artifacts_data=[{"id": "tbl_stress_1", "page": 1, "page_start": 1, "page_end": 1, "artifact_type": "table"}],
            child_chunk_size=150,  # Deliberately small to force multiple splits
        )

        self.assertGreaterEqual(len(child_chunks), 5)
        for chunk in child_chunks:
            chunk_text = chunk["text"]
            lines = chunk_text.strip().split("\n")
            for line in lines:
                if line.startswith("|"):
                    # Every table line must end with '|' and not be truncated mid-cell
                    self.assertTrue(
                        line.endswith("|"),
                        f"Table line was sliced mid-cell: {line}"
                    )
            # Table-specific chunks should have metadata
            if "|" in chunk_text:
                self.assertTrue(chunk.get("has_table"))
                self.assertIn("tbl_stress_1", chunk.get("table_ids", []))

    # -------------------------------------------------------------------------
    # Test 5: Multi-SOP Scalability Matrix: N=4 (6 pairs) and N=5 (10 pairs)
    # -------------------------------------------------------------------------
    def test_multi_sop_scalability_pairwise_matrix(self):
        """
        Verify exact n*(n-1)/2 pairwise comparisons generated for N=4 (6 pairs)
        and N=5 (10 pairs) with symmetric consistency.
        """
        def make_sop_doc(fn, speed):
            return {
                "id": fn,
                "filename": fn,
                "title": f"Standard Procedure {fn}",
                "sections": [
                    {"heading": "1.0 Purpose", "content": f"Purpose for {fn}."},
                    {"heading": "7.0 Procedure", "content": f"Agitate solution at {speed} for 30 minutes."},
                ],
            }

        # N = 4 SOPs -> 4 * 3 / 2 = 6 pairs
        filenames_4 = ["SOP_1.pdf", "SOP_2.pdf", "SOP_3.pdf", "SOP_4.pdf"]
        sops_4 = [make_sop_doc(fn, f"{1000 + i*200} RPM") for i, fn in enumerate(filenames_4)]
        inv_4 = build_section_inventory(sops_4)
        aligned_4 = align_sections_across_sops(inv_4)
        comp_4 = perform_pairwise_and_group_section_comparisons(aligned_4, filenames_4)

        self.assertEqual(comp_4["pairwise_pairs_total"], 6, "Expected exactly 6 pairs for N=4")

        # N = 5 SOPs -> 5 * 4 / 2 = 10 pairs
        filenames_5 = filenames_4 + ["SOP_5.pdf"]
        sops_5 = [make_sop_doc(fn, f"{1000 + i*200} RPM") for i, fn in enumerate(filenames_5)]
        inv_5 = build_section_inventory(sops_5)
        aligned_5 = align_sections_across_sops(inv_5)
        comp_5 = perform_pairwise_and_group_section_comparisons(aligned_5, filenames_5)

        self.assertEqual(comp_5["pairwise_pairs_total"], 10, "Expected exactly 10 pairs for N=5")

    # -------------------------------------------------------------------------
    # Test 6: Multi-Dimensional Parameter Conflict Detection across 6 Units
    # -------------------------------------------------------------------------
    def test_multi_parameter_conflict_detection_across_units(self):
        """
        Verify that conflicting values across multiple units (RPM, °C, bar, pH, min, mg/mL)
        are all detected and that validation fails unless explicitly flagged.
        """
        sops = [
            {
                "id": "SOP_Site_A.pdf",
                "filename": "SOP_Site_A.pdf",
                "title": "Site A Compounding SOP",
                "sections": [
                    {
                        "heading": "7.0 Procedure",
                        "content": (
                            "Operate mixer at 1500 RPM.\n"
                            "Maintain temperature at 25 °C.\n"
                            "Pressurize chamber to 1.5 bar.\n"
                            "Adjust solution until pH 7.0.\n"
                            "Mix continuously for 30 minutes.\n"
                            "Final active concentration must be 5 mg/mL."
                        ),
                    }
                ],
            },
            {
                "id": "SOP_Site_B.pdf",
                "filename": "SOP_Site_B.pdf",
                "title": "Site B Compounding SOP",
                "sections": [
                    {
                        "heading": "7.0 Procedure",
                        "content": (
                            "Operate mixer at 2000 RPM.\n"
                            "Maintain temperature at 35 °C.\n"
                            "Pressurize chamber to 2.2 bar.\n"
                            "Adjust solution until pH 5.5.\n"
                            "Mix continuously for 45 minutes.\n"
                            "Final active concentration must be 10 mg/mL."
                        ),
                    }
                ],
            },
        ]

        inv = build_section_inventory(sops)
        aligned = align_sections_across_sops(inv)
        comp = perform_pairwise_and_group_section_comparisons(aligned, [s["filename"] for s in sops])
        conflicts = comp["parameter_conflicts"]

        self.assertGreaterEqual(len(conflicts), 5, f"Expected at least 5 parameter conflicts, found {len(conflicts)}")

        # Unflagged harmonized text MUST fail validation
        unflagged_sections = [
            {"heading": "1.0 Purpose", "content": "Compounding SOP purpose."},
            {"heading": "2.0 Scope", "content": "All sites."},
            {"heading": "3.0 Definitions", "content": "| Term | Definition |\n| Active | API |"},
            {"heading": "4.0 Roles and Responsibilities", "content": "| Role | Responsibility |\n| Operator | Mixes |"},
            {
                "heading": "7.0 Procedure",
                "content": "Operate mixer at 1500 RPM. Maintain temperature at 25 °C.",  # Silently adopted Site A
            },
            {"heading": "Revision History", "content": "| Version | Description |\n| 1.0 | Initial |"},
        ]

        val_res = validation_agent.validate_sections(
            sections=unflagged_sections,
            selected_suggestions=[],
            custom_instructions="",
            doc_title="Compounding SOP",
            parameter_conflicts=conflicts,
        )
        self.assertFalse(val_res["passed"], "Validation must reject silent parameter resolution")
        self.assertGreater(len(val_res["missing_conflicts"]), 0)

        # Remediate sections
        remediated_secs, _ = validation_agent.remediate_sections(
            sections=unflagged_sections,
            missing_suggestions=[],
            missing_custom=[],
            doc_title="Compounding SOP",
            missing_conflicts=val_res["missing_conflicts"],
        )
        val_res_remediated = validation_agent.validate_sections(
            sections=remediated_secs,
            selected_suggestions=[],
            custom_instructions="",
            doc_title="Compounding SOP",
            parameter_conflicts=conflicts,
        )
        self.assertTrue(val_res_remediated["passed"], "Remediated SOP with conflict callouts must pass")

    # -------------------------------------------------------------------------
    # Test 7: Parameter Consensus Verification (Zero False Positives)
    # -------------------------------------------------------------------------
    def test_parameter_consensus_zero_false_positives(self):
        """
        Verify that when all SOPs agree on parameter values (consensus),
        NO parameter conflicts are flagged.
        """
        sops = [
            {
                "id": "SOP_1.pdf",
                "filename": "SOP_1.pdf",
                "title": "SOP 1",
                "sections": [
                    {
                        "heading": "7.0 Procedure",
                        "content": "Autoclave instruments at 121 °C under 1.5 bar for 20 minutes.",
                    }
                ],
            },
            {
                "id": "SOP_2.pdf",
                "filename": "SOP_2.pdf",
                "title": "SOP 2",
                "sections": [
                    {
                        "heading": "7.0 Procedure",
                        "content": "Instruments must be autoclaved at 121 °C at 1.5 bar for 20 minutes.",
                    }
                ],
            },
        ]

        inv = build_section_inventory(sops)
        aligned = align_sections_across_sops(inv)
        comp = perform_pairwise_and_group_section_comparisons(aligned, [s["filename"] for s in sops])

        self.assertEqual(len(comp["parameter_conflicts"]), 0, f"Expected 0 conflicts for identical parameters, got {comp['parameter_conflicts']}")

    # -------------------------------------------------------------------------
    # Test 8: Case 5 Unique Domain Procedures Preservation
    # -------------------------------------------------------------------------
    def test_case_5_unique_domain_procedures_preservation(self):
        """
        Verify that unique specialized procedures from different SOPs are both
        preserved in the harmonized output and not dropped.
        """
        sops = [
            {
                "id": "SOP_A.pdf",
                "filename": "SOP_A.pdf",
                "title": "Aseptic Filling",
                "sections": [
                    {"heading": "1.0 Purpose", "content": "Aseptic filling standards."},
                    {"heading": "7.1 Core Filling", "content": "Fill vials under ISO 5 laminar hood."},
                    {"heading": "7.2 Nitrogen Overlay", "content": "Purge headspace with sterile nitrogen before sealing."},
                ],
            },
            {
                "id": "SOP_B.pdf",
                "filename": "SOP_B.pdf",
                "title": "Vial Inspection",
                "sections": [
                    {"heading": "1.0 Purpose", "content": "Vial inspection standards."},
                    {"heading": "7.1 Core Filling", "content": "Fill vials under ISO 5 laminar hood."},
                    {"heading": "7.3 Automated Optical Inspection", "content": "Inspect each sealed vial with laser particle detector."},
                ],
            },
        ]

        inv = build_section_inventory(sops)
        aligned = align_sections_across_sops(inv)
        comp = perform_pairwise_and_group_section_comparisons(aligned, [s["filename"] for s in sops])
        harmonized_sections = synthesize_conservative_sections_deterministically(aligned, comp, doc_title="Preservation Test")

        headings = [s["heading"] for s in harmonized_sections]
        contents = [s["content"] for s in harmonized_sections]
        self.assertTrue(
            any("Nitrogen Overlay" in h or "Nitrogen Overlay" in c for h, c in zip(headings, contents)),
            "Unique domain procedure 'Nitrogen Overlay' must be preserved",
        )
        self.assertTrue(
            any("Automated Optical Inspection" in h or "Automated Optical Inspection" in c for h, c in zip(headings, contents)),
            "Unique domain procedure 'Automated Optical Inspection' must be preserved",
        )

    # -------------------------------------------------------------------------
    # Test 9: Case 7 Structured Table Deduplication & Row Merge
    # -------------------------------------------------------------------------
    def test_case_7_structured_table_deduplication(self):
        """
        Verify that overlapping tables across SOPs are merged without duplicate rows.
        """
        tbl_1 = (
            "| Role | Responsibilities |\n"
            "| --- | --- |\n"
            "| Plant Manager | Allocates site resources. |\n"
            "| Quality Assurance | Reviews change controls. |"
        )
        tbl_2 = (
            "| Role | Responsibilities |\n"
            "| --- | --- |\n"
            "| Quality Assurance | Reviews change controls. |\n"
            "| Production Lead | Oversees shift handoff. |"
        )

        sops = [
            {
                "id": "SOP_1.pdf",
                "filename": "SOP_1.pdf",
                "title": "Site 1",
                "sections": [{"heading": "4.0 Roles and Responsibilities", "content": tbl_1}],
            },
            {
                "id": "SOP_2.pdf",
                "filename": "SOP_2.pdf",
                "title": "Site 2",
                "sections": [{"heading": "4.0 Roles and Responsibilities", "content": tbl_2}],
            },
        ]

        inv = build_section_inventory(sops)
        aligned = align_sections_across_sops(inv)
        comp = perform_pairwise_and_group_section_comparisons(aligned, [s["filename"] for s in sops])
        harmonized_sections = synthesize_conservative_sections_deterministically(aligned, comp, doc_title="Table Merge Test")

        roles_sec = [s for s in harmonized_sections if "4.0" in s["heading"]][0]
        content = roles_sec["content"]

        self.assertIn("Plant Manager", content)
        self.assertIn("Production Lead", content)
        self.assertIn("Quality Assurance", content)
        # Quality Assurance row should appear only once (deduplicated)
        self.assertEqual(content.count("Quality Assurance"), 1, "Duplicate table row must be eliminated")

    # -------------------------------------------------------------------------
    # Test 10: Native ReportLab Table Flowable PDF Generation & Text Searchability
    # -------------------------------------------------------------------------
    def test_native_reportlab_table_pdf_rendering(self):
        """
        Verify that create_kenvue_pdf creates native, searchable ReportLab Table
        flowables for structured table artifacts.
        """
        sections = [
            {"heading": "1.0 Purpose", "content": "Define testing parameters for Kenvue."},
            {"heading": "2.0 Scope", "content": "All packaging lines."},
            {
                "heading": "3.0 Key Terms and Definitions",
                "content": "| Term | Definition |\n| CQA | Critical Quality Attribute |\n| CPP | Critical Process Parameter |",
            },
            {
                "heading": "4.0 Roles and Responsibilities",
                "content": "| Role | Responsibilities |\n| Analyst | Perform test. |\n| Reviewer | Check data. |",
            },
            {
                "heading": "7.0 Procedure",
                "content": "Execute sampling according to standard operating conditions.",
            },
            {
                "heading": "Revision History",
                "content": "| Version | Date | Description | Author |\n| 1.0 | 2026-10-26 | First release | QA Team |",
            },
        ]

        table_artifacts = [
            {
                "id": "tbl_artifact_1",
                "page": 1,
                "table_name": "Packaging Specifications",
                "headers": ["Seal Type", "Dwell Time", "Temperature", "Tolerance"],
                "rows": [
                    ["Pouch Seal", "1.2 s", "145 °C", "± 2 °C"],
                    ["Blister Seal", "0.8 s", "160 °C", "± 3 °C"],
                ],
            }
        ]

        buf = io.BytesIO()
        create_kenvue_pdf(
            title="Standard Packaging Validation SOP",
            sections=sections,
            artifacts=table_artifacts,
            output_stream=buf,
        )
        pdf_bytes = buf.getvalue()

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)

        # Inspect with PyMuPDF to ensure native vector text searchability
        pdf_doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        self.assertGreaterEqual(pdf_doc.page_count, 1)

        all_text = "\n".join([page.get_text() for page in pdf_doc])
        self.assertIn("Standard Packaging Validation SOP", all_text)
        self.assertIn("Pouch Seal", all_text)
        self.assertIn("Blister Seal", all_text)
        self.assertIn("145 °C", all_text)
        self.assertIn("Critical Quality Attribute", all_text)

    # -------------------------------------------------------------------------
    # Test 11: Full End-to-End Harmonization Pipeline Execution
    # -------------------------------------------------------------------------
    def test_full_harmonization_pipeline_execution(self):
        """
        Verify that harmonize_sops executes all stages (A through G) end-to-end,
        populates the full harmonization report, and returns valid enforced sections.
        """
        from unittest.mock import AsyncMock, patch

        raw_sops = [
            {
                "id": "SOP-SITE-01.pdf",
                "filename": "SOP-SITE-01.pdf",
                "title": "Site 01 Granulation SOP",
                "sections": [
                    {"heading": "1.0 Purpose", "content": "Define high-shear wet granulation."},
                    {"heading": "2.0 Scope", "content": "Granulator Line 1."},
                    {"heading": "3.0 Definitions", "content": "| Term | Definition |\n| LOD | Loss on Drying |"},
                    {"heading": "4.0 Roles", "content": "| Role | Task |\n| Granulator Operator | Loads powder |"},
                    {"heading": "7.0 Procedure", "content": "Add binder at 500 mL/min and impeller at 150 RPM."},
                    {"heading": "Revision History", "content": "| Version | Note |\n| 1.0 | Initial |"},
                ],
            },
            {
                "id": "SOP-SITE-02.pdf",
                "filename": "SOP-SITE-02.pdf",
                "title": "Site 02 Granulation SOP",
                "sections": [
                    {"heading": "1.0 Purpose", "content": "Define high-shear wet granulation operation."},
                    {"heading": "2.0 Scope", "content": "Granulator Line 2."},
                    {"heading": "3.0 Definitions", "content": "| Term | Definition |\n| LOD | Loss on Drying |"},
                    {"heading": "4.0 Roles", "content": "| Role | Task |\n| Granulator Operator | Loads powder |"},
                    {"heading": "7.0 Procedure", "content": "Add binder at 650 mL/min and impeller at 180 RPM."},
                    {"heading": "Revision History", "content": "| Version | Note |\n| 1.0 | Initial |"},
                ],
            },
        ]

        with patch("harmonization_engine.evaluate_sop_with_llm", new=AsyncMock(return_value={
            "template_score": 92,
            "readability_score": 88,
            "quality_score": 90,
            "average_score": 90,
            "summary": "High-shear wet granulation harmonized standard",
            "suggestions": [],
        })):
            result = asyncio.run(
                harmonization_engine.harmonize_sops(
                    conversation_id="conv_e2e_stress_test",
                    username="admin",
                    source_documents=raw_sops,
                    title_override="Harmonized High-Shear Wet Granulation SOP",
                )
            )

        self.assertIn("harmonized_sections", result)
        self.assertIn("harmonization_report", result)

        report = result["harmonization_report"]
        self.assertEqual(report["source_documents_count"], 2)
        self.assertEqual(report["pairwise_comparisons_count"], 1)
        self.assertGreater(report["section_inventory_count"], 0)
        self.assertGreater(report["aligned_sections_count"], 0)
        self.assertGreater(len(report["parameter_conflicts_flagged"]), 0)
        self.assertTrue(report["human_review_required"])

        # Check that harmonized sections adhere to Kenvue 10 tiers
        headings = [s["heading"] for s in result["harmonized_sections"]]
        self.assertTrue(any("1.0" in h for h in headings))
        self.assertTrue(any("2.0" in h for h in headings))
        self.assertTrue(any("3.0" in h for h in headings))
        self.assertTrue(any("4.0" in h for h in headings))
        self.assertTrue(any("7.0" in h for h in headings))
        self.assertTrue(any("Revision" in h for h in headings))

        # Check that parameter divergence callout is present in Procedure
        proc_sec = [s for s in result["harmonized_sections"] if "7.0" in s["heading"]][0]
        self.assertIn("[REVIEW REQUIRED - Parameter Divergence", proc_sec["content"])


if __name__ == "__main__":
    unittest.main()
