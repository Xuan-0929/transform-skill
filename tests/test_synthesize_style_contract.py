from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from persona_distill.models import EvidenceClaim, EvidenceSpan, PersonaProfile
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
    assert "执行优先级：Layer 0 > PART B 人格判断 > PART A 记忆锚点 > 对话形态约束 > 其他规则。" in skill_text
    assert "避免“结论：/理由很简单：/现在就执行：”这类报告口吻。" in skill_text
    assert "先给结论，再给理由，再给可执行动作。" not in skill_text
    assert "至少引用了1条心智模型或决策启发式。" not in skill_text
    assert "默认 1-2 句" not in skill_text
    assert "回复长度跟语境走" in skill_text
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


def test_render_skill_finalizes_minimum_persona_contract(tmp_path: Path) -> None:
    from persona_distill.validation import run_validation

    profile = _profile()
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=profile,
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )

    validation = run_validation(output_dir, profile, {"style_memory"})

    assert validation.ok, validation.schema_errors + validation.consistency_errors
    assert len(profile.model_cards) >= 2
    assert len(profile.decision_rules) >= 5
    skill_text = (output_dir / "SKILL.md").read_text(encoding="utf-8")
    assert skill_text.count("### 模型") >= 2


def test_skill_markdown_enforces_embodied_roleplay_not_ai_boundary(tmp_path: Path) -> None:
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=_profile(),
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )
    skill_text = (output_dir / "SKILL.md").read_text(encoding="utf-8")

    assert "你就是 friend-demo，不是 AI 助手" in skill_text
    assert "evidence linkage" not in skill_text
    assert "boundary honesty" not in skill_text
    assert "先由 PART B 判断" in skill_text
    assert "再由 PART A 补充" in skill_text
    assert "内部判断" in skill_text
    assert "稳定信息不足" not in skill_text
    assert "我不能编" not in skill_text
    assert "语料没给" not in skill_text
    assert "MUST 在证据不足时显式声明不确定性。" not in skill_text
    assert "遇到证据不足，不要硬演" not in skill_text
    assert "最多给最小动作并说明缺什么信息" not in skill_text


def test_skill_markdown_filters_extraction_diagnostics_from_runtime(tmp_path: Path) -> None:
    profile = _profile()
    profile.style_memory = ["01-07 03:55:06", "你先吃，别跟我演减肥。"]
    profile.context_reply_memory = [
        {"context": "01-07 03:55:06", "reply": "01-07 03:55:09"},
        {"context": "晚上吃什么", "reply": "你就点个热的，别空腹硬扛。"},
    ]
    profile.sections["beliefs_and_values"] = [
        EvidenceClaim(
            id="claim-diagnostic",
            section="beliefs_and_values",
            claim="仅有“代表性表达”和时间戳，缺少具体内容，无法提炼 beliefs_and_values。",
            confidence=0.4,
            evidence=[
                EvidenceSpan(
                    item_id="style_memory",
                    excerpt="你先吃，别跟我演减肥。",
                )
            ],
        )
    ]
    profile.sections["mental_models"] = [
        EvidenceClaim(
            id="claim-meta-thin",
            section="mental_models",
            claim="只凭一句“无所谓”，证据太薄，推不出稳定心智模型。",
            confidence=0.4,
            evidence=[
                EvidenceSpan(
                    item_id="style_memory",
                    excerpt="你先吃，别跟我演减肥。",
                )
            ],
        )
    ]
    output_dir = tmp_path / "skill"
    render_skill_package(
        profile=profile,
        output_dir=output_dir,
        provider=_StubProvider(),
        persona_name="friend-demo",
    )
    skill_text = (output_dir / "SKILL.md").read_text(encoding="utf-8")

    assert "无法提炼" not in skill_text
    assert "无有效内容" not in skill_text
    assert "仅有“代表性表达”" not in skill_text
    assert "证据太薄" not in skill_text
    assert "推不出" not in skill_text
    assert "01-07 03:55:06" not in skill_text
    assert "> 「你先吃，别跟我演减肥。」" in skill_text
    assert "- 别人说：晚上吃什么" in skill_text
