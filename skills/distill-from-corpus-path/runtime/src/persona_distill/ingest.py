from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import CorpusItem
from .utils import stable_hash, tokenize

SPEAKER_LINE_RE = re.compile(
    r"^(?:\[(?P<ts>[^\]]+)\]\s*)?(?P<speaker>[^:：\n]{1,40})[:：]\s*(?P<content>.+)$"
)
MEDIA_PLACEHOLDER_RE = re.compile(r"^\[(图片|视频|文件|语音|卡片消息|表情).+\]$")
REPLY_PREFIX_RE = re.compile(r"^\[回复 [^\]]+\]\s*")
SUPPORTED_INPUT_SUFFIXES = {".json", ".csv", ".txt", ".md"}
INLINE_TIMESTAMP_RE = re.compile(
    r"^(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?$"
)


def detect_format(path: Path, declared: str) -> str:
    if declared != "auto":
        return declared
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return "text"
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        return "csv"
    return "text"


def iter_input_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Input path not found: {path}")
    files = [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file()
        and not candidate.name.startswith(".")
        and candidate.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
    ]
    return sorted(files)


def _with_source_metadata(records: list[dict[str, Any]], source: Path) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        row = dict(record)
        row.setdefault("_source_path", str(source))
        row.setdefault("_source_order", idx)
        enriched.append(row)
    return enriched


def parse_timestamp(raw: str | int | float | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = float(raw)
        # QQ exports are usually milliseconds.
        if ts > 10_000_000_000:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    text = str(raw).strip()
    if not text:
        return None

    candidates = [text, text.replace("Z", "+00:00")]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def score_quality(content: str, speaker: str) -> float:
    tokens = tokenize(content)
    char_len = len(content)
    length_score = min(char_len / 36, 1.0)
    token_score = min(len(tokens) / 16, 1.0) * 0.35
    punctuation_bonus = 0.08 if any(p in content for p in ".!?。！？") else 0.0
    question_bonus = 0.08 if "?" in content or "？" in content else 0.0
    speaker_bonus = 0.06 if speaker and speaker != "unknown" else 0.0
    short_penalty = -0.22 if char_len < 2 else (-0.1 if char_len < 5 else 0.0)
    score = 0.1 + length_score * 0.45 + token_score + punctuation_bonus + question_bonus + speaker_bonus + short_penalty
    return max(0.0, min(1.0, score))


def _clean_content_text(text: str) -> str:
    cleaned = text.strip()
    cleaned = REPLY_PREFIX_RE.sub("", cleaned)
    cleaned = re.sub(r"\n+", " ", cleaned).strip()
    cleaned = re.sub(r"^@[^\s]+\\s*", "", cleaned).strip()
    cleaned = cleaned.lstrip("]】 ").strip()
    cleaned = cleaned.strip()
    return cleaned


def _looks_like_inline_timestamp(text: str) -> bool:
    cleaned = text.strip()
    return bool(INLINE_TIMESTAMP_RE.match(cleaned)) or parse_timestamp(cleaned) is not None


def _records_from_text(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    pending_speaker: str | None = None
    pending_timestamp: str | None = None
    pending_lines: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_speaker, pending_timestamp, pending_lines
        if pending_speaker and pending_lines:
            records.append(
                {
                    "speaker": pending_speaker,
                    "content": _clean_content_text("\n".join(pending_lines)),
                    "timestamp": pending_timestamp,
                    "recalled": False,
                    "system": False,
                }
            )
        pending_speaker = None
        pending_timestamp = None
        pending_lines = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = SPEAKER_LINE_RE.match(stripped)
        if match:
            speaker = match.group("speaker").strip()
            content = _clean_content_text(match.group("content") or "")
            timestamp = match.group("ts")
            # Some chat exports use:
            #   Speaker: 2025-12-12 01:05:13
            #   message body on the next line
            # Treat the first line as metadata, not as the speaker's content.
            if not timestamp and _looks_like_inline_timestamp(content):
                flush_pending()
                pending_speaker = speaker
                pending_timestamp = content
                pending_lines = []
                continue

            flush_pending()
            records.append(
                {
                    "speaker": speaker,
                    "content": content,
                    "timestamp": timestamp,
                    "recalled": False,
                    "system": False,
                }
            )
        else:
            if pending_speaker:
                pending_lines.append(stripped)
                continue
            records.append(
                {
                    "speaker": "unknown",
                    "content": _clean_content_text(stripped),
                    "timestamp": None,
                    "recalled": False,
                    "system": False,
                }
            )
    flush_pending()
    return records


def _sender_name(item: dict[str, Any]) -> str:
    sender = item.get("sender")
    if isinstance(sender, dict):
        return str(sender.get("name") or sender.get("uid") or "unknown")
    if isinstance(sender, str) and sender.strip():
        return sender.strip()
    return str(item.get("speaker") or item.get("role") or item.get("author") or "unknown")


def _extract_content_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return _clean_content_text(content)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return _clean_content_text(text)
        elements = content.get("elements")
        if isinstance(elements, list):
            pieces: list[str] = []
            for element in elements:
                if not isinstance(element, dict):
                    continue
                et = element.get("type")
                data = element.get("data") or {}
                if et == "text" and isinstance(data, dict) and data.get("text"):
                    pieces.append(str(data.get("text")))
            return _clean_content_text("\n".join(pieces))
    text = item.get("text") or item.get("message") or item.get("value") or ""
    return _clean_content_text(str(text))


def _flatten_json_messages(obj: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if isinstance(obj, list):
        iterable = obj
    elif isinstance(obj, dict):
        iterable = obj.get("messages") or obj.get("conversation") or obj.get("data") or []
        if not iterable and {"content", "text"} & set(obj.keys()):
            iterable = [obj]
    else:
        iterable = []

    for item in iterable:
        if not isinstance(item, dict):
            continue

        content_text = _extract_content_text(item)
        if not content_text:
            continue

        speaker = _sender_name(item)
        message_id = item.get("id") or item.get("msgId") or item.get("seq")
        tags: list[str] = []
        for key in ("type", "msgType"):
            val = item.get(key)
            if val:
                tags.append(str(val))
        if item.get("recalled"):
            tags.append("recalled")
        if item.get("system"):
            tags.append("system")

        entries.append(
            {
                "speaker": speaker,
                "content": content_text,
                "timestamp": item.get("time") or item.get("timestamp") or item.get("created_at"),
                "tags": tags,
                "recalled": bool(item.get("recalled", False)),
                "system": bool(item.get("system", False)),
                "source_message_id": str(message_id) if message_id is not None else None,
            }
        )
    return entries


def _records_from_json(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _flatten_json_messages(data)


def _pick_column(row: dict[str, str], names: list[str], default: str = "") -> str:
    for name in names:
        if name in row and str(row[name]).strip():
            return str(row[name]).strip()
    return default


def _records_from_csv(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            content = _clean_content_text(_pick_column(row, ["content", "text", "message", "utterance", "dialogue"]))
            if not content:
                continue
            speaker = _pick_column(row, ["speaker", "role", "author", "name"], "unknown")
            timestamp = _pick_column(row, ["timestamp", "time", "created_at", "date"], "")
            tags_raw = _pick_column(row, ["tags", "label", "labels"], "")
            tags = [t.strip() for t in re.split(r"[,;|]", tags_raw) if t.strip()]
            records.append(
                {
                    "speaker": speaker,
                    "content": content,
                    "timestamp": timestamp,
                    "tags": tags,
                    "recalled": False,
                    "system": False,
                    "source_message_id": _pick_column(row, ["id", "message_id", "msg_id"], "") or None,
                }
            )
    return records


def parse_input(path: Path, fmt: str = "auto") -> list[dict[str, Any]]:
    if path.is_dir():
        records: list[dict[str, Any]] = []
        for source in iter_input_files(path):
            records.extend(parse_input(source, fmt))
        return records

    resolved_format = detect_format(path, fmt)
    if resolved_format == "text":
        return _with_source_metadata(_records_from_text(path), path)
    if resolved_format == "json":
        return _with_source_metadata(_records_from_json(path), path)
    if resolved_format == "csv":
        return _with_source_metadata(_records_from_csv(path), path)
    raise ValueError(f"Unsupported format: {resolved_format}")


def normalize_records(
    source: Path,
    records: list[dict[str, Any]],
    speaker_filter: str | None = None,
    drop_media_placeholders: bool = True,
) -> list[CorpusItem]:
    items: list[CorpusItem] = []
    seen_keys: set[tuple[str, str, str]] = set()
    source_label = source.name
    target = speaker_filter.strip() if speaker_filter else None

    for idx, record in enumerate(records):
        if record.get("recalled") or record.get("system"):
            continue
        speaker = str(record.get("speaker") or "unknown").strip() or "unknown"
        if target and speaker != target:
            continue

        content = _clean_content_text(str(record.get("content", "")))
        if not content:
            continue
        if drop_media_placeholders and MEDIA_PLACEHOLDER_RE.match(content):
            continue

        raw_mid = record.get("source_message_id")
        if raw_mid is not None and str(raw_mid).strip():
            dedup_key = (speaker, f"mid:{str(raw_mid).strip()}", content)
        else:
            ts = parse_timestamp(record.get("timestamp") if isinstance(record, dict) else None)
            ts_key = ts.isoformat() if ts else f"idx:{idx}"
            dedup_key = (speaker, ts_key, content)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        content_hash = stable_hash(content)
        source_message_id = raw_mid
        item = CorpusItem(
            id=stable_hash(f"{source_label}:{idx}:{speaker}:{source_message_id or content}", prefix="item"),
            source=source_label,
            speaker=speaker,
            timestamp=parse_timestamp(record.get("timestamp") if isinstance(record, dict) else None),
            content=content,
            content_hash=content_hash,
            source_message_id=str(source_message_id) if source_message_id else None,
            tags=[str(t) for t in record.get("tags", []) if str(t).strip()],
            quality_score=score_quality(content, speaker),
            metadata={"source_path": str(source)},
        )
        items.append(item)
    return items


def ingest_file(
    path: Path,
    fmt: str = "auto",
    speaker_filter: str | None = None,
    drop_media_placeholders: bool = True,
) -> list[CorpusItem]:
    if path.is_dir():
        items: list[CorpusItem] = []
        for source in iter_input_files(path):
            items.extend(
                ingest_file(
                    source,
                    fmt=fmt,
                    speaker_filter=speaker_filter,
                    drop_media_placeholders=drop_media_placeholders,
                )
            )
        return items

    records = parse_input(path, fmt)
    return normalize_records(
        path,
        records,
        speaker_filter=speaker_filter,
        drop_media_placeholders=drop_media_placeholders,
    )
