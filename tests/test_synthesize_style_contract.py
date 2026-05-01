from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from persona_distill.models import PersonaProfile
from persona_distill.providers.base import ModelProvider
from persona_distill.synthesize import render_skill_package


class _StubProvider(ModelProvider):
    def __init__(self) -> None:
        super().__init__(provider="stub", model="stub")

    def refine_claim(self, section: str, candidate: str) -> str:
        return candidate

    def summarize_section(self, section: str, claims: list[str]) -> str:
        return " ".join(claims[:1]) if claims else ""

    def generate_response(self, prompt: str, context: str) -> str:
        return "stub"

    def run_agent(self, prompt: str) -> str:
        return '{"claims":[]}'


def _profile() -> PersonaProfile:
    return PersonaProfile(
        persona_id="friend-demo",
        version="v0001",
        generated_at=datetime.now(timezone.utc),
        sections={},
        expression_metrics={
            "avg_chars_per_turn": 16.0,
            "median_chars_per_turn": 15.0,
            "question_ratio": 0.2,
            "exclaim_ratio": 0.1,
            "short_reply_ratio": 0.35,
            "directness_score": 0.9,
        },
        uncertainty_notes=[],
        signature_lexicon=["别磨叽", "先干了再说"],
        style_memory=["你先吃，别跟我演减肥。", "别纠结，先做再说。"],
        context_reply_memory=[
            {"context": "晚上吃什么", "reply": "你就点个热的，别空腹硬扛。"},
            {"context": "我怕做错", "reply": "怕个锤子，先干，错了我陪你改。"},
        ],
        model_cards=[],
        decision_rules=[],
        contradictions=[],
        known_answer_anchors=[],
        source_metrics={},
        source_item_count=12,
    )


def test_skill_markdown_uses_conversation_first_contract(tmp_path: Path) -> None:
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=_profile(),
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )
    skill_text = (output_dir / "SKILL.md").read_text(encoding="utf-8")

    assert "## 对话输出形态（风格优先）" in skill_text
    assert "## Layer 0：硬规则（最高优先级）" in skill_text
    assert "## 原声回复锚点（强约束）" in skill_text
    assert "你就是这个人，不是客服，不是咨询师，不是教程生成器。" in skill_text
    assert "执行优先级：Layer 0 > 对话形态约束 > 原声锚点与场景示例 > 其他规则。" in skill_text
    assert "避免“结论：/理由很简单：/现在就执行：”这类报告口吻。" in skill_text
    assert "先给结论，再给理由，再给可执行动作。" not in skill_text
    assert "至少引用了1条心智模型或决策启发式。" not in skill_text
    assert "MUST NOT 无依据扩写具体名词清单（菜名、店名、行程等）。" in skill_text


def test_usage_examples_prefer_corpus_pairs(tmp_path: Path) -> None:
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=_profile(),
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )
    usage_text = (output_dir / "examples" / "usage.md").read_text(encoding="utf-8")

    assert "## Example 1: Corpus Pair" in usage_text
    assert "User: 晚上吃什么" in usage_text
    assert "Assistant style target: 你就点个热的，别空腹硬扛。" in usage_text


def test_skill_markdown_contains_scene_examples(tmp_path: Path) -> None:
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=_profile(),
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )
    skill_text = (output_dir / "SKILL.md").read_text(encoding="utf-8")
    assert "## 场景化原声示例" in skill_text
    assert "### 场景 1" in skill_text
    assert "- 别人说：晚上吃什么" in skill_text
