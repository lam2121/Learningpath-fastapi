"""Automated Japanese Furigana Morphological Cross-Checking Engine.

Validates:
1. Bracket syntax: `[漢字|かんじ]` formatting, unclosed brackets, and Hiragana-only readings.
2. Morphological cross-checking: Compares generative model readings against
   SudachiPy and pykakasi ground-truth dictionaries to flag hallucinations before
   human review.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Cache tokenizer and kakasi instances for speed
_sudachi_tokenizer = None
_kakasi_instance = None


def _get_sudachi_tokenizer():
    global _sudachi_tokenizer
    if _sudachi_tokenizer is None:
        try:
            from sudachipy import dictionary
            _sudachi_tokenizer = dictionary.Dictionary().create()
        except Exception as exc:
            logger.warning("Could not initialize SudachiPy dictionary: %s", exc)
    return _sudachi_tokenizer


def _get_kakasi():
    global _kakasi_instance
    if _kakasi_instance is None:
        try:
            import pykakasi
            _kakasi_instance = pykakasi.kakasi()
        except Exception as exc:
            logger.warning("Could not initialize pykakasi: %s", exc)
    return _kakasi_instance


def is_hiragana(text: str) -> bool:
    """Return True if text contains only Hiragana, prolonged sound marks, or middle dots."""
    if not text:
        return False
    return all(
        "\u3040" <= ch <= "\u309f" or ch in ("ー", "・", " ")
        for ch in text
    )


def is_japanese_script(text: str) -> bool:
    """Return True if string contains Japanese characters (Hiragana, Katakana, or Kanji)."""
    return any(
        ("\u3040" <= ch <= "\u309f")  # Hiragana
        or ("\u30a0" <= ch <= "\u30ff")  # Katakana
        or ("\u4e00" <= ch <= "\u9fff")  # CJK Unified Ideographs (Kanji)
        for ch in text
    )


def get_morphological_reading(kanji: str) -> str | None:
    """Get the standard Hiragana reading of a kanji compound from SudachiPy or pykakasi."""
    tok = _get_sudachi_tokenizer()
    if tok is not None:
        try:
            import jaconv
            from sudachipy import tokenizer
            tokens = tok.tokenize(kanji, tokenizer.Tokenizer.SplitMode.C)
            katakana = "".join(t.reading_form() for t in tokens)
            if katakana:
                return jaconv.kata2hira(katakana)
        except Exception as e:
            logger.debug("SudachiPy tokenization error for '%s': %s", kanji, e)

    kakasi = _get_kakasi()
    if kakasi is not None:
        try:
            res = kakasi.convert(kanji)
            reading = "".join(item.get("hira", "") for item in res)
            if reading:
                return reading
        except Exception as e:
            logger.debug("pykakasi conversion error for '%s': %s", kanji, e)

    return None


def repair_furigana_text(text: str) -> str:
    """Auto-repair common furigana anomalies using morphological analysis:
    1. Clean markdown italics asterisks around/inside furigana (e.g. *Kanji|reading]* -> [Kanji|reading]).
    2. Strip stray leading/trailing brackets (e.g. ][Kanji|reading] -> [Kanji|reading]).
    3. If reading is not hiragana (e.g. [拡大|拡大], [図|図], or [発生|Hassei]): look up dictionary reading and replace with [kanji|dict_reading].
    4. If kanji part has no kanji at all (e.g. [テスト|テスト] or [これ|これ]): strip brackets to 'テスト' or 'これ'.
    """
    if not text or not isinstance(text, str):
        return text

    # Strip stray leading/trailing unclosed brackets
    text = re.sub(r"^\]+", "", text)
    text = re.sub(r"\[+$", "", text)

    # Normalize asterisks combined with furigana brackets from markdown italics:
    # 1. *Kanji|reading]* -> [Kanji|reading]
    text = re.sub(r"\*([^|*\[\]\n]+)\|([^|*\[\]\n]+)\]\*?", r"[\1|\2]", text)
    # 2. *Kanji|reading* -> [Kanji|reading]
    text = re.sub(r"\*([^|*\[\]\n]+)\|([^|*\[\]\n]+)\*", r"[\1|\2]", text)
    # 3. [*Kanji|reading*] -> [Kanji|reading]
    text = re.sub(r"\[\*([^|*\[\]\n]+)\|([^|*\[\]\n]+)\*\]", r"[\1|\2]", text)
    # 4. [*Kanji|reading] -> [Kanji|reading]
    text = re.sub(r"\[\*([^|*\[\]\n]+)\|", r"[\1|", text)
    # 5. [Kanji|reading*] -> [Kanji|reading]
    text = re.sub(r"\|([^|*\[\]\n]+)\*\]", r"|\1]", text)

    # Deduplicate repeated okurigana, e.g. [先送り|さきおく]り -> [先送|さきおく]り
    text = re.sub(r"\[([^|\]]+?)([\u3040-\u309f])\|([^|\]]+?)\]\2", r"[\1|\3]\2", text)

    bracket_pattern = re.compile(r"\[([^|\]\n]+)\|([^|\]\n]+)\]")

    def _sub_func(match: re.Match) -> str:
        kanji = match.group(1).strip()
        reading = match.group(2).strip()

        # Clean any remaining asterisks
        kanji = kanji.replace("*", "").strip()
        reading = reading.replace("*", "").strip()

        # If kanji has no kanji characters at all (e.g. [テスト|テスト] or [これ|これ])
        has_kanji = any("\u4e00" <= ch <= "\u9fff" for ch in kanji)
        if not has_kanji:
            return kanji

        # For pure multi-kanji compounds (len >= 2, all Kanji): cross-check against morphological dictionary
        is_pure_kanji_compound = len(kanji) >= 2 and all("\u4e00" <= ch <= "\u9fff" for ch in kanji)
        if is_pure_kanji_compound:
            dict_reading = get_morphological_reading(kanji)
            if dict_reading and is_hiragana(dict_reading):
                if dict_reading != reading:
                    logger.info("Auto-repaired compound furigana for '%s': '%s' -> '%s'", kanji, reading, dict_reading)
                return f"[{kanji}|{dict_reading}]"

        # If reading is already valid hiragana, keep it
        if is_hiragana(reading):
            return f"[{kanji}|{reading}]"

        # Reading is not hiragana (e.g. model repeated the kanji or wrote kanji/katakana/romaji)
        dict_reading = get_morphological_reading(kanji)
        if dict_reading and is_hiragana(dict_reading):
            logger.info("Auto-repaired furigana for '%s': '%s' -> '%s'", kanji, reading, dict_reading)
            return f"[{kanji}|{dict_reading}]"

        return match.group(0)

    return bracket_pattern.sub(_sub_func, text)


def repair_theory_furigana(content: Any) -> Any:
    """Walk through theory content dictionary and auto-repair furigana anomalies in Japanese texts."""
    if isinstance(content, dict):
        for k, v in content.items():
            if k in ("ja", "japanese_text") and isinstance(v, str):
                content[k] = repair_furigana_text(v)
            elif k == "reading" and isinstance(v, str):
                v_clean = v.strip()
                if not is_hiragana(v_clean):
                    term_val = content.get("term")
                    if isinstance(term_val, dict) and "ja" in term_val:
                        ja_str = str(term_val.get("ja") or "")
                        clean_term = re.sub(r"\[([^|\]]+)\|[^\]]+\]", r"\1", ja_str).strip()
                        dict_rd = get_morphological_reading(clean_term)
                        if dict_rd and is_hiragana(dict_rd):
                            content[k] = dict_rd
            elif isinstance(v, (dict, list)):
                repair_theory_furigana(v)
    elif isinstance(content, list):
        for item in content:
            repair_theory_furigana(item)
    return content


def validate_furigana_text(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Validate furigana syntax and verify reading accuracy for a single Japanese text string.

    Returns:
        (syntax_errors, discrepancies)
    """
    errors: list[str] = []
    discrepancies: list[dict[str, str]] = []

    if not text or not isinstance(text, str):
        return errors, discrepancies

    # Check for unmatched brackets
    open_count = text.count("[")
    close_count = text.count("]")
    if open_count != close_count:
        errors.append(
            f"Mismatched furigana brackets: found {open_count} '[' and {close_count} ']' in: '{text[:80]}...'"
        )

    # Extract all [kanji|reading] bracket pairs
    bracket_pattern = re.compile(r"\[([^|\]\n]+)\|([^|\]\n]+)\]")
    matches = bracket_pattern.findall(text)

    for kanji, reading in matches:
        kanji = kanji.strip()
        reading = reading.strip()

        if not kanji:
            errors.append(f"Empty kanji token in furigana bracket '[|{reading}]'")
            continue

        if not reading:
            errors.append(f"Empty reading token in furigana bracket '[{kanji}|]'")
            continue

        # Readings MUST be valid Hiragana
        if not is_hiragana(reading):
            errors.append(
                f"Invalid furigana reading '{reading}' for '{kanji}': reading must be written in Hiragana"
            )
            continue

        # Morphological dictionary cross-check
        dict_reading = get_morphological_reading(kanji)
        if dict_reading and dict_reading != reading:
            # Allow minor phonetic shifts (e.g., small tsu vs full tsu, geminate consonants)
            # or record as discrepancy
            discrepancies.append(
                {
                    "kanji": kanji,
                    "model_reading": reading,
                    "dict_reading": dict_reading,
                    "context": text[:120],
                }
            )

    return errors, discrepancies


def validate_theory_furigana(content: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """Walk through a theory content dictionary and validate all Japanese text fields."""
    all_errors: list[str] = []
    all_discrepancies: list[dict[str, str]] = []

    def _walk(obj: Any, path: str = ""):
        if isinstance(obj, dict):
            # If the dict is a trilingual text object with "ja" key
            if "ja" in obj and isinstance(obj["ja"], str):
                ja_text = obj["ja"]
                errs, disc = validate_furigana_text(ja_text)
                for e in errs:
                    all_errors.append(f"{path}.ja: {e}")
                for d in disc:
                    d["path"] = f"{path}.ja"
                    all_discrepancies.append(d)

            # Check for japanese_text key (legacy or alias)
            if "japanese_text" in obj and isinstance(obj["japanese_text"], str):
                ja_text = obj["japanese_text"]
                errs, disc = validate_furigana_text(ja_text)
                for e in errs:
                    all_errors.append(f"{path}.japanese_text: {e}")
                for d in disc:
                    d["path"] = f"{path}.japanese_text"
                    all_discrepancies.append(d)

            # Check vocab item reading field
            if "reading" in obj and isinstance(obj["reading"], str):
                reading = obj["reading"].strip()
                if not is_hiragana(reading):
                    all_errors.append(f"{path}.reading: '{reading}' must be pure Hiragana")

            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else k)

        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(content)
    return all_errors, all_discrepancies
