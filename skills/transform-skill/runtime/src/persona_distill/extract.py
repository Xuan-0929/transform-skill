from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from .models import (
    CORE_SECTIONS,
    ContradictionItem,
    CorrectionNote,
    CorpusItem,
    DecisionRule,
    EvidenceClaim,
    EvidenceSpan,
    ModelCard,
    PersonaProfile,
)
from .providers import ModelProvider
from .utils import has_negation, jaccard_similarity, safe_excerpt, stable_hash, tokenize, utc_now

BELIEF_PATTERNS = ["我觉得", "我认为", "我感觉", "我只要", "我更", "我喜欢", "我讨厌", "无所谓"]
DECISION_PATTERNS = ["先", "再", "然后", "如果", "就", "优先", "回头", "不如"]
MODEL_PATTERNS = ["因为", "所以", "相当于", "等于", "本质", "逻辑", "意味着", "说明", "归根结底"]
ANTI_PATTERNS = ["不", "别", "不能", "不要", "没必要", "不想", "不会"]
STYLE_MARKERS = ["哈哈", "笑死", "绷", "离谱", "有点", "真", "太", "？", "！", "呜呜", "捏", "牛逼", "nb", "sb"]
DISTINCTIVE_SHORT_UTTERANCES = {
    "牛逼",
    "牛",
    "nb",
    "无敌",
    "无敌了",
    "你sb吧",
    "这sb",
    "遇到sb了",
    "dnmd",
    "dnmdcsb",
    "笑死",
    "笑死我了",
}
HEDGE_WORDS = ["可能", "大概", "也许", "差不多", "应该"]
NOISE_KEYWORDS = [
    "复制打开抖音",
    "http://",
    "https://",
    "群通知:",
    "合并转发",
    "聊天记录",
    "动画表情",
]
STOPWORDS = {
    "这个",
    "那个",
    "就是",
    "然后",
    "我们",
    "你们",
    "他们",
    "一个",
    "不是",
    "真的",
    "感觉",
    "因为",
    "所以",
    "title",
    "color",
    "size",
    "summary",
    "source",
    "item",
    "msg",
    "reply",
    "hr",
}

LOW_SIGNAL_LEXICON = {
    "是的",
    "可以",
    "可以的",
    "没有",
    "不知道",
    "等下",
    "看看",
    "差不多",
    "应该不是",
    "这个人",
    "然后",
    "就是",
}

LOW_SIGNAL_CONTEXTS = {
    "这个",
    "那个",
    "这个呢",
    "那个呢",
    "是的",
    "好的",
    "好滴",
    "嗯",
    "哦",
    "啊",
    "哈",
    "哈哈",
    "没有",
    "哈哈没有",
    "有吗",
    "ok",
    "+1",
    "111",
}

NON_PERSONA_MEME_HINTS = {
    "疯狂星期四",
    "v我50",
    "v我 50",
    "kfc",
    "复制这条",
    "今日疯四",
    "转发抽奖",
    "仅聊天",
    "互关",
}

MAX_CONTEXT_GAP_SECONDS = 3 * 60 * 60

LOW_SIGNAL_REPLY_CANONICAL = {
    "是的",
    "好的",
    "好滴",
    "可以",
    "嗯",
    "哦",
    "哈",
    "哈哈",
    "ok",
    "111",
}

MODEL_THEME_KEYWORDS: dict[str, list[str]] = {
    "risk_control": ["风险", "不该", "别", "不要", "不能", "稳", "保", "收手", "谨慎", "输", "高"],
    "evidence_boundary": ["证据", "确定", "不确定", "判断", "信息", "依据", "真假", "怀疑"],
    "sequential_execution": ["先", "再", "然后", "步骤", "顺序", "反应", "拆", "流程"],
    "causal_accounting": ["因为", "所以", "本质", "逻辑", "代价", "成本", "收益", "划算"],
    "social_calibration": ["对面", "别人", "团队", "关系", "交流", "情绪价值", "同伴", "对线"],
    "resource_leverage": ["效率", "高效", "时间", "投入", "省", "快速", "马上", "直接"],
}

THEME_MODEL_NAME = {
    "risk_control": "胜率-风险闸门模型",
    "evidence_boundary": "证据强度定标模型",
    "sequential_execution": "先感知后动作模型",
    "causal_accounting": "因果-成本核算模型",
    "social_calibration": "关系-场域校准模型",
    "resource_leverage": "低成本杠杆模型",
    "mixed": "经验压缩迁移模型",
}

THEME_MODEL_DEFINITION = {
    "risk_control": "先评估风险暴露与胜率，再决定是否推进；胜率不明时优先收手保节奏。",
    "evidence_boundary": "把结论强度绑定到证据强度；证据不足时明确降级判断并补充信息。",
    "sequential_execution": "把任务拆成可执行顺序链条，先感知关键变量，再触发动作。",
    "causal_accounting": "先识别因果约束与成本差异，再选择代价更低、可持续的路径。",
    "social_calibration": "先判断关系场域和对手强度，再决定语气、动作和推进力度。",
    "resource_leverage": "优先选择低投入高反馈动作，小步验证后再扩大投入。",
    "mixed": "先给可执行立场，再根据反馈迭代，不在信息不足时硬性定论。",
}


@dataclass
class Candidate:
    section: str
    claim: str
    item: CorpusItem
    start: int
    end: int


def _split_sentences(text: str) -> list[str]:
    raw = re.split(r"(?<=[.!?。！？])\s+|\n+", text)
    return [s.strip() for s in raw if s.strip()]


def _is_valid_utterance(text: str) -> bool:
    cleaned = text.strip()
    if len(cleaned) < 2 or len(cleaned) > 60:
        return False
    if re.fullmatch(r"[?？!！。，、~\s]+", cleaned):
        return False
    if cleaned.lower().startswith("http"):
        return False
    if "[卡片消息" in cleaned:
        return False
    if any(k in cleaned for k in NOISE_KEYWORDS):
        return False
    if re.match(r"^\d+\.", cleaned):
        return False
    if len(re.findall(r"\d+\.", cleaned)) >= 2:
        return False
    if cleaned.count("，") >= 5 and "？" not in cleaned and "?" not in cleaned:
        return False
    if cleaned.startswith("[") and cleaned.endswith("]"):
        return False
    return True


def _find_sections(sentence: str) -> list[str]:
    sections: list[str] = []
    if any(p in sentence for p in BELIEF_PATTERNS):
        sections.append("beliefs_and_values")
    if ("先" in sentence and any(p in sentence for p in ["再", "然后", "就"])) or (
        "如果" in sentence and "就" in sentence
    ) or any(p in sentence for p in ["优先", "不如"]):
        sections.append("decision_heuristics")
    if any(p in sentence for p in MODEL_PATTERNS):
        sections.append("mental_models")
    if any(p in sentence for p in ANTI_PATTERNS) and len(sentence) >= 4:
        sections.append("anti_patterns_and_limits")
    return sorted(set(sections))


def _extract_candidates(items: list[CorpusItem]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for item in items:
        for sentence in _split_sentences(item.content):
            if not _is_valid_utterance(sentence):
                continue
            sections = _find_sections(sentence)
            if not sections:
                continue
            start = max(0, item.content.find(sentence))
            end = start + len(sentence)
            for section in sections:
                candidates.append(Candidate(section=section, claim=sentence, item=item, start=start, end=end))
    return candidates


def _build_signature_lexicon(items: list[CorpusItem], limit: int = 30) -> list[str]:
    counter: Counter[str] = Counter()
    for item in items:
        if not _is_valid_utterance(item.content):
            continue
        compact = re.sub(r"\s+", "", item.content.lower())
        for tok in tokenize(item.content):
            if len(tok) < 2:
                continue
            if tok in STOPWORDS:
                continue
            if tok in LOW_SIGNAL_LEXICON:
                continue
            if tok.isdigit():
                continue
            if len(tok) > 10:
                continue
            if not re.search(r"[\u4e00-\u9fff]", tok):
                continue
            counter[tok] += 1
            if tok.lower() in DISTINCTIVE_SHORT_UTTERANCES or tok.lower() in compact and any(
                marker in compact for marker in ("牛逼", "nb", "sb")
            ):
                counter[tok] += 4
    return [tok for tok, _ in counter.most_common(limit)]


def _build_style_memory(items: list[CorpusItem], limit: int = 220) -> list[str]:
    freq: Counter[str] = Counter()
    quality: dict[str, float] = {}

    for item in items:
        text = item.content.strip()
        if not _is_valid_utterance(text):
            continue
        if text.startswith("回复 ") or text.startswith("[回复 "):
            continue
        if not _is_persona_signal_text(text):
            continue
        if _is_fragmentary_style_text(text):
            continue
        freq[text] += 1
        quality[text] = max(quality.get(text, 0.0), item.quality_score)

    scored: list[tuple[float, str]] = []
    for text, count in freq.items():
        marker_bonus = 0.15 if any(m in text for m in STYLE_MARKERS) else 0.0
        rhythm_bonus = 0.08 if len(text) <= 16 else 0.0
        score = quality.get(text, 0.0) * 0.6 + min(count / 6, 1.0) * 0.25 + marker_bonus + rhythm_bonus
        scored.append((score, text))
    scored.sort(key=lambda x: x[0], reverse=True)

    memory: list[str] = []
    seen = set()
    for _, text in scored:
        if text in seen:
            continue
        seen.add(text)
        memory.append(text)
        if len(memory) >= limit:
            break
    return memory


def _is_fragmentary_style_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    lowered = compact.lower()
    if not compact:
        return True
    # keep very short reaction words in reply priors, but avoid using them as core style anchors.
    if len(compact) <= 8 and lowered in DISTINCTIVE_SHORT_UTTERANCES:
        return False
    if len(compact) <= 4 and lowered not in {"完了", "卧槽", "笑死", "不是", "没有", "难说", "稀有"}:
        return True
    if lowered in LOW_SIGNAL_REPLY_CANONICAL:
        return True
    if re.fullmatch(r"(有点|会有点|还真是|然后|所以|因为|那就|就|这个|那个)+", lowered):
        return True
    if len(tokenize(compact)) <= 1 and len(compact) <= 6 and compact.endswith(("了", "的", "吗", "吧", "呢")):
        return True
    return False


def _build_expression_metrics(items: list[CorpusItem]) -> tuple[dict[str, float | str], list[str]]:
    if not items:
        return {}, []

    filtered = [i.content for i in items if i.content.strip() and _is_persona_signal_text(i.content, allow_brief=True)]
    texts = filtered if filtered else [i.content for i in items if i.content.strip()]
    char_counts = [len(t) for t in texts]
    joined = "\n".join(texts)
    turns = max(1, len(texts))

    question_count = joined.count("?") + joined.count("？")
    exclaim_count = joined.count("!") + joined.count("！")
    hedge_hits = sum(1 for word in HEDGE_WORDS if word in joined)
    short_ratio = sum(1 for c in char_counts if c <= 4) / turns
    directness = max(0.0, min(1.0, 1 - min(hedge_hits / 30, 1.0)))

    metrics: dict[str, float | str] = {
        "avg_chars_per_turn": round(sum(char_counts) / turns, 2),
        "median_chars_per_turn": float(median(char_counts)) if char_counts else 0.0,
        "question_ratio": round(question_count / turns, 3),
        "exclaim_ratio": round(exclaim_count / turns, 3),
        "short_reply_ratio": round(short_ratio, 3),
        "directness_score": round(directness, 2),
        "negation_signal": round(1.0 if has_negation(joined) else 0.0, 2),
    }

    notes: list[str] = []
    if turns < 200:
        notes.append("语料量偏小，人格信号可能不完整。")
    if short_ratio > 0.45:
        notes.append("目标对象短句占比较高，但回复长度应随对话语义自然变化。")
    if metrics["question_ratio"] > 0.2:
        notes.append("检测到较高追问/反问比例，可自然保留该语气特征。")
    return metrics, notes


def _is_persona_signal_text(text: str, *, allow_brief: bool = False) -> bool:
    normalized = re.sub(r"\s+", "", text or "")
    if not normalized:
        return False
    lowered = normalized.lower()
    if any(h in lowered for h in NON_PERSONA_MEME_HINTS):
        return False
    if lowered in LOW_SIGNAL_CONTEXTS:
        return False
    if lowered in LOW_SIGNAL_REPLY_CANONICAL and not allow_brief:
        return False
    if lowered in DISTINCTIVE_SHORT_UTTERANCES:
        return True
    if re.fullmatch(r"(哈|哈哈|哈哈哈|啊|嗯|哦|ok|111|233|666)+", lowered):
        return False
    if len(normalized) <= 3 and not allow_brief:
        return False
    if len(tokenize(normalized)) <= 1 and len(normalized) <= 6 and not allow_brief:
        return False
    if normalized.count("哈") >= 3 and len(normalized) <= 8:
        return False
    return True


def _is_distinctive_micro_context(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    lowered = compact.lower()
    if not lowered:
        return False
    if lowered in LOW_SIGNAL_CONTEXTS:
        return False
    if lowered in {"为何", "为什么", "sry", "sorry"}:
        return True
    if re.fullmatch(r"(哈|哈哈|哈哈哈|啊|嗯|哦|ok|111|233|666)+", lowered):
        return False
    if compact.startswith(("这个", "那个")) and len(compact) <= 6:
        return False
    core_chars = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", compact)
    if len(core_chars) < 2:
        return False
    # short colloquial signals like "完了/稀有/塘湾了" should be retained for reply-style learning.
    return True


def _is_informative_context(text: str) -> bool:
    normalized_ctx = re.sub(r"\s+", "", text or "")
    if not normalized_ctx:
        return False
    lowered = normalized_ctx.lower()
    if len(normalized_ctx) <= 5:
        return _is_distinctive_micro_context(normalized_ctx)
    if not _is_persona_signal_text(normalized_ctx):
        return False
    if lowered in LOW_SIGNAL_CONTEXTS:
        return False
    if lowered.startswith(("这个", "那个")) and len(lowered) <= 8:
        return False
    if len(tokenize(normalized_ctx)) <= 1 and len(normalized_ctx) <= 6:
        return False
    if len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", normalized_ctx)) < 3:
        return False
    if re.fullmatch(r"[0-9a-zA-Z+]+", normalized_ctx):
        return False
    if normalized_ctx.count("哈") >= 2 and len(normalized_ctx) <= 8:
        return False
    return True


def _build_context_reply_memory(
    items: list[CorpusItem],
    target_speaker: str,
    limit: int = 1600,
) -> list[dict[str, str]]:
    timeline = sorted(
        items,
        key=lambda x: (
            x.timestamp.isoformat() if x.timestamp else "",
            x.source_message_id or "",
            x.id,
        ),
    )
    candidates: list[tuple[float, dict[str, str]]] = []
    for idx, item in enumerate(timeline):
        if item.speaker != target_speaker:
            continue
        reply = item.content.strip()
        if not _is_valid_utterance(reply):
            continue
        if not _is_persona_signal_text(reply, allow_brief=True) and len(reply) <= 6:
            continue
        if idx <= 0:
            continue
        # Only bind the first target turn after a non-target turn. Consecutive
        # same-speaker streaks are usually continuation thoughts, not direct replies.
        if timeline[idx - 1].speaker == target_speaker:
            continue
        context_item: CorpusItem | None = None
        for j in range(idx - 1, max(-1, idx - 8), -1):
            prev = timeline[j]
            if prev.source != item.source:
                continue
            if prev.speaker == target_speaker:
                break
            text = prev.content.strip()
            if not _is_valid_utterance(text):
                continue
            if not _is_informative_context(text):
                continue
            context_item = prev
            break
        if not context_item:
            continue
        if context_item.timestamp and item.timestamp:
            gap = abs((item.timestamp - context_item.timestamp).total_seconds())
            if gap > MAX_CONTEXT_GAP_SECONDS:
                continue
        context = context_item.content.strip()
        context_norm = re.sub(r"\s+", "", context)
        reply_norm = re.sub(r"\s+", "", reply)
        micro_pair = len(context_norm) <= 8 and len(reply_norm) <= 16
        recency = (idx + 1) / max(1, len(timeline))
        richness = min((len(context) + len(reply)) / 80, 1.0)
        micro_bonus = 0.12 if micro_pair else 0.0
        score = recency * 0.32 + richness * 0.56 + micro_bonus
        candidates.append((score, {"context": context, "reply": reply}))

    candidates.sort(key=lambda x: x[0], reverse=True)
    pairs: list[dict[str, str]] = []
    seen = set()
    for _, pair in candidates:
        key = f"{pair['context']}|||{pair['reply']}"
        if key in seen:
            continue
        seen.add(key)
        pairs.append(pair)
        if len(pairs) >= limit:
            break
    return pairs


def _fallback_claims(style_memory: list[str], section: str, provider: ModelProvider) -> list[EvidenceClaim]:
    if not style_memory:
        return []
    excerpt = style_memory[0]
    candidate = f"{section} 代表性表达：{excerpt}"
    refined = provider.refine_claim(section, candidate)
    return [
        EvidenceClaim(
            id=stable_hash(f"{section}:{refined}", prefix="claim"),
            section=section,
            claim=refined,
            confidence=0.45,
            evidence=[EvidenceSpan(item_id="style_memory", start=0, end=0, excerpt=safe_excerpt(excerpt, 160))],
            tags=["fallback"],
        )
    ]


def _claim_themes(text: str) -> set[str]:
    themes: set[str] = set()
    for theme, words in MODEL_THEME_KEYWORDS.items():
        if any(word in text for word in words):
            themes.add(theme)
    if not themes and ("如果" in text and "就" in text):
        themes.add("sequential_execution")
    if not themes and ("因为" in text and "所以" in text):
        themes.add("causal_accounting")
    return themes or {"mixed"}


def _dominant_theme(claims: list[EvidenceClaim]) -> str:
    counter: Counter[str] = Counter()
    for claim in claims:
        counter.update(_claim_themes(claim.claim))
    if not counter:
        return "mixed"
    return counter.most_common(1)[0][0]


def _model_name_from_theme(theme: str, idx: int) -> str:
    return f"{THEME_MODEL_NAME.get(theme, THEME_MODEL_NAME['mixed'])}{idx}"


def _model_sees_first(theme: str) -> str:
    if theme == "risk_control":
        return "优先看到风险暴露、胜率和止损边界。"
    if theme == "evidence_boundary":
        return "优先看到证据强弱与可验证性。"
    if theme == "sequential_execution":
        return "优先看到动作顺序与执行节奏。"
    if theme == "causal_accounting":
        return "优先看到因果链条与成本结构。"
    if theme == "social_calibration":
        return "优先看到对手强弱、关系位置和场域氛围。"
    if theme == "resource_leverage":
        return "优先看到投入产出比和验证速度。"
    return "优先看到可立即落地的经验规则。"


def _model_filters_out(theme: str) -> str:
    if theme == "risk_control":
        return "容易忽略高收益但高波动的探索窗口。"
    if theme == "evidence_boundary":
        return "容易忽略关系层面的情绪缓冲与表达润滑。"
    if theme == "sequential_execution":
        return "容易低估并行策略和非常规捷径价值。"
    if theme == "causal_accounting":
        return "容易低估短期情绪反馈对决策接受度的影响。"
    if theme == "social_calibration":
        return "容易弱化客观数据，过度依赖场域直觉。"
    if theme == "resource_leverage":
        return "容易低估长期维护成本和复利建设。"
    return "容易忽略长期系统性影响和慢变量。"


def _model_reframes(theme: str) -> str:
    if theme == "risk_control":
        return "把问题重构为“风险够不够可控，再决定是否出手”。"
    if theme == "evidence_boundary":
        return "把问题重构为“证据到哪一步，结论就说到哪一步”。"
    if theme == "sequential_execution":
        return "把问题重构为“拆步骤、控顺序、逐步推进”。"
    if theme == "causal_accounting":
        return "把问题重构为“先因后果，再看成本收益”。"
    if theme == "social_calibration":
        return "把问题重构为“先看人和场，再定动作强度”。"
    if theme == "resource_leverage":
        return "把问题重构为“小投入试错，验证后扩张”。"
    return "把问题重构为“先给立场，再补证据和动作”。"


def _model_definition_from_cluster(claims: list[EvidenceClaim], theme: str) -> str:
    base = THEME_MODEL_DEFINITION.get(theme, THEME_MODEL_DEFINITION["mixed"])
    if any("如果" in c.claim and "就" in c.claim for c in claims):
        return f"{base} 决策时使用“条件触发 -> 动作执行”的分支结构。"
    if any("先" in c.claim and ("再" in c.claim or "然后" in c.claim) for c in claims):
        return f"{base} 决策时强调先后顺序，避免动作与信息错位。"
    return base


def _claim_anchor(claim: EvidenceClaim) -> str:
    if claim.evidence:
        return safe_excerpt(claim.evidence[0].excerpt, 120)
    return safe_excerpt(claim.claim, 120)


def _claim_item_time(claim: EvidenceClaim, items_by_id: dict[str, CorpusItem]) -> datetime | None:
    for ev in claim.evidence:
        item = items_by_id.get(ev.item_id)
        if item and item.timestamp:
            return item.timestamp
    return None


def _claim_context_key(claim: EvidenceClaim, items_by_id: dict[str, CorpusItem]) -> str:
    for ev in claim.evidence:
        item = items_by_id.get(ev.item_id)
        if not item:
            continue
        month = item.timestamp.strftime("%Y-%m") if item.timestamp else "unknown-month"
        return f"{item.source}:{month}"
    return "unknown-source:unknown-month"


def _is_model_candidate(claim: EvidenceClaim) -> bool:
    text = claim.claim.strip()
    if len(text) < 6 or len(text) > 88:
        return False
    if any(k in text for k in NOISE_KEYWORDS):
        return False
    if text.count("，") > 5 and "如果" not in text and "因为" not in text:
        return False
    if "http://" in text or "https://" in text:
        return False
    if any(m in text for m in ["🐱", "🦌"]) and len(text) > 28:
        return False
    if sum(1 for ch in text if ch in "！？?!") >= 3:
        return False
    has_reason_pattern = any(p in text for p in ["如果", "就", "先", "再", "然后", "因为", "所以", "本质", "逻辑"])
    return has_reason_pattern or has_negation(text) or ("我觉得" in text or "我认为" in text)


def _cluster_model_claims(
    claims: list[EvidenceClaim],
) -> list[list[EvidenceClaim]]:
    clusters: list[list[EvidenceClaim]] = []
    for claim in claims:
        themes = _claim_themes(claim.claim)
        best_idx = -1
        best_score = 0.0
        for idx, cluster in enumerate(clusters):
            rep = cluster[0]
            sim = jaccard_similarity(claim.claim, rep.claim)
            theme_overlap = len(themes & _claim_themes(rep.claim))
            score = sim + (0.16 if theme_overlap > 0 else 0.0)
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx >= 0 and best_score >= 0.25:
            clusters[best_idx].append(claim)
        else:
            clusters.append([claim])
    return clusters


def _build_model_cards(
    grouped: dict[str, list[EvidenceClaim]],
    items_by_id: dict[str, CorpusItem],
    signature_lexicon: list[str],
) -> list[ModelCard]:
    seed_claims = (
        list(grouped.get("mental_models", []))
        + list(grouped.get("decision_heuristics", []))[:14]
        + list(grouped.get("beliefs_and_values", []))[:10]
    )
    unique_claims: list[EvidenceClaim] = []
    seen_text = set()
    for claim in seed_claims:
        if claim.claim in seen_text:
            continue
        seen_text.add(claim.claim)
        unique_claims.append(claim)
    base_claims = [claim for claim in unique_claims if _is_model_candidate(claim)][:22]
    if not base_claims:
        return []

    clusters = _cluster_model_claims(base_claims)
    clusters.sort(
        key=lambda c: (
            len(c),
            sum(claim.confidence for claim in c) / max(1, len(c)),
        ),
        reverse=True,
    )

    cards: list[ModelCard] = []
    used_themes: set[str] = set()
    for cluster in clusters[:10]:
        dominant_theme = _dominant_theme(cluster)
        if dominant_theme in used_themes and len(cards) >= 2:
            continue
        contexts = {_claim_context_key(claim, items_by_id) for claim in cluster}
        sources = {ctx.split(":", 1)[0] for ctx in contexts}
        months = {ctx.split(":", 1)[1] for ctx in contexts}
        joined = " ".join(claim.claim for claim in cluster)
        theme_hits = sum(1 for claim in cluster if dominant_theme in _claim_themes(claim.claim))
        theme_ratio = theme_hits / max(1, len(cluster))

        gate_cross = len(contexts) >= 2 or len(months) >= 2 or len(sources) >= 2 or len(cluster) >= 3
        gate_generative = (
            any("如果" in c.claim and "就" in c.claim for c in cluster)
            or any("先" in c.claim and ("再" in c.claim or "然后" in c.claim) for c in cluster)
            or any("因为" in c.claim and "所以" in c.claim for c in cluster)
            or theme_ratio >= 0.7
        )
        lex_hit = sum(1 for tok in signature_lexicon[:20] if tok and tok in joined)
        gate_exclusive = theme_ratio >= 0.55 or lex_hit >= 2
        gates = {
            "cross_context": gate_cross,
            "generative": gate_generative,
            "exclusive": gate_exclusive,
        }
        gate_score = sum(1 for v in gates.values() if v) / 3
        anchors: list[str] = []
        seen_anchor = set()
        for c in sorted(cluster, key=lambda x: x.confidence, reverse=True)[:6]:
            anchor = _claim_anchor(c)
            if anchor in seen_anchor:
                continue
            seen_anchor.add(anchor)
            anchors.append(anchor)
        avg_conf = sum(c.confidence for c in cluster) / max(1, len(cluster))
        definition = _model_definition_from_cluster(cluster, dominant_theme)
        source_claim = sorted(cluster, key=lambda x: x.confidence, reverse=True)[0]

        cards.append(
            ModelCard(
                id=stable_hash(f"model:{source_claim.id}", prefix="model"),
                name=_model_name_from_theme(dominant_theme, len(cards) + 1),
                definition=definition,
                sees_first=_model_sees_first(dominant_theme),
                filters_out=_model_filters_out(dominant_theme),
                reframes=_model_reframes(dominant_theme),
                evidence_anchors=anchors[:3],
                failure_mode=_model_filters_out(dominant_theme),
                gates=gates,
                confidence=round(min(0.98, avg_conf * 0.55 + gate_score * 0.45), 3),
                source_claim_id=source_claim.id,
            )
        )
        used_themes.add(dominant_theme)
        if len(cards) >= 7:
            break
    return cards


def _apply_model_gate_demotion(
    grouped: dict[str, list[EvidenceClaim]],
    model_cards: list[ModelCard],
) -> tuple[dict[str, list[EvidenceClaim]], dict[str, int], list[ModelCard]]:
    model_claims = list(grouped.get("mental_models", []))
    heuristics = list(grouped.get("decision_heuristics", []))
    by_id = {c.id: c for c in model_claims}
    heuristic_texts = {h.claim for h in heuristics}

    keep_ids: set[str] = set()
    keep_cards: list[ModelCard] = []
    demoted_count = 0
    for card in model_cards:
        source_id = card.source_claim_id
        if not source_id:
            continue
        gate_passes = sum(1 for v in card.gates.values() if v)
        if gate_passes >= 3:
            keep_ids.add(source_id)
            keep_cards.append(card)
            continue

        # 1-2 gates: demote to decision heuristics (Nuwa style)
        claim = by_id.get(source_id)
        if claim is None:
            continue
        if claim.claim in heuristic_texts:
            demoted_count += 1
            continue
        demoted = EvidenceClaim(
            id=stable_hash(f"demoted:{claim.id}", prefix="claim"),
            section="decision_heuristics",
            claim=claim.claim,
            confidence=round(max(0.35, claim.confidence * 0.88), 3),
            evidence=claim.evidence,
            tags=sorted(set(claim.tags + ["demoted_from_model"])),
        )
        heuristics.append(demoted)
        heuristic_texts.add(demoted.claim)
        demoted_count += 1

    filtered_models = [c for c in model_claims if c.id in keep_ids]
    if len(filtered_models) < 2 and model_cards:
        scored_cards = sorted(
            model_cards,
            key=lambda c: (
                sum(1 for v in c.gates.values() if v),
                c.confidence,
            ),
            reverse=True,
        )
        for card in scored_cards:
            sid = card.source_claim_id
            if not sid or sid in keep_ids:
                continue
            keep_ids.add(sid)
            keep_cards.append(card)
            claim = by_id.get(sid)
            if claim:
                filtered_models.append(claim)
            if len(filtered_models) >= 2:
                break

    grouped["mental_models"] = filtered_models[:24]
    grouped["decision_heuristics"] = sorted(heuristics, key=lambda x: x.confidence, reverse=True)[:24]
    keep_cards = [c for c in model_cards if c.source_claim_id in keep_ids]
    if len(keep_cards) < 2 and filtered_models:
        existing_sources = {c.source_claim_id for c in keep_cards if c.source_claim_id}
        for claim in sorted(filtered_models, key=lambda x: x.confidence, reverse=True):
            if claim.id in existing_sources:
                continue
            theme = _dominant_theme([claim])
            anchors = [_claim_anchor(claim)]
            gates = {
                "cross_context": len(claim.evidence) >= 2,
                "generative": any(tok in claim.claim for tok in ["如果", "就", "先", "再", "因为", "所以"]),
                "exclusive": bool(_claim_themes(claim.claim)),
            }
            keep_cards.append(
                ModelCard(
                    id=stable_hash(f"model:fallback:{claim.id}", prefix="model"),
                    name=_model_name_from_theme(theme, len(keep_cards) + 1),
                    definition=_model_definition_from_cluster([claim], theme),
                    sees_first=_model_sees_first(theme),
                    filters_out=_model_filters_out(theme),
                    reframes=_model_reframes(theme),
                    evidence_anchors=anchors,
                    failure_mode=_model_filters_out(theme),
                    gates=gates,
                    confidence=round(max(0.55, claim.confidence), 3),
                    source_claim_id=claim.id,
                )
            )
            existing_sources.add(claim.id)
            if len(keep_cards) >= 2:
                break
    return grouped, {"kept_models": len(filtered_models), "demoted_models": demoted_count}, keep_cards


def _decision_rationale(text: str) -> str:
    if "如果" in text and "就" in text:
        return "先分支判断再动作，可降低误判。"
    if "先" in text and ("再" in text or "然后" in text):
        return "先后顺序明确，便于执行和复盘。"
    if has_negation(text):
        return "优先规避高风险路径，减少反噬。"
    return "基于经验压缩的快速决策。"


def _decision_boundary(text: str) -> str:
    if has_negation(text):
        return "在高不确定场景有效，但可能过度保守。"
    if len(text) > 26:
        return "依赖具体语境，迁移到新场景需校准。"
    return "适合快决策，不适合复杂系统问题。"


def _parse_rule_parts(text: str) -> tuple[str, str]:
    cleaned = text.strip("。")
    if "如果" in cleaned and "就" in cleaned:
        if_idx = cleaned.find("如果")
        then_idx = cleaned.find("就", if_idx + 1)
        if then_idx > if_idx >= 0:
            left = cleaned[if_idx + 2 : then_idx]
            right = cleaned[then_idx + 1 :]
            condition = left.strip("，。 ")
            action = right.strip("，。 ")
            return (condition or "触发条件出现时", action or cleaned)
    if "先" in cleaned and ("再" in cleaned or "然后" in cleaned):
        return ("需要分步推进时", cleaned)
    return ("遇到类似情境时", cleaned)


def _build_decision_rules(grouped: dict[str, list[EvidenceClaim]]) -> list[DecisionRule]:
    claims = grouped.get("decision_heuristics", [])[:12]
    rules: list[DecisionRule] = []
    for claim in claims[:10]:
        condition, action = _parse_rule_parts(claim.claim)
        rules.append(
            DecisionRule(
                id=stable_hash(f"rule:{claim.id}", prefix="rule"),
                rule=claim.claim,
                condition=condition,
                action=action,
                rationale=_decision_rationale(claim.claim),
                boundary=_decision_boundary(claim.claim),
                evidence_anchor=_claim_anchor(claim),
                confidence=round(claim.confidence, 3),
            )
        )
    return rules


def _build_contradictions(
    grouped: dict[str, list[EvidenceClaim]],
    items_by_id: dict[str, CorpusItem],
) -> list[ContradictionItem]:
    contradictions: list[ContradictionItem] = []
    seen = set()
    sections_to_scan = ["beliefs_and_values", "mental_models", "decision_heuristics", "anti_patterns_and_limits"]
    for section in sections_to_scan:
        claims = grouped.get(section, [])[:12]
        for i in range(len(claims)):
            for j in range(i + 1, len(claims)):
                a = claims[i]
                b = claims[j]
                sim = jaccard_similarity(a.claim, b.claim)
                if has_negation(a.claim) == has_negation(b.claim):
                    continue
                same_theme = bool(_claim_themes(a.claim) & _claim_themes(b.claim))
                if sim < 0.28 and not (same_theme and sim >= 0.08):
                    continue
                aid = a.id if a.id < b.id else b.id
                bid = b.id if a.id < b.id else a.id
                key = f"{section}:{aid}:{bid}"
                if key in seen:
                    continue
                seen.add(key)
                ta = _claim_item_time(a, items_by_id)
                tb = _claim_item_time(b, items_by_id)
                ctype = "contextual"
                if ta and tb and abs((ta - tb).days) >= 30:
                    ctype = "temporal"
                description = (
                    f"{section} 出现相反倾向："
                    f"「{safe_excerpt(a.claim, 28)}」 vs 「{safe_excerpt(b.claim, 28)}」"
                )
                contradictions.append(
                    ContradictionItem(
                        id=stable_hash(key, prefix="contra"),
                        type=ctype,
                        description=description,
                        evidence=[_claim_anchor(a), _claim_anchor(b)],
                    )
                )
    # 扩展：跨分区张力（价值 vs 边界 / 模型 vs 边界 / 启发式 vs 边界）
    cross_pairs = [
        ("beliefs_and_values", "anti_patterns_and_limits"),
        ("mental_models", "anti_patterns_and_limits"),
        ("decision_heuristics", "anti_patterns_and_limits"),
    ]
    for left_section, right_section in cross_pairs:
        left_claims = grouped.get(left_section, [])[:10]
        right_claims = grouped.get(right_section, [])[:10]
        local_hits = 0
        for left in left_claims:
            for right in right_claims:
                if left.claim == right.claim:
                    continue
                sim = jaccard_similarity(left.claim, right.claim)
                left_neg = has_negation(left.claim)
                right_neg = has_negation(right.claim)
                same_theme = bool(_claim_themes(left.claim) & _claim_themes(right.claim))
                if left_neg == right_neg:
                    continue
                if sim < 0.24 and not (same_theme and sim >= 0.1):
                    continue
                key = f"cross:{left_section}:{left.id}:{right_section}:{right.id}"
                if key in seen:
                    continue
                seen.add(key)
                contradictions.append(
                    ContradictionItem(
                        id=stable_hash(key, prefix="contra"),
                        type="cross_section",
                        description=(
                            f"{left_section} 与 {right_section} 存在张力："
                            f"「{safe_excerpt(left.claim, 28)}」 vs 「{safe_excerpt(right.claim, 28)}」"
                        ),
                        evidence=[_claim_anchor(left), _claim_anchor(right)],
                    )
                )
                local_hits += 1
                if local_hits >= 6:
                    break
            if local_hits >= 6:
                break

    # 扩展：时间切片冲突（同主题、相反倾向、跨30天）
    all_claims = [
        *grouped.get("beliefs_and_values", [])[:10],
        *grouped.get("mental_models", [])[:10],
        *grouped.get("decision_heuristics", [])[:10],
    ]
    for i in range(len(all_claims)):
        for j in range(i + 1, len(all_claims)):
            a = all_claims[i]
            b = all_claims[j]
            if has_negation(a.claim) == has_negation(b.claim):
                continue
            sim = jaccard_similarity(a.claim, b.claim)
            if sim < 0.18:
                continue
            if not (_claim_themes(a.claim) & _claim_themes(b.claim)):
                continue
            ta = _claim_item_time(a, items_by_id)
            tb = _claim_item_time(b, items_by_id)
            if not ta or not tb:
                continue
            if abs((ta - tb).days) < 30:
                continue
            key = f"temporal:{a.id}:{b.id}"
            if key in seen:
                continue
            seen.add(key)
            contradictions.append(
                ContradictionItem(
                    id=stable_hash(key, prefix="contra"),
                    type="temporal",
                    description=(
                        "同主题决策出现时间迁移反转："
                        f"「{safe_excerpt(a.claim, 26)}」 vs 「{safe_excerpt(b.claim, 26)}」"
                    ),
                    evidence=[_claim_anchor(a), _claim_anchor(b)],
                )
            )

    # 兜底：补一个价值-边界张力
    beliefs = grouped.get("beliefs_and_values", [])
    antis = grouped.get("anti_patterns_and_limits", [])
    if beliefs and antis:
        b = beliefs[0]
        a = antis[0]
        for alt in antis:
            if alt.claim != b.claim:
                a = alt
                break
        contradictions.append(
            ContradictionItem(
                id=stable_hash(f"value-tension:{b.id}:{a.id}", prefix="contra"),
                type="inherent",
                description=(
                    f"价值观与边界存在张力：重视「{safe_excerpt(b.claim, 24)}」，"
                    f"同时警惕「{safe_excerpt(a.claim, 24)}」。"
                ),
                evidence=[_claim_anchor(b), _claim_anchor(a)],
            )
        )
    deduped: list[ContradictionItem] = []
    seen_desc = set()
    seen_evidence_pair = set()
    for item in contradictions:
        key = safe_excerpt(item.description, 70)
        pair_key = "||".join(sorted(item.evidence[:2]))
        if key in seen_desc:
            continue
        if pair_key and pair_key in seen_evidence_pair:
            continue
        seen_desc.add(key)
        if pair_key:
            seen_evidence_pair.add(pair_key)
        deduped.append(item)
    return deduped[:10]


def _build_known_answer_anchors(context_reply_memory: list[dict[str, str]]) -> list[dict[str, str]]:
    anchors: list[dict[str, str]] = []
    for pair in context_reply_memory[:20]:
        context = pair.get("context", "").strip()
        reply = pair.get("reply", "").strip()
        if len(context) < 4 or len(reply) < 2:
            continue
        anchors.append(
            {
                "question": safe_excerpt(context, 80),
                "expected_direction": safe_excerpt(reply, 80),
                "confidence": "medium",
            }
        )
        if len(anchors) >= 5:
            break
    return anchors


def _build_source_metrics(items: list[CorpusItem], all_items: list[CorpusItem]) -> dict[str, float | int | str]:
    timestamps = [i.timestamp for i in items if i.timestamp is not None]
    span_days = 0
    active_months = 0
    if len(timestamps) >= 2:
        span_days = abs((max(timestamps) - min(timestamps)).days)
        active_months = len({ts.strftime("%Y-%m") for ts in timestamps})
    unique_sources = len({i.source for i in items if i.source})
    source_speakers = len({f"{i.source}:{i.speaker}" for i in all_items if i.source})
    avg_quality = 0.0
    if items:
        avg_quality = round(sum(i.quality_score for i in items) / len(items), 3)
    return {
        "source_item_count": len(items),
        "unique_source_files": unique_sources,
        "source_speaker_pairs": source_speakers,
        "time_span_days": span_days,
        "active_month_buckets": active_months,
        "avg_quality_score": avg_quality,
    }


def _parse_agent_json_claims(raw_text: str) -> list[dict]:
    payload = raw_text.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?", "", payload).strip()
        payload = re.sub(r"```$", "", payload).strip()
    start = payload.find("{")
    end = payload.rfind("}")
    if start >= 0 and end > start:
        payload = payload[start : end + 1]
    try:
        data = json.loads(payload)
    except Exception:
        return []
    claims = data.get("claims", []) if isinstance(data, dict) else []
    if not isinstance(claims, list):
        return []
    return [c for c in claims if isinstance(c, dict)]


def _select_agent_candidates(section: str, candidates: list[Candidate], limit: int = 32) -> list[Candidate]:
    if section == "mental_models":
        section_pool = {"mental_models", "decision_heuristics", "beliefs_and_values"}
    elif section == "anti_patterns_and_limits":
        section_pool = {"anti_patterns_and_limits", "beliefs_and_values"}
    else:
        section_pool = {section}

    scored: list[tuple[float, Candidate]] = []
    for candidate in candidates:
        if candidate.section not in section_pool:
            continue
        score = candidate.item.quality_score
        if section == "mental_models" and any(k in candidate.claim for k in ["因为", "所以", "如果", "就", "本质", "逻辑"]):
            score += 0.35
        if section == "decision_heuristics" and any(k in candidate.claim for k in ["先", "再", "然后", "优先", "建议"]):
            score += 0.35
        if section == "beliefs_and_values" and any(k in candidate.claim for k in ["我觉得", "我认为", "我感觉"]):
            score += 0.28
        if section == "anti_patterns_and_limits" and has_negation(candidate.claim):
            score += 0.3
        scored.append((score, candidate))

    scored.sort(key=lambda x: x[0], reverse=True)
    selected: list[Candidate] = []
    seen = set()
    for _, candidate in scored:
        key = candidate.claim.strip()
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _friend_object_model_block() -> str:
    return (
        "朋友人格对象模型：\n"
        "- 保持双向朋友立场：直给但不羞辱，关心但不端着；\n"
        "- 长期信任优先于短期讨好；\n"
        "- 兼顾陪伴行为：给实操建议、兜住情绪、边界诚实；\n"
        "- 保留打趣和烟火气，避免“心理咨询师式”过度修饰。\n"
    )


def _style_anchor_block(style_anchors: list[str], signature_anchors: list[str]) -> str:
    if not style_anchors and not signature_anchors:
        return ""
    style_lines = "\n".join(f"- {line}" for line in style_anchors[:8]) or "- 暂无"
    lexicon_line = "、".join(signature_anchors[:16]) if signature_anchors else "暂无"
    return (
        "已有 skill 风格连续性锚点：\n"
        "- 除非新证据非常强，否则优先保留这些既有表达节奏。\n"
        f"{style_lines}\n"
        f"- 可自然保留的签名词：{lexicon_line}\n"
        "- 新语料与锚点冲突时，先降置信度，不要暴力覆盖。\n"
    )


def _agent_section_prompt(
    persona_id: str,
    section: str,
    selected: list[tuple[str, Candidate]],
    profile_mode: str,
    style_anchors: list[str],
    signature_anchors: list[str],
) -> str:
    section_goal = {
        "beliefs_and_values": "core value ordering and stable preference priors",
        "mental_models": "portable cognitive lenses that can generalize to new situations",
        "decision_heuristics": "if-then decision rules with trigger and action",
        "anti_patterns_and_limits": "explicit refusal boundaries and failure modes",
    }.get(section, "persona signals")
    evidence_lines = "\n".join(f"[{ev_id}] {candidate.claim}" for ev_id, candidate in selected)
    mode_block = ""
    if profile_mode == "friend_cold_start":
        mode_block = _friend_object_model_block()
    elif profile_mode == "style_anchored_update":
        mode_block = _style_anchor_block(style_anchors, signature_anchors)
    return (
        "你是 Friend-Skill 人格蒸馏代理。\n"
        "TASK:SECTION_EXTRACTION\n"
        f"PERSONA:{persona_id}\n"
        f"PROFILE_MODE:{profile_mode}\n"
        f"SECTION:{section}\n"
        f"GOAL: 提炼 {section_goal}。\n"
        f"{mode_block}"
        "硬约束：\n"
        "1) 输出必须是中文，不要翻译成英文规则句。\n"
        "2) 保留说话人的语气纹理（例如短句、反问、口语力度），不要抹平成咨询腔。\n"
        "3) 结论要可迁移，但允许保留少量有辨识度的原生表达。\n"
        "4) 有冲突就保留冲突，不要强行圆。\n"
        "5) 证据弱时降置信度或丢弃，不要硬编。\n"
        "6) 写行为规则，不写空泛形容词（如'很温柔''很理性'）。\n"
        "7) 证据不足时允许输出'信息不足'类规则，不要补脑。\n"
        "分层约束：\n"
        "- beliefs_and_values: 提炼稳定偏好排序（重什么、拒绝什么）。\n"
        "- mental_models: 提炼可复用认知透镜，能跨场景迁移。\n"
        "- decision_heuristics: 产出可执行规则，可用“如果…就…”或口语动作规则句。\n"
        "- anti_patterns_and_limits: 明确边界/雷区/失败模式。\n"
        "证据规则：\n"
        "- 每条 claim 绑定 1-3 个 evidence_ids。\n"
        "- 一次性段子或单点情绪句，默认降权。\n"
        "- 冲突条目保留并用 tags 标注 tension。\n"
        "压缩规则：\n"
        "- 删除纯梗、无关人名、不可迁移细节。\n"
        "- 但不要过度去口语化，保留人格辨识度。\n"
        "- 禁止无证据补全具体名词（菜名、地点、人物背景）。\n"
        "当 SECTION=mental_models 时执行三重门禁：\n"
        "- cross_context: 至少跨 2 个上下文/证据组出现；\n"
        "- generative: 可推断相邻新问题的立场；\n"
        "- exclusive: 能体现该人格独特视角，不是通用鸡汤。\n"
        "若 mental-model 候选失败 >=2 项，不要放进 mental_models。\n"
        "仅返回 JSON（不要 markdown），schema：\n"
        '{"claims":[{"claim":"...", "evidence_ids":["ev_001"], "confidence":0.0, "tags":["agent","cross_context","generative","exclusive","tension"]}]}\n'
        "补充规则：\n"
        "- 每条 claim 最长 120 字。\n"
        "- 最多输出 8 条。\n"
        "- confidence 范围 [0.35, 0.95]。\n"
        "- 禁止空泛励志句。\n"
        "- anti_patterns_and_limits 必须写出“不要做什么”。\n"
        "Evidence:\n"
        f"{evidence_lines}\n"
    )


def _agent_refine_prompt(
    persona_id: str,
    section: str,
    selected: list[tuple[str, Candidate]],
    draft_claims: list[dict],
) -> str:
    evidence_lines = "\n".join(f"[{ev_id}] {candidate.claim}" for ev_id, candidate in selected)
    draft_json = json.dumps({"claims": draft_claims[:8]}, ensure_ascii=False)
    return (
        "你是 Distillation-Reviewer 代理。\n"
        "TASK:SECTION_REFINEMENT\n"
        f"PERSONA:{persona_id}\n"
        f"SECTION:{section}\n"
        "目标：提升草稿的风格保真度、迁移性和约束合规性。\n"
        "检查清单：\n"
        "1) 去掉无迁移价值的噪声细节；\n"
        "2) 保留人格语气纹理，不要修成公文腔；\n"
        "3) 决策规则要可执行，但不强制写成英文 IF-THEN；\n"
        "4) 保留有效冲突，删除重复或近重复；\n"
        "5) 根据证据强弱校准 confidence。\n"
        "禁止新增无证据支持的 claim。\n"
        "仅返回 JSON：\n"
        '{"claims":[{"claim":"...", "evidence_ids":["ev_001"], "confidence":0.0, "tags":["agent","cross_context","generative","exclusive","tension"]}]}\n'
        "规则：\n"
        "- 输出中文。\n"
        "- 最多 8 条。\n"
        "- confidence 范围 [0.35, 0.95]。\n"
        "- 每条 claim 使用 1-3 个 evidence_ids。\n"
        "- 每条 claim 最长 120 字。\n"
        "- 不要凭空新增语料中未出现的具体对象名。\n"
        "Evidence:\n"
        f"{evidence_lines}\n"
        "Draft:\n"
        f"{draft_json}\n"
    )


def _build_agent_grouped(
    persona_id: str,
    provider: ModelProvider,
    candidates: list[Candidate],
    profile_mode: str,
    style_anchors: list[str],
    signature_anchors: list[str],
) -> dict[str, list[EvidenceClaim]]:
    grouped: dict[str, list[EvidenceClaim]] = defaultdict(list)

    for section in ["beliefs_and_values", "mental_models", "decision_heuristics", "anti_patterns_and_limits"]:
        selected_candidates = _select_agent_candidates(section, candidates)
        if not selected_candidates:
            grouped[section] = []
            continue

        selected = [(f"ev_{idx:03d}", c) for idx, c in enumerate(selected_candidates, start=1)]
        ev_map = {ev_id: c for ev_id, c in selected}
        prompt = _agent_section_prompt(
            persona_id=persona_id,
            section=section,
            selected=selected,
            profile_mode=profile_mode,
            style_anchors=style_anchors,
            signature_anchors=signature_anchors,
        )

        try:
            raw = provider.run_agent(prompt)
        except Exception:
            raw = '{"claims":[]}'
        payload_claims = _parse_agent_json_claims(raw)
        if payload_claims:
            review_prompt = _agent_refine_prompt(
                persona_id=persona_id,
                section=section,
                selected=selected,
                draft_claims=payload_claims,
            )
            try:
                reviewed_raw = provider.run_agent(review_prompt)
                reviewed_claims = _parse_agent_json_claims(reviewed_raw)
                if reviewed_claims:
                    payload_claims = reviewed_claims
            except Exception:
                pass

        produced: list[EvidenceClaim] = []
        seen_claim = set()
        seen_refined = set()
        for item in payload_claims[:8]:
            claim_text = str(item.get("claim", "")).strip()
            if not claim_text or claim_text in seen_claim:
                continue
            seen_claim.add(claim_text)
            ref_ids = item.get("evidence_ids", [])
            if not isinstance(ref_ids, list):
                ref_ids = []
            evidence_spans: list[EvidenceSpan] = []
            max_quality = 0.0
            for ev_id in ref_ids[:3]:
                candidate = ev_map.get(str(ev_id))
                if not candidate:
                    continue
                max_quality = max(max_quality, candidate.item.quality_score)
                evidence_spans.append(
                    EvidenceSpan(
                        item_id=candidate.item.id,
                        start=candidate.start,
                        end=candidate.end,
                        excerpt=safe_excerpt(candidate.claim, 180),
                    )
                )
            if not evidence_spans:
                candidate = selected[0][1]
                max_quality = candidate.item.quality_score
                evidence_spans = [
                    EvidenceSpan(
                        item_id=candidate.item.id,
                        start=candidate.start,
                        end=candidate.end,
                        excerpt=safe_excerpt(candidate.claim, 180),
                    )
                ]
            confidence = item.get("confidence", max(0.45, min(0.9, 0.35 + max_quality * 0.58)))
            tags = item.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            refined_claim = provider.refine_claim(section, claim_text)
            if refined_claim in seen_refined:
                continue
            seen_refined.add(refined_claim)
            produced.append(
                EvidenceClaim(
                    id=stable_hash(f"{section}:agent:{refined_claim}", prefix="claim"),
                    section=section,
                    claim=refined_claim,
                    confidence=round(float(confidence), 3),
                    evidence=evidence_spans,
                    tags=sorted(set(["agent"] + [str(t) for t in tags if str(t).strip()])),
                )
            )

        if produced:
            grouped[section] = sorted(produced, key=lambda x: x.confidence, reverse=True)[:24]
        else:
            grouped[section] = []
    return grouped


def _finalize_profile(
    persona_id: str,
    version: str,
    items: list[CorpusItem],
    working_items: list[CorpusItem],
    grouped: dict[str, list[EvidenceClaim]],
    corrections: list[CorrectionNote],
    provider: ModelProvider,
    style_memory: list[str],
    signature_lexicon: list[str],
    context_reply_memory: list[dict[str, str]],
    distillation_mode: str,
) -> PersonaProfile:
    metrics, uncertainty = _build_expression_metrics(working_items)
    avg_chars = metrics.get("avg_chars_per_turn", 0)
    short_ratio = metrics.get("short_reply_ratio", 0)
    directness = metrics.get("directness_score", 0)
    question_ratio = metrics.get("question_ratio", 0)
    signature_preview = "、".join(signature_lexicon[:10]) or "暂无"
    style_preview = " / ".join(safe_excerpt(x, 18) for x in style_memory[:3]) or "暂无"
    expr_claims = [
        f"常用短句推进对话，平均每轮约 {avg_chars} 字，短句比例 {short_ratio}。",
        f"表达直给，直接性得分约 {directness}，遇到犹豫场景倾向先给立场。",
        f"反问/追问频率约 {question_ratio}，必要时会用追问逼近重点。",
        f"高频口语签名：{signature_preview}。",
        f"代表性句感：{style_preview}。",
    ]
    grouped["expression_dna"] = [
        EvidenceClaim(
            id=stable_hash(f"expression_dna:{claim}", prefix="claim"),
            section="expression_dna",
            claim=provider.refine_claim("expression_dna", claim),
            confidence=0.78,
            evidence=[
                EvidenceSpan(
                    item_id=items[0].id if items else "none",
                    start=0,
                    end=0,
                    excerpt="Derived from corpus-level language statistics and repeated utterance patterns.",
                )
            ],
            tags=["metric"],
        )
        for claim in expr_claims
    ]

    for note in corrections:
        section = note.section if note.section in CORE_SECTIONS else "beliefs_and_values"
        corrected_claim = provider.refine_claim(section, f"Correction preference: {note.instruction}")
        grouped[section].append(
            EvidenceClaim(
                id=stable_hash(f"{section}:{note.id}:{corrected_claim}", prefix="claim"),
                section=section,
                claim=corrected_claim,
                confidence=0.92,
                evidence=[EvidenceSpan(item_id="correction_layer", start=0, end=0, excerpt=note.instruction)],
                tags=["correction"],
            )
        )

    for section in CORE_SECTIONS:
        if not grouped.get(section):
            grouped[section].extend(_fallback_claims(style_memory, section, provider))
        grouped[section] = sorted(grouped.get(section, []), key=lambda x: x.confidence, reverse=True)[:24]

    items_by_id = {i.id: i for i in items}
    model_cards = _build_model_cards(grouped, items_by_id, signature_lexicon)
    grouped, gate_stats, kept_model_cards = _apply_model_gate_demotion(grouped, model_cards)
    decision_rules = _build_decision_rules(grouped)
    contradictions = _build_contradictions(grouped, items_by_id)
    known_answer_anchors = _build_known_answer_anchors(context_reply_memory)
    source_metrics = _build_source_metrics(working_items, items)
    source_metrics.update(gate_stats)
    source_metrics["distillation_mode"] = distillation_mode

    return PersonaProfile(
        persona_id=persona_id,
        version=version,
        generated_at=utc_now(),
        sections={k: grouped.get(k, []) for k in CORE_SECTIONS},
        expression_metrics=metrics,
        uncertainty_notes=uncertainty,
        signature_lexicon=signature_lexicon,
        style_memory=style_memory,
        context_reply_memory=context_reply_memory,
        model_cards=kept_model_cards,
        decision_rules=decision_rules,
        contradictions=contradictions,
        known_answer_anchors=known_answer_anchors,
        source_metrics=source_metrics,
        source_item_count=len(working_items),
    )


def extract_profile_agentic(
    persona_id: str,
    version: str,
    items: list[CorpusItem],
    corrections: list[CorrectionNote],
    provider: ModelProvider,
    target_speaker: str | None = None,
    profile_mode: str = "friend_cold_start",
    style_anchor_profile: PersonaProfile | None = None,
) -> PersonaProfile:
    resolved_speaker = target_speaker or persona_id
    target_items = [i for i in items if i.speaker == resolved_speaker]
    working_items = target_items or items

    candidates = _extract_candidates(working_items)
    style_memory = _build_style_memory(working_items)
    signature_lexicon = _build_signature_lexicon(working_items)
    context_reply_memory = _build_context_reply_memory(items, resolved_speaker)
    style_anchors = style_anchor_profile.style_memory[:40] if style_anchor_profile else []
    signature_anchors = style_anchor_profile.signature_lexicon[:40] if style_anchor_profile else []
    grouped = _build_agent_grouped(
        persona_id=persona_id,
        provider=provider,
        candidates=candidates,
        profile_mode=profile_mode,
        style_anchors=style_anchors,
        signature_anchors=signature_anchors,
    )

    return _finalize_profile(
        persona_id=persona_id,
        version=version,
        items=items,
        working_items=working_items,
        grouped=grouped,
        corrections=corrections,
        provider=provider,
        style_memory=style_memory,
        signature_lexicon=signature_lexicon,
        context_reply_memory=context_reply_memory,
        distillation_mode=f"agent:{profile_mode}",
    )
