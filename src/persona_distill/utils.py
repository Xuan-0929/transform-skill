from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "persona"


def stable_hash(text: str, prefix: str = "") -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if prefix:
        return f"{prefix}_{digest[:12]}"
    return digest


def safe_excerpt(text: str, max_len: int = 240) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_len:
        return clean
    return clean[: max_len - 3] + "..."


def tokenize(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z\u4e00-\u9fff0-9_]+", text.lower()) if len(w) > 1]


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    chars = [c for c in text.lower() if not c.isspace()]
    if len(chars) < n:
        return {"".join(chars)} if chars else set()
    return {"".join(chars[i : i + n]) for i in range(len(chars) - n + 1)}


def jaccard_similarity(a: str, b: str) -> float:
    ta = set(tokenize(a))
    tb = set(tokenize(b))
    token_sim = 0.0
    if ta and tb:
        token_sim = len(ta & tb) / len(ta | tb)
    elif not ta and not tb:
        token_sim = 1.0

    ca = _char_ngrams(a, n=2)
    cb = _char_ngrams(b, n=2)
    char_sim = 0.0
    if ca and cb:
        char_sim = len(ca & cb) / len(ca | cb)
    elif not ca and not cb:
        char_sim = 1.0

    return max(token_sim, char_sim * 0.9)


def has_negation(text: str) -> bool:
    markers = ["never", "not", "don't", "avoid", "cannot", "不", "别", "不要", "不能"]
    lower = text.lower()
    return any(m in lower for m in markers)


def canonical_skill_name(text: str) -> str:
    base = slugify(text)
    if base == "persona" or len(base) < 3:
        base = f"persona-{stable_hash(text)[:8]}"
    base = re.sub(r"-{2,}", "-", base).strip("-")
    return base[:64]
