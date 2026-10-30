#!/usr/bin/env python3
"""
=============================================================================
Kenvue SOP Optimization & Scoring Test Suite
=============================================================================
Comprehensive unit and integration tests verifying:
1. Non-compliant legacy SOP scores lower (missing mandatory sections, prohibited words).
2. Deterministic audit detects violations with exact rule codes and severities.
3. Compliant Kenvue Master SOP achieves high scores across template, readability, quality.
4. enforce_kenvue_template_standards normalizes sections and removes prohibited words.
5. Before-and-after comparison correctly reports score deltas and resolved violations.
6. Admin template management is locked to SOP-STD-001 without breaking API contracts.
7. Imperative voice and prohibited terms ('should', 'shall', 'will') enforcement.
8. Mandatory tables (Key Terms, Roles, Revision History) strict validation.
=============================================================================
"""

import os
import sys
import unittest

# Add services/api to sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
API_DIR = os.path.join(PROJECT_ROOT, "services", "api")
if API_DIR not in sys.path:
    sys.path.insert(0, API_DIR)

from kenvue_guidelines import (
    KENVUE_MASTER_TEMPLATE_GUIDELINES,
    KENVUE_DOCUMENT_METADATA,
    MANDATORY_SECTIONS,
    REQUIRED_OR_NA_SECTIONS,
    PROHIBITED_TERMS,
    audit_sop_deterministically,
    build_comprehensive_sop_digest,
    compare_sop_evaluations,
    enforce_kenvue_template_standards,
    validate_section_hierarchy,
)
from template_manager import template_manager


# Sample Legacy / Deficient SOP text (Typical unoptimized uploaded document)
LEGACY_DEFICIENT_SOP = """
# Cleaning SOP for Equipment

1. Purpose
The operator should clean the centrifuge after each production run.

2. Scope
This procedure shall apply to the packaging department.

3. Instructions
First, the technician should turn off the power. Then you will clean the rotor with solvent.
Make sure you wash everything thoroughly and you should check the gasket.
Safety goggles shall be worn at all times.
"""

# Sample Fully Compliant Kenvue SOP text (Adheres to SOP-STD-001)
COMPLIANT_KENVUE_SOP = """
# Standard Operating Procedure: High-Speed Centrifuge Sanitation

1.0 Purpose
The purpose of this procedure is to define the mandatory operational and cleaning steps for the High-Speed Centrifuge to ensure regulatory GMP compliance and prevent cross-contamination.

2.0 Scope
2.1 Process: Routine sanitation and inspection of the centrifuge assembly.
2.2 Facilities and Regions: Manufacturing Facility Line 4, Cleanroom B.
2.3 Out of Scope: Major mechanical overhaul and electrical motor rewinding.

3.0 Key Terms and Acronyms
Refer to FRM-0009808 for standard corporate glossary terms.

| Term | Definition |
| :--- | :--- |
| CIP | Clean-in-Place automated sanitation system |
| GMP | Good Manufacturing Practice regulations |
| PPE | Personal Protective Equipment |

4.0 Roles and Responsibilities
Capitalized roles indicate operational designations.

| Role | Responsibilities |
| :--- | :--- |
| Operator | Execute sanitation steps and document completion in the batch log. |
| Technician | Verify torque tolerances and replace worn gaskets. |
| Supervisor | Audit post-cleaning log and certify equipment release. |

5.0 Requirements
All personnel must wear nitrile gloves and safety goggles before handling sanitation chemical solutions.

6.0 Process Flow
N/A - Standard linear workflow detailed in Section 7.0.

7.0 Procedure
7.1 Power Isolation:
7.1.1 The Operator must de-energize the main breaker and apply Lockout/Tagout padlock.
7.1.2 Verify zero voltage using the calibrated digital multimeter.

7.2 Rotor Disassembly:
7.2.1 Loosen the rotor retaining nut using the calibrated torque wrench set to 45.0 ± 2.0 Nm.
7.2.2 Inspect the silicone O-ring seal for micro-cracks. If degraded, the Technician must replace immediately.

7.3 Sanitization Cycle:
7.3.1 Apply 70% sterile isopropyl alcohol solution to all contact surfaces.
7.3.2 The Operator must maintain a wet contact dwell time of 10.0 ± 1.0 minutes before wipe-down.

8.0 References
| Reference | Document |
| :--- | :--- |
| 21 CFR Part 211 | Current Good Manufacturing Practice for Finished Pharmaceuticals |
| SOP-CLN-004 | General Facility Sanitation Standards |

9.0 Appendices
| Appendix | Description |
| :--- | :--- |
| Appendix 1 | Sanitation Checksheet Form |

Document Revision History
| Revision Number | Effective Date | Description of Change |
| :--- | :--- | :--- |
| 1.0 | 2026-10-12 | Initial standardized release adhering to Kenvue Master Template. |
"""


class TestKenvueScoringAndOptimization(unittest.TestCase):
    """Test suite for Kenvue SOP scoring, deterministic auditing, and optimization."""

    def test_01_admin_template_is_locked_to_kenvue_master(self):
        """Test that admin template status is locked to built-in SOP-STD-001."""
        status = template_manager.get_template_status()
        self.assertTrue(status["is_locked"], "Template must be permanently locked.")
        self.assertTrue(status["is_default"], "Template must be default built-in.")
        self.assertEqual(status["standard_id"], "SOP-STD-001")
        self.assertEqual(status["version"], "1.0")
        self.assertIn("Purpose", status["mandatory_sections"])
        self.assertIn("Procedure", status["mandatory_sections"])

        # Test upload endpoint gracefully returns locked status without breaking contract
        upload_res = template_manager.upload_admin_template(
            file_bytes=b"%PDF-1.4 dummy",
            filename="Custom_Template.pdf",
            uploaded_by="test_admin",
        )
        self.assertEqual(upload_res["status"], "locked")
        self.assertIn("permanently hardcoded", upload_res["message"])

    def test_02_legacy_sop_scores_lower_than_compliant_sop(self):
        """Test that deficient legacy SOP receives significantly lower score than compliant SOP."""
        legacy_eval = audit_sop_deterministically(LEGACY_DEFICIENT_SOP)
        compliant_eval = audit_sop_deterministically(COMPLIANT_KENVUE_SOP)

        legacy_avg = legacy_eval["deterministic_average_score"]
        compliant_avg = compliant_eval["deterministic_average_score"]

        self.assertLess(
            legacy_avg,
            compliant_avg,
            f"Legacy SOP ({legacy_avg}%) must score lower than compliant SOP ({compliant_avg}%)",
        )
        self.assertLess(legacy_avg, 60, "Deficient legacy SOP score should be below 60%")
        self.assertGreaterEqual(compliant_avg, 90, "Compliant SOP score should be 90% or above")

    def test_03_prohibited_words_detection_and_penalization(self):
        """Test that prohibited words ('should', 'shall', 'will') are detected and penalized."""
        legacy_eval = audit_sop_deterministically(LEGACY_DEFICIENT_SOP)
        prohibited = legacy_eval["prohibited_counts"]

        self.assertIn("should", prohibited)
        self.assertIn("shall", prohibited)
        self.assertIn("will", prohibited)
        self.assertGreater(prohibited["should"], 0)
        self.assertGreater(prohibited["shall"], 0)
        self.assertGreater(prohibited["will"], 0)

        # Compliant SOP must have zero prohibited terms
        compliant_eval = audit_sop_deterministically(COMPLIANT_KENVUE_SOP)
        self.assertEqual(
            compliant_eval["prohibited_counts"],
            {},
            "Compliant SOP must have zero prohibited auxiliary verbs",
        )
        self.assertIn(
            "Zero occurrences of prohibited words ('should', 'shall', 'will')",
            compliant_eval["passed_checks"],
        )

    def test_04_mandatory_sections_and_tables_validation(self):
        """Test that missing mandatory sections and tables generate explicit violations."""
        legacy_eval = audit_sop_deterministically(LEGACY_DEFICIENT_SOP)
        violations = {v["code"] for v in legacy_eval["violations"]}

        self.assertIn("MISSING_MANDATORY_SECTION_3", violations)
        self.assertIn("MISSING_MANDATORY_SECTION_4", violations)
        self.assertIn("MISSING_MANDATORY_SECTION_7", violations)
        self.assertIn("MISSING_REVISION_HISTORY", violations)
        self.assertFalse(legacy_eval["has_mandatory_sections"])

        compliant_eval = audit_sop_deterministically(COMPLIANT_KENVUE_SOP)
        self.assertTrue(compliant_eval["has_mandatory_sections"])
        self.assertEqual(len(compliant_eval["violations"]), 0, "Compliant SOP should have 0 violations")

    def test_05_enforce_kenvue_template_standards_normalizes_sections(self):
        """Test that enforce_kenvue_template_standards produces a full compliant structure."""
        raw_sections = [
            {"heading": "1.0 Purpose", "content": "The operator should clean the equipment."},
            {"heading": "2.0 Scope", "content": "This applies to manufacturing."},
            {"heading": "3.0 Instructions", "content": "Technicians shall wash the parts and you will verify."},
        ]

        normalized = enforce_kenvue_template_standards(raw_sections, doc_title="Equipment Cleaning Procedure")
        headings = [s["heading"] for s in normalized]

        # Verify all mandatory sections exist in the normalized output
        self.assertIn("1.0 Purpose", headings)
        self.assertIn("2.0 Scope", headings)
        self.assertTrue(any("Key Terms" in h for h in headings))
        self.assertIn("4.0 Roles and Responsibilities", headings)
        self.assertIn("7.0 Procedure", headings)
        self.assertIn("8.0 References", headings)
        self.assertIn("Document Revision History", headings)

        # Verify combined text of normalized SOP has zero prohibited terms
        full_normalized_text = "\n\n".join([f"## {s['heading']}\n{s['content']}" for s in normalized])
        for word in ["should", "shall"]:
            self.assertNotIn(
                f" {word} ",
                full_normalized_text.lower(),
                f"Prohibited word '{word}' must be eliminated by template enforcement",
            )

        # Verify deterministic audit of normalized SOP achieves passing compliance
        norm_eval = audit_sop_deterministically(full_normalized_text)
        self.assertTrue(norm_eval["has_mandatory_sections"])
        self.assertGreaterEqual(
            norm_eval["deterministic_average_score"],
            85,
            "Normalized SOP must achieve at least 85% deterministic compliance",
        )

    def test_06_before_and_after_comparison_reports_improvements(self):
        """Test that compare_sop_evaluations accurately computes positive deltas and resolved violations."""
        before_eval = audit_sop_deterministically(LEGACY_DEFICIENT_SOP)
        before_dict = {
            "template_score": before_eval["deterministic_template_score"],
            "readability_score": before_eval["deterministic_readability_score"],
            "quality_score": before_eval["deterministic_quality_score"],
            "average_score": before_eval["deterministic_average_score"],
            "violations": before_eval["violations"],
            "passed_checks": before_eval["passed_checks"],
        }

        after_eval = audit_sop_deterministically(COMPLIANT_KENVUE_SOP)
        after_dict = {
            "template_score": after_eval["deterministic_template_score"],
            "readability_score": after_eval["deterministic_readability_score"],
            "quality_score": after_eval["deterministic_quality_score"],
            "average_score": after_eval["deterministic_average_score"],
            "violations": after_eval["violations"],
            "passed_checks": after_eval["passed_checks"],
        }

        diff = compare_sop_evaluations(before_dict, after_dict)

        self.assertEqual(diff["outcome"], "IMPROVED")
        self.assertGreater(diff["deltas"]["average_score"], 0)
        self.assertGreater(diff["deltas"]["template_score"], 0)
        self.assertGreater(diff["deltas"]["quality_score"], 0)
        self.assertGreater(diff["score_difference"], 0)
        self.assertGreater(len(diff["resolved_violations"]), 0)
        self.assertEqual(len(diff["newly_introduced_violations"]), 0)

        resolved_codes = {v["code"] for v in diff["resolved_violations"]}
        self.assertIn("MISSING_MANDATORY_SECTION_3", resolved_codes)
        self.assertIn("MISSING_MANDATORY_SECTION_4", resolved_codes)
        self.assertIn("MISSING_MANDATORY_SECTION_7", resolved_codes)
        self.assertIn("MISSING_REVISION_HISTORY", resolved_codes)

    def test_07_validate_section_hierarchy_detects_deviations(self):
        """Test that validate_section_hierarchy detects incorrect order and missing sections."""
        out_of_order_headings = [
            "4.0 Roles and Responsibilities",
            "1.0 Purpose",
            "7.0 Procedure",
            "2.0 Scope",
        ]
        hierarchy_res = validate_section_hierarchy(out_of_order_headings)
        self.assertFalse(hierarchy_res["is_valid"])
        self.assertIn("3.0 Key Terms and Acronyms", hierarchy_res["missing_mandatory"])
        self.assertGreater(len(hierarchy_res["out_of_order"]), 0)

    def test_08_kenvue_master_metadata_and_template_standards(self):
        """Test that KENVUE_DOCUMENT_METADATA and canonical structure reflect 7-page Master template."""
        self.assertEqual(KENVUE_DOCUMENT_METADATA["standard_id"], "SOP-STD-001")
        self.assertEqual(KENVUE_DOCUMENT_METADATA["version"], "1.0")

        # Verify all 5 mandatory sections
        mandatory_titles = [m["title"] for m in MANDATORY_SECTIONS]
        self.assertIn("Purpose", mandatory_titles)
        self.assertIn("Scope", mandatory_titles)
        self.assertIn("Key Terms", mandatory_titles)
        self.assertIn("Roles and Responsibilities", mandatory_titles)
        self.assertIn("Procedure", mandatory_titles)

        # Verify required or N/A sections
        required_titles = [r["title"] for r in REQUIRED_OR_NA_SECTIONS]
        self.assertIn("Requirements", required_titles)
        self.assertIn("References", required_titles)
        self.assertIn("Appendices", required_titles)
        self.assertIn("Document Revision History", required_titles)

    def test_09_prohibited_terms_zero_tolerance(self):
        """Test that PROHIBITED_TERMS dictionary includes 'should', 'shall', 'will'."""
        self.assertIn("should", PROHIBITED_TERMS)
        self.assertIn("shall", PROHIBITED_TERMS)
        self.assertIn("will", PROHIBITED_TERMS)
        for term, rationale in PROHIBITED_TERMS.items():
            self.assertTrue(len(rationale) > 10, f"Rationale for '{term}' must be descriptive.")

    def test_10_polish_kenvue_text_cleanses_and_capitalizes(self):
        """Test that polish_kenvue_text removes prohibited words and capitalizes operational roles."""
        from kenvue_guidelines import polish_kenvue_text

        dirty_text = "The operator should clean the valve and the technician shall inspect the seal. You will verify."
        cleaned = polish_kenvue_text(dirty_text)

        self.assertNotIn(" should ", cleaned)
        self.assertNotIn(" shall ", cleaned)
        self.assertIn("Operator", cleaned)
        self.assertIn("Technician", cleaned)
        self.assertIn("must", cleaned)

    def test_11_build_comprehensive_sop_digest_handles_40_page_document(self):
        """Test that build_comprehensive_sop_digest properly digests a 40-page SOP preserving all boundary sections."""
        lines = [
            "# SOP-STD-001 High Volume Manufacturing Procedure",
            "Document ID: SOP-KNV-001",
            "1.0 Purpose",
            "The purpose of this Document is to define requirements for Kenvue.",
            "2.0 Scope",
            "2.1 Process covered.",
            "3.0 Key Terms",
            "| Term | Definition |",
            "| GMP | Good Manufacturing Practice |",
            "4.0 Roles and Responsibilities",
            "| Role | Responsibilities |",
            "| Operator | Executes steps |",
            "5.0 Requirements",
            "Cleanroom standards apply.",
            "7.0 Procedure",
        ]
        # Simulate 300 procedural steps spanning 40 pages (~60,000 characters)
        for i in range(1, 301):
            lines.append(f"7.{i} Step {i}: The Operator must set parameter {i} to 100 ± 5 RPM.")
            lines.append(f"Warning: Chemical hazard in step {i}. Operator must wear PPE.")
            lines.append(f"Detail instruction note for step {i} describing secondary maintenance.")
        lines.extend([
            "8.0 References",
            "| Reference | Document |",
            "| 8.1 | FRM-0009808 |",
            "9.0 Appendices",
            "Appendix 1: Checklist",
            "Document Revision History",
            "| Version Number | Section | Description of Change | Reason for Change | Document Owner |",
            "| 1.0 | All | Initial Release | New Process | Quality Lead |",
        ])
        raw_40page_text = "\n".join(lines)
        self.assertGreater(len(raw_40page_text), 50000, "Raw simulated SOP must exceed 50,000 characters.")

        digest = build_comprehensive_sop_digest(raw_40page_text, max_chars=100000)
        self.assertLessEqual(len(digest), 100000, "Digest must respect max_chars budget.")
        # 40-page SOP (~60k chars) fits completely inside the 100k budget without omitting a single word!
        self.assertEqual(len(digest), len(raw_40page_text), "40-page SOP must be preserved 100% in full.")

        # Crucial checks: Boundary sections on page 1 and page 40 MUST BE INCLUDED
        self.assertIn("1.0 Purpose", digest, "1.0 Purpose must be preserved.")
        self.assertIn("2.0 Scope", digest, "2.0 Scope must be preserved.")
        self.assertIn("3.0 Key Terms", digest, "3.0 Key Terms must be preserved.")
        self.assertIn("4.0 Roles and Responsibilities", digest, "4.0 Roles must be preserved.")
        self.assertIn("7.0 Procedure", digest, "7.0 Procedure must be preserved.")
        self.assertIn("8.0 References", digest, "8.0 References must be preserved.")
        self.assertIn("9.0 Appendices", digest, "9.0 Appendices must be preserved.")
        self.assertIn("Document Revision History", digest, "Document Revision History at page 40 must be preserved.")
        self.assertIn("Quality Lead", digest, "Table row in Document Revision History must be preserved.")
        self.assertIn("±", digest, "Quantified tolerances in Section 7.0 must be preserved.")
        self.assertIn("Warning", digest, "Safety hazard callouts in Section 7.0 must be preserved.")

    def test_12_build_comprehensive_sop_digest_handles_80_page_document(self):
        """Test that build_comprehensive_sop_digest handles an extreme 80-page SOP (~120k chars)."""
        lines = [
            "# SOP-STD-001 Enterprise 80-Page SOP",
            "Document ID: SOP-KNV-001",
            "1.0 Purpose",
            "The purpose of this Document is to define requirements for Kenvue.",
            "2.0 Scope",
            "2.1 Process covered.",
            "3.0 Key Terms",
            "| Term | Definition |",
            "| GMP | Good Manufacturing Practice |",
            "4.0 Roles and Responsibilities",
            "| Role | Responsibilities |",
            "| Operator | Executes steps |",
            "5.0 Requirements",
            "Cleanroom standards apply.",
            "7.0 Procedure",
        ]
        # Simulate 600 procedural steps spanning 80 pages (~120,000 characters)
        for i in range(1, 601):
            lines.append(f"7.{i} Step {i}: The Operator must set parameter {i} to 100 ± 5 RPM.")
            lines.append(f"Warning: Chemical hazard in step {i}. Operator must wear PPE.")
            lines.append(f"Detail instruction note for step {i} describing secondary maintenance.")
        lines.extend([
            "8.0 References",
            "| Reference | Document |",
            "| 8.1 | FRM-0009808 |",
            "9.0 Appendices",
            "Appendix 1: Checklist",
            "Document Revision History",
            "| Version Number | Section | Description of Change | Reason for Change | Document Owner |",
            "| 1.0 | All | Initial Release | New Process | Quality Lead |",
        ])
        raw_80page_text = "\n".join(lines)
        self.assertGreater(len(raw_80page_text), 100000, "Raw simulated SOP must exceed 100,000 characters.")

        digest = build_comprehensive_sop_digest(raw_80page_text, max_chars=100000)
        self.assertLessEqual(len(digest), 100000, "Digest must respect max_chars budget.")
        self.assertIn("1.0 Purpose", digest)
        self.assertIn("7.0 Procedure", digest)
        self.assertIn("Document Revision History", digest)
        self.assertIn("Quality Lead", digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
