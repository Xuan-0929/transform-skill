from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re

from .evaluation import _persona_context
from .ingest import parse_input, parse_timestamp
from .models import PersonaProfile
from .providers import ModelProvider
from .utils import jaccard_similarity, stable_hash

MAX_CONTEXT_GAP_SECONDS = 3 * 60 * 60


def _record_source(record: dict) -> str:
    return str(record.get("_source_path") or record.get("source") or "")


def _same_source(records: list[dict], left: int, right: int) -> bool:
    if left < 0 or right < 0 or left >= len(records) or right >= len(records):
        return False
    left_source = _record_source(records[left])
    right_source = _record_source(records[right])
    return left_source == right_source


def _speaker_name_matches(text: str, speaker: str) -> bool:
    cleaned = (text or "").strip()
    target = (speaker or "").strip()
    if not cleaned or not target:
        return False
    return f"@{target}" in cleaned or target in cleaned


def _char_set(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", text or ""))


def _char_overlap(a: str, b: str) -> float:
    left = _char_set(a)
    right = _char_set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def _context_reply_relevance(context: str, reply: str, *, target_speaker: str, distance: int) -> float:
    ctx = (context or "").strip()
    rep = (reply or "").strip()
    if not ctx or not rep:
        return 0.0
    score = 0.45 * jaccard_similarity(ctx, rep) + 0.35 * _char_overlap(ctx, rep)
    if ctx == rep:
        score += 0.45
    if ctx in rep or rep in ctx:
        score += 0.2
    if _speaker_name_matches(ctx, target_speaker):
        score += 0.14
    if any(h in ctx for h in ("谁", "哪个", "哪位", "什么人")) and len(rep) <= 16:
        score += 0.24
    if any(h in ctx for h in ("为什么", "为何", "怎么", "咋")) and any(
        h in rep for h in ("因为", "可能", "应该", "紧张", "不知道", "难说", "是")
    ):
        score += 0.16
    if ctx.endswith(("吗", "嘛", "么", "？", "?")) and len(rep) <= 24:
        score += 0.12
    score += max(0.0, 0.06 - distance * 0.01)
    return score


def _choose_context_candidate(
    candidates: list[tuple[int, dict]],
    reply: str,
    *,
    target_speaker: str,
) -> tuple[int, dict] | None:
    if not candidates:
        return None
    non_target_speakers = {
        str(record.get("speaker") or "unknown").strip()
        for _, record in candidates
        if str(record.get("speaker") or "unknown").strip() != target_speaker
    }
    scored: list[tuple[float, int, dict]] = []
    for distance, (idx, record) in enumerate(candidates):
        text = str(record.get("content") or "").strip()
        score = _context_reply_relevance(
            text,
            reply,
            target_speaker=target_speaker,
            distance=distance,
        )
        scored.append((score, idx, record))
    scored.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    best_score, best_idx, best_record = scored[0]
    closest_idx, closest_record = candidates[0]
    closest_score = _context_reply_relevance(
        str(closest_record.get("content") or ""),
        reply,
        target_speaker=target_speaker,
        distance=0,
    )
    if len(non_target_speakers) <= 1:
        # In private or single-counterpart blocks, keep the natural adjacent turn unless
        # an older line is clearly a better thread anchor.
        if best_idx != closest_idx and best_score >= closest_score + 0.12:
            return best_idx, best_record
        return closest_idx, closest_record
    if best_score < 0.13:
        return None
    return best_idx, best_record


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
    marker_pool = [
        "？",
        "?",
        "！",
        "!",
        "哈哈",
        "笑死",
        "卧槽",
        "完了",
        "离谱",
        "逆天",
        "捏",
        "呜呜",
        "sb",
        "傻逼",
        "dnm",
        "csb",
        "牛逼",
        "nb",
        "无敌",
    ]
    return {m for m in marker_pool if m in text}


def _style_registers(text: str) -> set[str]:
    compact = _norm_text(text)
    registers: set[str] = set()
    if re.search(r"sb|傻逼|几把|dnm|csb", compact):
        registers.add("retort_profane")
    if any(h in compact for h in ("牛逼", "nb", "厉害", "无敌", "牛的")):
        registers.add("praise")
    if any(h in compact for h in ("哈哈", "笑死", "笑")):
        registers.add("laugh")
    if any(h in compact for h in ("卧槽", "我去", "完了", "离谱", "逆天")):
        registers.add("strong_reaction")
    if any(h in compact for h in ("没事", "别慌", "稳", "正常")):
        registers.add("comfort")
    if any(h in compact for h in ("不知道", "难说", "不好说", "看情况")):
        registers.add("uncertain")
    if any(h in compact for h in ("不是", "没有", "不行", "别", "不对")):
        registers.add("negative")
    if re.search(r"[a-z]{2,}", compact):
        registers.add("latin_slang")
    if re.search(r"[\U00010000-\U0010ffff]", text):
        registers.add("emoji")
    if text.strip().endswith(("?", "？")):
        registers.add("question_shape")
    if text.strip().endswith(("!", "！")):
        registers.add("exclaim_shape")
    return registers


def _terminal_particle(text: str) -> str:
    compact = _norm_text(text)
    if not compact:
        return ""
    for size in (2, 1):
        tail = compact[-size:]
        if tail in {"吧", "啊", "呢", "吗", "了", "呗", "哈", "哦", "呀", "嘛", "捏", "的", "了吧", "了啊"}:
            return tail
    return ""


def _shape_score(response: str, reference: str) -> float:
    r_norm = _norm_text(response)
    t_norm = _norm_text(reference)
    if not r_norm or not t_norm:
        return 0.0
    r_len = len(r_norm)
    t_len = len(t_norm)
    len_score = 1.0 - min(abs(r_len - t_len) / max(1, max(r_len, t_len)), 1.0)
    short_band = 1.0 if ((r_len <= 6) == (t_len <= 6)) else 0.35
    sentence_band = 1.0 if (len(re.split(r"[。！？!?]", response)) == len(re.split(r"[。！？!?]", reference))) else 0.65
    return max(0.0, min(1.0, 0.5 * len_score + 0.3 * short_band + 0.2 * sentence_band))


def _register_score(response: str, reference: str) -> float:
    rm = _style_registers(response)
    tm = _style_registers(reference)
    if not rm and not tm:
        return 0.72
    if not rm or not tm:
        return 0.18
    score = len(rm & tm) / max(1, len(rm | tm))
    # Profanity/latin/praise are high-salience register switches in casual chat.
    high_salience = {"retort_profane", "latin_slang", "praise"}
    if (rm & high_salience) != (tm & high_salience):
        score *= 0.45
    return max(0.0, min(1.0, score))


def _single_speaking_style_score(response: str, reference: str) -> float:
    if not response or not reference:
        return 0.0
    shape = _shape_score(response, reference)
    markers = _style_markers(response)
    target_markers = _style_markers(reference)
    if not markers and not target_markers:
        marker_score = 0.68
    elif markers and target_markers:
        marker_score = len(markers & target_markers) / max(1, len(markers | target_markers))
    else:
        marker_score = 0.15
    register = _register_score(response, reference)
    intent = _intent_compat_score(response, [reference])
    particle = 1.0 if _terminal_particle(response) == _terminal_particle(reference) else 0.35
    score = 0.28 * shape + 0.22 * marker_score + 0.28 * register + 0.16 * intent + 0.06 * particle
    # Penalize performed catchphrase collage when the reference is compact.
    if len(_norm_text(reference)) <= 8 and len(_style_markers(response)) >= 3:
        score *= 0.78
    if len(_norm_text(reference)) <= 4 and len(_norm_text(response)) > 8:
        score *= 0.86
    return round(max(0.0, min(1.0, score)), 3)


def _speaking_style_score(response: str, references: list[str]) -> float:
    if not response or not references:
        return 0.0
    return max(_single_speaking_style_score(response, ref) for ref in references if ref.strip())


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


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "").strip().lower()


def _intent_bucket(text: str) -> str:
    cleaned = _norm_text(text)
    if not cleaned:
        return "other"
    if re.search(r"sb|傻逼|几把|dnm|csb", cleaned):
        return "retort"
    if any(h in cleaned for h in ("牛逼", "nb", "厉害", "无敌", "牛的")):
        return "praise"
    if any(h in cleaned for h in ("没事", "别慌", "慢慢来", "稳", "可以的", "正常", "先稳住", "放心")):
        return "comfort"
    if any(h in cleaned for h in ("不好说", "难说", "不知道", "看情况", "不确定", "大概")):
        return "uncertain"
    if any(h in cleaned for h in ("不是", "没有", "没呢", "不行", "不对", "算了", "不太", "没来", "别")):
        return "negative"
    if cleaned.endswith("没") or cleaned.endswith("没有"):
        return "negative"
    if any(h in cleaned for h in ("是的", "对的", "可以", "好的", "好滴", "行", "行吧", "ok", "对", "嗯", "确实", "还真是", "是啊", "对啊")):
        return "affirmative"
    if any(h in cleaned for h in ("笑", "哈哈", "笑死", "搞笑", "绷")):
        return "reaction_laugh"
    if any(h in cleaned for h in ("完了", "卧槽", "我去", "可恶", "离谱", "逆天", "炸", "瓦", "崩")):
        return "reaction_panic"
    return "other"


def _intent_compat_score(response: str, references: list[str]) -> float:
    if not response or not references:
        return 0.0
    rb = _intent_bucket(response)
    ref_buckets_all = {_intent_bucket(ref) for ref in references if ref.strip()}
    if not ref_buckets_all:
        return 0.0
    ref_buckets = {b for b in ref_buckets_all if b != "other"}
    if not ref_buckets:
        # No clear intent signal in references: keep this metric neutral instead of rewarding generic replies.
        return 0.5
    if rb == "other":
        return 0.2
    if rb in ref_buckets:
        return 1.0
    if rb.startswith("reaction_") and any(b.startswith("reaction_") for b in ref_buckets):
        return 0.7
    if rb == "retort" and "negative" in ref_buckets:
        return 0.6
    if rb == "praise" and "affirmative" in ref_buckets:
        return 0.65
    return 0.0


def _persona_alignment_brief(profile: PersonaProfile) -> str:
    lines: list[str] = []
    labels = {
        "beliefs_and_values": "价值观",
        "mental_models": "认知方式",
        "decision_heuristics": "决策习惯",
        "anti_patterns_and_limits": "边界",
        "expression_dna": "表达方式",
    }
    for section in (
        "beliefs_and_values",
        "mental_models",
        "decision_heuristics",
        "anti_patterns_and_limits",
        "expression_dna",
    ):
        for claim in profile.sections.get(section, [])[:2]:
            text = str(getattr(claim, "claim", "") or "").strip()
            if text:
                lines.append(f"- {labels.get(section, section)}: {text}")
    if profile.signature_lexicon:
        lines.append("- 口吻词库（只能少量使用）: " + " / ".join(profile.signature_lexicon[:12]))
    metrics = profile.expression_metrics or {}
    if metrics:
        lines.append(
            "- 表达统计: "
            f"median_chars_per_turn={metrics.get('median_chars_per_turn', 0)}, "
            f"short_reply_ratio={metrics.get('short_reply_ratio', 0)}, "
            f"directness_score={metrics.get('directness_score', 0)}"
        )
    return "\n".join(lines[:12])


def _parse_alignment_score(raw: str) -> tuple[float, str]:
    try:
        payload = json.loads(raw)
    except Exception:
        return 0.0, "judge returned invalid JSON"
    if not isinstance(payload, dict):
        return 0.0, "judge returned non-object JSON"
    try:
        score = float(payload.get("score", 0.0))
    except Exception:
        score = 0.0
    rationale = str(payload.get("rationale") or "")[:180]
    return max(0.0, min(1.0, score)), rationale


def _judge_persona_alignment(
    provider: ModelProvider,
    profile: PersonaProfile,
    *,
    target_speaker: str,
    prompt: str,
    recent_window: list[str],
    response: str,
) -> tuple[float, str]:
    recent_block = "\n".join(f"- {line}" for line in recent_window[-20:])
    judge_prompt = (
        "You are evaluating persona distillation quality, not exact wording overlap.\n"
        "Return JSON only: {\"score\": 0.0-1.0, \"rationale\": \"short Chinese reason\"}.\n"
        "Score the GENERATED_REPLY on these dimensions:\n"
        "1) value/stance alignment with PERSONA_BRIEF;\n"
        "2) dialogue act fit for the live RECENT_CONTEXT;\n"
        "3) natural expression style without overusing catchphrases;\n"
        "4) target speaker continuity in a group chat;\n"
        "5) no generic assistant/report tone.\n"
        "Do not penalize compact replies solely for being low-information when PERSONA_BRIEF shows a short-reply baseline; judge whether the compact dialogue act is natural for this speaker and context.\n"
        "Do not penalize laugh-only or reaction-only replies solely for lacking new facts when the speaker's evidence shows laugh bursts and the recent prompt is a boast, meme, tease, or group-chat reaction; judge whether that reaction is the natural next move.\n"
        "Do not reward copying. Reward persona mechanism and conversational plausibility.\n\n"
        f"[TARGET_SPEAKER]\n{target_speaker}\n\n"
        f"[PERSONA_BRIEF]\n{_persona_alignment_brief(profile)}\n\n"
        f"[RECENT_CONTEXT]\n{recent_block}\n\n"
        f"[LATEST_PROMPT]\n{prompt}\n\n"
        f"[GENERATED_REPLY]\n{response}\n"
    )
    try:
        raw = provider.run_agent(judge_prompt)
    except Exception as exc:
        return 0.0, f"judge failed: {exc}"
    return _parse_alignment_score(raw)


def _target_stance_hints(recent_window: list[str], target_speaker: str, limit: int = 3) -> list[str]:
    hints: list[str] = []
    stance_markers = ("不是", "是", "问题是", "我觉得", "我感觉", "没逼", "正常", "不行", "可以")
    prefix = f"{target_speaker}:"
    for line in recent_window:
        cleaned = line.strip()
        if not cleaned.startswith(prefix):
            continue
        text = cleaned.split(":", 1)[1].strip()
        if not text:
            continue
        if any(marker in text for marker in stance_markers):
            hints.append(text)
    return hints[-limit:]


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
        if idx <= 0:
            continue
        if not _same_source(records, idx, idx - 1):
            continue
        prev_speaker = str(records[idx - 1].get("speaker") or "unknown").strip()
        if prev_speaker == target_speaker:
            continue
        context = ""
        context_record: dict | None = None
        context_idx = -1
        candidates: list[tuple[int, dict]] = []
        for j in range(idx - 1, max(-1, idx - lookback), -1):
            if not _same_source(records, idx, j):
                break
            prev = records[j]
            prev_speaker = str(prev.get("speaker") or "unknown").strip()
            prev_text = str(prev.get("content") or "").strip()
            if prev_speaker == target_speaker:
                break
            if _valid_text(prev_text):
                candidates.append((j, prev))
        chosen = _choose_context_candidate(candidates, reply, target_speaker=target_speaker)
        if chosen is not None:
            context_idx, context_record = chosen
            context = str(context_record.get("content") or "").strip()
        if not context:
            continue
        if context_record is not None:
            reply_ts = parse_timestamp(record.get("timestamp"))
            context_ts = parse_timestamp(context_record.get("timestamp"))
            if reply_ts and context_ts:
                gap = abs((reply_ts - context_ts).total_seconds())
                if gap > MAX_CONTEXT_GAP_SECONDS:
                    continue
        if len(context) > 26:
            continue
        groups[context].append(reply)
    return groups


def _build_recent_context_windows(
    holdout_path: Path,
    target_speaker: str,
    lookback: int = 8,
    history_turns: int = 4,
) -> dict[str, list[str]]:
    records = parse_input(holdout_path, "auto")
    windows: dict[str, list[str]] = {}
    for idx, record in enumerate(records):
        speaker = str(record.get("speaker") or "unknown").strip()
        if speaker != target_speaker:
            continue
        reply = str(record.get("content") or "").strip()
        if not _valid_text(reply):
            continue
        if len(reply) > 24:
            continue
        if idx <= 0:
            continue
        if not _same_source(records, idx, idx - 1):
            continue
        prev_speaker = str(records[idx - 1].get("speaker") or "unknown").strip()
        if prev_speaker == target_speaker:
            continue

        context = ""
        context_record: dict | None = None
        context_idx = -1
        candidates: list[tuple[int, dict]] = []
        for j in range(idx - 1, max(-1, idx - lookback), -1):
            if not _same_source(records, idx, j):
                break
            prev = records[j]
            prev_speaker = str(prev.get("speaker") or "unknown").strip()
            prev_text = str(prev.get("content") or "").strip()
            if prev_speaker == target_speaker:
                break
            if _valid_text(prev_text):
                candidates.append((j, prev))
        chosen = _choose_context_candidate(candidates, reply, target_speaker=target_speaker)
        if chosen is not None:
            context_idx, context_record = chosen
            context = str(context_record.get("content") or "").strip()
        if not context or context_idx < 0:
            continue
        if context_record is not None:
            reply_ts = parse_timestamp(record.get("timestamp"))
            context_ts = parse_timestamp(context_record.get("timestamp"))
            if reply_ts and context_ts:
                gap = abs((reply_ts - context_ts).total_seconds())
                if gap > MAX_CONTEXT_GAP_SECONDS:
                    continue
        if len(context) > 26:
            continue

        start = max(0, context_idx - max(1, history_turns) + 1)
        rendered: list[str] = []
        for k in range(start, context_idx + 1):
            if not _same_source(records, context_idx, k):
                continue
            row = records[k]
            row_speaker = str(row.get("speaker") or "unknown").strip() or "unknown"
            row_text = str(row.get("content") or "").strip()
            if not _valid_text(row_text):
                continue
            if len(row_text) > 80:
                row_text = row_text[:80] + "..."
            rendered.append(f"{row_speaker}: {row_text}")
        if not rendered:
            rendered = [f"other: {context}"]

        previous = windows.get(context, [])
        if len(rendered) >= len(previous):
            windows[context] = rendered
    return windows


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
    context_turns: int = 20,
    judge_persona_alignment: bool = False,
    min_persona_alignment: float = 0.0,
) -> dict:
    groups = _build_context_reply_groups(holdout_path, target_speaker=target_speaker)
    context_windows = _build_recent_context_windows(
        holdout_path,
        target_speaker=target_speaker,
        lookback=8,
        history_turns=context_turns,
    )
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
    agent_intent_scores: list[float] = []
    baseline_intent_scores: list[float] = []
    persona_alignment_scores: list[float] = []
    speaking_style_scores: list[float] = []
    for _, context, replies in selected:
        holdout_reply = replies[0]
        acceptable_refs = replies[1:] if len(replies) > 1 else replies[:]
        if not acceptable_refs:
            continue
        persona_context = _persona_context(profile, context)
        recent_window = context_windows.get(context, [])
        if recent_window:
            window_block = "\n".join(f"- {line}" for line in recent_window[-max(1, context_turns):])
            persona_context = (
                f"{persona_context}\n"
                "[EVAL_TARGET_SPEAKER]\n"
                f"{target_speaker}\n"
                "[EVAL_RECENT_CONTEXT]\n"
                "- 仅作本轮语境参考，不覆盖 PERSONA_CORE。\n"
                f"{window_block}"
            )
            stance_hints = _target_stance_hints(recent_window, target_speaker=target_speaker)
            if stance_hints:
                persona_context = (
                    f"{persona_context}\n"
                    "[EVAL_TARGET_STANCE]\n"
                    + "\n".join(f"- {hint}" for hint in stance_hints)
                )
        if judge_persona_alignment:
            persona_context = (
                f"{persona_context}\n"
                "[PERSONA_ALIGNMENT_MODE]\n"
                "- 优先评估人格机制、价值立场和上下文连续性；不要为了贴原句而只输出低信息短答。"
            )
        response = provider.generate_response(context, persona_context).strip()
        persona_alignment = None
        persona_alignment_rationale = ""
        if judge_persona_alignment:
            persona_alignment, persona_alignment_rationale = _judge_persona_alignment(
                provider,
                profile,
                target_speaker=target_speaker,
                prompt=context,
                recent_window=recent_window,
                response=response,
            )
            persona_alignment_scores.append(persona_alignment)
        semantic_style_sim = max(
            0.8 * jaccard_similarity(response, ref) + 0.2 * _style_compat_score(response, ref)
            for ref in acceptable_refs
        )
        speaking_style = _speaking_style_score(response, acceptable_refs)
        intent_score = _intent_compat_score(response, acceptable_refs)
        multi_ref_sim = 0.78 * semantic_style_sim + 0.22 * intent_score
        strict_sim = jaccard_similarity(response, holdout_reply)
        base_semantic_style = max(
            0.8 * jaccard_similarity(baseline_response, ref) + 0.2 * _style_compat_score(baseline_response, ref)
            for ref in acceptable_refs
        )
        base_intent = _intent_compat_score(baseline_response, acceptable_refs)
        base_sim = 0.78 * base_semantic_style + 0.22 * base_intent
        agent_scores.append(multi_ref_sim)
        strict_scores.append(strict_sim)
        baseline_scores.append(base_sim)
        agent_intent_scores.append(intent_score)
        baseline_intent_scores.append(base_intent)
        speaking_style_scores.append(speaking_style)
        example = {
            "prompt": context,
            "holdout_reply": holdout_reply,
            "acceptable_refs": acceptable_refs[:6],
            "resp": response,
            "multi_ref_sim": round(multi_ref_sim, 3),
            "speaking_style_sim": round(speaking_style, 3),
            "strict_sim": round(strict_sim, 3),
            "intent_match": round(intent_score, 3),
        }
        if judge_persona_alignment:
            example["persona_alignment"] = round(float(persona_alignment or 0.0), 3)
            example["persona_alignment_rationale"] = persona_alignment_rationale
        examples.append(example)

    def _avg(values: list[float]) -> float:
        if not values:
            return 0.0
        return round(sum(values) / len(values), 3)

    agent_avg = _avg(agent_scores)
    baseline_avg = _avg(baseline_scores)
    strict_avg = _avg(strict_scores)
    intent_avg = _avg(agent_intent_scores)
    baseline_intent_avg = _avg(baseline_intent_scores)
    speaking_style_avg = _avg(speaking_style_scores)
    persona_alignment_avg = _avg(persona_alignment_scores) if judge_persona_alignment else None
    delta = round(agent_avg - baseline_avg, 3)
    intent_delta = round(intent_avg - baseline_intent_avg, 3)
    pass_rule = (
        f"agent_avg_similarity>={min_avg_similarity:.2f} and "
        f"delta_vs_baseline>={min_delta_vs_baseline:.2f}"
    )
    if judge_persona_alignment:
        pass_rule += f" and persona_alignment_avg>={min_persona_alignment:.2f}"
    passed = (
        len(examples) >= max(3, min(6, max_cases))
        and agent_avg >= min_avg_similarity
        and delta >= min_delta_vs_baseline
        and (not judge_persona_alignment or (persona_alignment_avg or 0.0) >= min_persona_alignment)
    )
    report = {
        "selection": "multi-answer-context-holdout-from-user-corpus",
        "test_cases": len(examples),
        "metric": "max composite similarity (0.78 semantic-style + 0.22 intent) to acceptable reply set per context",
        "context_turns": context_turns,
        "persona_alignment_metric": "LLM judge: value/stance + dialogue act + style naturalness + context continuity" if judge_persona_alignment else None,
        "agent_avg_similarity": agent_avg,
        "speaking_style_similarity": speaking_style_avg,
        "strict_avg_similarity_to_exact_holdout": strict_avg,
        "baseline_avg_similarity": baseline_avg,
        "delta_vs_baseline": delta,
        "agent_intent_match_rate": intent_avg,
        "baseline_intent_match_rate": baseline_intent_avg,
        "delta_intent_vs_baseline": intent_delta,
        "pass_rule": pass_rule,
        "passed": passed,
        "examples": examples,
    }
    if judge_persona_alignment:
        report["persona_alignment_avg"] = persona_alignment_avg or 0.0
    return report
