from __future__ import annotations

from datetime import datetime, timezone

from persona_distill.evaluation import _persona_context
from persona_distill.models import DecisionRule, EvidenceClaim, EvidenceSpan, PersonaProfile


def _profile() -> PersonaProfile:
    return PersonaProfile(
        persona_id="demo",
        version="v0001",
        generated_at=datetime.now(timezone.utc),
        sections={
            "expression_dna": [
                EvidenceClaim(
                    id="c1",
                    section="expression_dna",
                    claim="短句为主，口语化，常用‘还真是’‘笑死’这类表达。",
                    confidence=0.82,
                    evidence=[EvidenceSpan(item_id="i1", start=0, end=0, excerpt="笑死我了")],
                )
            ],
            "decision_heuristics": [
                EvidenceClaim(
                    id="c2",
                    section="decision_heuristics",
                    claim="先看风险和胜率，打不过就撤。",
                    confidence=0.8,
                    evidence=[EvidenceSpan(item_id="i2", start=0, end=0, excerpt="打不过就跑")],
                )
            ],
        },
        expression_metrics={
            "avg_chars_per_turn": 7.2,
            "median_chars_per_turn": 5.0,
            "short_reply_ratio": 0.62,
            "question_ratio": 0.11,
        },
        uncertainty_notes=[],
        signature_lexicon=["还真是", "笑死", "完了"],
        style_memory=["还真是", "笑死我了", "完了"],
        context_reply_memory=[
            {"context": "荞麦地太搞笑了", "reply": "笑死我了"},
            {"context": "小孩姐打上瓦了", "reply": "完了"},
            {"context": "这个", "reply": "密码是什么"},
        ],
        model_cards=[],
        decision_rules=[
            DecisionRule(
                id="r1",
                rule="先试探再决定是否追击",
                condition="需要对局决策时",
                action="先看位置和技能，再决定追不追",
                rationale="避免高风险硬顶",
                boundary="信息不全就先撤",
                evidence_anchor="先Q试减速",
                confidence=0.8,
            )
        ],
        contradictions=[],
        known_answer_anchors=[],
        source_metrics={},
        source_item_count=200,
    )


def test_persona_context_uses_style_profile_and_dialogue_for_casual_prompt() -> None:
    ctx = _persona_context(_profile(), "荞麦地太搞笑了")
    assert "[STYLE_PROFILE]" in ctx
    assert "[PERSONA_CORE]" in ctx
    assert "[HABIT_PROFILE]" in ctx
    assert "[EXPRESSION_DNA]" in ctx
    assert "[CATCHPHRASE_HINTS]" in ctx
    assert "length_policy: 回复长度由对话语义与人格机制共同决定，不做固定字数约束" in ctx
    assert "observed_short_reply_ratio" in ctx
    assert "context: 荞麦地太搞笑了 => reply: 笑死我了" in ctx
    assert "context: 这个 => reply: 密码是什么" not in ctx
    assert "IF 需要对局决策时 THEN" not in ctx


def test_persona_context_includes_rules_for_reasoning_prompt() -> None:
    ctx = _persona_context(_profile(), "这局怎么打，给我步骤")
    assert "[PERSONA_CORE]" in ctx
    assert "IF 需要对局决策时 THEN 先看位置和技能，再决定追不追" in ctx


def test_persona_context_keeps_stable_core_for_casual_prompt() -> None:
    ctx = _persona_context(_profile(), "居然没关评论区")

    assert "[PERSONA_CORE]" in ctx
    assert "先看风险和胜率" in ctx or "先看风险" in ctx


def test_reply_priors_put_budui_in_negative_bucket() -> None:
    from persona_distill.evaluation import _build_reply_priors

    profile = _profile()
    profile.style_memory.append("不对")
    priors = _build_reply_priors(profile, per_bucket_limit=10)

    assert "不对" not in priors.get("affirmative", [])
    assert "不对" in priors.get("negative", [])
