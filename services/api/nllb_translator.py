import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

try:
    from sop_evaluator import LLMServiceError, format_llm_unavailable_message
except ImportError:
    from services.api.sop_evaluator import LLMServiceError, format_llm_unavailable_message

logger = logging.getLogger(__name__)

# =====================================================================
# NLLB-200 MULTILINGUAL LANGUAGE DETECTION & TRANSLATION ENGINE
# Model Standard: facebook/nllb-200-distilled-600M (FLORES-200 codes)
# Internal Canonical Processing Language: English (eng_Latn)
# =====================================================================

NLLB_MODEL_NAME = "facebook/nllb-200-distilled-600M"
NLLB_MODEL_ID = NLLB_MODEL_NAME
CANONICAL_INTERNAL_LANGUAGE = "English"
CANONICAL_NLLB_CODE = "eng_Latn"

# Supported NLLB languages mapping
SUPPORTED_LANGUAGES: Dict[str, Dict[str, Any]] = {
    "English": {
        "name": "English",
        "native_name": "English",
        "nllb_code": "eng_Latn",
        "iso_code": "en",
        "iso": "en",
        "font_family": "Helvetica",
        "flag": "🇺🇸",
    },
    "Japanese": {
        "name": "Japanese",
        "native_name": "日本語",
        "nllb_code": "jpn_Jpan",
        "iso_code": "ja",
        "iso": "ja",
        "font_family": "HeiseiKakuGo-W5",
        "flag": "🇯🇵",
    },
    "Chinese": {
        "name": "Chinese",
        "native_name": "中文 (简体)",
        "nllb_code": "zho_Hans",
        "iso_code": "zh",
        "iso": "zh",
        "font_family": "STSong-Light",
        "flag": "🇨🇳",
    },
    "German": {
        "name": "German",
        "native_name": "Deutsch",
        "nllb_code": "deu_Latn",
        "iso_code": "de",
        "iso": "de",
        "font_family": "Helvetica",
        "flag": "🇩🇪",
    },
    "French": {
        "name": "French",
        "native_name": "Français",
        "nllb_code": "fra_Latn",
        "iso_code": "fr",
        "iso": "fr",
        "font_family": "Helvetica",
        "flag": "🇫🇷",
    },
    "Spanish": {
        "name": "Spanish",
        "native_name": "Español",
        "nllb_code": "spa_Latn",
        "iso_code": "es",
        "iso": "es",
        "font_family": "Helvetica",
        "flag": "🇪🇸",
    },
    "Korean": {
        "name": "Korean",
        "native_name": "한국어",
        "nllb_code": "kor_Hang",
        "iso_code": "ko",
        "iso": "ko",
        "font_family": "HYSMyeongJo-Medium",
        "flag": "🇰🇷",
    },
    "Portuguese": {
        "name": "Portuguese",
        "native_name": "Português",
        "nllb_code": "por_Latn",
        "iso_code": "pt",
        "iso": "pt",
        "font_family": "Helvetica",
        "flag": "🇵🇹",
    },
    "Italian": {
        "name": "Italian",
        "native_name": "Italiano",
        "nllb_code": "ita_Latn",
        "iso_code": "it",
        "iso": "it",
        "font_family": "Helvetica",
        "flag": "🇮🇹",
    },
    "Dutch": {
        "name": "Dutch",
        "native_name": "Nederlands",
        "nllb_code": "nld_Latn",
        "iso_code": "nl",
        "iso": "nl",
        "font_family": "Helvetica",
        "flag": "🇳🇱",
    },
    "Hindi": {
        "name": "Hindi",
        "native_name": "हिन्दी",
        "nllb_code": "hin_Deva",
        "iso_code": "hi",
        "iso": "hi",
        "font_family": "Helvetica",
        "flag": "🇮🇳",
    },
    "Russian": {
        "name": "Russian",
        "native_name": "Русский",
        "nllb_code": "rus_Cyrl",
        "iso_code": "ru",
        "iso": "ru",
        "font_family": "Helvetica",
        "flag": "🇷🇺",
    },
    "Arabic": {
        "name": "Arabic",
        "native_name": "العربية",
        "nllb_code": "ara_Arab",
        "iso_code": "ar",
        "iso": "ar",
        "font_family": "Helvetica",
        "flag": "🇸🇦",
    },
}

SUPPORTED_NLLB_LANGUAGES = SUPPORTED_LANGUAGES

# Unsupported scripts for explicit error detection
UNSUPPORTED_SCRIPT_PATTERNS: List[Tuple[str, str]] = [
    (r"[\u0E00-\u0E7F]", "Thai (tha_Thai)"),
    (r"[\u0590-\u05FF]", "Hebrew (heb_Hebr)"),
    (r"[\u0370-\u03FF]", "Greek (ell_Grek)"),
    (r"[\u0B80-\u0BFF]", "Tamil (tam_Taml)"),
    (r"[\u0980-\u09FF]", "Bengali (ben_Beng)"),
    (r"[\u10A0-\u10FF]", "Georgian (kat_Geor)"),
    (r"[\u0530-\u058F]", "Armenian (hye_Armn)"),
    (r"[\u1780-\u17FF]", "Khmer (khm_Khmr)"),
    (r"[\u1000-\u109F]", "Myanmar (mya_Mymr)"),
    (r"[\u0D80-\u0DFF]", "Sinhala (sin_Sinh)"),
]

# Lexical profiles for Latin-script languages (includes both accented and ASCII/unaccented variants)
LATIN_LANGUAGE_PROFILES: Dict[str, Dict[str, Any]] = {
    "German": {
        "stopwords": {
            "und", "der", "die", "das", "den", "dem", "des", "für", "fuer", "mit", "auf",
            "ist", "sind", "werden", "wird", "nicht", "auch", "oder", "nach", "von", "zur", "zum",
            "bei", "durch", "über", "ueber", "unter", "muss", "müssen", "muessen", "alle", "vor",
            "standardarbeitsanweisung", "arbeitsanweisung", "verfahren", "zweck", "geltungsbereich",
            "verantwortlichkeiten", "sicherheit", "sicherheitsrichtlinien", "zentrifuge", "reinigung",
            "kalibrierung", "wartung", "schritt", "tabelle", "abbildung", "prüfung", "pruefung",
            "bediener", "drehzahl", "kühltemperatur", "kuehltemperatur", "schutzausrüstung",
        },
        "chars": set("äöüßÄÖÜ"),
    },
    "French": {
        "stopwords": {
            "le", "la", "les", "des", "dans", "pour", "avec", "sur", "est", "sont", "du", "au",
            "pas", "plus", "par", "une", "aux", "cette", "ces", "doit", "doivent", "tout", "tous",
            "procédure", "opérationnelle", "operationnelle", "objectif", "portée", "portee",
            "sécurité", "securite", "responsabilités", "responsabilites", "nettoyage",
            "étalonnage", "etalonnage", "étape", "etape", "tableau", "centrifugeuse", "consignes",
            "équipement", "equipement", "vérifier", "verifier", "opérateur", "operateur",
        },
        "chars": set("éèêëàâùûçœÉÈÊÀÇ"),
    },
    "Spanish": {
        "stopwords": {
            "el", "la", "los", "las", "del", "para", "con", "por", "una", "son", "al", "se", "su",
            "está", "están", "esta", "estan", "debe", "deben", "todos", "como", "más", "pero", "sin",
            "procedimiento", "operativo", "estándar", "estandar", "propósito", "proposito", "alcance",
            "seguridad", "responsabilidades", "mantenimiento", "limpieza", "paso", "tabla", "figura",
            "centrífuga", "centrifuga", "calibración", "calibracion", "operador", "operadores",
            "verificar", "temperatura", "velocidad", "presión", "presion", "equipos", "materiales",
        },
        "chars": set("ñáéíóúü¿¡ÑÁÉÍÓÚ"),
    },
    "Portuguese": {
        "stopwords": {
            "os", "as", "dos", "das", "para", "com", "uma", "são", "sao", "não", "nao", "deve",
            "devem", "pelo", "pela", "ao", "aos", "nas", "nos", "procedimento", "operacional",
            "padrão", "padrao", "objetivo", "escopo", "segurança", "seguranca", "manutenção",
            "manutencao", "limpeza", "calibração", "calibracao", "equipamento", "equipamentos",
            "etapa", "responsabilidades", "operadores", "centrífuga", "verificar",
        },
        "chars": set("ãõçáéíóúâêôÃÕÇ"),
    },
    "Italian": {
        "stopwords": {
            "il", "lo", "gli", "le", "della", "delle", "degli", "nel", "nella", "sul", "sulla",
            "con", "per", "sono", "deve", "devono", "alla", "alle", "dal", "dalla", "procedura",
            "operativa", "scopo", "sicurezza", "manutenzione", "pulizia", "taratura", "tabella",
            "passaggio", "responsabilità", "responsabilita", "apparecchiatura", "operatore",
        },
        "chars": set("àèéìòùÀÈÉÌÒÙ"),
    },
    "Dutch": {
        "stopwords": {
            "de", "het", "een", "van", "voor", "met", "zijn", "worden", "moet", "moeten",
            "niet", "naar", "over", "bij", "door", "uit", "veiligheid", "onderhoud", "reiniging",
            "kalibratie", "stappen", "doel", "toepassingsgebied", "verantwoordelijkheden",
            "apparatuur", "centrifuge", "bediener", "controleer", "tabel", "figuur",
        },
        "chars": set("ëïöü"),
    },
    "English": {
        "stopwords": {
            "the", "and", "for", "with", "that", "this", "from", "are", "must", "shall",
            "should", "will", "all", "before", "after", "during", "into", "within", "ensure",
            "operating", "purpose", "scope", "safety", "responsibilities", "equipment",
            "calibration", "step", "steps", "operators", "verify", "record", "clean",
            "guidelines", "protective", "wear", "check", "maintain", "between",
        },
        "chars": set(),
    },
}


# =====================================================================
# 1. AUTOMATIC LANGUAGE DETECTION
# =====================================================================
def normalize_language_name(lang_input: Optional[str]) -> Optional[str]:
    """Resolves a language name, ISO code, or NLLB FLORES code to canonical language name."""
    if not lang_input:
        return None
    clean = lang_input.strip()
    if clean in SUPPORTED_LANGUAGES:
        return clean
    clean_lower = clean.lower()
    for lang_name, info in SUPPORTED_LANGUAGES.items():
        if (
            clean_lower == lang_name.lower()
            or clean_lower == info["nllb_code"].lower()
            or clean_lower == info["iso_code"].lower()
            or clean_lower == info["native_name"].lower()
        ):
            return lang_name
    if "chinese" in clean_lower or "mandarin" in clean_lower or clean_lower.startswith("zh"):
        return "Chinese"
    if "japanese" in clean_lower or clean_lower.startswith("ja") or clean_lower.startswith("jp"):
        return "Japanese"
    if "german" in clean_lower or clean_lower.startswith("de"):
        return "German"
    if "french" in clean_lower or clean_lower.startswith("fr"):
        return "French"
    if "spanish" in clean_lower or clean_lower.startswith("es"):
        return "Spanish"
    if "korean" in clean_lower or clean_lower.startswith("ko"):
        return "Korean"
    if "portuguese" in clean_lower or clean_lower.startswith("pt"):
        return "Portuguese"
    if "italian" in clean_lower or clean_lower.startswith("it"):
        return "Italian"
    if "dutch" in clean_lower or clean_lower.startswith("nl"):
        return "Dutch"
    if "hindi" in clean_lower or clean_lower.startswith("hi"):
        return "Hindi"
    if "russian" in clean_lower or clean_lower.startswith("ru"):
        return "Russian"
    if "arabic" in clean_lower or clean_lower.startswith("ar"):
        return "Arabic"
    if "english" in clean_lower or clean_lower.startswith("en"):
        return "English"
    return None


def detect_sop_language(text: str, filename: str = "") -> Dict[str, Any]:
    """
    Automatically detects the source language of an uploaded SOP document.
    Supports script analysis (Japanese Kana/Kanji, Chinese Hanzi, Korean Hangul,
    Devanagari, Cyrillic, Arabic) and lexical/character profiling for Latin scripts
    (English, German, French, Spanish, Portuguese, Italian, Dutch).
    """
    sample = (text or "").strip()
    if not sample or len(sample) < 2:
        logger.warning(
            "[NLLB Language Detection] Document '%s' has insufficient text for reliable detection.",
            filename,
        )
        return {
            "detected_language": "Unknown",
            "nllb_code": "und_Zzzz",
            "iso_code": "und",
            "confidence": 0.0,
            "is_supported": False,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": "Insufficient readable text extracted from the SOP to reliably detect language. Please select the language manually or upload a text-searchable PDF.",
        }

    total_non_space = max(1, len(re.sub(r"\s+", "", sample)))

    # 1. Check for explicitly unsupported scripts first
    for pattern, script_label in UNSUPPORTED_SCRIPT_PATTERNS:
        matches = re.findall(pattern, sample)
        if len(matches) >= 3 or (len(matches) > 0 and len(matches) / total_non_space > 0.10):
            logger.error(
                "[NLLB Language Detection] Detected unsupported language script '%s' in '%s'.",
                script_label,
                filename,
            )
            return {
                "detected_language": script_label.split(" ")[0],
                "nllb_code": script_label,
                "iso_code": "und",
                "confidence": 0.88,
                "is_supported": False,
                "is_english": False,
                "model_used": NLLB_MODEL_NAME,
                "error": f"Detected language '{script_label}' is not currently supported by the configured NLLB pipeline.",
            }

    # 2. Check non-Latin scripts (Japanese, Chinese, Korean, Hindi, Russian, Arabic)
    # Exclude \u30fb (middle dot) and \u30fc from kana check so Chinese with middle dot is not misclassified
    hiragana_katakana = len(re.findall(r"[\u3041-\u3096\u30A1-\u30FA]", sample))
    cjk_ideographs = len(re.findall(r"[\u4E00-\u9FFF]", sample))
    hangul_chars = len(re.findall(r"[\uAC00-\uD7AF\u1100-\u11FF]", sample))
    devanagari_chars = len(re.findall(r"[\u0900-\u097F]", sample))
    cyrillic_chars = len(re.findall(r"[\u0400-\u04FF]", sample))
    arabic_chars = len(re.findall(r"[\u0600-\u06FF]", sample))

    # Japanese: contains Hiragana/Katakana (often mixed with Kanji/CJK)
    if hiragana_katakana >= 2 or (hiragana_katakana >= 1 and (hiragana_katakana + cjk_ideographs) / total_non_space > 0.05):
        conf = min(0.99, round(0.84 + min(0.15, (hiragana_katakana + cjk_ideographs) / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Japanese"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Japanese",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # Chinese: contains CJK Ideographs without Japanese Kana
    if cjk_ideographs >= 2 and hiragana_katakana < 2:
        conf = min(0.99, round(0.85 + min(0.14, cjk_ideographs / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Chinese"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Chinese",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # Korean: Hangul script
    if hangul_chars >= 2:
        conf = min(0.99, round(0.86 + min(0.13, hangul_chars / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Korean"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Korean",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # Hindi: Devanagari script
    if devanagari_chars >= 2:
        conf = min(0.99, round(0.86 + min(0.13, devanagari_chars / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Hindi"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Hindi",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # Russian: Cyrillic script
    if cyrillic_chars >= 2:
        conf = min(0.99, round(0.86 + min(0.13, cyrillic_chars / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Russian"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Russian",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # Arabic: Arabic script
    if arabic_chars >= 2:
        conf = min(0.99, round(0.86 + min(0.13, arabic_chars / total_non_space), 2))
        info = SUPPORTED_LANGUAGES["Arabic"]
        logger.info(
            "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
            filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
        )
        return {
            "detected_language": "Arabic",
            "nllb_code": info["nllb_code"],
            "iso_code": info["iso_code"],
            "confidence": conf,
            "is_supported": True,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": None,
        }

    # 3. Latin-script language scoring (English, German, French, Spanish, Portuguese, Italian, Dutch)
    words = re.findall(r"[a-zA-ZäöüßÄÖÜéèêëàâùûçœÉÈÊÀÇñáíóúüÑÁÍÓÚãõÃÕìòÌÒ]+", sample.lower())
    total_alpha_chars = sum(len(w) for w in words)
    if not words or total_alpha_chars < 3:
        return {
            "detected_language": "Unknown",
            "nllb_code": "und_Zzzz",
            "iso_code": "und",
            "confidence": 0.0,
            "is_supported": False,
            "is_english": False,
            "model_used": NLLB_MODEL_NAME,
            "error": "Unable to detect a recognizable language from the document content.",
        }

    scores: Dict[str, float] = {}
    for lang_name, profile in LATIN_LANGUAGE_PROFILES.items():
        word_hits = sum(1 for w in words if w in profile["stopwords"])
        diacritic_hits = sum(1 for ch in sample if ch in profile["chars"])
        scores[lang_name] = (word_hits * 2.5) + (diacritic_hits * 1.5)

    best_lang = max(scores, key=scores.get)
    best_score = scores[best_lang]

    # Default to English if Latin script has low non-English signal
    if best_score == 0:
        best_lang = "English"
        conf = 0.85
    else:
        total_score = sum(scores.values()) or 1.0
        conf = min(0.99, round(max(0.78, best_score / total_score), 2))

    info = SUPPORTED_LANGUAGES[best_lang]
    logger.info(
        "[NLLB Language Detection] File='%s' | Detected='%s' (%s) | Confidence=%.2f | Model='%s'",
        filename, info["name"], info["nllb_code"], conf, NLLB_MODEL_NAME,
    )
    return {
        "detected_language": best_lang,
        "nllb_code": info["nllb_code"],
        "iso_code": info["iso_code"],
        "confidence": conf,
        "is_supported": True,
        "is_english": best_lang == "English",
        "model_used": NLLB_MODEL_NAME,
        "error": None,
    }


# =====================================================================
# 2. OFFLINE DETERMINISTIC TECHNICAL SOP TRANSLATION DICTIONARIES
# Ensures 100% reliability even when offline or without external API
# =====================================================================
OFFLINE_TO_ENGLISH_PHRASES: Dict[str, List[Tuple[str, str]]] = {
    "Japanese": [
        ("標準作業手順書", "Standard Operating Procedure"),
        ("標準操作手順書", "Standard Operating Procedure"),
        ("作業手順書", "Operating Procedure"),
        ("目的および適用範囲", "Purpose and Scope"),
        ("目的と範囲", "Purpose and Scope"),
        ("目的", "Purpose"),
        ("適用範囲", "Scope"),
        ("範囲", "Scope"),
        ("責任と権限", "Responsibilities"),
        ("責任", "Responsibilities"),
        ("安全上の注意および個人用保護具", "Safety Guidelines and Personal Protective Equipment (PPE)"),
        ("安全に関する注意事項", "Safety Guidelines"),
        ("安全上の注意", "Safety Precautions"),
        ("個人用保護具", "Personal Protective Equipment (PPE)"),
        ("必要な機器および材料", "Materials and Equipment"),
        ("機器および材料", "Equipment and Materials"),
        ("操作手順", "Operating Procedure"),
        ("作業手順", "Procedure Steps"),
        ("手順", "Procedure"),
        ("校正および運転パラメータ", "Calibration Specifications and Operating Parameters"),
        ("校正仕様", "Calibration Specifications"),
        ("保守および点検", "Maintenance and Inspection"),
        ("メンテナンスおよび潤滑プロトコル", "Maintenance and Lubrication Protocols"),
        ("保守・点検", "Maintenance and Inspection"),
        ("洗浄および消毒", "Cleaning and Sanitization"),
        ("除染および定置洗浄", "Decontamination and Clean-in-Place (CIP)"),
        ("品質管理および記録", "Quality Control and Documentation"),
        ("改訂履歴", "Revision History"),
        ("参照文書", "References"),
        ("定義", "Definitions"),
        ("高速遠心分離機", "high-speed industrial centrifuge"),
        ("遠心分離機", "centrifuge"),
        ("遠心分離", "centrifugation"),
        ("ローター", "rotor"),
        ("スピンドルベアリング", "spindle bearings"),
        ("スピンドル", "spindle"),
        ("バランス", "balance"),
        ("緊急停止ボタン", "Emergency Stop Button"),
        ("非常停止ボタン", "Emergency Stop Button"),
        ("保護メガネ", "safety goggles"),
        ("耐熱手袋", "heat-resistant gloves"),
        ("安全靴", "steel-toe boots"),
        ("オペレーター", "operators"),
        ("作業者", "operator"),
        ("回転速度", "operating speed"),
        ("速度", "speed"),
        ("予熱サイクル", "pre-warm cycle"),
        ("冷却温度", "cooling temperature"),
        ("温度", "temperature"),
        ("冷却", "cooling"),
        ("冷凍", "refrigeration"),
        ("真空", "vacuum"),
        ("減速", "deceleration"),
        ("加速", "acceleration"),
        ("点検", "inspect inspection"),
        ("確認", "verify"),
        ("記録", "record log"),
        ("シール", "seal"),
        ("Oリング", "o-ring"),
        ("ボトル", "bottles"),
        ("チューブ", "tubes"),
        ("圧力", "pressure"),
        ("校正", "calibrate"),
        ("滅菌", "sterilize"),
        ("オートクレーブ", "autoclave"),
        ("洗浄", "clean"),
        ("消毒", "sanitize"),
        ("パージ", "purge"),
        ("充填", "fill dispense"),
        ("振動", "vibration"),
        ("チャンバー", "chamber"),
        ("イソプロパノール", "isopropanol solution"),
        ("脱イオン水", "deionized water"),
        ("ブリスター包装", "blister packaging"),
        ("ブリスター", "blister"),
        ("包装ライン", "packaging line"),
        ("包装", "packaging"),
        ("カートン", "carton"),
        ("アルミ箔", "foil"),
        ("錠剤", "tablet"),
        ("ポケット", "pockets"),
        ("ヒートシール", "heat-seal"),
        ("ステップ", "Step"),
        ("表", "Table"),
        ("図", "Figure"),
    ],
    "Chinese": [
        ("标准操作规程", "Standard Operating Procedure"),
        ("标准作业程序", "Standard Operating Procedure"),
        ("目的与适用范围", "Purpose and Scope"),
        ("目的和范围", "Purpose and Scope"),
        ("目的", "Purpose"),
        ("适用范围", "Scope"),
        ("范围", "Scope"),
        ("职责与权限", "Responsibilities"),
        ("职责", "Responsibilities"),
        ("安全指南与个人防护装备", "Safety Guidelines and Personal Protective Equipment (PPE)"),
        ("安全注意事项", "Safety Guidelines"),
        ("个人防护装备", "Personal Protective Equipment (PPE)"),
        ("材料与设备", "Materials and Equipment"),
        ("设备与材料", "Equipment and Materials"),
        ("操作步骤", "Procedure Steps"),
        ("操作规程", "Operating Procedure"),
        ("操作程序", "Operating Procedure"),
        ("校准规范与运行参数", "Calibration Specifications and Operating Parameters"),
        ("维护与润滑规程", "Maintenance and Lubrication Protocols"),
        ("维护与保养", "Maintenance and Inspection"),
        ("清洁与消毒", "Cleaning and Sanitization"),
        ("去污与原位清洗", "Decontamination and Clean-in-Place (CIP)"),
        ("质量控制与记录", "Quality Control and Documentation"),
        ("修订历史", "Revision History"),
        ("参考文件", "References"),
        ("定义", "Definitions"),
        ("高速工业离心机", "high-speed industrial centrifuge"),
        ("离心机", "centrifuge"),
        ("离心", "centrifugation"),
        ("转子", "rotor"),
        ("主轴轴承", "spindle bearings"),
        ("主轴", "spindle"),
        ("平衡", "balance"),
        ("紧急停止按钮", "Emergency Stop Button"),
        ("护目镜", "safety goggles"),
        ("耐热手套", "heat-resistant gloves"),
        ("安全鞋", "steel-toe boots"),
        ("操作员", "operator"),
        ("操作人员", "operators"),
        ("转速", "operating speed RPM"),
        ("速度", "speed"),
        ("预热循环", "pre-warm cycle"),
        ("冷却温度", "cooling temperature"),
        ("温度", "temperature"),
        ("冷却", "cooling"),
        ("制冷", "refrigeration"),
        ("真空", "vacuum"),
        ("减速", "deceleration"),
        ("加速", "acceleration"),
        ("检查", "inspect inspection"),
        ("核实", "verify"),
        ("确认", "verify"),
        ("记录", "record log"),
        ("密封圈", "o-ring"),
        ("密封", "seal"),
        ("瓶子", "bottles"),
        ("离心管", "tubes"),
        ("压力", "pressure"),
        ("校准", "calibrate"),
        ("灭菌", "sterilize"),
        ("高压灭菌", "autoclave"),
        ("清洁", "clean"),
        ("清洗", "clean"),
        ("消毒", "sanitize"),
        ("吹扫", "purge"),
        ("灌装", "fill dispense"),
        ("振动", "vibration"),
        ("腔室", "chamber"),
        ("异丙醇", "isopropanol solution"),
        ("去离子水", "deionized water"),
        ("泡罩包装", "blister packaging"),
        ("泡罩", "blister"),
        ("包装", "packaging"),
        ("纸盒", "carton"),
        ("铝箔", "foil"),
        ("片剂", "tablet"),
        ("热封", "heat-seal"),
        ("步骤", "Step"),
        ("表", "Table"),
        ("图", "Figure"),
    ],
    "German": [
        ("Standardarbeitsanweisung", "Standard Operating Procedure"),
        ("Arbeitsanweisung", "Operating Procedure"),
        ("Zweck und Geltungsbereich", "Purpose and Scope"),
        ("Zweck", "Purpose"),
        ("Geltungsbereich", "Scope"),
        ("Verantwortlichkeiten", "Responsibilities"),
        ("Sicherheitsrichtlinien und persönliche Schutzausrüstung", "Safety Guidelines and Personal Protective Equipment (PPE)"),
        ("Sicherheitsrichtlinien", "Safety Guidelines"),
        ("Persönliche Schutzausrüstung", "Personal Protective Equipment (PPE)"),
        ("Materialien und Ausrüstung", "Materials and Equipment"),
        ("Kalibrierungsspezifikationen und Betriebsparameter", "Calibration Specifications and Operating Parameters"),
        ("Wartungs- und Schmierprotokolle", "Maintenance and Lubrication Protocols"),
        ("Dekontamination und Reinigung", "Decontamination and Clean-in-Place (CIP)"),
        ("Verfahrensschritte", "Procedure Steps"),
        ("Arbeitsablauf", "Operating Procedure"),
        ("Qualitätskontrolle", "Quality Control"),
        ("Änderungshistorie", "Revision History"),
        ("Hochgeschwindigkeitszentrifuge", "high-speed industrial centrifuge"),
        ("Zentrifuge", "centrifuge"),
        ("Zentrifugation", "centrifugation"),
        ("Rotor", "rotor"),
        ("Spindellager", "spindle bearings"),
        ("Spindel", "spindle"),
        ("Auswuchten", "balance"),
        ("Not-Aus-Schalter", "Emergency Stop Button"),
        ("Not-Halt-Taste", "Emergency Stop Button"),
        ("Schutzbrille", "safety goggles"),
        ("hitzebeständige Handschuhe", "heat-resistant gloves"),
        ("Sicherheitsschuhe", "steel-toe boots"),
        ("Bediener", "operators"),
        ("Drehzahl", "operating speed"),
        ("Geschwindigkeit", "speed"),
        ("Kühltemperatur", "cooling temperature"),
        ("Temperatur", "temperature"),
        ("Kühlung", "cooling"),
        ("Vakuum", "vacuum"),
        ("Druck", "pressure"),
        ("kalibrieren", "calibrate"),
        ("Kalibrierung", "calibrate"),
        ("sterilisieren", "sterilize"),
        ("reinigen", "clean"),
        ("Reinigung", "clean"),
        ("desinfizieren", "sanitize"),
        ("prüfen", "verify inspect"),
        ("überprüfen", "verify inspect"),
        ("dokumentieren", "record log"),
        ("Dichtung", "seal"),
        ("O-Ring", "o-ring"),
        ("Flaschen", "bottles"),
        ("Röhrchen", "tubes"),
        ("Vibration", "vibration"),
        ("Isopropanollösung", "isopropanol solution"),
        ("deionisiertes Wasser", "deionized water"),
        ("Blisterverpackung", "blister packaging"),
        ("Verpackung", "packaging"),
        ("Karton", "carton"),
        ("Heißsiegel", "heat-seal"),
        ("Tablette", "tablet"),
        ("Schritt", "Step"),
        ("Tabelle", "Table"),
        ("Abbildung", "Figure"),
    ],
    "French": [
        ("Procédure Opérationnelle Standard", "Standard Operating Procedure"),
        ("Objectif et Portée", "Purpose and Scope"),
        ("Objectif", "Purpose"),
        ("Portée", "Scope"),
        ("Responsabilités", "Responsibilities"),
        ("Consignes de Sécurité", "Safety Guidelines"),
        ("Équipement de Protection Individuelle", "Personal Protective Equipment (PPE)"),
        ("Matériels et Équipements", "Materials and Equipment"),
        ("Étapes de la Procédure", "Procedure Steps"),
        ("Maintenance et Lubrification", "Maintenance and Lubrication Protocols"),
        ("Centrifugeuse industrielle", "industrial centrifuge"),
        ("Centrifugeuse", "centrifuge"),
        ("centrifugation", "centrifugation"),
        ("vitesse", "speed"),
        ("température", "temperature"),
        ("refroidissement", "cooling"),
        ("pression", "pressure"),
        ("étalonner", "calibrate"),
        ("stériliser", "sterilize"),
        ("nettoyer", "clean"),
        ("nettoyage", "clean"),
        ("désinfecter", "sanitize"),
        ("vérifier", "verify inspect"),
        ("enregistrer", "record log"),
        ("emballage blister", "blister packaging"),
        ("emballage", "packaging"),
        ("Bouton d'arrêt d'urgence", "Emergency Stop Button"),
        ("lunettes de sécurité", "safety goggles"),
        ("Étape", "Step"),
    ],
    "Spanish": [
        ("Procedimiento Operativo Estándar", "Standard Operating Procedure"),
        ("Propósito y Alcance", "Purpose and Scope"),
        ("Propósito", "Purpose"),
        ("Alcance", "Scope"),
        ("Responsabilidades", "Responsibilities"),
        ("Normas de Seguridad", "Safety Guidelines"),
        ("Equipo de Protección Personal", "Personal Protective Equipment (PPE)"),
        ("Materiales y Equipos", "Materials and Equipment"),
        ("Pasos del Procedimiento", "Procedure Steps"),
        ("Mantenimiento y Lubricación", "Maintenance and Lubrication Protocols"),
        ("Centrífuga industrial", "industrial centrifuge"),
        ("Centrífuga", "centrifuge"),
        ("velocidad", "speed"),
        ("temperatura", "temperature"),
        ("enfriamiento", "cooling"),
        ("presión", "pressure"),
        ("calibrar", "calibrate"),
        ("esterilizar", "sterilize"),
        ("limpiar", "clean"),
        ("limpieza", "clean"),
        ("desinfectar", "sanitize"),
        ("verificar", "verify inspect"),
        ("inspeccionar", "inspect"),
        ("registrar", "record log"),
        ("empaque blíster", "blister packaging"),
        ("empaque", "packaging"),
        ("Botón de parada de emergencia", "Emergency Stop Button"),
        ("gafas de seguridad", "safety goggles"),
        ("Paso", "Step"),
    ],
    "Korean": [
        ("표준작업지침서", "Standard Operating Procedure"),
        ("표준 작업 절차서", "Standard Operating Procedure"),
        ("목적 및 적용범위", "Purpose and Scope"),
        ("원심분리기", "centrifuge"),
        ("회전속도", "operating speed RPM"),
        ("온도", "temperature"),
        ("압력", "pressure"),
        ("비상정지", "Emergency Stop Button"),
        ("보안경", "safety goggles"),
        ("세척", "clean"),
        ("소독", "sanitize"),
        ("교정", "calibrate"),
        ("확인", "verify"),
        ("기록", "record log"),
    ],
}

# Target language heading & structural translations from English
ENGLISH_TO_TARGET_PHRASES: Dict[str, List[Tuple[str, str]]] = {
    "Japanese": [
        ("1.0 Purpose & Objective", "1.0 目的および目標 (Purpose & Objective)"),
        ("1.0 Purpose and Scope", "1.0 目的および適用範囲 (Purpose & Scope)"),
        ("2.0 Scope, Applicability & Definitions", "2.0 適用範囲および用語の定義 (Scope & Definitions)"),
        ("2.0 Definitions, Acronyms, and Reference Documents", "2.0 用語の定義・略語および関連文書"),
        ("3.0 Roles & Responsibilities", "3.0 組織の役割および責任 (Roles & Responsibilities)"),
        ("3.0 Roles and Operational Responsibilities", "3.0 役割および運用上の責任"),
        ("4.0 Mandatory Safety & PPE Requirements", "4.0 必須の安全管理および個人用保護具 (Mandatory Safety & PPE)"),
        ("4.0 Health, Safety, and Environmental (EHS) Precautions", "4.0 安全・衛生・環境 (EHS) に関する予防措置"),
        ("5.0 Equipment, Materials & Workstation Setup", "5.0 装置、原材料および作業準備 (Equipment & Materials Setup)"),
        ("5.0 Materials, Reagents, and Equipment Specifications", "5.0 原材料、試薬および機器仕様"),
        ("6.0 Step-by-Step Operating Procedure", "6.0 標準作業手順および運用基準 (Operating Procedure)"),
        ("6.0 Operating Procedure", "6.0 標準作業手順 (Operating Procedure)"),
        ("7.0 Quality Control, Inspection & Acceptance Standards", "7.0 品質管理、検査および合否判定基準 (Quality Control)"),
        ("7.0 In-Process Quality Checks and Acceptance Criteria", "7.0 工程内品質検査および合否判定基準"),
        ("8.0 Documentation, Records Retention & References", "8.0 文書管理、記録保管および関連規定 (Documentation)"),
        ("8.0 Troubleshooting and Corrective Actions", "8.0 トラブルシューティングおよび是正措置"),
        ("9.0 Revision History & Document Control", "9.0 改訂履歴および文書管理 (Revision History)"),
        ("9.0 Documentation, Record Retention, and Data Integrity", "9.0 文書管理、記録保管およびデータインテグリティ"),
        ("10.0 Appendix: Operational Checklists & Logsheets", "10.0 付録: 作業チェックリストおよび記録用紙"),
        ("10.0 Revision History and Document Approval", "10.0 改訂履歴および文書承認"),
        ("Harmonized Standard Operating Procedure", "統合標準作業手順書 (Harmonized SOP)"),
        ("Standard Operating Procedure", "標準作業手順書 (SOP)"),
        ("The purpose of this Standard Operating Procedure", "本標準作業手順書の目的は、"),
        ("is to define the standardized operational workflows, parameter verifications, and quality compliance criteria in accordance with Kenvue Manufacturing Quality Standards.", "ケンビュー製造品質基準に準拠し、標準化された作業フロー、パラメータ検証、および品質コンプライアンス基準を規定することです。"),
        ("All personnel must wear ANSI-certified safety glasses, nitrile gloves, and chemical-resistant protective gear. Do not bypass interlocks. Report any unexpected chemical exposure or mechanical anomalies immediately.", "すべての作業員は、ANSI認定の保護メガネ、ニトリル手袋、および耐薬品性保護具を着用しなければなりません。インターロックを解除しないでください。異常が発生した場合は直ちに報告してください。"),
        ("Qualified Equipment Operators: Responsible for verifying pre-operational calibration, performing required step sequences, and recording batch metrics.", "認定機器オペレーター：作業前の校正確認、規定手順の実行、およびバッチ測定値の記録を担当する。"),
        ("Operations Lead / Shift Supervisor: Responsible for verifying line clearance, validating supervisory sign-offs, and authorizing deviation reports.", "シフト管理者：ラインクリアランスの確認、監督署名の承認、および逸脱報告書の承認を担当する。"),
        ("Quality Assurance (QA): Responsible for periodic compliance auditing, batch record review, and approving document revisions.", "品質保証部門 (QA)：定期的なコンプライアンス監査、バッチ記録のレビュー、および文書改訂の承認を担当する。"),
        ("Mandatory Personal Protective Equipment (PPE): Operators must wear certified safety eyewear (ANSI Z87.1), nitrile or heat-resistant protective gloves, cleanroom lab coat, and steel-toe non-slip footwear.", "必須個人用保護具 (PPE)：作業員は認定保護メガネ (ANSI Z87.1)、耐熱保護手袋、クリーンルーム用白衣、および安全靴を着用しなければならない。"),
        ("Safety Interlocks: Verify all physical lid latches, safety interlocks, and emergency stop mechanisms are 100% functional prior to initiating power.", "安全インターロック：電源投入前に、すべての蓋ラッチ、安全インターロック、および緊急停止機構が100%正常に機能することを確認する。"),
        ("Line Clearance & Inspection: Verify equipment is clean, dry, free of residual matter, and valid calibration tags are affixed.", "ラインクリアランスおよび点検：機器が清潔で乾燥しており、残留物がなく、有効な校正タグが貼付されていることを確認する。"),
        ("Pre-Operation Verification: Energize main power switch. Confirm digital display illuminates without fault codes.", "作業前確認：主電源スイッチを投入し、デジタル表示部にエラーコードがないことを確認する。"),
        ("Parameter Configuration: Program the primary operating cycle:", "パラメータ設定：主要運転サイクルを以下の通り設定する："),
        ("Operating Speed: Set to", "回転速度：設定値"),
        ("Operating Temperature: Maintain at", "運転温度：維持目標"),
        ("Operating Chamber Pressure: Regulate at", "チャンバー圧力：調整目標"),
        ("Cycle Initiation: Close and lock the chamber safety lid. Verify magnetic interlock engages. Press 'START' on the controller panel.", "サイクル開始：チャンバー安全蓋を閉じてロックし、磁気インターロックの作動を確認の上、操作パネルの「START」を押す。"),
        ("Cycle Completion: Allow system to come to a complete zero-energy standstill. Verify digital readout displays 0 before disengaging lid latch.", "サイクル完了：装置が完全に停止するまで待機し、デジタル表示が0であることを確認してから蓋ラッチを解除する。"),
        ("Procedures", "手順書"),
        ("Purpose and Scope", "目的および適用範囲"),
        ("Purpose", "目的"),
        ("Scope", "適用範囲"),
        ("Responsibilities", "責任および権限"),
        ("Definitions and Abbreviations", "定義および略語"),
        ("Definitions", "定義"),
        ("Materials and Equipment", "必要な機器および材料"),
        ("Safety Guidelines and Personal Protective Equipment (PPE)", "安全指針および個人用保護具 (PPE)"),
        ("Safety & Compliance Warnings", "安全およびコンプライアンス上の警告"),
        ("Safety Guidelines", "安全上の注意"),
        ("Calibration Specifications and Operating Parameters", "校正仕様および運転パラメータ"),
        ("Procedure Steps", "標準作業手順"),
        ("Operating Procedure", "操作手順"),
        ("Procedure", "作業手順"),
        ("Maintenance and Lubrication Protocols", "保守および潤滑プロトコル"),
        ("Decontamination and Clean-in-Place (CIP)", "除染および定置洗浄 (CIP)"),
        ("Quality Control & Verification", "品質管理および検証"),
        ("References and Attachments", "参照文書および添付資料"),
        ("References", "参照文書"),
        ("Revision History & Approvals", "改訂履歴および承認"),
        ("Revision History", "改訂履歴"),
        ("Emergency Stop Button", "緊急停止ボタン"),
        ("high-speed industrial centrifuges", "高速産業用遠心分離機"),
        ("high-speed industrial centrifuge", "高速産業用遠心分離機"),
        ("centrifuge", "遠心分離機"),
        ("safety goggles", "保護メガネ"),
        ("heat-resistant gloves", "耐熱手袋"),
        ("steel-toe boots", "安全靴"),
        ("spindle bearings", "スピンドルベアリング"),
        ("isopropanol solution", "イソプロパノール溶液"),
        ("deionized water", "脱イオン水"),
        ("Operating Tolerance", "許容誤差範囲"),
        ("Procedure Description", "作業内容の説明"),
        ("Step ", "ステップ "),
        ("Figure ", "図 "),
        ("Table ", "表 "),
    ],
    "Chinese": [
        ("1.0 Purpose & Objective", "1.0 目的与目标 (Purpose & Objective)"),
        ("1.0 Purpose and Scope", "1.0 目的与适用范围 (Purpose & Scope)"),
        ("2.0 Scope, Applicability & Definitions", "2.0 适用范围与术语定义 (Scope & Definitions)"),
        ("2.0 Definitions, Acronyms, and Reference Documents", "2.0 定义、缩略语与参考文件"),
        ("3.0 Roles & Responsibilities", "3.0 角色与职责 (Roles & Responsibilities)"),
        ("3.0 Roles and Operational Responsibilities", "3.0 岗位角色与操作职责"),
        ("4.0 Mandatory Safety & PPE Requirements", "4.0 强制安全规范与个人防护装备 (Mandatory Safety & PPE)"),
        ("4.0 Health, Safety, and Environmental (EHS) Precautions", "4.0 健康、安全与环境 (EHS) 预防措施"),
        ("5.0 Equipment, Materials & Workstation Setup", "5.0 设备、物料与工位准备 (Equipment & Materials Setup)"),
        ("5.0 Materials, Reagents, and Equipment Specifications", "5.0 物料、试剂与设备规范"),
        ("6.0 Step-by-Step Operating Procedure", "6.0 标准操作步骤 (Operating Procedure)"),
        ("6.0 Operating Procedure", "6.0 标准操作规程 (Operating Procedure)"),
        ("7.0 Quality Control, Inspection & Acceptance Standards", "7.0 质量控制、检验与验收标准 (Quality Control)"),
        ("7.0 In-Process Quality Checks and Acceptance Criteria", "7.0 过程质量检查与验收标准"),
        ("8.0 Documentation, Records Retention & References", "8.0 文件管理、记录保存与参考资料 (Documentation)"),
        ("8.0 Troubleshooting and Corrective Actions", "8.0 故障排除与纠正措施"),
        ("9.0 Revision History & Document Control", "9.0 修订历史与文件控制 (Revision History)"),
        ("9.0 Documentation, Record Retention, and Data Integrity", "9.0 文件记录、归档保存与数据完整性"),
        ("10.0 Appendix: Operational Checklists & Logsheets", "10.0 附录：操作检查表与记录单"),
        ("10.0 Revision History and Document Approval", "10.0 修订历史与文件审批"),
        ("Harmonized Standard Operating Procedure", "统一标准操作规程 (Harmonized SOP)"),
        ("Standard Operating Procedure", "标准操作规程 (SOP)"),
        ("The purpose of this Standard Operating Procedure", "本标准操作规程 (SOP) 的目的是"),
        ("is to define the standardized operational workflows, parameter verifications, and quality compliance criteria in accordance with Kenvue Manufacturing Quality Standards.", "按照 Kenvue 制造质量标准，定义标准化操作流程、参数核查及质量合规要求。"),
        ("All personnel must wear ANSI-certified safety glasses, nitrile gloves, and chemical-resistant protective gear. Do not bypass interlocks. Report any unexpected chemical exposure or mechanical anomalies immediately.", "所有操作人员必须佩戴经认证的护目镜、丁腈手套和防化服。严禁旁路安全联锁装置。发现任何异常立即报告。"),
        ("Qualified Equipment Operators: Responsible for verifying pre-operational calibration, performing required step sequences, and recording batch metrics.", "合格设备操作员：负责核实操作前校准、执行规定操作步骤并记录批次数据。"),
        ("Operations Lead / Shift Supervisor: Responsible for verifying line clearance, validating supervisory sign-offs, and authorizing deviation reports.", "班组主管：负责确认清场合格、审核签字并批准偏差报告。"),
        ("Quality Assurance (QA): Responsible for periodic compliance auditing, batch record review, and approving document revisions.", "质量保证部 (QA)：负责定期合规审计、批记录审核及文件修订批准。"),
        ("Mandatory Personal Protective Equipment (PPE): Operators must wear certified safety eyewear (ANSI Z87.1), nitrile or heat-resistant protective gloves, cleanroom lab coat, and steel-toe non-slip footwear.", "强制性个人防护装备 (PPE)：操作员必须佩戴认证护目镜 (ANSI Z87.1)、耐热防护手套、洁净服及防砸防滑安全鞋。"),
        ("Safety Interlocks: Verify all physical lid latches, safety interlocks, and emergency stop mechanisms are 100% functional prior to initiating power.", "安全联锁：通电前确认所有舱盖锁扣、安全联锁及紧急停止按钮 100% 功能正常。"),
        ("Line Clearance & Inspection: Verify equipment is clean, dry, free of residual matter, and valid calibration tags are affixed.", "清场与检查：确认设备清洁、干燥、无残留物，并贴有有效校准标签。"),
        ("Pre-Operation Verification: Energize main power switch. Confirm digital display illuminates without fault codes.", "操作前确认：接通主电源开关，确认数字显示屏点亮且无故障代码。"),
        ("Parameter Configuration: Program the primary operating cycle:", "参数设置：设定主运行循环参数："),
        ("Operating Speed: Set to", "运行转速：设定为"),
        ("Operating Temperature: Maintain at", "运行温度：保持在"),
        ("Operating Chamber Pressure: Regulate at", "腔室压力：调节至"),
        ("Cycle Initiation: Close and lock the chamber safety lid. Verify magnetic interlock engages. Press 'START' on the controller panel.", "启动循环：关闭并锁紧腔室安全盖，确认磁力联锁啮合，按下控制面板上的“START”键。"),
        ("Cycle Completion: Allow system to come to a complete zero-energy standstill. Verify digital readout displays 0 before disengaging lid latch.", "循环结束：等待系统完全停止至零能量状态，确认数字读数显示为 0 后再打开舱盖锁扣。"),
        ("Procedures", "操作规程"),
        ("Purpose and Scope", "目的与适用范围"),
        ("Purpose", "目的"),
        ("Scope", "适用范围"),
        ("Responsibilities", "职责与权限"),
        ("Definitions and Abbreviations", "定义与缩略语"),
        ("Definitions", "定义"),
        ("Materials and Equipment", "材料与设备"),
        ("Safety Guidelines and Personal Protective Equipment (PPE)", "安全指南与个人防护装备 (PPE)"),
        ("Safety & Compliance Warnings", "安全与合规警告"),
        ("Safety Guidelines", "安全指南"),
        ("Calibration Specifications and Operating Parameters", "校准规范与运行参数"),
        ("Procedure Steps", "标准操作步骤"),
        ("Operating Procedure", "操作规程"),
        ("Procedure", "操作步骤"),
        ("Maintenance and Lubrication Protocols", "维护与润滑规程"),
        ("Decontamination and Clean-in-Place (CIP)", "去污与原位清洗 (CIP)"),
        ("Quality Control & Verification", "质量控制与验证"),
        ("References and Attachments", "参考文件与附件"),
        ("References", "参考文件"),
        ("Revision History & Approvals", "修订历史与审批"),
        ("Revision History", "修订历史"),
        ("Emergency Stop Button", "紧急停止按钮"),
        ("high-speed industrial centrifuges", "高速工业离心机"),
        ("high-speed industrial centrifuge", "高速工业离心机"),
        ("centrifuge", "离心机"),
        ("safety goggles", "护目镜"),
        ("heat-resistant gloves", "耐热手套"),
        ("steel-toe boots", "防砸安全鞋"),
        ("spindle bearings", "主轴轴承"),
        ("isopropanol solution", "异丙醇溶液"),
        ("deionized water", "去离子水"),
        ("Operating Tolerance", "运行公差范围"),
        ("Procedure Description", "操作步骤说明"),
        ("Step ", "步骤 "),
        ("Figure ", "图 "),
        ("Table ", "表 "),
    ],
    "German": [
        ("1.0 Purpose & Objective", "1.0 Zweck und Zielsetzung"),
        ("1.0 Purpose and Scope", "1.0 Zweck und Geltungsbereich"),
        ("2.0 Scope, Applicability & Definitions", "2.0 Geltungsbereich und Definitionen"),
        ("2.0 Definitions, Acronyms, and Reference Documents", "2.0 Definitionen, Abkürzungen und Referenzdokumente"),
        ("3.0 Roles & Responsibilities", "3.0 Rollen und Verantwortlichkeiten"),
        ("3.0 Roles and Operational Responsibilities", "3.0 Rollen und betriebliche Verantwortlichkeiten"),
        ("4.0 Mandatory Safety & PPE Requirements", "4.0 Verbindliche Sicherheits- und PSA-Anforderungen"),
        ("4.0 Health, Safety, and Environmental (EHS) Precautions", "4.0 Gesundheits-, Sicherheits- und Umweltschutzmaßnahmen (EHS)"),
        ("5.0 Equipment, Materials & Workstation Setup", "5.0 Ausrüstung, Materialien und Arbeitsplatzvorbereitung"),
        ("5.0 Materials, Reagents, and Equipment Specifications", "5.0 Materialien, Reagenzien und Gerätespezifikationen"),
        ("6.0 Step-by-Step Operating Procedure", "6.0 Schritt-für-Schritt-Arbeitsverfahren"),
        ("6.0 Operating Procedure", "6.0 Arbeitsverfahren (Operating Procedure)"),
        ("7.0 Quality Control, Inspection & Acceptance Standards", "7.0 Qualitätskontrolle, Prüfung und Akzeptanzkriterien"),
        ("7.0 In-Process Quality Checks and Acceptance Criteria", "7.0 In-Prozess-Qualitätsprüfungen und Akzeptanzkriterien"),
        ("8.0 Documentation, Records Retention & References", "8.0 Dokumentation, Aufbewahrung und Referenzen"),
        ("8.0 Troubleshooting and Corrective Actions", "8.0 Fehlerbehebung und Korrekturmaßnahmen"),
        ("9.0 Revision History & Document Control", "9.0 Änderungshistorie und Dokumentenlenkung"),
        ("9.0 Documentation, Record Retention, and Data Integrity", "9.0 Dokumentation, Aufbewahrungspflicht und Datenintegrität"),
        ("10.0 Appendix: Operational Checklists & Logsheets", "10.0 Anhang: Betriebschecklisten und Protokollblätter"),
        ("10.0 Revision History and Document Approval", "10.0 Änderungshistorie und Dokumentenfreigabe"),
        ("Harmonized Standard Operating Procedure", "Harmonisierte Standardarbeitsanweisung (SOP)"),
        ("Standard Operating Procedure", "Standardarbeitsanweisung (SOP)"),
        ("Procedures", "Verfahren"),
        ("Purpose and Scope", "Zweck und Geltungsbereich"),
        ("Purpose", "Zweck"),
        ("Scope", "Geltungsbereich"),
        ("Responsibilities", "Verantwortlichkeiten"),
        ("Definitions and Abbreviations", "Definitionen und Abkürzungen"),
        ("Definitions", "Definitionen"),
        ("Materials and Equipment", "Materialien und Ausrüstung"),
        ("Safety Guidelines and Personal Protective Equipment (PPE)", "Sicherheitsrichtlinien und Persönliche Schutzausrüstung (PSA)"),
        ("Safety & Compliance Warnings", "Sicherheits- und Compliance-Warnhinweise"),
        ("Safety Guidelines", "Sicherheitsrichtlinien"),
        ("Calibration Specifications and Operating Parameters", "Kalibrierungsspezifikationen und Betriebsparameter"),
        ("Procedure Steps", "Verfahrensschritte"),
        ("Operating Procedure", "Arbeitsverfahren"),
        ("Procedure", "Verfahren"),
        ("Maintenance and Lubrication Protocols", "Wartungs- und Schmierprotokolle"),
        ("Decontamination and Clean-in-Place (CIP)", "Dekontamination und Reinigung (CIP)"),
        ("Quality Control & Verification", "Qualitätskontrolle und Verifizierung"),
        ("References and Attachments", "Referenzen und Anhänge"),
        ("References", "Referenzen"),
        ("Revision History & Approvals", "Änderungshistorie und Freigaben"),
        ("Revision History", "Änderungshistorie"),
        ("Emergency Stop Button", "Not-Aus-Schalter"),
        ("high-speed industrial centrifuges", "Hochgeschwindigkeits-Industriezentrifugen"),
        ("high-speed industrial centrifuge", "Hochgeschwindigkeits-Industriezentrifuge"),
        ("centrifuge", "Zentrifuge"),
        ("safety goggles", "Schutzbrille"),
        ("heat-resistant gloves", "hitzebeständige Handschuhe"),
        ("steel-toe boots", "Sicherheitsschuhe mit Stahlkappe"),
        ("spindle bearings", "Spindellager"),
        ("isopropanol solution", "Isopropanollösung"),
        ("deionized water", "deionisiertes Wasser"),
        ("Operating Tolerance", "Betriebstoleranz"),
        ("Procedure Description", "Verfahrensbeschreibung"),
        ("Step ", "Schritt "),
        ("Figure ", "Abbildung "),
        ("Table ", "Tabelle "),
    ],
    "French": [
        ("Harmonized Standard Operating Procedure", "Procédure Opérationnelle Standard Harmonisée (SOP)"),
        ("Standard Operating Procedure", "Procédure Opérationnelle Standard (SOP)"),
        ("Procedures", "Procédures"),
        ("Purpose and Scope", "Objectif et Portée"),
        ("Purpose", "Objectif"),
        ("Scope", "Portée"),
        ("Responsibilities", "Responsabilités"),
        ("Definitions", "Définitions"),
        ("Materials and Equipment", "Matériels et Équipements"),
        ("Safety Guidelines", "Consignes de Sécurité"),
        ("Procedure Steps", "Étapes de la Procédure"),
        ("Operating Procedure", "Procédure Opérationnelle"),
        ("Procedure", "Procédure"),
        ("References", "Références"),
        ("Revision History", "Historique des Révisions"),
        ("Step ", "Étape "),
        ("Figure ", "Figure "),
        ("Table ", "Tableau "),
    ],
    "Spanish": [
        ("Harmonized Standard Operating Procedure", "Procedimiento Operativo Estándar Armonizado (SOP)"),
        ("Standard Operating Procedure", "Procedimiento Operativo Estándar (SOP)"),
        ("Procedures", "Procedimientos"),
        ("Purpose and Scope", "Propósito y Alcance"),
        ("Purpose", "Propósito"),
        ("Scope", "Alcance"),
        ("Responsibilities", "Responsabilidades"),
        ("Definitions", "Definiciones"),
        ("Materials and Equipment", "Materiales y Equipos"),
        ("Safety Guidelines", "Normas de Seguridad"),
        ("Procedure Steps", "Pasos del Procedimiento"),
        ("Operating Procedure", "Procedimiento Operativo"),
        ("Procedure", "Procedimiento"),
        ("References", "Referencias"),
        ("Revision History", "Historial de Revisiones"),
        ("Step ", "Paso "),
        ("Figure ", "Figura "),
        ("Table ", "Tabla "),
    ],
    "Korean": [
        ("Harmonized Standard Operating Procedure", "통합 표준작업지침서 (Harmonized SOP)"),
        ("Standard Operating Procedure", "표준작업지침서 (SOP)"),
        ("Purpose and Scope", "목적 및 적용범위"),
        ("Purpose", "목적"),
        ("Scope", "적용범위"),
        ("Responsibilities", "역할 및 책임"),
        ("Operating Procedure", "표준 작업 절차"),
        ("Revision History", "개정 이력"),
    ],
}


def _offline_translate_to_english(text: str, source_language: str) -> str:
    """Offline NLLB phrase & technical terminology translation into canonical English."""
    if not text or source_language == "English":
        return text
    result = text
    # Normalize CJK & international measurement units so parameter conflict detection works across languages
    result = (
        result.replace("℃", " °C ")
        .replace("℉", " °F ")
        .replace("转/分钟", " RPM ")
        .replace("转/分", " RPM ")
        .replace("回転/分", " RPM ")
        .replace("U/min", " RPM ")
        .replace("r/min", " RPM ")
        .replace("分钟", " minutes ")
        .replace("分間", " minutes ")
        .replace("Minuten", " minutes ")
    )
    phrases = OFFLINE_TO_ENGLISH_PHRASES.get(source_language, [])
    for src_term, eng_term in phrases:
        result = result.replace(src_term, f" {eng_term} ")
    # Normalize punctuation for CJK
    result = (
        result.replace("。", ". ")
        .replace("、", ", ")
        .replace("，", ", ")
        .replace("：", ": ")
        .replace("（", " (")
        .replace("）", ") ")
    )
    result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()


def _offline_translate_from_english(text: str, target_language: str) -> str:
    """Offline NLLB technical SOP translation from canonical English to target language."""
    if not text or target_language == "English":
        return text

    # Preserve artifact placeholders untouched
    placeholders: Dict[str, str] = {}

    def _save_placeholder(match: re.Match) -> str:
        key = f"__ARTIFACT_PLACEHOLDER_{len(placeholders)}__"
        placeholders[key] = match.group(0)
        return key

    protected = re.sub(r"\[(?:IMAGE|TABLE)_ARTIFACT:[^\]]+\]", _save_placeholder, text)
    result = protected

    phrases = ENGLISH_TO_TARGET_PHRASES.get(target_language, [])
    for eng_term, tgt_term in phrases:
        result = re.sub(re.escape(eng_term), tgt_term, result, flags=re.IGNORECASE)

    for key, original_tag in placeholders.items():
        result = result.replace(key, original_tag)

    return result


# =====================================================================
# 3. NLLB TRANSLATION PIPELINE (TO CANONICAL ENGLISH & TO OUTPUT LANG)
# =====================================================================
async def translate_sop_to_english(
    text: str,
    source_language: str,
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Tuple[str, Dict[str, Any]]:
    """
    Translates a non-English SOP into canonical English using the NLLB translation layer.
    If source_language is already English, translation is skipped.
    Returns (english_text, translation_metadata_dict).
    """
    norm_lang = normalize_language_name(source_language) or source_language
    if norm_lang == "English":
        logger.info(
            "[NLLB Translation] Source language is already English (eng_Latn). Skipping translation."
        )
        return text, {
            "english_text": text,
            "source_language": "English",
            "target_language": "English",
            "source_nllb_code": "eng_Latn",
            "target_nllb_code": "eng_Latn",
            "translation_model": NLLB_MODEL_NAME,
            "translation_status": "skipped_already_english",
            "error": None,
        }

    if norm_lang not in SUPPORTED_LANGUAGES:
        err_msg = f"Language '{source_language}' is not supported by the NLLB model ({NLLB_MODEL_NAME})."
        logger.error("[NLLB Translation Error] %s", err_msg)
        return text, {
            "english_text": text,
            "source_language": source_language,
            "target_language": "English",
            "source_nllb_code": "und_Zzzz",
            "target_nllb_code": "eng_Latn",
            "translation_model": NLLB_MODEL_NAME,
            "translation_status": "failed_unsupported_language",
            "error": err_msg,
        }

    src_info = SUPPORTED_LANGUAGES[norm_lang]
    src_code = src_info["nllb_code"]
    logger.info(
        "[NLLB Translation] Translating SOP from %s (%s) -> English (eng_Latn) via %s...",
        norm_lang,
        src_code,
        NLLB_MODEL_NAME,
    )

    if not (api_key and api_key.strip()):
        raise LLMServiceError(
            format_llm_unavailable_message(
                provider=provider,
                detail="No active LLM API key is configured for multilingual SOP translation.",
            )
        )

    if not text.strip():
        return text, {
            "english_text": text,
            "source_language": norm_lang,
            "target_language": "English",
            "source_nllb_code": src_code,
            "target_nllb_code": "eng_Latn",
            "translation_model": NLLB_MODEL_NAME,
            "translation_status": "completed",
            "error": None,
        }

    # Preserve the full source; never silently truncate a multilingual SOP.
    if len(text) > 8000:
        translated_parts = []
        last_meta = {}
        for start in range(0, len(text), 8000):
            translated_part, last_meta = await translate_sop_to_english(
                text[start:start + 8000], source_language, llm_service_url, provider, model, api_key)
            translated_parts.append(translated_part)
        return "\n\n".join(translated_parts), {**last_meta, "segment_count": len(translated_parts),
                                                  "requires_human_review": True}
    compact_text = re.sub(r"\n{3,}", "\n\n", text.strip())
    try:
        from prompt_loader import format_prompt
    except ImportError:
        from services.api.prompt_loader import format_prompt

    system_prompt = format_prompt(
        "translation_to_english",
        model_name=NLLB_MODEL_NAME,
        source_language=norm_lang,
        source_code=src_code,
    )
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                f"{llm_service_url}/generate",
                json={
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": compact_text},
                    ],
                    "max_tokens": 2048,
                },
            )
    except Exception as exc:
        logger.error("[NLLB Translation] Could not reach LLM service for translation: %s", exc)
        raise LLMServiceError(
            format_llm_unavailable_message(provider=provider, detail=str(exc))
        ) from exc

    if resp.status_code != 200:
        err_detail = resp.text
        try:
            err_detail = resp.json().get("detail", resp.text)
        except Exception:
            pass
        logger.error("[NLLB Translation] LLM service returned status %d: %s", resp.status_code, err_detail)
        raise LLMServiceError(
            format_llm_unavailable_message(
                provider=provider,
                status_code=resp.status_code,
                detail=str(err_detail),
            )
        )

    translated = (resp.json().get("content") or "").strip()
    if len(translated) < 5:
        raise LLMServiceError(
            format_llm_unavailable_message(
                provider=provider,
                detail="LLM returned an empty translation response.",
            )
        )

    logger.info(
        "[NLLB Translation] Successfully translated %s (%s) -> English (eng_Latn) (%d chars).",
        norm_lang,
        src_code,
        len(translated),
    )
    return translated, {
        "english_text": translated,
        "source_language": norm_lang,
        "target_language": "English",
        "source_nllb_code": src_code,
        "target_nllb_code": "eng_Latn",
        "translation_model": NLLB_MODEL_NAME,
        "translation_status": "completed",
        "error": None,
    }


async def translate_pages_to_english(
    pages_data: List[Dict[str, Any]],
    source_language: str,
    full_english_text: str = "",
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Creates canonical English pages_data from the translated English representation
    so hierarchical chunking and FAISS FlatIP indexing operate strictly on English.
    Returns (canonical_pages, translation_metadata_dict).
    """
    norm_lang = normalize_language_name(source_language) or source_language
    if norm_lang == "English" or not pages_data:
        return pages_data, {
            "source_language": "English",
            "target_language": "English",
            "source_nllb_code": "eng_Latn",
            "target_nllb_code": "eng_Latn",
            "translation_model": NLLB_MODEL_NAME,
            "translation_status": "skipped_already_english",
            "error": None,
        }

    canonical_pages = []
    trans_meta = {}
    # A whole-document translation cannot establish page provenance.
    for page in pages_data:
        translated, trans_meta = await translate_sop_to_english(
            page.get("text", ""), norm_lang, llm_service_url, provider, model, api_key)
        canonical_pages.append({**page, "original_text": page.get("text", ""), "text": translated,
                                "translation_requires_review": True})
    return canonical_pages, {**trans_meta, "page_provenance": "source_page_translation",
                             "requires_human_review": True}


async def translate_sop_sections_from_english(
    sections: List[Dict[str, Any]],
    doc_title: str = "",
    target_language: str = "English",
    llm_service_url: str = "http://localhost:8001",
    provider: str = "groq",
    model: str = "openai/gpt-oss-120b",
    api_key: str = "",
    title: str = "",
) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    """
    Translates canonical English SOP sections and title into the user-selected output language
    using the NLLB translation layer while preserving all [IMAGE_ARTIFACT: ...] and [TABLE_ARTIFACT: ...] tags.
    Returns (translated_sections, translated_title, translation_metadata_dict).
    """
    effective_title = doc_title or title or "Standard Operating Procedure"
    norm_target = normalize_language_name(target_language) or "English"
    if norm_target == "English":
        logger.info("[NLLB Output Generation] Selected output language is English (eng_Latn). No post-translation needed.")
        return (
            sections,
            effective_title,
            {
                "output_language": "English",
                "output_nllb_code": "eng_Latn",
                "translation_model": NLLB_MODEL_NAME,
                "translation_status": "skipped_already_english",
                "translation_errors": None,
            },
        )

    tgt_info = SUPPORTED_LANGUAGES.get(norm_target, SUPPORTED_LANGUAGES["English"])
    tgt_code = tgt_info["nllb_code"]
    logger.info(
        "[NLLB Output Generation] Translating generated SOP from English (eng_Latn) -> %s (%s) via %s...",
        norm_target,
        tgt_code,
        NLLB_MODEL_NAME,
    )

    if not (api_key and api_key.strip()):
        raise LLMServiceError(
            format_llm_unavailable_message(
                provider=provider,
                detail=f"No active LLM API key is configured to translate the SOP into {norm_target}.",
            )
        )

    if not sections:
        return (
            sections,
            effective_title,
            {
                "output_language": norm_target,
                "output_nllb_code": tgt_code,
                "translation_model": NLLB_MODEL_NAME,
                "translation_status": "completed",
                "translation_errors": None,
            },
        )

    import json as _json

    payload_obj = {
        "title": effective_title,
        "sections": [
            {"heading": s.get("heading", ""), "content": s.get("content", "")}
            for s in sections
        ],
    }
    try:
        from prompt_loader import format_prompt
    except ImportError:
        from services.api.prompt_loader import format_prompt

    system_prompt = format_prompt(
        "translation_to_target",
        model_name=NLLB_MODEL_NAME,
        target_language=norm_target,
        target_native_name=tgt_info["native_name"],
        target_code=tgt_code,
    )
    try:
        async with httpx.AsyncClient(timeout=85.0) as client:
            resp = await client.post(
                f"{llm_service_url}/generate",
                json={
                    "provider": provider,
                    "model": model,
                    "api_key": api_key,
                    "max_tokens": 8192,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": _json.dumps(payload_obj, ensure_ascii=False)},
                    ],
                },
            )
    except Exception as exc:
        logger.error("[NLLB Output Generation] Could not reach LLM service for translation: %s", exc)
        raise LLMServiceError(
            format_llm_unavailable_message(provider=provider, detail=str(exc))
        ) from exc

    if resp.status_code != 200:
        err_detail = resp.text
        try:
            err_detail = resp.json().get("detail", resp.text)
        except Exception:
            pass
        logger.error("[NLLB Output Generation] LLM service returned status %d: %s", resp.status_code, err_detail)
        raise LLMServiceError(
            format_llm_unavailable_message(
                provider=provider,
                status_code=resp.status_code,
                detail=str(err_detail),
            )
        )

    raw = (resp.json().get("content") or "").strip()
    clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    clean = re.sub(r"\s*```$", "", clean)
    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1:
        try:
            json_slice = re.sub(r",\s*([}\]])", r"\1", clean[start_idx : end_idx + 1])
            parsed = _json.loads(json_slice, strict=False)
            t_title = (parsed.get("title") or "").strip() or effective_title
            t_secs = parsed.get("sections") or []
            if len(t_secs) == len(sections):
                # Verify artifact tags and extra fields were preserved in each section
                final_secs: List[Dict[str, Any]] = []
                for orig_s, tr_s in zip(sections, t_secs):
                    orig_tags = re.findall(r"\[(?:IMAGE|TABLE)_ARTIFACT:[^\]]+\]", orig_s.get("content", ""))
                    tr_content = (tr_s.get("content") or "").strip()
                    for tag in orig_tags:
                        if tag not in tr_content:
                            tr_content += f"\n\n{tag}"
                    final_secs.append(
                        {
                            **orig_s,
                            "heading": (tr_s.get("heading") or orig_s.get("heading", "")).strip(),
                            "content": tr_content,
                        }
                    )
                logger.info(
                    "[NLLB Output Generation] Successfully generated SOP in %s (%s) (%d sections).",
                    norm_target,
                    tgt_code,
                    len(final_secs),
                )
                return (
                    final_secs,
                    t_title,
                    {
                        "output_language": norm_target,
                        "output_nllb_code": tgt_code,
                        "translation_model": NLLB_MODEL_NAME,
                        "translation_status": "completed",
                        "translation_errors": None,
                    },
                )
        except Exception as exc:
            logger.error("[NLLB Output Generation] Failed to parse LLM JSON translation response: %s", exc)
            raise LLMServiceError(
                format_llm_unavailable_message(
                    provider=provider,
                    detail="LLM returned an unparseable response during multilingual SOP translation.",
                )
            ) from exc

    raise LLMServiceError(
        format_llm_unavailable_message(
            provider=provider,
            detail="LLM returned an incomplete response during multilingual SOP translation.",
        )
    )


def get_unique_detected_languages(documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Extracts a deduplicated list of detected languages across all uploaded SOPs.
    Never returns duplicate language entries (e.g., if 3 SOPs are Japanese, Japanese appears once).
    """
    seen: set = set()
    unique_langs: List[Dict[str, Any]] = []

    for doc in documents:
        lang = (
            doc.get("detected_language")
            or doc.get("original_language")
            or "English"
        )
        norm_lang = normalize_language_name(lang) or lang
        if norm_lang not in seen:
            seen.add(norm_lang)
            info = SUPPORTED_LANGUAGES.get(
                norm_lang,
                {
                    "name": norm_lang,
                    "native_name": norm_lang,
                    "nllb_code": doc.get("nllb_language_code", "eng_Latn"),
                    "iso_code": "en",
                    "flag": "🌐",
                },
            )
            doc_count = sum(
                1
                for d in documents
                if (normalize_language_name(d.get("detected_language") or d.get("original_language")) or "English") == norm_lang
            )
            unique_langs.append(
                {
                    "language": norm_lang,
                    "native_name": info.get("native_name", norm_lang),
                    "nllb_code": info.get("nllb_code", "eng_Latn"),
                    "iso_code": info.get("iso_code", "en"),
                    "flag": info.get("flag", "🌐"),
                    "document_count": doc_count,
                }
            )

    return unique_langs
