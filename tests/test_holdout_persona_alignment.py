from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from persona_distill.holdout import evaluate_multi_ref_holdout
from persona_distill.models import EvidenceClaim, EvidenceSpan, PersonaProfile
from persona_distill.providers.base import ModelProvider


class _JudgeProvider(ModelProvider):
    def __init__(self) -> None:
        super().__init__(provider="stub", model="stub")
        self.judge_prompts: list[str] = []

    def refine_claim(self, section: str, candidate: str) -> str:
        return candidate

    def summarize_section(self, section: str, claims: list[str]) -> str:
        return " ".join(claims)

    def generate_response(self, prompt: str, context: str) -> str:
        return "不行，先看风险再说。"

    def run_agent(self, prompt: str) -> str:
        self.judge_prompts.append(prompt)
        return json.dumps({"score": 0.84, "rationale": "价值立场和风险偏好匹配"}, ensure_ascii=False)


def _profile() -> PersonaProfile:
    return PersonaProfile(
        persona_id="demo",
        version="v0001",
        generated_at=datetime.now(timezone.utc),
        sections={
            "beliefs_and_values": [
                EvidenceClaim(
                    id="c1",
                    section="beliefs_and_values",
                    claim="遇到风险先刹车，不为了面子硬上。",
                    confidence=0.9,
                    evidence=[EvidenceSpan(item_id="i1", start=0, end=0, excerpt="不行")],
                )
            ],
            "expression_dna": [
                EvidenceClaim(
                    id="c2",
                    section="expression_dna",
                    claim="短句直给，先表态再补一句理由。",
                    confidence=0.85,
                    evidence=[EvidenceSpan(item_id="i2", start=0, end=0, excerpt="先别")],
                )
            ],
        },
        expression_metrics={"median_chars_per_turn": 8.0, "short_reply_ratio": 0.5},
        uncertainty_notes=[],
        signature_lexicon=["不行", "先看"],
        style_memory=["不行", "先看风险"],
        context_reply_memory=[],
        model_cards=[],
        decision_rules=[],
        contradictions=[],
        known_answer_anchors=[],
        source_metrics={},
        source_item_count=2,
    )


def test_holdout_can_report_persona_alignment_judge_score(tmp_path: Path) -> None:
    holdout = tmp_path / "holdout.json"
    holdout.write_text(
        json.dumps(
            [
                {"speaker": "B", "content": "我打算硬冲", "timestamp": "2025-01-01T00:00:00Z"},
                {"speaker": "A", "content": "不行", "timestamp": "2025-01-01T00:00:02Z"},
                {"speaker": "B", "content": "要不要继续", "timestamp": "2025-01-01T00:00:04Z"},
                {"speaker": "A", "content": "先看风险", "timestamp": "2025-01-01T00:00:06Z"},
                {"speaker": "B", "content": "那就硬上", "timestamp": "2025-01-01T00:00:08Z"},
                {"speaker": "A", "content": "别上", "timestamp": "2025-01-01T00:00:10Z"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    provider = _JudgeProvider()

    report = evaluate_multi_ref_holdout(
        profile=_profile(),
        provider=provider,
        holdout_path=holdout,
        target_speaker="A",
        max_cases=3,
        min_refs=1,
        min_avg_similarity=0.0,
        min_delta_vs_baseline=-1.0,
        judge_persona_alignment=True,
        min_persona_alignment=0.8,
    )

    assert report["persona_alignment_avg"] == 0.84
    assert report["passed"] is True
    assert report["examples"][0]["persona_alignment"] == 0.84
    assert "遇到风险先刹车" in provider.judge_prompts[0]
    assert "Do not penalize compact replies solely for being low-information" in provider.judge_prompts[0]
    assert "laugh-only or reaction-only replies" in provider.judge_prompts[0]
    assert "median_chars_per_turn" in provider.judge_prompts[0]
