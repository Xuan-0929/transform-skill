from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .evaluation import _persona_context
from .ingest import parse_input
from .models import PersonaProfile
from .providers import ModelProvider
from .utils import jaccard_similarity, stable_hash


def _valid_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if len(cleaned) < 2:
        return False
    if len(cleaned) > 40:
        return False
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return False
    if "[图片" in cleaned or "请使用最新版本手机QQ" in cleaned:
        return False
    if "可以发起屏幕控制请求" in cleaned:
        return False
    if any(ord(ch) < 32 for ch in cleaned):
        return False
    return True


def _style_markers(text: str) -> set[str]:
    marker_pool = ["？", "?", "！", "!", "哈哈", "笑死", "卧槽", "吗", "吧", "了", "呢", "捏"]
    return {m for m in marker_pool if m in text}


def _style_compat_score(response: str, reference: str) -> float:
    if not response or not reference:
        return 0.0
    rlen = len(response)
    tlen = len(reference)
    len_score = 1.0 - min(abs(rlen - tlen) / max(1, tlen), 1.0)
    rm = _style_markers(response)
    tm = _style_markers(reference)
    if not rm and not tm:
        marker_score = 1.0
    else:
        marker_score = len(rm & tm) / max(1, len(rm | tm))
    brevity_score = 1.0 if ((rlen <= 12) == (tlen <= 12)) else 0.4
    return round(0.5 * len_score + 0.35 * marker_score + 0.15 * brevity_score, 3)


def _build_context_reply_groups(
    holdout_path: Path,
    target_speaker: str,
    lookback: int = 8,
) -> dict[str, list[str]]:
    records = parse_input(holdout_path, "auto")
    groups: dict[str, list[str]] = defaultdict(list)
    for idx, record in enumerate(records):
        speaker = str(record.get("speaker") or "unknown").strip()
        if speaker != target_speaker:
            continue
        reply = str(record.get("content") or "").strip()
        if not _valid_text(reply):
            continue
        if len(reply) > 24:
            continue
        context = ""
        for j in range(idx - 1, max(-1, idx - lookback), -1):
            prev = records[j]
            prev_speaker = str(prev.get("speaker") or "unknown").strip()
            prev_text = str(prev.get("content") or "").strip()
            if prev_speaker == target_speaker:
                continue
            if _valid_text(prev_text):
                context = prev_text
                break
        if not context:
            continue
        if len(context) > 26:
            continue
        groups[context].append(reply)
    return groups


def evaluate_multi_ref_holdout(
    profile: PersonaProfile,
    provider: ModelProvider,
    holdout_path: Path,
    target_speaker: str,
    *,
    max_cases: int = 16,
    min_refs: int = 2,
    min_avg_similarity: float = 0.2,
    min_delta_vs_baseline: float = 0.12,
) -> dict:
    groups = _build_context_reply_groups(holdout_path, target_speaker=target_speaker)
    group_items: list[tuple[float, str, list[str]]] = []
    for context, replies in groups.items():
        deduped = []
        seen = set()
        for reply in replies:
            key = reply.strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        if len(deduped) >= min_refs:
            # one-to-many chat contexts are inherently noisy; keep all valid multi-answer groups,
            # then rank by response-set richness and deterministic hash.
            support = round(min(1.0, 0.35 + len(deduped) * 0.08), 4)
            group_items.append((support, context, deduped))
    group_items.sort(
        key=lambda x: (
            x[0],
            len(x[2]),
            stable_hash(x[1], prefix="ctx"),
        ),
        reverse=True,
    )
    selected = group_items[:max_cases]
    baseline_response = "I do not have enough persona context; I can offer a generic answer with caveats."

    examples = []
    agent_scores: list[float] = []
    strict_scores: list[float] = []
    baseline_scores: list[float] = []
    for _, context, replies in selected:
        holdout_reply = replies[0]
        acceptable_refs = replies[1:] if len(replies) > 1 else replies[:]
        if not acceptable_refs:
            continue
        persona_context = _persona_context(profile, context)
        response = provider.generate_response(context, persona_context).strip()
        multi_ref_sim = max(
            0.7 * jaccard_similarity(response, ref) + 0.3 * _style_compat_score(response, ref)
            for ref in acceptable_refs
        )
        strict_sim = jaccard_similarity(response, holdout_reply)
        base_sim = max(
            0.7 * jaccard_similarity(baseline_response, ref) + 0.3 * _style_compat_score(baseline_response, ref)
            for ref in acceptable_refs
        )
        agent_scores.append(multi_ref_sim)
        strict_scores.append(strict_sim)
        baseline_scores.append(base_sim)
        examples.append(
            {
                "prompt": context,
                "holdout_reply": holdout_reply,
                "acceptable_refs": acceptable_refs[:6],
                "resp": response,
                "multi_ref_sim": round(multi_ref_sim, 3),
                "strict_sim": round(strict_sim, 3),
            }
        )

    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 3)

    agent_avg = _avg(agent_scores)
    baseline_avg = _avg(baseline_scores)
    strict_avg = _avg(strict_scores)
    delta = round(agent_avg - baseline_avg, 3)
    pass_rule = (
        f"agent_avg_similarity>={min_avg_similarity:.2f} and "
        f"delta_vs_baseline>={min_delta_vs_baseline:.2f}"
    )
    passed = (
        len(examples) >= max(3, min(6, max_cases))
        and agent_avg >= min_avg_similarity
        and delta >= min_delta_vs_baseline
    )
    return {
        "selection": "multi-answer-context-holdout-from-user-corpus",
        "test_cases": len(examples),
        "metric": "max composite similarity (0.7 semantic + 0.3 style) to acceptable reply set per context",
        "agent_avg_similarity": agent_avg,
        "strict_avg_similarity_to_exact_holdout": strict_avg,
        "baseline_avg_similarity": baseline_avg,
        "delta_vs_baseline": delta,
        "pass_rule": pass_rule,
        "passed": passed,
        "examples": examples,
    }
