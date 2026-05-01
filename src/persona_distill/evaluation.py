from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
from pathlib import Path

from .extract import _is_fragmentary_style_text
from .models import CORE_SECTIONS, EvalBenchmark, EvalCase, EvalCaseResult, EvalComparison, EvalRunResult, PersonaProfile
from .providers import ModelProvider
from .utils import jaccard_similarity, tokenize

DECISION_INTENT_HINTS = (
    "怎么",
    "如何",
    "建议",
    "应该",
    "要不要",
    "怎么做",
    "方案",
    "选择",
    "取舍",
    "计划",
    "步骤",
    "分析",
    "复盘",
)

AFFIRMATIVE_REPLY_HINTS = ("是的", "对的", "可以", "好的", "好滴", "行", "行吧", "也行", "ok", "OK", "对", "嗯", "确实", "还真是", "是啊", "对啊")
NEGATIVE_REPLY_HINTS = ("不是", "没有", "没呢", "不行", "不对", "别", "算了", "不太")
UNCERTAIN_REPLY_HINTS = ("不好说", "难说", "不知道", "看情况", "不确定", "大概")
REACTION_REPLY_HINTS = ("笑死", "哈哈", "我去", "卧槽", "完了", "离谱", "逆天", "可恶")
COMFORT_REPLY_HINTS = ("没事", "别慌", "慢慢来", "稳", "可以")
STYLE_MEMORY_MARKERS = ("还真是", "笑死", "完了", "卧槽", "哈哈", "可以", "是的", "难说", "不知道", "好滴")
GENERIC_OVERLAP_TOKENS = {"有点", "这个", "那个", "就是", "真的", "现在", "然后", "还真是", "太", "很"}
GENERIC_STYLE_CUES = {
    "还真是",
    "是的",
    "可以",
    "可以的",
    "好的",
    "好滴",
    "嗯",
    "哦对",
    "哈哈",
    "哈哈没有",
    "不知道",
    "难说",
    "没有",
    "不是",
}


def load_benchmark(path: Path | None) -> EvalBenchmark:
    if path is None or not path.exists():
        return EvalBenchmark(
            name="default-minimal",
            cases=[
                EvalCase(
                    id="default-1",
                    prompt="Give a recommendation with tradeoffs.",
                    expected_output="recommendation with tradeoffs",
                    assertions=[
                        {"type": "contains", "value": "tradeoff", "critical": True},
                        {"type": "contains", "value": "recommend", "critical": True},
                    ],
                )
            ],
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    return EvalBenchmark.model_validate(payload)


def _claim_relevance(prompt: str, claim: str) -> float:
    return jaccard_similarity(prompt, claim)


def _has_content_overlap(a: str, b: str) -> bool:
    at = {t for t in tokenize(a) if len(t) >= 2}
    bt = {t for t in tokenize(b) if len(t) >= 2}
    if not at or not bt:
        return False
    overlap = at & bt
    if not overlap:
        return False
    content_overlap = [tok for tok in overlap if tok not in GENERIC_OVERLAP_TOKENS]
    return bool(content_overlap)


def _looks_reasoning_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if any(k in text for k in DECISION_INTENT_HINTS):
        return True
    if any(k in lowered for k in ("recommend", "tradeoff", "steps", "plan", "analyze")):
        return True
    return False


def _looks_casual_turn(prompt: str) -> bool:
    compact = _norm_text(prompt)
    if not compact:
        return False
    if any(k in prompt for k in DECISION_INTENT_HINTS):
        return False
    if prompt.strip().endswith("?") or prompt.strip().endswith("？"):
        return len(compact) <= 24
    return len(compact) <= 20


def _style_length_profile(profile: PersonaProfile) -> str:
    metrics = profile.expression_metrics or {}
    avg_chars = metrics.get("avg_chars_per_turn", 0)
    median_chars = metrics.get("median_chars_per_turn", 0)
    short_ratio = metrics.get("short_reply_ratio", 0)
    return (
        f"- observed_avg_chars_per_turn: {avg_chars}\n"
        f"- observed_median_chars_per_turn: {median_chars}\n"
        f"- observed_short_reply_ratio: {short_ratio}\n"
        "- length_policy: 回复长度由对话语义与人格机制共同决定，不做固定字数约束"
    )


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip().lower()


def _classify_short_reply(reply: str) -> str | None:
    cleaned = _norm_text(reply)
    if not cleaned or len(cleaned) > 6:
        return None
    if any(p in reply for p in ("，", ",", "。", ";", "；", "、")) and len(cleaned) > 6:
        return None
    if any(h in cleaned for h in REACTION_REPLY_HINTS):
        return "reaction"
    if any(h in cleaned for h in UNCERTAIN_REPLY_HINTS):
        return "uncertain"
    if any(h in cleaned for h in NEGATIVE_REPLY_HINTS):
        return "negative"
    if any(h in cleaned for h in COMFORT_REPLY_HINTS):
        return "comfort"
    if any(h in cleaned for h in AFFIRMATIVE_REPLY_HINTS):
        return "affirmative"
    return None


def _build_reply_priors(profile: PersonaProfile, per_bucket_limit: int = 5) -> dict[str, list[str]]:
    bucket_freq: dict[str, dict[str, int]] = {
        "affirmative": {},
        "negative": {},
        "uncertain": {},
        "reaction": {},
        "comfort": {},
    }

    def _add_reply(reply: str, weight: int) -> None:
        bucket = _classify_short_reply(reply)
        cleaned = reply.strip()
        if bucket is None or not cleaned:
            return
        current = bucket_freq[bucket].get(cleaned, 0)
        bucket_freq[bucket][cleaned] = current + weight

    for pair in profile.context_reply_memory:
        _add_reply(pair.get("reply", ""), weight=2)
    for text in profile.style_memory[:160]:
        _add_reply(text, weight=1)

    priors: dict[str, list[str]] = {}
    for bucket, mapping in bucket_freq.items():
        filtered: list[tuple[str, int]] = []
        for text, count in mapping.items():
            norm = _norm_text(text)
            if bucket in {"affirmative", "negative", "uncertain"} and len(norm) > 4:
                continue
            if bucket == "reaction" and len(norm) > 6:
                continue
            if bucket == "negative" and ("可能" in norm or "不是没有" in norm):
                continue
            if re.search(r"[a-zA-Z]", text) and norm not in {"ok"}:
                continue
            if bucket == "affirmative" and "要么" in norm:
                continue
            filtered.append((text, count))
        ranked = sorted(filtered, key=lambda x: (-x[1], len(_norm_text(x[0])), x[0]))
        priors[bucket] = [text for text, _ in ranked[:per_bucket_limit]]
    return priors


def _select_dialogue_pairs(
    profile: PersonaProfile,
    prompt: str,
    *,
    limit: int = 12,
    prefer_short_reply: bool = False,
) -> list[dict[str, str]]:
    scored: list[tuple[float, dict[str, str]]] = []
    prompt_text = (prompt or "").strip()
    prompt_compact = _norm_text(prompt_text)
    for pair in profile.context_reply_memory:
        ctx = pair.get("context", "").strip()
        rep = pair.get("reply", "").strip()
        if not ctx or not rep:
            continue
        ctx_compact = _norm_text(ctx)
        ctx_len = len(ctx_compact)
        if ctx_len <= 1:
            continue
        if ctx_len <= 3 and prompt_compact != ctx_compact:
            continue
        if prefer_short_reply and len(rep) > 22:
            continue
        context_sim = _claim_relevance(prompt_text, ctx)
        content_overlap = _has_content_overlap(prompt_text, ctx)
        seq_sim = SequenceMatcher(None, prompt_text, ctx).ratio()
        if prompt_text and (prompt_text in ctx or ctx in prompt_text):
            seq_sim += 0.35
        context_sim = max(context_sim, min(1.0, seq_sim))
        overlap = 0.0
        if prompt_compact and ctx_compact:
            overlap = len(set(prompt_compact) & set(ctx_compact)) / max(1, len(set(prompt_compact) | set(ctx_compact)))
        short_exactish = ctx_len <= 4 and (prompt_compact == ctx_compact or context_sim >= 0.62)
        if not content_overlap and context_sim < 0.66 and not short_exactish:
            continue
        if overlap < 0.08 and context_sim < 0.42 and not short_exactish:
            continue
        reply_sim = _claim_relevance(prompt, rep)
        compact_bonus = 0.08 if len(rep) <= 14 else 0.0
        if short_exactish:
            compact_bonus += 0.08
        score = context_sim * 0.76 + reply_sim * 0.16 + compact_bonus + overlap * 0.08
        if len(ctx) <= 4 and context_sim < 0.45 and not short_exactish:
            continue
        scored.append((score, {"context": ctx, "reply": rep}))
    scored.sort(key=lambda x: x[0], reverse=True)

    selected = [pair for score, pair in scored if score >= 0.24][:limit]
    if selected:
        return selected
    selected = [pair for score, pair in scored if score >= 0.2][: max(4, limit // 2)]
    if selected:
        return selected
    return []


def _select_style_memory(profile: PersonaProfile, prompt: str, limit: int = 10, *, strict: bool = False) -> list[str]:
    scored: list[tuple[float, str]] = []
    prompt_compact = _norm_text(prompt)
    prefer_short = len(prompt_compact) <= 20
    for text in profile.style_memory:
        if _is_fragmentary_style_text(text):
            continue
        if prefer_short and len(_norm_text(text)) > 30:
            continue
        score = _claim_relevance(prompt, text)
        if score > 0 and not _has_content_overlap(prompt, text):
            score *= 0.25
        if prefer_short and len(_norm_text(text)) <= 10 and score > 0.01:
            score += 0.06
        if any(m in text for m in STYLE_MEMORY_MARKERS):
            score += 0.08
        if _norm_text(text) in GENERIC_STYLE_CUES:
            score -= 0.06
            if score <= 0:
                continue
        if len(text) <= 4 and score < 0.2 and not prefer_short:
            continue
        scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)
    min_pick_score = 0.16 if strict else 0.0
    picked = [text for score, text in scored if score > min_pick_score][:limit]
    if picked:
        return picked
    if prefer_short:
        short_only = [
            text
            for text in profile.style_memory
            if 1 < len(_norm_text(text)) <= 12 and _norm_text(text) not in GENERIC_STYLE_CUES
        ]
        if short_only:
            return short_only[:limit]
    # Do not fall back to weakly-related style lines for casual prompts.
    if not prefer_short and not strict:
        fallback = [text for _, text in scored[:limit]]
        if fallback:
            return fallback
    if strict:
        return []
    return [] if prefer_short else profile.style_memory[:limit]


def _select_section_claims(
    profile: PersonaProfile,
    section: str,
    prompt: str,
    *,
    limit: int,
    relevance_floor: float = 0.0,
    score_floor: float = 0.2,
) -> list[str]:
    claims = profile.sections.get(section, [])
    if not claims:
        return []

    scored: list[tuple[float, str]] = []
    for claim in claims:
        relevance = _claim_relevance(prompt, claim.claim)
        if relevance < relevance_floor:
            continue
        confidence = float(getattr(claim, "confidence", 0.5) or 0.5)
        support = min(1.0, len(getattr(claim, "evidence", []) or []) / 3)
        score = 0.42 * relevance + 0.38 * confidence + 0.2 * support
        scored.append((score, claim.claim))
    scored.sort(key=lambda x: x[0], reverse=True)

    picked = [text for score, text in scored if score >= score_floor][:limit]
    if picked:
        return picked

    by_conf = sorted(
        claims,
        key=lambda c: float(getattr(c, "confidence", 0.5) or 0.5),
        reverse=True,
    )
    return [c.claim for c in by_conf[:limit]]


def _derive_habit_profile(profile: PersonaProfile, *, include_decision_habit: bool) -> list[str]:
    metrics = profile.expression_metrics or {}
    short_ratio = float(metrics.get("short_reply_ratio", 0) or 0)
    question_ratio = float(metrics.get("question_ratio", 0) or 0)
    directness = float(metrics.get("directness_score", 0) or 0)
    median_chars = float(metrics.get("median_chars_per_turn", 0) or 0)
    habits: list[str] = []

    if short_ratio >= 0.45 or median_chars <= 8:
        habits.append("回复常偏短平快，按语义需要再补一句解释。")
    elif short_ratio <= 0.18 or median_chars >= 30:
        habits.append("回复常偏展开，容易补背景与前后因果。")
    else:
        habits.append("回复长度中等，常在关键点后补一层理由。")

    if question_ratio >= 0.12:
        habits.append("常用追问/反问推进对话。")
    elif question_ratio <= 0.03:
        habits.append("追问频率较低，更偏直接表态。")

    if directness >= 0.78:
        habits.append("表达直接，不喜欢绕圈。")
    elif directness <= 0.45:
        habits.append("表达更谨慎，常先留余地。")

    if include_decision_habit and profile.decision_rules:
        sample = profile.decision_rules[0]
        habits.append(f"遇到决策时倾向：先{sample.condition}，再{sample.action}。")
    return habits[:4]


def _core_claims_by_section(
    profile: PersonaProfile,
    prompt: str,
    reasoning_prompt: bool,
    *,
    casual_turn: bool,
) -> list[tuple[str, str]]:
    decision_like = reasoning_prompt or any(k in (prompt or "") for k in DECISION_INTENT_HINTS)
    section_order = [
        "beliefs_and_values",
        "mental_models",
        "decision_heuristics",
        "anti_patterns_and_limits",
    ]
    limits = {
        "beliefs_and_values": 1 if casual_turn else 2,
        "mental_models": 2 if reasoning_prompt else (0 if casual_turn else 1),
        "decision_heuristics": 3 if decision_like else 0,
        "anti_patterns_and_limits": 0 if casual_turn else 1,
    }
    titled: list[tuple[str, str]] = []
    for section in section_order:
        selected = _select_section_claims(
            profile,
            section,
            prompt,
            limit=limits[section],
            relevance_floor=0.1 if casual_turn else 0.0,
            score_floor=0.26 if casual_turn else 0.2,
        )
        for claim in selected:
            titled.append((section, claim))
    if titled:
        return titled
    if casual_turn:
        return []

    fallback_sections = [
        "beliefs_and_values",
        "mental_models",
        "anti_patterns_and_limits",
    ]
    if decision_like:
        fallback_sections.append("decision_heuristics")

    for section in fallback_sections:
        claims = profile.sections.get(section, [])
        if not claims:
            continue
        for claim in claims[:2]:
            titled.append((section, claim.claim))
    if titled:
        return titled

    for claim in profile.sections.get("expression_dna", [])[:2]:
        titled.append(("expression_dna", claim.claim))
    return titled


def _core_block_lines(
    profile: PersonaProfile,
    prompt: str,
    reasoning_prompt: bool,
    *,
    casual_turn: bool,
) -> list[str]:
    labels = {
        "beliefs_and_values": "价值偏好",
        "mental_models": "认知框架",
        "decision_heuristics": "决策习惯",
        "anti_patterns_and_limits": "边界禁区",
        "expression_dna": "表达习惯",
    }
    lines: list[str] = []
    for section, claim in _core_claims_by_section(profile, prompt, reasoning_prompt, casual_turn=casual_turn):
        lines.append(f"[{labels.get(section, section)}] {claim}")
    return lines[:8]


def _stable_core_lines_for_casual(profile: PersonaProfile, limit: int = 3) -> list[str]:
    """Keep casual turns grounded in persona mechanisms without overloading them."""

    labels = {
        "beliefs_and_values": "价值偏好",
        "mental_models": "认知框架",
        "decision_heuristics": "决策习惯",
        "anti_patterns_and_limits": "边界禁区",
    }
    candidates: list[tuple[float, str]] = []
    for section in (
        "beliefs_and_values",
        "mental_models",
        "decision_heuristics",
        "anti_patterns_and_limits",
    ):
        for claim in profile.sections.get(section, [])[:8]:
            confidence = float(getattr(claim, "confidence", 0.5) or 0.5)
            support = min(1.0, len(getattr(claim, "evidence", []) or []) / 3)
            score = 0.7 * confidence + 0.3 * support
            candidates.append((score, f"[{labels.get(section, section)}] {claim.claim}"))
    candidates.sort(key=lambda row: row[0], reverse=True)
    return [line for _, line in candidates[:limit]]


def _persona_context(profile: PersonaProfile, prompt: str) -> str:
    reasoning_prompt = _looks_reasoning_prompt(prompt)
    casual_turn = _looks_casual_turn(prompt) and not reasoning_prompt
    style_top = _select_style_memory(profile, prompt, limit=8 if casual_turn else 10, strict=casual_turn)
    if casual_turn:
        core_lines = _stable_core_lines_for_casual(profile, limit=2)
    else:
        core_lines = _core_block_lines(profile, prompt, reasoning_prompt, casual_turn=casual_turn)
    if not core_lines and not casual_turn:
        anchor = ""
        if style_top:
            anchor = style_top[0]
        elif profile.style_memory:
            for candidate in profile.style_memory:
                if _is_fragmentary_style_text(candidate):
                    continue
                anchor = candidate
                break
            if not anchor:
                anchor = profile.style_memory[0]
        if anchor:
            core_lines = [f"[表达锚点] {anchor}"]
    expression_claims = _select_section_claims(
        profile,
        "expression_dna",
        prompt,
        limit=3 if reasoning_prompt else 4,
    )
    habits = _derive_habit_profile(profile, include_decision_habit=reasoning_prompt)

    if casual_turn:
        lexicon_terms = [tok for tok in profile.signature_lexicon if tok and tok in prompt][:8]
    else:
        lexicon_terms = profile.signature_lexicon[:20]
    lexicon = ", ".join(lexicon_terms)
    claim_block = "\n".join(f"- {line}" for line in core_lines[:8])
    expression_block = "\n".join(f"- {line}" for line in expression_claims[:4])
    habits_block = "\n".join(f"- {line}" for line in habits[:4])
    style_block = "" if casual_turn else "\n".join(f"- {line}" for line in style_top[:8])
    model_block = ""
    if reasoning_prompt:
        model_scored: list[tuple[float, str]] = []
        for card in profile.model_cards[:10]:
            score = _claim_relevance(prompt, f"{card.name} {card.definition} {card.reframes}")
            model_scored.append((score, f"{card.name}: {card.definition}"))
        model_scored.sort(key=lambda x: x[0], reverse=True)
        model_top = [line for score, line in model_scored if score > 0][:4]
        if not model_top:
            model_top = [f"{card.name}: {card.definition}" for card in profile.model_cards[:2]]
        model_block = "\n".join(f"- {line}" for line in model_top)

    rule_block = ""
    if reasoning_prompt:
        rule_scored: list[tuple[float, str]] = []
        for rule in profile.decision_rules[:20]:
            merged = f"{rule.rule} {rule.condition} {rule.action} {rule.rationale}"
            score = _claim_relevance(prompt, merged)
            rule_scored.append((score, f"IF {rule.condition} THEN {rule.action} // {rule.rationale}"))
        rule_scored.sort(key=lambda x: x[0], reverse=True)
        rule_top = [line for score, line in rule_scored if score > 0][:4]
        if not rule_top:
            rule_top = [f"IF {rule.condition} THEN {rule.action} // {rule.rationale}" for rule in profile.decision_rules[:2]]
        rule_block = "\n".join(f"- {line}" for line in rule_top)

    prefer_short_reply = (not reasoning_prompt) and len(_norm_text(prompt)) <= 20
    dialogue_top = _select_dialogue_pairs(
        profile,
        prompt,
        limit=10 if prefer_short_reply else 14,
        prefer_short_reply=prefer_short_reply,
    )
    dialogue_block = "\n".join(
        f"- context: {pair.get('context', '')} => reply: {pair.get('reply', '')}"
        for pair in dialogue_top
    )
    reply_priors = _build_reply_priors(profile, per_bucket_limit=10)
    reply_prior_block = "\n".join(
        f"- {bucket}: {' | '.join(values)}"
        for bucket, values in reply_priors.items()
        if values
    )
    style_profile = _style_length_profile(profile)
    turn_policy = "casual_alignment_first" if casual_turn else ("reasoning_required" if reasoning_prompt else "general_chat")
    turn_hint = (
        "先接住对方这句话的意思和情绪，再决定是否补充说明；未被请求时不主动展开策略。"
        if casual_turn
        else "优先保证语义对齐，再自然呈现该人格的判断路径。"
    )
    return (
        "[STYLE_PROFILE]\n"
        f"{style_profile}\n"
        "[TURN_PROFILE]\n"
        f"- turn_mode: {turn_policy}\n"
        f"- turn_hint: {turn_hint}\n"
        "[PERSONA_CORE]\n"
        f"{claim_block}\n"
        "[HABIT_PROFILE]\n"
        f"{habits_block}\n"
        "[EXPRESSION_DNA]\n"
        f"{expression_block}\n"
        "[MODEL_CARDS]\n"
        f"{model_block}\n"
        "[DECISION_RULES]\n"
        f"{rule_block}\n"
        "[STYLE_MEMORY]\n"
        f"{style_block}\n"
        "[DIALOGUE_MEMORY]\n"
        f"{dialogue_block}\n"
        "[REPLY_PRIORS]\n"
        f"{reply_prior_block}\n"
        "[CATCHPHRASE_HINTS]\n"
        f"{lexicon}\n"
        "[LEXICON]\n"
        f"{lexicon}"
    )


def _apply_assertion(assertion_type: str, value: str | float, response: str, expected: str | None) -> tuple[bool, str]:
    text = response.lower()
    if assertion_type == "contains":
        ok = str(value).lower() in text
        return ok, f"missing contains('{value}')" if not ok else ""
    if assertion_type == "not_contains":
        ok = str(value).lower() not in text
        return ok, f"contains forbidden '{value}'" if not ok else ""
    if assertion_type == "regex":
        ok = re.search(str(value), response) is not None
        return ok, f"regex '{value}' not matched" if not ok else ""
    if assertion_type == "min_similarity":
        target = expected or ""
        sim = jaccard_similarity(response, target)
        ok = sim >= float(value)
        return ok, f"similarity {sim:.2f} < {value}" if not ok else ""
    return False, f"unknown assertion type: {assertion_type}"


def _run_case(case: EvalCase, response: str) -> EvalCaseResult:
    failures: list[str] = []
    passed_flags: list[bool] = []
    critical_flags: list[bool] = []

    for assertion in case.assertions:
        ok, err = _apply_assertion(assertion.type, assertion.value, response, case.expected_output)
        passed_flags.append(ok)
        if assertion.critical:
            critical_flags.append(ok)
        if not ok and err:
            failures.append(err)

    if not case.assertions and case.expected_output:
        sim = jaccard_similarity(response, case.expected_output)
        passed = sim >= 0.06
        if not passed:
            failures.append(f"similarity {sim:.2f} below default threshold")
        score = sim
        critical_passed = True
    else:
        passed = all(passed_flags) if passed_flags else True
        critical_passed = all(critical_flags) if critical_flags else True
        score = sum(1.0 for ok in passed_flags if ok) / max(1, len(passed_flags))

    return EvalCaseResult(
        case_id=case.id,
        passed=passed,
        critical_passed=critical_passed,
        score=round(score, 3),
        failures=failures,
        response=response,
    )


def run_eval_mode(
    benchmark: EvalBenchmark,
    profile: PersonaProfile | None,
    provider: ModelProvider,
    mode: str,
) -> EvalRunResult:
    results: list[EvalCaseResult] = []
    responses: list[str] = []

    for case in benchmark.cases:
        if mode == "baseline" or profile is None:
            response = "I do not have enough persona context; I can offer a generic answer with caveats."
        else:
            context = _persona_context(profile, case.prompt)
            response = provider.generate_response(case.prompt, context)
        responses.append(response)
        results.append(_run_case(case, response))

    pass_rate = sum(1 for r in results if r.passed) / max(1, len(results))
    critical_rate = sum(1 for r in results if r.critical_passed) / max(1, len(results))
    avg_score = sum(r.score for r in results) / max(1, len(results))
    avg_tokens = sum(len(tokenize(r)) for r in responses) / max(1, len(responses))
    avg_chars = sum(len(r) for r in responses) / max(1, len(responses))

    return EvalRunResult(
        mode=mode,
        pass_rate=round(pass_rate, 3),
        critical_pass_rate=round(critical_rate, 3),
        avg_score=round(avg_score, 3),
        avg_response_tokens=round(avg_tokens, 3),
        avg_response_chars=round(avg_chars, 3),
        case_results=results,
    )


def _known_answer_eval(profile: PersonaProfile, provider: ModelProvider) -> tuple[float, int]:
    anchors = profile.known_answer_anchors[:5]
    if not anchors:
        return 0.0, 0
    scores: list[float] = []
    for anchor in anchors:
        prompt = anchor.get("question", "").strip()
        expected = anchor.get("expected_direction", "").strip()
        if not prompt or not expected:
            continue
        context = _persona_context(profile, prompt)
        response = provider.generate_response(prompt, context)
        scores.append(jaccard_similarity(response, expected))
    if not scores:
        return 0.0, 0
    return round(sum(scores) / len(scores), 3), len(scores)


def compare_eval(
    benchmark: EvalBenchmark,
    profile: PersonaProfile,
    provider: ModelProvider,
    previous_stable_pass_rate: float | None = None,
) -> EvalComparison:
    with_skill = run_eval_mode(benchmark, profile, provider, mode="with_skill")
    baseline = run_eval_mode(benchmark, None, provider, mode="baseline")

    reasons: list[str] = []
    gate_passed = True

    if with_skill.pass_rate < baseline.pass_rate:
        gate_passed = False
        reasons.append(
            f"pass_rate regressed vs baseline: {with_skill.pass_rate} < {baseline.pass_rate}"
        )
    if (
        baseline.pass_rate > 0.05
        and with_skill.pass_rate == baseline.pass_rate
        and with_skill.avg_score <= baseline.avg_score
    ):
        gate_passed = False
        reasons.append(
            "avg_score did not improve when pass_rate tied baseline "
            f"({with_skill.avg_score} <= {baseline.avg_score})"
        )
    if with_skill.critical_pass_rate < 1.0:
        gate_passed = False
        reasons.append("critical assertions are not all passing")
    if (
        previous_stable_pass_rate is not None
        and previous_stable_pass_rate >= 0.1
        and with_skill.pass_rate + 0.01 < previous_stable_pass_rate
    ):
        gate_passed = False
        reasons.append(
            "pass_rate regressed vs previous stable "
            f"({with_skill.pass_rate} < {previous_stable_pass_rate})"
        )
    baseline_tokens = max(1.0, baseline.avg_response_tokens)
    token_growth = with_skill.avg_response_tokens / baseline_tokens
    if token_growth > 3.0:
        gate_passed = False
        reasons.append(
            "response token growth exceeded threshold "
            f"({token_growth:.2f}x > 3.0x); require manual confirmation"
        )

    known_answer_score, known_answer_count = _known_answer_eval(profile, provider)
    if known_answer_count >= 2 and known_answer_score < 0.08:
        gate_passed = False
        reasons.append(
            "known-answer anchor similarity too low "
            f"(avg={known_answer_score}, n={known_answer_count})"
        )
    elif known_answer_count >= 2:
        reasons.append(
            f"known-answer anchor similarity avg={known_answer_score} (n={known_answer_count})"
        )

    return EvalComparison(
        with_skill=with_skill,
        baseline=baseline,
        gate_passed=gate_passed,
        reasons=reasons,
    )
