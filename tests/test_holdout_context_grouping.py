from __future__ import annotations

import json
from pathlib import Path

from persona_distill.holdout import _build_context_reply_groups, _build_recent_context_windows


def test_holdout_groups_skip_consecutive_same_speaker_replies(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": "荞麦地太搞笑了", "timestamp": "2025-12-17 21:14:22"},
        {"speaker": "A", "content": "笑死我了", "timestamp": "2025-12-17 21:14:29"},
        {"speaker": "A", "content": "是娃我吃", "timestamp": "2025-12-18 12:18:59"},
        {"speaker": "A", "content": "感觉可以", "timestamp": "2025-12-18 12:19:02"},
        {"speaker": "B", "content": "她日服270级", "timestamp": "2025-12-18 12:20:00"},
        {"speaker": "A", "content": "还是老资历", "timestamp": "2025-12-18 12:20:04"},
    ]
    path = tmp_path / "holdout.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    groups = _build_context_reply_groups(path, target_speaker="A")

    assert groups["荞麦地太搞笑了"] == ["笑死我了"]
    assert "是娃我吃" not in groups["荞麦地太搞笑了"]
    assert groups["她日服270级"] == ["还是老资历"]


def test_holdout_groups_skip_far_time_gap(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": "明天你来吗", "timestamp": "2025-12-17 09:00:00"},
        {"speaker": "A", "content": "行", "timestamp": "2025-12-17 13:30:00"},
    ]
    path = tmp_path / "holdout_gap.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    groups = _build_context_reply_groups(path, target_speaker="A")

    assert groups == {}


def test_recent_context_windows_include_up_to_four_turns(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": "前置1", "timestamp": "2025-12-17 09:00:00"},
        {"speaker": "A", "content": "前置2", "timestamp": "2025-12-17 09:00:02"},
        {"speaker": "B", "content": "前置3", "timestamp": "2025-12-17 09:00:04"},
        {"speaker": "B", "content": "当前问句", "timestamp": "2025-12-17 09:00:06"},
        {"speaker": "A", "content": "当前回复", "timestamp": "2025-12-17 09:00:08"},
    ]
    path = tmp_path / "holdout_window.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    windows = _build_recent_context_windows(path, target_speaker="A", history_turns=4)
    lines = windows["当前问句"]

    assert len(lines) == 4
    assert lines[-1].endswith("当前问句")


def test_recent_context_windows_can_include_larger_window(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": f"前置{i}", "timestamp": f"2025-12-17 09:00:{i:02d}"}
        for i in range(1, 9)
    ]
    payload.append({"speaker": "A", "content": "当前回复", "timestamp": "2025-12-17 09:00:10"})
    path = tmp_path / "holdout_large_window.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    windows = _build_recent_context_windows(path, target_speaker="A", history_turns=8)

    assert len(windows["前置8"]) == 8
    assert windows["前置8"][0].endswith("前置1")


def test_holdout_directory_does_not_cross_file_boundary(tmp_path: Path) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(
        json.dumps(
            [
                {"speaker": "B", "content": "上一份最后一句", "timestamp": "2025-12-17 09:00:00"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            [
                {"speaker": "A", "content": "第二份第一句", "timestamp": "2025-12-17 09:00:01"},
                {"speaker": "B", "content": "第二份上下文", "timestamp": "2025-12-17 09:00:02"},
                {"speaker": "A", "content": "第二份回复", "timestamp": "2025-12-17 09:00:03"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    groups = _build_context_reply_groups(tmp_path, target_speaker="A")
    windows = _build_recent_context_windows(tmp_path, target_speaker="A", history_turns=4)

    assert "上一份最后一句" not in groups
    assert groups["第二份上下文"] == ["第二份回复"]
    assert "B: 上一份最后一句" not in windows["第二份上下文"]
    assert windows["第二份上下文"][-1] == "B: 第二份上下文"


def test_holdout_uses_best_recent_context_in_multispeaker_thread(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": "@A 什么时候回牢日", "timestamp": "2025-12-17 09:00:00"},
        {"speaker": "C", "content": "我可以帮你配电脑", "timestamp": "2025-12-17 09:00:01"},
        {"speaker": "B", "content": "等我回家来", "timestamp": "2025-12-17 09:00:02"},
        {"speaker": "A", "content": "牢日的生鱼片确实很棒", "timestamp": "2025-12-17 09:00:03"},
    ]
    path = tmp_path / "holdout_thread.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    groups = _build_context_reply_groups(path, target_speaker="A")
    windows = _build_recent_context_windows(path, target_speaker="A", history_turns=4)

    assert "等我回家来" not in groups
    assert groups["@A 什么时候回牢日"] == ["牢日的生鱼片确实很棒"]
    assert windows["@A 什么时候回牢日"][-1] == "B: @A 什么时候回牢日"


def test_holdout_keeps_short_answer_to_who_question(tmp_path: Path) -> None:
    payload = [
        {"speaker": "B", "content": "你们又聊什么了", "timestamp": "2025-12-17 09:00:00"},
        {"speaker": "B", "content": "谁是未成年人", "timestamp": "2025-12-17 09:00:01"},
        {"speaker": "A", "content": "存在感", "timestamp": "2025-12-17 09:00:02"},
    ]
    path = tmp_path / "holdout_who.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    groups = _build_context_reply_groups(path, target_speaker="A")

    assert groups["谁是未成年人"] == ["存在感"]


def test_target_stance_hint_extracts_latest_target_contrast() -> None:
    from persona_distill.holdout import _target_stance_hints

    hints = _target_stance_hints(
        [
            "脸接大招: 傻逼的不是玩家是厂商啊",
            "极客小猪: 傻逼的是玩家不是厂商啊",
            "脸接大招: 搞这么个抽卡系统",
        ],
        target_speaker="极客小猪",
    )

    assert hints == ["傻逼的是玩家不是厂商啊"]
