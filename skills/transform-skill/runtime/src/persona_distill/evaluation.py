from __future__ import annotations

import json
import re
from pathlib import Path

from .models import EvalBenchmark, EvalCase, EvalCaseResult, EvalComparison, EvalRunResult, PersonaProfile
from .providers import ModelProvider
from .utils import jaccard_similarity, tokenize


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


def _persona_context(profile: PersonaProfile, prompt: str) -> str:
    scored: list[tuple[float, str]] = []
    for claims in profile.sections.values():
        for claim in claims:
            score = _claim_relevance(prompt, claim.claim)
            scored.append((score, claim.claim))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [claim for score, claim in scored[:5] if score > 0]
    if not top:
        top = [claim.claim for claim in profile.sections.get("decision_heuristics", [])[:3]]
    style_scored: list[tuple[float, str]] = []
    for text in profile.style_memory:
        style_scored.append((_claim_relevance(prompt, text), text))
    style_scored.sort(key=lambda x: x[0], reverse=True)
    style_top = [text for score, text in style_scored[:8] if score > 0]
    if not style_top:
        style_top = profile.style_memory[:8]

    lexicon = ", ".join(profile.signature_lexicon[:20])
    claim_block = "\n".join(f"- {line}" for line in top[:5])
    style_block = "\n".join(f"- {line}" for line in style_top[:8])
    model_block = "\n".join(
        f"- {card.name}: {card.definition}"
        for card in profile.model_cards[:8]
    )
    rule_block = "\n".join(
        f"- IF {rule.condition} THEN {rule.action} // {rule.rationale}"
        for rule in profile.decision_rules[:12]
    )
    dialogue_scored: list[tuple[float, dict[str, str]]] = []
    for pair in profile.context_reply_memory:
        ctx = pair.get("context", "")
        rep = pair.get("reply", "")
        if not ctx or not rep:
            continue
        score = _claim_relevance(prompt, ctx)
        dialogue_scored.append((score, {"context": ctx, "reply": rep}))
    dialogue_scored.sort(key=lambda x: x[0], reverse=True)
    dialogue_top = [pair for score, pair in dialogue_scored[:220] if score > 0]
    if not dialogue_top:
        dialogue_top = profile.context_reply_memory[:220]
    dialogue_block = "\n".join(
        f"- context: {pair.get('context', '')} => reply: {pair.get('reply', '')}"
        for pair in dialogue_top
    )
    return (
        "[CLAIMS]\n"
        f"{claim_block}\n"
        "[MODEL_CARDS]\n"
        f"{model_block}\n"
        "[DECISION_RULES]\n"
        f"{rule_block}\n"
        "[STYLE_MEMORY]\n"
        f"{style_block}\n"
        "[DIALOGUE_MEMORY]\n"
        f"{dialogue_block}\n"
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
