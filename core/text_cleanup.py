from __future__ import annotations

import re

INLINE_WHITESPACE_RE = re.compile(r"\s+")
SPACE_BEFORE_PUNCTUATION_RE = re.compile(r"\s+([,.;:!?])")


def clean_command_text(text: str) -> str:
    cleaned = _apply_ftfy(text)
    cleaned = cleaned.replace("\u00a0", " ")
    cleaned = SPACE_BEFORE_PUNCTUATION_RE.sub(r"\1", cleaned)
    cleaned = INLINE_WHITESPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def _apply_ftfy(text: str) -> str:
    try:
        from ftfy import fix_text
    except ImportError:
        return text
    return fix_text(text)
