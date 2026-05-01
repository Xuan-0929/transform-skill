from __future__ import annotations

from datetime import datetime, timezone

from persona_distill.evaluation import _build_reply_priors
from persona_distill.holdout import _speaking_style_score
from persona_distill.models import PersonaProfile


def _profile() -> PersonaProfile:
    return PersonaProfile(
        persona_id="jc",
        version="v0001",
        generated_at=datetime.now(timezone.utc),
        sections={},
        expression_metrics={"median_chars_per_turn": 4.0, "short_reply_ratio": 0.58},
        uncertainty_notes=[],
        signature_lexicon=["挺好", "牛逼", "这sb", "没事"],
        style_memory=["你sb吧", "那挺好的", "笑死我了"],
        context_reply_memory=[
            {"context": "大床上睡几个人啊", "reply": "你是不是sb"},
            {"context": "个人", "reply": "牛逼"},
            {"context": "不知道", "reply": "没事了"},
            {"context": "没遇到技术跟我一样的", "reply": "哈哈哈哈哈哈哈哈哈"},
        ],
        model_cards=[],
        decision_rules=[],
        contradictions=[],
        known_answer_anchors=[],
        source_metrics={},
        source_item_count=12,
    )


def test_speaking_style_score_penalizes_missing_register_even_when_semantics_fit() -> None:
    assert _speaking_style_score("你sb吧", ["你是不是sb"]) >= 0.78
    assert _speaking_style_score("两个人啊，不然呢。", ["你是不是sb"]) <= 0.45
    assert _speaking_style_score("那你这真是单刷了，牛的。", ["牛逼"]) <= 0.58


def test_reply_priors_include_signature_praise_retort_and_deflect_buckets() -> None:
    priors = _build_reply_priors(_profile(), per_bucket_limit=8)

    assert "牛逼" in priors["praise"]
    assert "你是不是sb" in priors["retort"]
    assert "你sb吧" in priors["retort"]
    assert "没事了" in priors["comfort"]
    assert "挺好" in priors["affirmative"]
    assert "哈哈哈哈哈哈哈哈哈" in priors["reaction"]


def test_style_memory_keeps_distinctive_short_utterances() -> None:
    from datetime import datetime, timezone

    from persona_distill.extract import _build_style_memory
    from persona_distill.models import CorpusItem

    def item(idx: int, content: str) -> CorpusItem:
        return CorpusItem(
            id=f"i{idx}",
            source="t.json",
            speaker="A",
            timestamp=datetime(2025, 1, 1, 0, 0, idx, tzinfo=timezone.utc),
            content=content,
            content_hash=f"h{idx}",
            quality_score=0.9,
        )

    memory = _build_style_memory([item(1, "牛逼"), item(2, "你sb吧"), item(3, "是的")], limit=10)

    assert "牛逼" in memory
    assert "你sb吧" in memory
    assert "是的" not in memory
