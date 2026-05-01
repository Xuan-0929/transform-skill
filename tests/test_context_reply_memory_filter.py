from __future__ import annotations

from datetime import datetime, timezone

from persona_distill.extract import _build_context_reply_memory
from persona_distill.ingest import ingest_file
from persona_distill.models import CorpusItem


def _item(idx: int, speaker: str, content: str) -> CorpusItem:
    return CorpusItem(
        id=f"i{idx}",
        source="t.json",
        speaker=speaker,
        timestamp=datetime(2025, 1, 1, 0, 0, idx + 1, tzinfo=timezone.utc),
        content=content,
        content_hash=f"h{idx}",
        quality_score=0.8,
    )


def test_context_reply_memory_skips_low_signal_context() -> None:
    items = [
        _item(1, "B", "这个"),
        _item(2, "A", "不是"),
        _item(3, "B", "她之前跟你说了没有"),
        _item(4, "A", "不是"),
    ]
    pairs = _build_context_reply_memory(items, target_speaker="A", limit=10)
    assert {"context": "这个", "reply": "不是"} not in pairs
    assert {"context": "她之前跟你说了没有", "reply": "不是"} in pairs


def test_context_reply_memory_skips_non_persona_meme_pairs() -> None:
    items = [
        _item(1, "B", "疯狂星期四v我50"),
        _item(2, "A", "哈哈"),
        _item(3, "B", "你这个选择其实风险挺大"),
        _item(4, "A", "先别急，我再看一眼"),
    ]
    pairs = _build_context_reply_memory(items, target_speaker="A", limit=10)
    assert {"context": "疯狂星期四v我50", "reply": "哈哈"} not in pairs
    assert {"context": "你这个选择其实风险挺大", "reply": "先别急，我再看一眼"} in pairs


def test_context_reply_memory_skips_continuation_reply_streak() -> None:
    items = [
        _item(1, "B", "荞麦地太搞笑了"),
        _item(2, "A", "笑死我了"),
        _item(3, "A", "是娃我吃"),
        _item(4, "A", "感觉可以"),
    ]
    pairs = _build_context_reply_memory(items, target_speaker="A", limit=10)
    assert {"context": "荞麦地太搞笑了", "reply": "笑死我了"} in pairs
    assert {"context": "荞麦地太搞笑了", "reply": "是娃我吃"} not in pairs
    assert {"context": "荞麦地太搞笑了", "reply": "感觉可以"} not in pairs


def test_ingest_file_accepts_directory_of_json_files(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(
        '[{"speaker":"A","content":"第一句","timestamp":"2025-01-01T00:00:01Z"}]',
        encoding="utf-8",
    )
    second.write_text(
        '[{"speaker":"B","content":"第二句","timestamp":"2025-01-01T00:00:02Z"}]',
        encoding="utf-8",
    )

    items = ingest_file(tmp_path, "auto")

    assert [item.content for item in items] == ["第一句", "第二句"]
    assert {item.source for item in items} == {"a.json", "b.json"}
    assert all(str(tmp_path) in item.metadata["source_path"] for item in items)
