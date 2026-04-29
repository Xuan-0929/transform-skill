from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .models import CORE_SECTIONS, EvidenceClaim, PersonaProfile
from .providers import ModelProvider
from .utils import canonical_skill_name, has_negation, safe_excerpt

SECTION_TITLES = {
    "beliefs_and_values": "Beliefs & Values",
    "mental_models": "Mental Models",
    "decision_heuristics": "Decision Heuristics",
    "expression_dna": "Expression DNA",
    "anti_patterns_and_limits": "Anti-Patterns & Limits",
}


def _first_evidence(claim: EvidenceClaim, fallback: str = "No direct evidence excerpt.") -> str:
    if not claim.evidence:
        return fallback
    return safe_excerpt(claim.evidence[0].excerpt, max_len=140)


def _title_from_claim(text: str, idx: int) -> str:
    cleaned = re.sub(r"[\s，。！？!?,;；：:\"'“”‘’（）()【】\[\]<>]", "", text).strip()
    if not cleaned:
        return f"核心模式{idx}"
    return cleaned[:16]


def _apply_hint(text: str) -> str:
    if "如果" in text and "就" in text:
        return "当场景存在明确条件分支、需要先判断再行动时使用。"
    if "先" in text and ("再" in text or "然后" in text):
        return "当任务可拆为步骤、需要控制执行顺序时使用。"
    if "因为" in text and "所以" in text:
        return "当需要解释因果链条、说服对方接受结论时使用。"
    if "不要" in text or "不能" in text or "别" in text:
        return "当你需要做风险规避或边界约束判断时使用。"
    return "当问题需要快速判断、并要求给出明确立场时使用。"


def _limit_hint(text: str) -> str:
    if has_negation(text):
        return "该规则在高风险场景下有效，但可能导致过度保守。"
    if len(text) > 30:
        return "该规则上下文依赖较强，跨场景迁移时容易失真。"
    return "该规则强调速度与明确性，可能牺牲细节完整度。"


def _skill_frontmatter(profile: PersonaProfile, persona_name: str, skill_name: str) -> str:
    description = (
        f"Use this skill when the user asks for analysis, decisions, or rewrites in the persona style of "
        f"'{persona_name}'. Execute with explicit reasoning rules, evidence linkage, and boundary honesty."
    )
    payload = {
        "name": skill_name,
        "description": description[:1024],
        "compatibility": (
            "Designed for Agent Skills compatible runtimes and Codex-style agents. "
            "Supports progressive loading with references/ and examples/."
        ),
        "metadata": {
            "persona_display_name": persona_name,
            "persona_id": profile.persona_id,
            "distill_version": profile.version,
            "source_item_count": str(profile.source_item_count),
            "template_profile": "high-density-v2",
        },
    }
    return "---\n" + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"


def _tagline(profile: PersonaProfile) -> str:
    beliefs = profile.sections.get("beliefs_and_values", [])
    if beliefs:
        return safe_excerpt(beliefs[0].claim, max_len=80)
    return "先判断，再表达；先边界，再结论。"


def _roleplay_block() -> str:
    return (
        "## 角色扮演规则（最重要）\n\n"
        "- Skill激活后直接以第一人称回应，不使用“ta会怎么想”的转述语气。\n"
        "- 优先复现决策方式，不追求机械复读口头禅。\n"
        "- 首次触发可做一次简短免责声明，后续不重复。\n"
        "- 用户要求“退出角色/切回正常模式”时立即退出。\n"
        "- 遇到证据不足，不要硬演，必须明确不确定性和缺失信息。\n\n"
    )


def _trigger_block(persona_name: str) -> str:
    return (
        "## 触发条件\n\n"
        f"- 用户明确要求“用{persona_name}的风格/视角”时触发。\n"
        "- 用户需要决策建议、话术改写、观点判断且希望保持该人格认知路径时触发。\n"
        "- 纯事实检索且与人格无关时不触发，直接走常规回答。\n\n"
    )


def _protocol_block() -> str:
    return (
        "## 回答工作流（Agentic Protocol）\n\n"
        "1. **问题分流**：先判断是决策题、改写题、还是事实题。\n"
        "2. **证据选取**：从心智模型/启发式/边界层各选至少1条相关证据。\n"
        "3. **生成回答**：先给结论，再给理由，再给可执行动作。\n"
        "4. **边界检查**：核对反模式、冲突项和不确定性声明是否齐全。\n"
        "5. **输出定稿**：满足输出契约和质量清单后再返回。\n\n"
    )


def _identity_block(profile: PersonaProfile, persona_name: str) -> str:
    metrics = profile.expression_metrics
    avg_chars = metrics.get("avg_chars_per_turn", 0)
    short_ratio = metrics.get("short_reply_ratio", 0)
    directness = metrics.get("directness_score", 0)
    source_metrics = profile.source_metrics or {}
    source_files = source_metrics.get("unique_source_files", 0)
    span_days = source_metrics.get("time_span_days", 0)
    signature_examples = "\n".join(f"- {x}" for x in profile.style_memory[:4]) or "- 暂无可用样本"
    return (
        "## 身份卡\n\n"
        f"- **我是谁**：{persona_name}（由聊天语料蒸馏得到的认知与表达操作系统）。\n"
        f"- **语料规模**：{profile.source_item_count} 条有效发言。\n"
        f"- **来源覆盖**：{source_files} 个来源文件，时间跨度约 {span_days} 天。\n"
        f"- **当前版本**：{profile.version}。\n"
        f"- **表达基线**：平均 {avg_chars} 字/轮，短句比例 {short_ratio}，直接性 {directness}。\n"
        "- **代表性话风样本**：\n"
        f"{signature_examples}\n\n"
    )


def _core_models_block(profile: PersonaProfile) -> str:
    if profile.model_cards:
        lines = ["## 核心心智模型", ""]
        for idx, card in enumerate(profile.model_cards[:7], start=1):
            lines.append(f"### 模型{idx}: {card.name}")
            lines.append(f"- **一句话**：{card.definition}")
            lines.append(f"- **看什么**：{card.sees_first}")
            lines.append(f"- **忽略什么**：{card.filters_out}")
            lines.append(f"- **如何重构问题**：{card.reframes}")
            if card.evidence_anchors:
                lines.append("- **证据锚点**：")
                for anchor in card.evidence_anchors[:3]:
                    lines.append(f"  - {anchor}")
            lines.append(
                "- **三重验证**："
                f"跨域复现={card.gates.get('cross_context', False)}，"
                f"生成力={card.gates.get('generative', False)}，"
                f"排他性={card.gates.get('exclusive', False)}"
            )
            lines.append(f"- **失效模式**：{card.failure_mode}")
            lines.append("")
        return "\n".join(lines) + "\n"

    claims = profile.sections.get("mental_models", [])[:6]
    if not claims:
        return "## 核心心智模型\n\n- 暂无高置信度模型。\n\n"

    lines = ["## 核心心智模型", ""]
    for idx, claim in enumerate(claims, start=1):
        title = _title_from_claim(claim.claim, idx)
        lines.append(f"### 模型{idx}: {title}")
        lines.append(f"- **一句话**：{claim.claim}")
        lines.append(f"- **证据**：{_first_evidence(claim)}")
        lines.append(f"- **应用**：{_apply_hint(claim.claim)}")
        lines.append(f"- **局限**：{_limit_hint(claim.claim)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _heuristics_block(profile: PersonaProfile) -> str:
    if profile.decision_rules:
        lines = ["## 决策启发式", ""]
        for idx, rule in enumerate(profile.decision_rules[:10], start=1):
            lines.append(f"{idx}. **规则{idx}**：{rule.rule}")
            lines.append(f"- 触发条件：{rule.condition}")
            lines.append(f"- 动作策略：{rule.action}")
            lines.append(f"- 背后逻辑：{rule.rationale}")
            lines.append(f"- 边界：{rule.boundary}")
            if rule.evidence_anchor:
                lines.append(f"- 证据片段：{rule.evidence_anchor}")
        lines.append("")
        return "\n".join(lines)

    claims = profile.sections.get("decision_heuristics", [])[:10]
    if not claims:
        return "## 决策启发式\n\n- 暂无高置信度启发式。\n\n"
    lines = ["## 决策启发式", ""]
    for idx, claim in enumerate(claims, start=1):
        lines.append(f"{idx}. **规则{idx}**：{claim.claim}")
        lines.append(f"- 应用场景：{_apply_hint(claim.claim)}")
        lines.append(f"- 证据片段：{_first_evidence(claim)}")
        lines.append(f"- 失效风险：{_limit_hint(claim.claim)}")
    lines.append("")
    return "\n".join(lines)


def _expression_block(profile: PersonaProfile) -> str:
    metrics = profile.expression_metrics
    lexicon = "、".join(profile.signature_lexicon[:20]) or "无"
    memory = "\n".join(f"- {x}" for x in profile.style_memory[:12]) or "- 暂无"
    return (
        "## 表达DNA\n\n"
        "- **句式倾向**：短句优先，结论先行，常配合反问/强调。\n"
        f"- **语言统计**：avg_chars={metrics.get('avg_chars_per_turn', 0)}，"
        f"median_chars={metrics.get('median_chars_per_turn', 0)}，"
        f"question_ratio={metrics.get('question_ratio', 0)}，"
        f"exclaim_ratio={metrics.get('exclaim_ratio', 0)}。\n"
        f"- **词汇签名**：{lexicon}\n"
        "- **语气策略**：在高不确定场景保持直接，但必须给边界说明。\n"
        "- **代表性表达片段**：\n"
        f"{memory}\n\n"
    )


def _values_and_anti_block(profile: PersonaProfile) -> str:
    beliefs = profile.sections.get("beliefs_and_values", [])[:6]
    antis = profile.sections.get("anti_patterns_and_limits", [])[:6]
    belief_lines = [f"- {c.claim}（证据：{_first_evidence(c)}）" for c in beliefs] or ["- 暂无"]
    anti_lines = [f"- {c.claim}（证据：{_first_evidence(c)}）" for c in antis] or ["- 暂无"]

    contradiction_lines = []
    for c in profile.contradictions[:6]:
        contradiction_lines.append(f"- [{c.type}] {c.description}")
    if not contradiction_lines:
        tension = "尚未提取出显著价值冲突。"
        if beliefs and antis:
            tension = f"一方面强调「{safe_excerpt(beliefs[0].claim, 26)}」，另一方面又警惕「{safe_excerpt(antis[0].claim, 26)}」。"
        contradiction_lines = [f"- {tension}"]

    return (
        "## 价值观与反模式\n\n"
        "**我追求的**：\n"
        + "\n".join(belief_lines)
        + "\n\n**我拒绝的**：\n"
        + "\n".join(anti_lines)
        + "\n\n**内在张力**：\n"
        + "\n".join(contradiction_lines)
        + "\n\n"
    )


def _output_contract_block() -> str:
    return (
        "## 输出契约\n\n"
        "- MUST 给出明确结论或下一步动作（若问题是决策导向）。\n"
        "- MUST 给出理由链，而不是只有态度。\n"
        "- MUST 在证据不足时显式声明不确定性。\n"
        "- MUST NOT 编造语料外的人设事实、经历或关系。\n"
        "- MUST NOT 用口头禅替代推理。\n\n"
    )


def _quality_checklist_block() -> str:
    return (
        "## 质量检查清单\n\n"
        "- [ ] 至少引用了1条心智模型或决策启发式。\n"
        "- [ ] 结论与证据一致，没有跳步推理。\n"
        "- [ ] 已检查反模式边界，没有越界输出。\n"
        "- [ ] 不确定性声明已给出（若需要）。\n"
        "- [ ] 语气相似但不过拟合口头禅。\n\n"
    )


def _boundaries_block(profile: PersonaProfile) -> str:
    notes = profile.uncertainty_notes[:6]
    note_lines = "\n".join(f"- {n}" for n in notes) or "- 当前未检测到额外不确定性提示。"
    return (
        "## 诚实边界\n\n"
        "此Skill只基于用户投喂语料提炼，不代表真实人物完整人格。\n\n"
        "- 对未覆盖场景的判断可能偏差较大。\n"
        "- 语料时间窗以当前仓库快照为准，后续变化不会自动同步。\n"
        "- 若问题需要外部事实，请先查证再套用该人格框架。\n"
        f"- 调研时间：{profile.generated_at.date().isoformat()}。\n\n"
        "### 当前不确定性信号\n\n"
        f"{note_lines}\n\n"
    )


def _research_audit_block(profile: PersonaProfile) -> str:
    m = profile.source_metrics or {}
    return (
        "## 研究与蒸馏审计\n\n"
        f"- source_item_count: {m.get('source_item_count', profile.source_item_count)}\n"
        f"- unique_source_files: {m.get('unique_source_files', 0)}\n"
        f"- time_span_days: {m.get('time_span_days', 0)}\n"
        f"- active_month_buckets: {m.get('active_month_buckets', 0)}\n"
        f"- avg_quality_score: {m.get('avg_quality_score', 0)}\n"
        f"- kept_models(triple-gate pass=3/3): {m.get('kept_models', 0)}\n"
        f"- demoted_models(pass<3 -> heuristics): {m.get('demoted_models', 0)}\n"
        f"- contradictions_detected: {len(profile.contradictions)}\n\n"
    )


def _appendix_block(profile: PersonaProfile) -> str:
    known_answer_lines = []
    for idx, anchor in enumerate(profile.known_answer_anchors[:3], start=1):
        q = anchor.get("question", "")
        a = anchor.get("expected_direction", "")
        known_answer_lines.append(f"- Q{idx}: {q}")
        known_answer_lines.append(f"  - expected: {a}")
    known_answer_text = "\n".join(known_answer_lines) if known_answer_lines else "- 暂无可用锚点。"
    return (
        "## 附录：调研与证据索引\n\n"
        "- `references/persona-profile.md`：逐条结论与证据映射。\n"
        "- `references/decision-heuristics.md`：决策规则浓缩清单。\n"
        "- `references/model-cards.md`：心智模型卡片（三重门禁）。\n"
        "- `references/contradictions.md`：矛盾与张力清单。\n"
        "- `references/style-memory.md`：高频表达样本。\n"
        "- `references/context-reply-memory.md`：上下文-回复对齐样本。\n"
        "- `examples/usage.md`：输入输出示例。\n\n"
        "### 已知问题锚点（Known-answer）\n\n"
        f"{known_answer_text}\n\n"
    )


def _build_skill_markdown(
    profile: PersonaProfile,
    provider: ModelProvider,
    persona_name: str,
    skill_name: str,
) -> str:
    _ = provider
    frontmatter = _skill_frontmatter(profile, persona_name, skill_name)
    title = (
        f"# {persona_name} · 思维操作系统\n\n"
        f"> 「{_tagline(profile)}」\n\n"
    )
    body = (
        _roleplay_block()
        + _trigger_block(persona_name)
        + _protocol_block()
        + _identity_block(profile, persona_name)
        + _core_models_block(profile)
        + _heuristics_block(profile)
        + _expression_block(profile)
        + _values_and_anti_block(profile)
        + _output_contract_block()
        + _quality_checklist_block()
        + _boundaries_block(profile)
        + _research_audit_block(profile)
        + _appendix_block(profile)
    )
    return frontmatter + title + body


def _render_references(profile: PersonaProfile) -> tuple[str, str, str, str, str, str, str, str]:
    profile_lines = ["# Persona Profile (Evidence Linked)", ""]
    heuristics_lines = ["# Decision Heuristics", ""]
    style_memory_lines = ["# Style Memory", ""]
    context_reply_lines = ["# Context-Reply Memory", ""]
    model_card_lines = ["# Model Cards", ""]
    contradiction_lines = ["# Contradictions", ""]
    blueprint_lines = [
        "# Skill Blueprint",
        "",
        "This file condenses high-value conclusions to help downstream agents load context progressively.",
        "",
    ]

    for section, claims in profile.sections.items():
        profile_lines.append(f"## {SECTION_TITLES.get(section, section)}")
        for claim in claims:
            ev = claim.evidence[0].excerpt if claim.evidence else ""
            profile_lines.append(f"- {claim.claim}")
            profile_lines.append(f"  - confidence: {claim.confidence}")
            profile_lines.append(f"  - evidence: {ev}")
        profile_lines.append("")
        if section == "decision_heuristics":
            for claim in claims:
                heuristics_lines.append(f"- {claim.claim}")

    if profile.model_cards:
        for idx, card in enumerate(profile.model_cards, start=1):
            model_card_lines.append(f"## Model {idx}: {card.name}")
            model_card_lines.append(f"- definition: {card.definition}")
            model_card_lines.append(f"- sees_first: {card.sees_first}")
            model_card_lines.append(f"- filters_out: {card.filters_out}")
            model_card_lines.append(f"- reframes: {card.reframes}")
            model_card_lines.append(
                f"- gates: cross_context={card.gates.get('cross_context', False)}, "
                f"generative={card.gates.get('generative', False)}, "
                f"exclusive={card.gates.get('exclusive', False)}"
            )
            model_card_lines.append(f"- failure_mode: {card.failure_mode}")
            if card.evidence_anchors:
                model_card_lines.append("- evidence_anchors:")
                for anchor in card.evidence_anchors[:3]:
                    model_card_lines.append(f"  - {anchor}")
            model_card_lines.append("")
    else:
        model_card_lines.append("- No model cards extracted.")

    if profile.contradictions:
        for c in profile.contradictions:
            contradiction_lines.append(f"- [{c.type}] {c.description}")
            for ev in c.evidence[:2]:
                contradiction_lines.append(f"  - evidence: {ev}")
    else:
        contradiction_lines.append("- No explicit contradictions extracted.")

    blueprint_lines.append("## Core Reasoning Contracts")
    if profile.model_cards:
        for card in profile.model_cards[:8]:
            blueprint_lines.append(f"- {card.name}: {card.definition}")
    else:
        for claim in profile.sections.get("mental_models", [])[:8]:
            blueprint_lines.append(f"- {claim.claim}")
    blueprint_lines.append("")
    blueprint_lines.append("## Core Decision Rules")
    if profile.decision_rules:
        for rule in profile.decision_rules[:12]:
            blueprint_lines.append(f"- IF {rule.condition} THEN {rule.action}")
    else:
        for claim in profile.sections.get("decision_heuristics", [])[:12]:
            blueprint_lines.append(f"- {claim.claim}")
    blueprint_lines.append("")
    blueprint_lines.append("## Core Anti-Patterns")
    for claim in profile.sections.get("anti_patterns_and_limits", [])[:10]:
        blueprint_lines.append(f"- {claim.claim}")
    blueprint_lines.append("")

    examples_text = """# Usage Examples

## Example 1: Decision
User: 现在该不该立刻推进？
Assistant behavior: 先给结论，再按风险/收益解释，并给下一步动作。

## Example 2: Rewrite
User: 帮我把这段话改成ta的口吻。
Assistant behavior: 保持其节奏与判断方式，但不编造语料外事实。

## Example 3: Uncertainty
User: 给一个很具体的行业判断。
Assistant behavior: 若语料中无足够依据，明确不确定，并给出需要补充的证据类型。
"""
    for idx, text in enumerate(profile.style_memory[:150], start=1):
        style_memory_lines.append(f"{idx}. {text}")

    for idx, pair in enumerate(profile.context_reply_memory[:220], start=1):
        context_reply_lines.append(f"## Pair {idx}")
        context_reply_lines.append(f"- context: {pair.get('context', '')}")
        context_reply_lines.append(f"- reply: {pair.get('reply', '')}")
        context_reply_lines.append("")

    return (
        "\n".join(profile_lines),
        "\n".join(heuristics_lines),
        examples_text,
        "\n".join(style_memory_lines),
        "\n".join(context_reply_lines),
        "\n".join(model_card_lines),
        "\n".join(contradiction_lines),
        "\n".join(blueprint_lines),
    )


def render_skill_package(
    profile: PersonaProfile,
    output_dir: Path,
    provider: ModelProvider,
    persona_name: str,
    skill_name: str | None = None,
) -> dict:
    resolved_skill_name = skill_name or canonical_skill_name(persona_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    refs_dir = output_dir / "references"
    ex_dir = output_dir / "examples"
    refs_dir.mkdir(parents=True, exist_ok=True)
    ex_dir.mkdir(parents=True, exist_ok=True)

    skill_text = _build_skill_markdown(profile, provider, persona_name, resolved_skill_name)
    (output_dir / "SKILL.md").write_text(skill_text, encoding="utf-8")

    (
        persona_profile_md,
        heuristics_md,
        examples_md,
        style_memory_md,
        context_reply_md,
        model_cards_md,
        contradiction_md,
        blueprint_md,
    ) = _render_references(profile)
    (refs_dir / "persona-profile.md").write_text(persona_profile_md, encoding="utf-8")
    (refs_dir / "decision-heuristics.md").write_text(heuristics_md, encoding="utf-8")
    (refs_dir / "style-memory.md").write_text(style_memory_md, encoding="utf-8")
    (refs_dir / "context-reply-memory.md").write_text(context_reply_md, encoding="utf-8")
    (refs_dir / "model-cards.md").write_text(model_cards_md, encoding="utf-8")
    (refs_dir / "contradictions.md").write_text(contradiction_md, encoding="utf-8")
    (refs_dir / "skill-blueprint.md").write_text(blueprint_md, encoding="utf-8")
    (ex_dir / "usage.md").write_text(examples_md, encoding="utf-8")

    section_counts = {section: len(profile.sections.get(section, [])) for section in CORE_SECTIONS}
    manifest = {
        "persona_id": profile.persona_id,
        "persona_display_name": persona_name,
        "skill_name": resolved_skill_name,
        "version": profile.version,
        "generated_at": profile.generated_at.isoformat(),
        "source_item_count": profile.source_item_count,
        "section_claim_counts": section_counts,
        "expression_metrics": profile.expression_metrics,
        "uncertainty_notes": profile.uncertainty_notes,
        "signature_lexicon": profile.signature_lexicon,
        "style_memory_size": len(profile.style_memory),
        "context_reply_memory_size": len(profile.context_reply_memory),
        "model_card_count": len(profile.model_cards),
        "decision_rule_count": len(profile.decision_rules),
        "contradiction_count": len(profile.contradictions),
        "files": [
            "SKILL.md",
            "references/persona-profile.md",
            "references/decision-heuristics.md",
            "references/style-memory.md",
            "references/context-reply-memory.md",
            "references/model-cards.md",
            "references/contradictions.md",
            "references/skill-blueprint.md",
            "examples/usage.md",
        ],
    }
    (output_dir / "persona_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
