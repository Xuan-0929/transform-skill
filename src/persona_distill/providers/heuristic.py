from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict

from ..utils import jaccard_similarity
from .base import ModelProvider


THEME_KEYWORDS: dict[str, list[str]] = {
    "risk_control": ["风险", "不该", "别", "不要", "不能", "谨慎", "收手", "稳", "保", "输", "高"],
    "evidence_boundary": ["证据", "确定", "不确定", "依据", "信息", "真假", "怀疑", "边界"],
    "sequential_execution": ["先", "再", "然后", "步骤", "顺序", "拆", "流程", "反应"],
    "causal_accounting": ["因为", "所以", "本质", "逻辑", "成本", "收益", "代价", "划算"],
    "social_calibration": ["对面", "别人", "团队", "交流", "关系", "情绪价值", "同伴", "场面"],
    "resource_leverage": ["效率", "高效", "时间", "投入", "省", "快速", "直接", "杠杆"],
}

MENTAL_MODEL_TEMPLATES = {
    "risk_control": "先估胜率和风险暴露，再决定是否出手；不占优时主动收手。",
    "evidence_boundary": "结论强度必须跟证据强度对齐；证据不足就降级判断并补信息。",
    "sequential_execution": "先感知关键变量，再执行动作；把问题拆成顺序链条推进。",
    "causal_accounting": "先看因果约束与成本收益，再选代价更低、可持续的路径。",
    "social_calibration": "先判断人和场，再决定表达强度和推进节奏。",
    "resource_leverage": "优先小投入高反馈动作，先验证再扩大投入。",
}

BELIEF_TEMPLATES = {
    "risk_control": "我更重视风险可控，不做胜率不占优的硬冲决策。",
    "evidence_boundary": "没证据就不装确定，先补信息再下判断。",
    "sequential_execution": "我倾向把复杂问题拆步执行，靠顺序控制降低失误。",
    "causal_accounting": "我做判断会先算清因果和成本，不靠情绪拍板。",
    "social_calibration": "交流应该互相提供情绪价值，而不是单向消耗。",
    "resource_leverage": "我偏好低成本试错，再按反馈迭代升级。",
}

ANTI_BOUNDARY_TEMPLATES = {
    "risk_control": "不在胜率不明或风险不可控时盲目上强度。",
    "evidence_boundary": "拒绝没依据的断言，不编造语料外事实。",
    "sequential_execution": "避免跳步骤硬推进，信息和动作必须先后对齐。",
    "causal_accounting": "避免只看表面结果、忽略代价与后续连锁反应。",
    "social_calibration": "不做单向情绪消耗型互动，避免无意义拉扯。",
    "resource_leverage": "避免高投入低反馈的蛮干路线。",
}


class HeuristicProvider(ModelProvider):
    def __init__(self) -> None:
        super().__init__(provider="runtime", model="skill")

    def refine_claim(self, section: str, candidate: str) -> str:
        cleaned = self._clean_text(candidate)
        if section == "decision_heuristics":
            return self._abstract_decision_rule(cleaned)
        if section == "anti_patterns_and_limits":
            theme = self._detect_theme(cleaned)
            return ANTI_BOUNDARY_TEMPLATES.get(theme, "不做证据不足且风险失控的判断。")
        if section == "mental_models":
            theme = self._detect_theme(cleaned)
            return MENTAL_MODEL_TEMPLATES.get(theme, cleaned[:180])
        if section == "beliefs_and_values":
            theme = self._detect_theme(cleaned)
            return BELIEF_TEMPLATES.get(theme, cleaned[:180])
        return cleaned[:180]

    def summarize_section(self, section: str, claims: list[str]) -> str:
        if not claims:
            return "No strong signal found."
        top = claims[:3]
        return "；".join(top)

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip().replace("  ", " ")
        cleaned = re.sub(r"\[em\]e\d+\[/em\]", "", cleaned)
        cleaned = re.sub(r"\[[^\]]{1,12}\]", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = cleaned.strip("。！？!?,，；; ")
        return cleaned[:180]

    def _detect_theme(self, text: str) -> str:
        best = "risk_control"
        best_score = -1
        for theme, words in THEME_KEYWORDS.items():
            score = sum(1 for w in words if w in text)
            if score > best_score:
                best = theme
                best_score = score
        if "如果" in text and "就" in text and best_score <= 0:
            return "sequential_execution"
        if "因为" in text and "所以" in text and best_score <= 0:
            return "causal_accounting"
        if best_score <= 0:
            return "resource_leverage"
        return best

    def _abstract_condition(self, text: str) -> str:
        if any(k in text for k in ["风险", "不该", "高", "输", "稳", "对面"]):
            return "风险偏高或胜率不占优"
        if any(k in text for k in ["证据", "确定", "不确定", "依据", "信息"]):
            return "证据不足或信息不完整"
        if any(k in text for k in ["先", "再", "然后", "步骤", "顺序"]):
            return "任务需要分步推进"
        if any(k in text for k in ["交流", "关系", "情绪价值", "同伴"]):
            return "人际场域需要先做关系校准"
        return "遇到类似场景"

    def _abstract_action(self, text: str) -> str:
        if any(k in text for k in ["别", "不要", "不能", "不该", "收手", "退出"]):
            return "先收手并控制风险"
        if "先" in text and ("再" in text or "然后" in text):
            return "先做关键感知，再执行动作"
        if any(k in text for k in ["补", "确认", "查", "看", "判断"]):
            return "先补信息再给结论"
        if any(k in text for k in ["直接", "马上", "启动"]):
            return "先做低成本验证，再逐步加码"
        return "按小步验证-反馈迭代推进"

    def _abstract_decision_rule(self, text: str) -> str:
        cleaned = self._clean_text(text)
        if not cleaned:
            return "如果证据不足，就先补信息再判断。"
        if "如果" in cleaned and "就" in cleaned:
            return f"如果{self._abstract_condition(cleaned)}，就{self._abstract_action(cleaned)}。"
        if "先" in cleaned and ("再" in cleaned or "然后" in cleaned):
            return "先感知关键变量，再执行动作；不跳步骤硬推进。"
        if any(k in cleaned for k in ["别", "不要", "不能", "不该"]):
            return "先确认边界和风险，不做高风险硬冲。"
        return f"遇到类似场景时，{self._abstract_action(cleaned)}。"

    def _parse_context(
        self, context: str
    ) -> tuple[list[str], list[str], list[dict[str, str]], list[str], list[str], list[str]]:
        claims: list[str] = []
        styles: list[str] = []
        dialogues: list[dict[str, str]] = []
        lexicon: list[str] = []
        model_cards: list[str] = []
        decision_rules: list[str] = []
        mode = ""
        for raw_line in context.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line == "[CLAIMS]":
                mode = "claims"
                continue
            if line == "[STYLE_MEMORY]":
                mode = "style"
                continue
            if line == "[MODEL_CARDS]":
                mode = "models"
                continue
            if line == "[DECISION_RULES]":
                mode = "rules"
                continue
            if line == "[DIALOGUE_MEMORY]":
                mode = "dialogue"
                continue
            if line == "[LEXICON]":
                mode = "lexicon"
                continue
            if mode in {"claims", "style", "models", "rules"}:
                line = line.lstrip("- ").strip()
                if not line:
                    continue
                if mode == "claims":
                    claims.append(line)
                elif mode == "style":
                    styles.append(line)
                elif mode == "models":
                    model_cards.append(line)
                else:
                    decision_rules.append(line)
            elif mode == "dialogue":
                line = line.lstrip("- ").strip()
                if "=> reply:" not in line:
                    continue
                left, right = line.split("=> reply:", 1)
                left = left.replace("context:", "").strip()
                right = right.strip()
                if left and right:
                    dialogues.append({"context": left, "reply": right})
            elif mode == "lexicon":
                lexicon = [tok.strip() for tok in line.split(",") if tok.strip()]
        return claims, styles, dialogues, lexicon, model_cards, decision_rules

    def _pick_by_similarity(self, prompt: str, candidates: list[str]) -> str | None:
        best = None
        best_score = -1.0
        for text in candidates:
            score = jaccard_similarity(prompt, text)
            if score > best_score:
                best_score = score
                best = text
        if best_score <= 0 and candidates:
            h = int(hashlib.sha256(prompt.encode("utf-8")).hexdigest(), 16)
            return candidates[h % len(candidates)]
        return best

    def generate_response(self, prompt: str, context: str) -> str:
        if not context.strip():
            return "不太确定，先补点上下文。"

        claims, styles, dialogues, lexicon, model_cards, decision_rules = self._parse_context(context)
        lower_prompt = prompt.lower()
        normalized_prompt = self._clean_text(prompt)
        decision_prompt = any(k in prompt for k in ["建议", "要不要", "该不该", "怎么选", "决策", "上线", "补测试"])
        if any(k in prompt for k in ["编造", "虚构", "捏造", "不存在的履历", "杜撰"]) or any(
            k in lower_prompt for k in ["fabricate", "make up"]
        ):
            return "不编造。边界是只基于已知语料和证据说话，缺失信息我会明确说明。"
        if dialogues and not decision_prompt:
            exact_replies = []
            for pair in dialogues:
                pair_ctx = self._clean_text(pair["context"])
                if pair_ctx and pair_ctx == normalized_prompt:
                    exact_replies.append(pair["reply"])
            if exact_replies:
                cnt = Counter(exact_replies)
                return cnt.most_common(1)[0][0][:90]
            best_pair = None
            best_score = -1.0
            for pair in dialogues:
                score = jaccard_similarity(prompt, pair["context"])
                if score > best_score:
                    best_score = score
                    best_pair = pair
            if best_pair:
                adaptive_threshold = 0.035 if len(prompt) > 20 else 0.015
                if best_score >= adaptive_threshold:
                    return best_pair["reply"][:90]

        pick = self._pick_by_similarity(prompt, styles) or self._pick_by_similarity(prompt, claims)
        rule_pick = self._pick_by_similarity(prompt, decision_rules)
        model_pick = self._pick_by_similarity(prompt, model_cards)

        if not pick:
            return "先看风险再决定，信息不够我就不乱说。"

        if decision_prompt:
            if rule_pick:
                compact = rule_pick.replace("IF ", "").replace("THEN ", "→")
                if "建议" not in compact:
                    compact = f"建议：{compact}"
                if "风险" not in compact:
                    compact = f"{compact}；先看风险再执行"
                return compact[:90]
            if "先" in pick and "再" in pick:
                sentence = pick
                if "建议" not in sentence:
                    sentence = f"建议：{sentence}"
                if "风险" not in sentence:
                    sentence = f"{sentence}，并先补风险判断。"
                return sentence[:90]
            return f"建议：{pick}，先看风险再说。"[:86]

        if any(k in prompt for k in ["解释", "为什么", "咋", "怎么"]):
            rationale = model_pick or self._pick_by_similarity(prompt, claims) or "本质上先确认边界和信息。"
            return f"{pick}。{rationale}"[:90]

        if lexicon and len(pick) < 8:
            return f"{pick} {lexicon[0]}"[:80]
        return pick[:80]

    def _parse_agent_evidence(self, prompt: str) -> tuple[str, list[tuple[str, str]]]:
        section = ""
        section_match = re.search(r"SECTION:\s*([a-z_]+)", prompt)
        if section_match:
            section = section_match.group(1).strip()

        evidence: list[tuple[str, str]] = []
        for raw in prompt.splitlines():
            line = raw.strip()
            m = re.match(r"^\[(ev_\d+)\]\s+(.+)$", line)
            if not m:
                continue
            evidence.append((m.group(1), m.group(2).strip()))
        return section, evidence

    def _section_score(self, section: str, text: str) -> float:
        score = 0.0
        if section == "beliefs_and_values":
            if any(k in text for k in ["我觉得", "我认为", "我感觉", "价值", "原则"]):
                score += 1.2
        elif section == "mental_models":
            if any(k in text for k in ["因为", "所以", "本质", "逻辑", "如果", "就"]):
                score += 1.2
        elif section == "decision_heuristics":
            if any(k in text for k in ["先", "再", "然后", "如果", "就", "建议", "优先"]):
                score += 1.2
        elif section == "anti_patterns_and_limits":
            if any(k in text for k in ["不", "别", "不要", "不能", "没必要", "边界"]):
                score += 1.2
        elif section == "expression_dna":
            if len(text) <= 18 or any(k in text for k in ["？", "！", "哈哈", "笑死"]):
                score += 1.0
        score += min(len(text) / 80, 0.4)
        return score

    def _build_belief_claims(self, evidence: list[tuple[str, str]]) -> list[dict]:
        buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ev_id, text in evidence:
            theme = self._detect_theme(text)
            buckets[theme].append((ev_id, text))
        ranked = sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True)
        claims: list[dict] = []
        for theme, rows in ranked[:6]:
            ev_ids = [ev_id for ev_id, _ in rows[:3]]
            confidence = min(0.9, 0.58 + 0.08 * len(rows))
            tags = ["agent"]
            if len(rows) >= 2:
                tags.append("cross_context")
            if theme in {"risk_control", "evidence_boundary", "causal_accounting", "sequential_execution"}:
                tags.append("generative")
            if theme in {"social_calibration", "risk_control", "resource_leverage"}:
                tags.append("exclusive")
            claims.append(
                {
                    "claim": BELIEF_TEMPLATES.get(theme, BELIEF_TEMPLATES["resource_leverage"]),
                    "evidence_ids": ev_ids,
                    "confidence": round(confidence, 3),
                    "tags": sorted(set(tags)),
                }
            )
        return claims

    def _build_mental_model_claims(self, evidence: list[tuple[str, str]]) -> list[dict]:
        buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ev_id, text in evidence:
            buckets[self._detect_theme(text)].append((ev_id, text))
        ranked = sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True)
        claims: list[dict] = []
        for theme, rows in ranked[:6]:
            ev_ids = [ev_id for ev_id, _ in rows[:3]]
            confidence = min(0.93, 0.6 + 0.07 * len(rows))
            tags = ["agent", "generative", "exclusive"]
            if len(rows) >= 2:
                tags.append("cross_context")
            claims.append(
                {
                    "claim": MENTAL_MODEL_TEMPLATES.get(theme, MENTAL_MODEL_TEMPLATES["resource_leverage"]),
                    "evidence_ids": ev_ids,
                    "confidence": round(confidence, 3),
                    "tags": sorted(set(tags)),
                }
            )
        return claims

    def _build_decision_claims(self, evidence: list[tuple[str, str]]) -> list[dict]:
        counter: Counter[str] = Counter()
        refs: dict[str, list[str]] = defaultdict(list)
        for ev_id, text in evidence:
            rule = self._abstract_decision_rule(text)
            if not rule:
                continue
            counter[rule] += 1
            refs[rule].append(ev_id)
        claims: list[dict] = []
        for rule, freq in counter.most_common(8):
            confidence = min(0.9, 0.57 + 0.07 * freq)
            tags = ["agent", "if_then"]
            if freq >= 2:
                tags.append("cross_context")
            claims.append(
                {
                    "claim": rule,
                    "evidence_ids": refs[rule][:3],
                    "confidence": round(confidence, 3),
                    "tags": tags,
                }
            )
        return claims

    def _build_anti_claims(self, evidence: list[tuple[str, str]]) -> list[dict]:
        neg_rows = [(ev_id, text) for ev_id, text in evidence if any(k in text for k in ["不", "别", "不要", "不能", "没必要"])]
        if not neg_rows:
            neg_rows = evidence[:]
        buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for ev_id, text in neg_rows:
            buckets[self._detect_theme(text)].append((ev_id, text))
        ranked = sorted(buckets.items(), key=lambda x: len(x[1]), reverse=True)
        claims: list[dict] = []
        for theme, rows in ranked[:6]:
            claim = ANTI_BOUNDARY_TEMPLATES.get(theme, ANTI_BOUNDARY_TEMPLATES["risk_control"])
            confidence = min(0.92, 0.6 + 0.06 * len(rows))
            tags = ["agent", "boundary"]
            if len(rows) >= 2:
                tags.append("cross_context")
            claims.append(
                {
                    "claim": claim,
                    "evidence_ids": [ev_id for ev_id, _ in rows[:3]],
                    "confidence": round(confidence, 3),
                    "tags": tags,
                }
            )
        return claims

    def run_agent(self, prompt: str) -> str:
        section, evidence = self._parse_agent_evidence(prompt)
        if not evidence:
            return '{"claims":[]}'
        scored = sorted(evidence, key=lambda x: self._section_score(section, x[1]), reverse=True)[:96]
        if section == "beliefs_and_values":
            claims = self._build_belief_claims(scored)
        elif section == "mental_models":
            claims = self._build_mental_model_claims(scored)
        elif section == "decision_heuristics":
            claims = self._build_decision_claims(scored)
        elif section == "anti_patterns_and_limits":
            claims = self._build_anti_claims(scored)
        else:
            claims = []
        if not claims:
            fallback_claims = []
            for ev_id, text in scored[:6]:
                claim = self._clean_text(text)
                if not claim:
                    continue
                fallback_claims.append(
                    {
                        "claim": claim[:160],
                        "evidence_ids": [ev_id],
                        "confidence": 0.58,
                        "tags": ["agent", "fallback"],
                    }
                )
            claims = fallback_claims
        return json.dumps({"claims": claims[:8]}, ensure_ascii=False)
