from __future__ import annotations

from datetime import datetime, timezone

from persona_distill.evaluation import compare_eval, load_benchmark
from persona_distill.models import PersonaProfile
from persona_distill.providers.base import ModelProvider


class _FriendlyProvider(ModelProvider):
    def __init__(self) -> None:
        super().__init__(provider="stub", model="friendly")

    def refine_claim(self, section: str, candidate: str) -> str:
        return candidate

    def summarize_section(self, section: str, claims: list[str]) -> str:
        return " ".join(claims)

    def generate_response(self, prompt: str, context: str) -> str:
        return "还行吧，最近有点忙。"

    def run_agent(self, prompt: str) -> str:
        return '{"claims":[]}'


def _profile() -> PersonaProfile:
    return PersonaProfile(
        persona_id="friend-demo",
        version="v0001",
        generated_at=datetime.now(timezone.utc),
        sections={},
        expression_metrics={"avg_chars_per_turn": 8, "median_chars_per_turn": 8, "short_reply_ratio": 0.6},
        uncertainty_notes=[],
        signature_lexicon=[],
        style_memory=["还行吧，最近有点忙。"],
        context_reply_memory=[],
        model_cards=[],
        decision_rules=[],
        contradictions=[],
        known_answer_anchors=[],
        source_metrics={},
        source_item_count=1,
    )


def test_default_benchmark_is_persona_smoke_not_english_recommendation() -> None:
    benchmark = load_benchmark(None)

    assert benchmark.name == "default-persona-smoke"
    assert benchmark.cases[0].prompt == "最近怎么样"
    values = {str(assertion.value) for assertion in benchmark.cases[0].assertions}
    assert "tradeoff" not in values
    assert "recommend" not in values
    assert {"AI", "语料", "证据不足", "稳定信息不足", "我不能编"} <= values


def test_default_benchmark_gate_accepts_natural_chinese_persona_reply() -> None:
    comparison = compare_eval(load_benchmark(None), _profile(), _FriendlyProvider())

    assert comparison.with_skill.critical_pass_rate == 1.0
    assert comparison.baseline.pass_rate == 0.0
    assert comparison.gate_passed, comparison.reasons
