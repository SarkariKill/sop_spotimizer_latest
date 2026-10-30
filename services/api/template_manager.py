import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from kenvue_guidelines import (
    KENVUE_MASTER_TEMPLATE_GUIDELINES,
    KENVUE_DOCUMENT_METADATA,
    ALL_CANONICAL_SECTIONS,
    MANDATORY_SECTIONS,
    REQUIRED_OR_NA_SECTIONS,
)

logger = logging.getLogger(__name__)

# Authoritative standard guideline text hardcoded from Kenvue Master SOP-WI Template_en-EN
DEFAULT_KENVUE_GUIDELINES = KENVUE_MASTER_TEMPLATE_GUIDELINES


class TemplateManager:
    """
    Manages the authoritative Kenvue SOP Template and Guidelines.
    In accordance with Kenvue Quality System Governance:
    - The approved Kenvue Master SOP-WI Template (Standard SOP-STD-001) is permanently
      hardcoded and built directly into the system.
    - Administrators can no longer replace or destabilize the official template via manual uploads.
    - All SOP scoring, generation, harmonization, and simplification workflows strictly
      reference this immutable, authoritative standard.
    """

    def __init__(self):
        self.active_template_name: str = "Kenvue Master SOP-WI Template_en-EN (SOP-STD-001)"
        self.active_template_uploaded_at: str = "Built-in Standard"
        self.rules_text: str = KENVUE_MASTER_TEMPLATE_GUIDELINES
        self.is_locked: bool = True
        logger.info(
            "TemplateManager initialized with authoritative hardcoded Kenvue Master SOP-WI Template (%s)",
            KENVUE_DOCUMENT_METADATA["standard_id"],
        )

    def upload_admin_template(self, file_bytes: bytes, filename: str, uploaded_by: str) -> Dict[str, Any]:
        """
        Preserved for backward-compatible API contracts, but manual template mutation
        is disabled. Informs the caller that Kenvue Master SOP-WI Template is authoritative and locked.
        """
        logger.info(
            "Admin upload requested for '%s' by '%s'; hardcoded Kenvue template remains authoritative and active.",
            filename,
            uploaded_by,
        )
        return {
            "status": "locked",
            "message": (
                "The Kenvue Master SOP-WI Template (Standard SOP-STD-001) is permanently hardcoded and locked. "
                "Manual template replacement has been superseded by authoritative built-in guidelines."
            ),
            "filename": self.active_template_name,
            "uploaded_at": self.active_template_uploaded_at,
            "standard_id": KENVUE_DOCUMENT_METADATA["standard_id"],
        }

    def get_template_status(self) -> Dict[str, Any]:
        """Returns the current state of the authoritative Kenvue guideline."""
        return {
            "has_custom_template": False,
            "template_name": self.active_template_name,
            "uploaded_at": self.active_template_uploaded_at,
            "is_default": True,
            "is_locked": True,
            "standard_id": KENVUE_DOCUMENT_METADATA["standard_id"],
            "version": KENVUE_DOCUMENT_METADATA["version"],
            "mandatory_sections": [s["title"] for s in MANDATORY_SECTIONS],
            "required_sections": [s["title"] for s in REQUIRED_OR_NA_SECTIONS],
        }

    def get_guidelines_summary(self) -> str:
        """Returns the active authoritative guideline rules for LLM evaluation and prompting."""
        return self.rules_text


# Singleton instance
template_manager = TemplateManager()
