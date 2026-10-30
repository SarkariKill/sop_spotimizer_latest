"""
Kenvue Prompt Loader & Dynamic Template Management Engine.

Responsible for:
- Discovering, caching, and loading externalized markdown (.md) agent prompts from `prompts/`.
- Hot-reloading prompts on disk changes without requiring application server restarts.
- Safe variable interpolation that prevents KeyError crashes on literal JSON examples/schemas.
"""
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("kenvue.prompt_loader")

# Base directory discovery
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_CANDIDATE_DIRS = [
    os.path.join(_CURRENT_DIR, "prompts"),
    os.path.join(os.path.dirname(_CURRENT_DIR), "prompts"),
    os.path.join(os.path.dirname(os.path.dirname(_CURRENT_DIR)), "prompts"),
]

PROMPTS_DIR = next((d for d in _CANDIDATE_DIRS if os.path.isdir(d)), os.path.join(_CURRENT_DIR, "prompts"))

# In-memory mtime cache: {prompt_name: (mtime, content)}
_PROMPT_CACHE: Dict[str, Tuple[float, str]] = {}


def get_prompts_dir() -> str:
    """Returns the resolved absolute path to the prompts directory."""
    return PROMPTS_DIR


def get_prompt_path(name: str) -> Optional[str]:
    """
    Resolves the absolute path for a given prompt name (with or without .md extension).
    """
    clean_name = name.strip()
    if not clean_name.endswith(".md"):
        clean_name += ".md"

    direct_path = os.path.join(PROMPTS_DIR, clean_name)
    if os.path.isfile(direct_path):
        return direct_path

    # Check alternative candidate directories
    for candidate_dir in _CANDIDATE_DIRS:
        alt_path = os.path.join(candidate_dir, clean_name)
        if os.path.isfile(alt_path):
            return alt_path

    return None


def has_prompt(name: str) -> bool:
    """Checks whether a prompt with the given name exists in the prompts directory."""
    return get_prompt_path(name) is not None


def list_available_prompts() -> List[str]:
    """Returns a list of all available prompt names (without .md extension)."""
    if not os.path.isdir(PROMPTS_DIR):
        return []
    prompts = []
    for f in sorted(os.listdir(PROMPTS_DIR)):
        if f.endswith(".md"):
            prompts.append(f[:-3])
    return prompts


def load_prompt(name: str, reload_if_changed: bool = True) -> str:
    """
    Loads raw prompt text from disk with automatic mtime-based reload caching.
    """
    clean_name = name.strip()
    if clean_name.endswith(".md"):
        clean_name = clean_name[:-3]

    path = get_prompt_path(clean_name)
    if not path or not os.path.isfile(path):
        logger.warning("[PromptLoader] Prompt file '%s' not found under %s", name, PROMPTS_DIR)
        raise FileNotFoundError(f"Prompt '{name}' not found under '{PROMPTS_DIR}'")

    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        current_mtime = 0.0

    if clean_name in _PROMPT_CACHE:
        cached_mtime, cached_content = _PROMPT_CACHE[clean_name]
        if not reload_if_changed or current_mtime <= cached_mtime:
            return cached_content

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        _PROMPT_CACHE[clean_name] = (current_mtime, content)
        logger.debug("[PromptLoader] Loaded/reloaded prompt '%s' from %s", clean_name, path)
        return content
    except Exception as exc:
        logger.error("[PromptLoader] Failed reading prompt '%s' from %s: %s", clean_name, path, exc)
        if clean_name in _PROMPT_CACHE:
            return _PROMPT_CACHE[clean_name][1]
        raise


def format_prompt(name_or_template: str, **kwargs: Any) -> str:
    """
    Interpolates variables into a prompt template safely without triggering KeyError
    on literal JSON syntax (e.g. `{"heading": "..."}`).

    Args:
        name_or_template: Either a prompt file name (e.g. "harmonization_agent") or a raw template string.
        **kwargs: Variables to replace (e.g. doc_title="...", guidelines="...").

    Returns:
        Interpolated prompt string with all kwargs replaced.
    """
    if has_prompt(name_or_template):
        text = load_prompt(name_or_template)
    else:
        text = name_or_template

    # Replace only specified kwargs to allow JSON examples with {} to remain untouched
    for key, value in kwargs.items():
        placeholder = "{" + str(key) + "}"
        text = text.replace(placeholder, str(value) if value is not None else "")

    return text


def clear_prompt_cache() -> None:
    """Clears the prompt cache (useful in test suites)."""
    _PROMPT_CACHE.clear()
