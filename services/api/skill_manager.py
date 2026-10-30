import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from minio_storage import minio_storage
from kenvue_guidelines import build_comprehensive_sop_digest

logger = logging.getLogger(__name__)

SKILLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skills")
AUDIT_SKILL_PATH = os.path.join(SKILLS_DIR, "kenvue_audit_skill.md")


class SkillManager:
    """
    Manages static evaluation skills and dynamically compiled session optimization skills.
    
    1. Master Audit Skill: 'skills/kenvue_audit_skill.md' defines exact scoring rubrics
       (Template Score, Readability Score, Quality Score) and suggestion taxonomy.
    2. Dynamic Session Skill: When the user selects recommendations and enters custom notes,
       a tailored 'optimization_skill.md' is generated, uploaded to MinIO, and used to guide
       the SOP generator.
    """

    def __init__(self):
        self._audit_skill_content: Optional[str] = None
        self._load_audit_skill()

    def _load_audit_skill(self) -> str:
        if os.path.exists(AUDIT_SKILL_PATH):
            try:
                with open(AUDIT_SKILL_PATH, "r", encoding="utf-8") as f:
                    self._audit_skill_content = f.read()
                logger.info("Loaded Master Kenvue Audit Skill from %s", AUDIT_SKILL_PATH)
            except Exception as e:
                logger.warning("Could not read audit skill from %s: %s", AUDIT_SKILL_PATH, e)
                self._audit_skill_content = None
        return self._audit_skill_content or ""

    def get_audit_skill(self) -> str:
        """Returns the Master Kenvue SOP Audit & Scoring Skill content."""
        if not self._audit_skill_content:
            return self._load_audit_skill()
        return self._audit_skill_content

    def build_optimization_skill(
        self,
        conversation_id: str,
        username: str,
        original_filename: str,
        selected_suggestions: List[Dict[str, str]],
        custom_instructions: str,
        artifacts: List[Dict[str, Any]],
        original_text: str,
        is_iterative: bool = False,
        current_title: Optional[str] = None,
        document_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        # --- HERE DYNAMIC SESSION OPTIMIZATION SKILL GENERATION HAPPENS ---
        Compiles the user's selected checkboxes + custom user notes into a formal
        SOP Optimization Directive & Execution Skill.
        Uploads this skill to MinIO under 'users/{username}/conversations/{id}/optimization_skill.md'
        for complete auditability and governance.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Format user-approved changes
        if selected_suggestions:
            approved_blocks = []
            for i, s in enumerate(selected_suggestions, start=1):
                title = s.get("title", "Improvement")
                desc = s.get("description", "")
                approved_blocks.append(f"### Rule {i}: {title}\n- **Directive**: {desc}\n- **Status**: MANDATORY / APPROVED BY USER")
            approved_str = "\n\n".join(approved_blocks)
        else:
            approved_str = "_Standard structural alignment to Kenvue Master SOP-WI standard (SOP-STD-001)._"

        if custom_instructions and custom_instructions.strip():
            try:
                from validation_agent import validation_agent, clean_instruction_text
            except ImportError:
                from services.api.validation_agent import validation_agent, clean_instruction_text
            reqs = validation_agent.extract_custom_requirements(custom_instructions)
            req_blocks = []
            for i, r in enumerate(reqs, start=1):
                cat = r.get("category", "USER_DIRECTIVE")
                raw = r.get("raw", "")
                target = r.get("target_section", "Relevant Section")
                clean = clean_instruction_text(raw)
                topic = r.get("topic", "")
                topic_directive = ""
                if cat == "ADD_NEW_SECTION" and topic:
                    topic_directive = (
                        f"\n- **Explicit Content Requirement**: You MUST append a dedicated terminal section (e.g. Section 10.0 / 11.0) "
                        f"at the very end of the document and write a full, informative paragraph/steps discussing '{topic}'. "
                        f"Do NOT omit this or place it into Section 1.0."
                    )
                elif cat == "FULL_DOCUMENT_LANGUAGE_OVERRIDE":
                    topic_directive = (
                        f"\n- **Explicit Language Requirement**: You MUST write the ENTIRE Standard Operating Procedure in fluent, authentic Japanese. "
                        f"The \"document_title\" must be in Japanese, and EVERY single section heading and content must be written in professional Japanese. "
                        f"Do NOT output any section in English."
                    )
                elif cat == "TITLE_LANGUAGE_OVERRIDE":
                    topic_directive = (
                        f"\n- **Explicit Language Requirement**: You MUST write the \"document_title\" in fluent, authentic Japanese (e.g. '標準作業手順書: ...'), "
                        f"and feature this Japanese title in Section 1.0 Purpose and Document Revision History."
                    )
                elif cat == "SECTION_LANGUAGE_OVERRIDE":
                    topic_directive = (
                        f"\n- **Explicit Language Requirement**: You MUST write the content of {target} "
                        f"in fluent, authentic Japanese. Do NOT leave it in English; write the requirements in Japanese as requested."
                    )
                req_blocks.append(
                    f"### Mandatory Override {i} [{cat}]: {clean}\n"
                    f"- **User Directive**: \"{raw}\"\n"
                    f"- **Target Implementation Location**: {target}{topic_directive}\n"
                    f"- **Priority**: HIGHEST / BINDING OVERRIDE (Must be explicitly executed in text)"
                )
            custom_str = (
                "⚠️ **CRITICAL COMPLIANCE DIRECTIVE: The user explicitly specified the following custom overrides in the instruction placeholder. "
                "You MUST implement 100% of these requirements directly into the specified sections:**\n\n"
                + "\n\n".join(req_blocks)
            )
        else:
            custom_str = "_No additional custom user overrides specified._"

        # Format asset preservation rules
        asset_rules = []
        for a in artifacts:
            a_type = a.get("artifact_type", "asset").upper()
            caption = a.get("caption", "Asset")
            page = a.get("page", 1)
            aid = a.get("id")
            asset_rules.append(f"- **[{a_type}] {aid}**: \"{caption}\" (Extracted from Original Page {page})")
        assets_str = "\n".join(asset_rules) if asset_rules else "_No embedded figures or tables in source document._"

        iterative_note = ""
        target_doc_name = current_title or original_filename
        if is_iterative:
            title_display = f'"{current_title}"' if current_title else f'"{original_filename}"'
            iterative_note = (
                f"\n\n⚠️ **CRITICAL ITERATIVE REFINEMENT DIRECTIVE (Version 2+)**:\n"
                f"This optimization is executing directly on top of the **previously generated SOP draft (not factual evidence)**.\n"
                f"- **Current Baseline Document Title**: {title_display}. You MUST strictly retain this title unless Section 3 contains an explicit command to rename the document.\n"
                f"- All previous structural transformations, custom titles, parameters, and specialized sections already established in the document MUST BE STRICTLY RETAINED as the baseline foundation.\n"
                f"- You must apply the newly requested changes (Section 2 & Section 3) ON TOP of the existing text.\n"
                f"- Do NOT reset, erase, or revert to the initial draft."
            )

        # Comprehensive source document excerpt (supporting 1-page to 40+ page documents, 100k safety budget)
        if original_text:
            text_excerpt = build_comprehensive_sop_digest(original_text, max_chars=100000)
        else:
            text_excerpt = "No original text available."

        skill_markdown = f"""# Kenvue SOP Dynamic Optimization Directive & Execution Skill
**Document Target**: {target_doc_name} (Source: {original_filename})  
**Session ID**: {conversation_id}  
**Target Standard**: Kenvue Master SOP-WI Architecture (SOP-STD-001)  
**Authorized User**: {username}  
**Created At**: {now_iso}  

---

## 1. Directive Overview
This dynamic skill file is compiled from user-approved quality remediation points and custom engineering instructions. These are requested editorial changes, not evidence of factual or operational requirements. Source reconciliation takes precedence; unsupported additions remain recommendations requiring author approval.{iterative_note}

---

## 2. User-Approved Transformation Directives
The following specific improvements were selected by the user and must be strictly implemented:

{approved_str}

---

## 3. Custom User Requirements & Overrides
{custom_str}

---

## 4. Asset Preservation & Placement Directives
All original figures, process diagrams, and tables stored in MinIO must be preserved as-is without modification. Each asset must be placed into its semantically relevant section:

{assets_str}

### Placement Rules:
1. **Terminology & Definitions**: Tables defining terms or abbreviations must be placed in **Section 3.0 Key Terms**.
2. **Roles & Responsibilities**: Tables describing roles and responsibilities belong in **Section 4.0 Roles and Responsibilities**.
3. **Process Requirements**: Process requirements belong in **Section 5.0 Requirements**.
4. **Process Flow**: Process flowcharts and decision diagrams belong in **Section 6.0 Process Flow** (or referenced in Section 7.0 / Appendix).
5. **Operating Procedures**: Workstation setups, equipment operations, and step-by-step instructions belong in **Section 7.0 Procedure**.
6. **References**: Document cross-references belong in **Section 8.0 References**.
7. **Appendices & Checklists**: Pre-operational checklists, forms, and supplemental materials belong in **Section 9.0 Appendices**.
8. **Revision Control**: Change history belongs in **Document Revision History**.

---

## 5. Standard Writing & Style Guidelines
- **Voice**: Strict imperative command voice (e.g., "Inspect", "Sanitize", "Measure", "Verify"). Use "must" for obligations, "can" for optional, "may" for permission.
- **Prohibited Terms**: ZERO tolerance for "should", "shall", or "will".
- **Capitalized Roles**: All operational roles (e.g. Operator, Supervisor, Approver) must be capitalized.
- **Tolerances**: Preserve only source-specified tolerances. Missing tolerances require author review; never invent values.
- **Section Hierarchy**: Strict adherence to Kenvue Master SOP sections (1.0 Purpose, 2.0 Scope, 3.0 Key Terms, 4.0 Roles and Responsibilities, 5.0 Requirements, 6.0 Process Flow, 7.0 Procedure, 8.0 References, 9.0 Appendices, Document Revision History).

---

## 6. Source Document Content
{text_excerpt}
"""

        # Upload dynamic skill file to MinIO
        skill_bytes = skill_markdown.encode("utf-8")
        safe_doc_id = re.sub(r"[^\w\-]", "_", str(document_id)) if document_id else None
        if safe_doc_id:
            object_name = f"users/{username}/conversations/{conversation_id}/optimization_skill_{safe_doc_id}.md"
        else:
            object_name = f"users/{username}/conversations/{conversation_id}/optimization_skill.md"

        minio_storage.upload_file_bytes(
            object_name=object_name,
            data=skill_bytes,
            content_type="text/markdown",
            metadata={
                "conversation_id": conversation_id,
                "document_id": document_id or "",
                "username": username,
                "type": "optimization_skill",
                "filename": original_filename,
            },
        )
        if safe_doc_id:
            minio_storage.upload_file_bytes(
                object_name=f"users/{username}/conversations/{conversation_id}/optimization_skill.md",
                data=skill_bytes,
                content_type="text/markdown",
                metadata={"conversation_id": conversation_id, "username": username, "type": "optimization_skill"},
            )
        logger.info("Compiled & uploaded dynamic SOP optimization skill to MinIO: %s (%d bytes)", object_name, len(skill_bytes))

        return {
            "skill_markdown": skill_markdown,
            "object_name": object_name,
            "created_at": now_iso,
        }


# Global singleton instance
skill_manager = SkillManager()
