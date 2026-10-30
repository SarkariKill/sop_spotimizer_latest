import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from kenvue_guidelines import (
    KENVUE_MASTER_TEMPLATE_GUIDELINES,
    audit_sop_deterministically,
    build_comprehensive_sop_digest,
    compare_sop_evaluations,
)
from skill_manager import skill_manager
from template_manager import template_manager

logger = logging.getLogger(__name__)

# =====================================================================
# AUTHORITATIVE KENVUE SOP EVALUATION ENGINE
# Evaluates uploaded and optimized SOPs against Kenvue Master Standards:
# 1. Template Score (structure & required Kenvue Master sections & tables)
# 2. Readability Score (imperative command voice, lack of 'should/shall/will')
# 3. Quality Score (tolerances, safety warnings, procedural completeness)
# 4. Average Score (mathematical average of all 3)
# 5. Checkbox Suggestions (actionable improvements for the user)
# 6. Deterministic Checklist & Violation Tracking
# =====================================================================


class LLMServiceError(RuntimeError):
    """Raised when the LLM microservice or configured LLM provider is down, unreachable, or misconfigured."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def format_llm_unavailable_message(
    provider: str = "LLM",
    status_code: int = 503,
    detail: str = "",
) -> str:
    """Builds a clean, UI-friendly error message when the LLM service is down or unavailable."""
    prov_label = (provider or "LLM").upper()
    detail_lower = (detail or "").lower()
    if (
        status_code in (401, 403)
        or "invalid api key" in detail_lower
        or "api_key_invalid" in detail_lower
        or "unauthorized" in detail_lower
    ):
        return (
            f"LLM Service Unavailable: The configured {prov_label} API key is invalid or unauthorized. "
            f"Please ask the Administrator to update the API key in LLM Settings."
        )
    if status_code == 400 and "not configured" in detail_lower:
        return (
            f"LLM Service Unavailable: No {prov_label} API key is configured. "
            f"Please ask the Administrator to configure a valid API key in LLM Settings."
        )
    if status_code == 429 or "rate limit" in detail_lower or "quota" in detail_lower:
        return (
            f"LLM Service Unavailable: {prov_label} rate limit or quota exceeded. "
            f"Please wait a moment and try again, or switch the active LLM provider in Admin Settings."
        )
    return (
        f"LLM Service Unavailable: The active LLM provider ({prov_label}) is currently down or unreachable. "
        f"SOP scoring, optimization, and harmonization cannot proceed while the LLM is offline. "
        f"Please verify that the LLM service is running and a valid API key is configured."
    )


def evaluate_sop_heuristics(sop_text: str) -> Dict[str, Any]:
    """
    Deprecated: Hardcoded heuristic fallback without LLM is disabled.
    SOP scoring strictly requires an active LLM service.
    """
    raise LLMServiceError(
        format_llm_unavailable_message("LLM", 503, "Heuristic fallback is disabled; active LLM is required."),
        status_code=503,
    )


def _build_comprehensive_sop_digest(sop_text: str, max_chars: int = 100000) -> str:
    """
    Creates a comprehensive structural and technical digest of an SOP of ANY length
    (from a 1-page document up to an enterprise document of 40 to 80+ pages; optimized
    for Azure OpenAI 128k context with a 100,000 character safety budget).
    Delegates to the authoritative build_comprehensive_sop_digest implementation.
    """
    return build_comprehensive_sop_digest(sop_text, max_chars=max_chars)


def _parse_llm_json_safely(raw_text: str) -> Dict[str, Any]:
    """
    Robustly extracts and parses a JSON object from an LLM response,
    handling markdown code fences, trailing commas, unescaped newlines,
    comments, and minor formatting quirks.
    """
    clean = re.sub(r"^```(?:json)?\s*", "", (raw_text or "").strip(), flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean).strip()
    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        clean = clean[start_idx : end_idx + 1]

    # Strip JS-style line and block comments outside strings
    clean = re.sub(r"/\*.*?\*/", "", clean, flags=re.DOTALL)
    # Strip accidental parenthetical type hints after keys
    clean = re.sub(r'("[\w_]+")\s*\([^)]*\)\s*:', r"\1:", clean)
    # Normalize "85%" or "85/100" numeric score values into plain integers
    clean = re.sub(
        r'("(?:template_score|readability_score|quality_score|average_score)"\s*:\s*)"?(\d+(?:\.\d+)?)\s*(?:%|/\s*100)?"?',
        r"\1\2",
        clean,
        flags=re.IGNORECASE,
    )
    # Remove trailing commas before } or ]
    clean = re.sub(r",\s*([}\]])", r"\1", clean)

    try:
        return json.loads(clean, strict=False)
    except json.JSONDecodeError:
        t_m = re.search(r'["\']?template[_\s]?score["\']?\s*:\s*["\']?(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
        r_m = re.search(r'["\']?readability[_\s]?score["\']?\s*:\s*["\']?(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
        q_m = re.search(r'["\']?quality[_\s]?score["\']?\s*:\s*["\']?(\d+(?:\.\d+)?)', clean, re.IGNORECASE)
        sum_m = re.search(r'["\']?summary["\']?\s*:\s*"(.*?)"\s*,\s*["\']?suggestions["\']?', clean, re.IGNORECASE | re.DOTALL)
        if not sum_m:
            sum_m = re.search(r'["\']?summary["\']?\s*:\s*"((?:\\.|[^"\n])*)"', clean, re.IGNORECASE)
        if t_m and r_m and q_m:
            extracted_sugs: List[Dict[str, str]] = []
            sugs_block_m = re.search(r'["\']?suggestions["\']?\s*:\s*\[(.*)', clean, re.IGNORECASE | re.DOTALL)
            sugs_text = sugs_block_m.group(1) if sugs_block_m else clean
            for obj_m in re.finditer(r"\{([^{}]+)\}", sugs_text, re.DOTALL):
                obj_body = obj_m.group(1)
                title_m = re.search(r'["\']?title["\']?\s*:\s*"((?:\\.|[^"])*)"', obj_body, re.IGNORECASE)
                desc_m = re.search(r'["\']?description["\']?\s*:\s*"((?:\\.|[^"])*)"', obj_body, re.IGNORECASE)
                id_m = re.search(r'["\']?id["\']?\s*:\s*"([^"]+)"', obj_body, re.IGNORECASE)
                if title_m and desc_m:
                    extracted_sugs.append({
                        "id": id_m.group(1).strip() if id_m else f"sug_{len(extracted_sugs) + 1}",
                        "title": title_m.group(1).strip(),
                        "description": desc_m.group(1).strip(),
                    })
            return {
                "template_score": int(round(float(t_m.group(1)))),
                "readability_score": int(round(float(r_m.group(1)))),
                "quality_score": int(round(float(q_m.group(1)))),
                "summary": sum_m.group(1).replace('\\"', '"').strip() if sum_m else "SOP compliance audit completed.",
                "suggestions": extracted_sugs,
            }
        raise


async def evaluate_sop_with_llm(
    sop_text: str,
    llm_service_url: str,
    provider: str,
    model: str,
    api_key: str,
    compact_mode: bool = False,
) -> Dict[str, Any]:
    """
    Evaluates an SOP against the authoritative Kenvue Master SOP-WI Template standards.
    Applies the EXACT SAME criteria whether evaluating an initial draft or an optimized document:

    1. Executes deterministic compliance auditing (mandatory sections, table formats,
       prohibited words like 'should/shall/will', role capitalization, numerical tolerances).
    2. Executes semantic quality assessment via the active LLM.
    3. Combines deterministic checks with LLM qualitative scores into an authoritative scorecard.
    4. Provides complete violation tracking and actionable remediation suggestions.

    Strictly requires an active, working LLM service; raises LLMServiceError if unavailable.
    """
    if not api_key or not api_key.strip():
        raise LLMServiceError(
            format_llm_unavailable_message(provider, 400, "API key is not configured"),
            status_code=503,
        )

    # Step 1: Run deterministic audit
    det = audit_sop_deterministically(sop_text)

    # Step 2: Build rich digest preserving all sections and tables
    # Supports enterprise documents up to 40-80+ pages (100,000 chars safety budget for Azure OpenAI)
    sop_excerpt = build_comprehensive_sop_digest(sop_text, max_chars=100000)

    audit_skill = skill_manager.get_audit_skill()
    guidelines = template_manager.get_guidelines_summary()

    try:
        from prompt_loader import format_prompt
    except ImportError:
        from services.api.prompt_loader import format_prompt

    prompt = format_prompt(
        "scoring_agent",
        guidelines=guidelines,
        audit_skill=audit_skill,
        sop_excerpt=sop_excerpt,
        has_mandatory_sections=det["has_mandatory_sections"],
        prohibited_count=sum(det["prohibited_counts"].values()),
        violations_count=len(det["violations"]),
    )

    body = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4096,
    }

    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                res = await client.post(f"{llm_service_url}/generate", json=body)
        except Exception as exc:
            logger.error("LLM evaluation request failed (attempt %d): %s", attempt + 1, exc)
            last_err = exc
            if attempt == 0:
                continue
            raise LLMServiceError(
                format_llm_unavailable_message(provider, 503, str(exc)),
                status_code=503,
            ) from exc

        if res.status_code != 200:
            err_text = res.text
            try:
                err_json = res.json()
                if isinstance(err_json, dict) and "detail" in err_json:
                    err_text = str(err_json["detail"])
            except Exception:
                pass
            logger.error("LLM evaluation returned HTTP %d (attempt %d): %s", res.status_code, attempt + 1, err_text[:200])
            if res.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                continue
            raise LLMServiceError(
                format_llm_unavailable_message(provider, res.status_code, err_text),
                status_code=503,
            )

        try:
            content = res.json().get("content", "").strip()
            if not content:
                raise ValueError("Empty content returned by LLM service")
            parsed = _parse_llm_json_safely(content)
            if (
                "template_score" not in parsed
                or "readability_score" not in parsed
                or "quality_score" not in parsed
            ):
                raise ValueError("LLM response missing required score fields")

            raw_t_score = max(0, min(100, int(parsed["template_score"])))
            raw_r_score = max(0, min(100, int(parsed["readability_score"])))
            raw_q_score = max(0, min(100, int(parsed["quality_score"])))

            # Step 3: Blend deterministic checks (40%) with LLM qualitative scores (60%)
            # This ensures mathematical integrity: documents with missing sections or prohibited words
            # cannot receive ungrounded scores, while compliant documents receive accurate high marks.
            det_t = det["deterministic_template_score"]
            det_r = det["deterministic_readability_score"]
            det_q = det["deterministic_quality_score"]

            final_t_score = max(0, min(100, round(0.4 * det_t + 0.6 * raw_t_score)))
            final_r_score = max(0, min(100, round(0.4 * det_r + 0.6 * raw_r_score)))
            final_q_score = max(0, min(100, round(0.4 * det_q + 0.6 * raw_q_score)))
            final_avg_score = round((final_t_score + final_r_score + final_q_score) / 3)

            suggestions = parsed.get("suggestions") if isinstance(parsed.get("suggestions"), list) else []
            summary = str(parsed.get("summary") or "").strip()

            return {
                "template_score": final_t_score,
                "readability_score": final_r_score,
                "quality_score": final_q_score,
                "average_score": final_avg_score,
                "overall_score": final_avg_score,
                "summary": summary,
                "suggestions": suggestions,
                "violations": det["violations"],
                "passed_checks": det["passed_checks"],
                "prohibited_counts": det["prohibited_counts"],
                "deterministic_scores": {
                    "template_score": det_t,
                    "readability_score": det_r,
                    "quality_score": det_q,
                    "average_score": det["deterministic_average_score"],
                },
            }
        except Exception as exc:
            logger.warning("Failed parsing LLM evaluation response (attempt %d): %s", attempt + 1, exc)
            last_err = exc
            if attempt == 0:
                continue
            raise LLMServiceError(
                format_llm_unavailable_message(provider, 502, str(exc)),
                status_code=503,
            ) from exc

    raise LLMServiceError(
        format_llm_unavailable_message(provider, 503, str(last_err or "Evaluation failed")),
        status_code=503,
    )
