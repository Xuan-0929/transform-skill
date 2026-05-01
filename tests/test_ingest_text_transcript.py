from __future__ import annotations

from pathlib import Path

from persona_distill.ingest import ingest_file


def test_text_ingest_binds_timestamp_header_to_following_message(tmp_path: Path) -> None:
    corpus = tmp_path / "chat.txt"
    corpus.write_text(
        "\n".join(
            [
                "极客小猪: 2025-12-12 01:05:13",
                "你跟张鑫说了什么",
                "",
                "橘柚: 2025-12-12 01:05:47",
                "？",
                "",
                "橘柚: 2025-12-12 01:06:09",
                "我12点15以后没发过东西啊",
            ]
        ),
        encoding="utf-8",
    )

    items = ingest_file(corpus, "auto")

    assert [(item.speaker, item.content) for item in items] == [
        ("极客小猪", "你跟张鑫说了什么"),
        ("橘柚", "？"),
        ("橘柚", "我12点15以后没发过东西啊"),
    ]
    assert all(item.timestamp is not None for item in items)
    assert "unknown" not in {item.speaker for item in items}


def test_text_ingest_keeps_single_line_speaker_messages(tmp_path: Path) -> None:
    corpus = tmp_path / "chat.txt"
    corpus.write_text("A: 直接一句话\nB: 收到", encoding="utf-8")

    items = ingest_file(corpus, "auto")

    assert [(item.speaker, item.content) for item in items] == [
        ("A", "直接一句话"),
        ("B", "收到"),
    ]
    assert all(item.timestamp is None for item in items)
