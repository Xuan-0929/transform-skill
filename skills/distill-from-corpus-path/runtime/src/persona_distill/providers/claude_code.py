from __future__ import annotations

from difflib import SequenceMatcher
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .base import ModelProvider
from ..utils import jaccard_similarity


CLI_AUTH_PATTERNS = [
    re.compile(r"not logged in", re.IGNORECASE),
    re.compile(r"\blogin\b", re.IGNORECASE),
    re.compile(r"authentication", re.IGNORECASE),
    re.compile(r"please run /login", re.IGNORECASE),
    re.compile(r"please run .* login", re.IGNORECASE),
    re.compile(r"loggedin['\":\s]*false", re.IGNORECASE),
]

STRUCTURE_REQUEST_PATTERNS = (
    "分点",
    "步骤",
    "详细",
    "展开",
    "清单",
    "列表",
    "结构化",
    "逐条",
    "表格",
    "分析",
)

OPTION_REQUEST_PATTERNS = (
    "选项",
    "备选",
    "几种",
    "几个方案",
    "怎么选",
    "对比",
    "三选一",
    "二选一",
)

TEMPLATE_HEADING_PATTERNS = (
    r"结论\s*[:：]",
    r"理由(?:很简单)?\s*[:：]",
    r"现在就执行\s*[:：]",
    r"执行步骤\s*[:：]",
)

YES_NO_QUERY_HINTS = ("是不是", "有没有", "行不行", "能不能", "要不要", "对不对", "了没有", "说了没有")
NEGATIVE_QUERY_HINTS = ("没有", "没", "不是", "不太", "不行", "没讲", "没说", "没来")
WHY_QUERY_HINTS = ("为什么", "为何", "咋")
APOLOGY_HINTS = ("sry", "sorry", "抱歉", "对不起", "不好意思")
THANKS_HINTS = ("谢谢", "thx", "thanks")
VULNERABILITY_HINTS = ("退缩", "怕", "慌", "紧张", "焦虑", "虚", "不敢", "没看懂", "看不懂", "不会", "不太会")
STANCE_ACK_HINTS = ("毕竟", "原来", "居然", "还是", "确实", "同道中人")
COMPREHENSION_HINTS = ("没看懂", "看不懂", "不懂", "没听懂", "听不懂", "啥意思", "什么意思")
LAUGH_REACTION_HINTS = ("笑", "搞笑", "哈哈", "哈", "乐", "绷")
PANIC_REACTION_HINTS = ("完了", "卧槽", "我去", "可恶", "牛逼", "nb", "炸", "离谱", "逆天", "寄", "瓦", "崩", "塌")
MEMORY_FRAGMENT_HINTS = ("圣诞节", "没人陪", "陪我", "今天", "昨天", "前天", "生日", "礼物")
COMPLETION_DONE_HINTS = (
    "跑完了",
    "看完了",
    "读完了",
    "听完了",
    "写完了",
    "做完了",
    "弄完了",
    "装完了",
    "下完了",
    "下载完了",
    "更新完了",
    "改完了",
    "测完了",
    "训完了",
    "编译完了",
    "吃完了",
)
AFFIRMATIVE_REPLY_HINTS = ("是的", "对的", "可以", "可以的", "好的", "好滴", "行", "行吧", "ok", "哦对", "嗯", "有", "确实", "还真是", "是啊", "对啊")
NEGATIVE_REPLY_HINTS = ("不是", "没有", "没呢", "不行", "不对", "别", "算了", "不太", "没来")
UNCERTAIN_REPLY_HINTS = ("不知道", "难说", "不好说", "看情况", "不确定", "大概率")
ADVICE_INTENT_HINTS = ("怎么", "如何", "要不要", "该不该", "建议", "步骤", "方案", "咋整", "咋办")
LOW_INFO_CHARS = set("的了啊吧吗呢是就也太很有在我你他她它这那个和都还真嘛呀哦嗯哈")
PRESCRIPTIVE_TONE_HINTS = ("先", "再", "步骤", "方案", "建议", "应该", "优先", "执行", "别")
GENERIC_CATCHPHRASES = {
    "还真是",
    "确实",
    "是的",
    "对的",
    "可以",
    "好的",
    "好滴",
    "嗯",
    "哦对",
    "不知道",
    "难说",
}
STACKABLE_CATCHPHRASE_MARKERS = (
    "还真是",
    "还真",
    "确实",
    "是的",
    "对的",
    "可以",
    "好的",
    "好滴",
    "嗯",
    "哦对",
    "卧槽",
    "笑死",
    "启动",
)


class ClaudeCodeProviderError(RuntimeError):
    pass


class ClaudeCodeAuthError(ClaudeCodeProviderError):
    pass


@dataclass
class ClaudeResult:
    text: str
    stderr: str
    returncode: int


def resolve_runtime_cli(preference: str = "auto") -> str:
    normalized = (preference or "auto").strip().lower()
    if normalized not in {"auto", "claude", "codex"}:
        raise ValueError("DISTILL_RUNTIME_CLI must be one of: auto, claude, codex.")
    if normalized in {"claude", "codex"}:
        return normalized

    codex_available = shutil.which("codex") is not None
    claude_available = shutil.which("claude") is not None

    # Prefer host-native CLI when running in Codex desktop/CLI environments.
    if os.environ.get("CODEX_SHELL") == "1" or os.environ.get("CODEX_THREAD_ID"):
        if codex_available:
            return "codex"

    # Backward-compatible fallback order for generic shell contexts.
    if claude_available:
        return "claude"
    if codex_available:
        return "codex"
    return "claude"


class ClaudeCodeProvider(ModelProvider):
    """Runtime provider that delegates content operations to host CLI runtime."""

    def __init__(
        self,
        cli_path: str | None = None,
        runtime_cli: str = "auto",
        model: str | None = None,
        timeout_sec: int = 90,
    ) -> None:
        self.runtime_cli = resolve_runtime_cli(runtime_cli)
        resolved_cli = (cli_path or self.runtime_cli).strip()
        provider_name = f"{self.runtime_cli}_cli"
        super().__init__(provider=provider_name, model=model or "default")
        self.cli_path = resolved_cli
        self.timeout_sec = max(20, int(timeout_sec))

    def refine_claim(self, section: str, candidate: str) -> str:
        prompt = (
            "You are a strict claim refiner for persona distillation.\n"
            f"SECTION: {section}\n"
            "Task:\n"
            "1) Rewrite the claim into compact transferable language.\n"
            "2) Keep original intent.\n"
            "3) Keep language in Chinese when possible; never translate into English by default.\n"
            "4) Preserve distinctive colloquial texture when it carries persona identity.\n"
            "5) Avoid copying chat trivia.\n"
            "Output rules:\n"
            "- Return plain text only.\n"
            "- Max 180 characters.\n"
            "- No markdown.\n\n"
            f"Candidate:\n{candidate}\n"
        )
        refined = self._ask_text(prompt)
        cleaned = self._clean_text(refined)
        if cleaned:
            return cleaned[:180]
        fallback = self._clean_text(candidate)
        return fallback[:180] or "信息不足，先补证据再判断。"

    def summarize_section(self, section: str, claims: list[str]) -> str:
        if not claims:
            return "No strong signal found."
        prompt = (
            "Summarize persona claims as one compact operational sentence.\n"
            f"SECTION: {section}\n"
            "Constraints:\n"
            "- Chinese output\n"
            "- max 80 chars\n"
            "- no markdown\n\n"
            "Claims:\n"
            + "\n".join(f"- {c}" for c in claims[:12])
        )
        text = self._clean_text(self._ask_text(prompt))
        return text[:80] if text else "No strong signal found."

    def generate_response(self, prompt: str, context: str) -> str:
        turn_mode = self._extract_turn_mode(context, prompt)
        recent = self._recent_context_reaction(prompt=prompt, context=context)
        if recent:
            if not self._should_defer_alignment_short_reply(reply=recent, prompt=prompt, context=context):
                guarded_recent = self._apply_style_guard(reply=recent, prompt=prompt, context=context)
                if guarded_recent:
                    return guarded_recent
        affective_echo = self._maybe_affective_echo(prompt)
        if affective_echo:
            if not self._should_defer_alignment_short_reply(reply=affective_echo, prompt=prompt, context=context):
                guarded_echo = self._apply_style_guard(reply=affective_echo, prompt=prompt, context=context)
                if guarded_echo:
                    return guarded_echo
        if self._should_try_prior(prompt=prompt, context=context) and not self._should_skip_prior_for_recent_context(
            prompt=prompt,
            context=context,
        ):
            prior = self._maybe_prior_reply(prompt=prompt, context=context)
            if prior:
                if not self._should_defer_generic_prior(
                    reply=prior,
                    prompt=prompt,
                    context=context,
                ) and not self._should_defer_alignment_short_reply(
                    reply=prior,
                    prompt=prompt,
                    context=context,
                ) and not self._should_defer_low_info_reaction(
                    reply=prior,
                    prompt=prompt,
                    context=context,
                ):
                    guarded_prior = self._apply_style_guard(reply=prior, prompt=prompt, context=context)
                    if guarded_prior:
                        return guarded_prior
        cached = self._maybe_memory_reply(prompt=prompt, context=context)
        if cached:
            if not self._should_defer_alignment_memory_reply(reply=cached, prompt=prompt, context=context):
                guarded_cached = self._apply_style_guard(reply=cached, prompt=prompt, context=context)
                if guarded_cached:
                    return guarded_cached

        req = (
            "You are emulating a distilled persona.\n"
            "Respond to the user prompt using provided persona context.\n"
            "Priority:\n"
            "L0) Follow TURN_PROFILE first: this defines current turn objective.\n"
            "L1) Preserve stable persona core: PERSONA_CORE + HABIT_PROFILE.\n"
            "L2) Use DECISION_RULES + MODEL_CARDS only when user asks for strategy/reasoning.\n"
            "L3) Then solve the user's task under that core.\n"
            "L4) Finally render expression style from EXPRESSION_DNA / STYLE_MEMORY / CATCHPHRASE_HINTS.\n"
            "L5) Before wording, pick one dialogue act that matches this turn (acknowledge / comfort / clarify / react / advise).\n"
            "Rules:\n"
            "- keep semantic intent aligned with the user prompt first\n"
            "- do not fabricate unknown facts\n"
            "- if asked to fabricate, explicitly refuse and mention boundary\n"
            "- you are the persona, not a consultant, not a report generator\n"
            "- write natural dialogue, not abstract personality slogans\n"
            "- keep value stance and decision tendency consistent with PERSONA_CORE\n"
            "- treat catchphrases as optional flavor only; never force them if semantic intent does not match\n"
            "- avoid stacking multiple habitual markers in one substantive reply; if a catchphrase helps, one light touch is usually enough\n"
            "- do not optimize for exact sentence reuse from corpus; preserve persona mechanism over wording overlap\n"
            "- when DIALOGUE_MEMORY and PERSONA_CORE conflict, PERSONA_CORE wins\n"
            "- response length should be decided by conversational need and persona reasoning, not fixed char bands\n"
            "- default to natural conversational tone, avoid fixed report templates\n"
            "- do not force '结论/理由/执行' headings unless user explicitly requests structure\n"
            "- do not switch to tutorial/document tone unless user explicitly requests it\n"
            "- do not invent concrete option lists (e.g., dish names, places, itineraries) without evidence or explicit request\n"
            "- use DIALOGUE_MEMORY as style evidence, not retrieval target; avoid parroting context-matched phrases\n"
            "- when EVAL_RECENT_CONTEXT exists, treat it as the live chat transcript for this turn\n"
            "- when EVAL_TARGET_SPEAKER exists, you are that speaker; answer as their next message in the live thread\n"
            "- when EVAL_RECENT_CONTEXT exists, first reconstruct the active thread: latest non-target turn, target speaker's recent stance/question, and the object under discussion\n"
            "- do not answer the latest line as a helpful assistant; continue what EVAL_TARGET_SPEAKER would naturally say next in that thread\n"
            "- if EVAL_TARGET_SPEAKER just asked a skeptical question or comparison, reply as a follow-up judgement/challenge grounded in that stance\n"
            "- in debate threads, target speaker's last stated side wins over the latest speaker's framing\n"
            "- if the latest turn challenges EVAL_TARGET_SPEAKER's prior claim, defend or clarify that stance instead of becoming neutral\n"
            "- in PERSONA_ALIGNMENT_MODE, identify EVAL_TARGET_SPEAKER's latest explicit stance before answering; if it contains X-not-Y / Y-not-X contrast, keep the same polarity\n"
            "- if EVAL_TARGET_STANCE exists, preserve that stance over generic PERSONA_CORE summaries\n"
            "- If the target speaker's previous turn was a question, respond as their follow-up after hearing the answer, not as a neutral summary of the answer\n"
            "- in group chats, the latest prompt can come from a third person; continue the target speaker's active thread, not a generic assistant conversation\n"
            "- if recent target-speaker messages contain concrete facts, entities, numbers, or stance, use those as grounding for the next reply\n"
            "- do not collapse context-rich turns into generic acknowledgements like '还真是' unless that is genuinely enough for the thread\n"
            "- keep lexical choices close to STYLE_MEMORY and LEXICON, avoid generic motivational filler\n"
            "- do not prepend habitual catchphrases by default; only use them when semantically natural for this prompt\n"
            "- if a reply already contains concrete stance/content, do not decorate it with extra catchphrase seasoning\n"
            "- do not use another group participant's name as a catchphrase or stylistic opener\n"
            "- do not reuse a memorized reply if it breaks the current live thread\n"
            "- do not introduce unrelated topics/entities that are absent from the user prompt\n"
            "- for casual chat / acknowledgement turns, first mirror meaning/emotion; expand only when user asks for reasoning or steps\n"
            "- for casual_alignment_first turns, prefer one concise sentence that matches the chosen dialogue act\n"
            "- if STYLE_PROFILE shows short-median persona and prompt is short, stay compact unless user asks for detail\n"
            "- for short casual prompts, keep at least one key term or semantic anchor from the user prompt\n"
            "- when PERSONA_ALIGNMENT_MODE exists, avoid replying with only a low-information catchphrase; add one concrete stance, reason, or next move from the persona mechanism\n"
            "- in PERSONA_ALIGNMENT_MODE, for laugh/meme reactions, add one tiny concrete reason from EVAL_RECENT_CONTEXT when available; stay in chat mode, not explanation mode\n"
            "- if evidence is insufficient, say so directly and ask at most one clarifying question\n"
            "- plain text only\n"
            "Negative examples to avoid unless user asks:\n"
            "- '结论：... 理由很简单：... 现在就执行：...'\n"
            "- '给你三个套餐/三选一' when user did not ask for options\n"
            "- plain text only\n\n"
            f"[PROMPT]\n{prompt}\n\n"
            f"[PERSONA_CONTEXT]\n{context}\n"
        )
        reply = self._clean_text(self._ask_text(req))
        if self._needs_generic_catchphrase_rewrite(prompt=prompt, reply=reply, context=context):
            generic_req = (
                req
                + "\n[GENERIC_CATCHPHRASE_FIX]\n"
                + "The draft is only a low-information catchphrase.\n"
                + "Rewrite it as the persona's next message in this live thread:\n"
                + "1) preserve the persona's value stance and recent target-speaker stance;\n"
                + "2) use concrete context from EVAL_RECENT_CONTEXT;\n"
                + "3) do not use generic fillers like 还真是/确实/不知道 as the whole reply;\n"
                + "4) keep the persona's natural length."
            )
            try:
                rewritten = self._clean_text(self._ask_text(generic_req))
            except Exception:
                rewritten = ""
            if rewritten and not self._is_generic_catchphrase(rewritten):
                reply = rewritten
        if self._needs_stacked_catchphrase_rewrite(prompt=prompt, reply=reply, context=context):
            stacked_req = (
                req
                + "\n[STACKED_CATCHPHRASE_FIX]\n"
                + "The draft stacks multiple habitual markers, making the persona sound performed.\n"
                + "Rewrite it as the same persona's next message:\n"
                + "1) preserve concrete stance, topic, and recent target-speaker continuity;\n"
                + "2) keep the natural dialogue act and natural length;\n"
                + "3) use at most a light touch of catchphrase flavor when it is semantically earned;\n"
                + "4) do not turn it into an explanation or assistant-style report."
            )
            try:
                rewritten = self._clean_text(self._ask_text(stacked_req))
            except Exception:
                rewritten = ""
            if rewritten and not self._has_stacked_catchphrases(rewritten):
                reply = rewritten
        if self._has_other_speaker_name_catchphrase(reply, prompt, context):
            speaker_req = (
                req
                + "\n[SPEAKER_NAME_CATCHPHRASE_FIX]\n"
                + "The draft uses another group participant's name as a catchphrase instead of a real thought.\n"
                + "Rewrite it as the target speaker's natural next message:\n"
                + "1) keep the current topic and live-thread continuity;\n"
                + "2) replace the name-as-meme with a concrete judgement or next move;\n"
                + "3) keep it short and conversational;\n"
                + "4) do not copy the previous wording."
            )
            try:
                rewritten = self._clean_text(self._ask_text(speaker_req))
            except Exception:
                rewritten = ""
            if rewritten and not self._has_other_speaker_name_catchphrase(rewritten, prompt, context):
                reply = rewritten
        if self._should_defer_low_info_reaction(reply=reply, prompt=prompt, context=context):
            reaction_req = (
                req
                + "\n[LOW_INFO_REACTION_FIX]\n"
                + "The draft is only a generic laugh/reaction while recent context contains concrete material.\n"
                + "Rewrite it as the persona's next chat message:\n"
                + "1) keep the laugh/reaction energy if natural;\n"
                + "2) include one concrete reason or object from EVAL_RECENT_CONTEXT;\n"
                + "3) keep it short and conversational;\n"
                + "4) do not become explanatory or assistant-like."
            )
            try:
                rewritten = self._clean_text(self._ask_text(reaction_req))
            except Exception:
                rewritten = ""
            if rewritten and not self._is_generic_laugh_reply(rewritten):
                reply = rewritten
        if self._contains_context_disconnected_memory_fragment(prompt=prompt, reply=reply, context=context):
            fragment_req = (
                req
                + "\n[DISCONNECTED_FRAGMENT_FIX]\n"
                + "The draft contains a memorized fragment that is not grounded in the current live thread.\n"
                + "Rewrite it as the target speaker's next chat message:\n"
                + "1) keep only details supported by PROMPT or EVAL_RECENT_CONTEXT;\n"
                + "2) preserve persona stance and natural tone;\n"
                + "3) remove unrelated remembered anecdotes;\n"
                + "4) keep it concise, not explanatory."
            )
            try:
                rewritten = self._clean_text(self._ask_text(fragment_req))
            except Exception:
                rewritten = ""
            if rewritten and not self._contains_context_disconnected_memory_fragment(
                prompt=prompt,
                reply=rewritten,
                context=context,
            ):
                reply = rewritten
        if self._should_casual_rewrite(prompt=prompt, reply=reply, turn_mode=turn_mode, context=context):
            casual_req = (
                req
                + "\n[CASUAL_ALIGNMENT_FIX]\n"
                + "User turn is not a strategy request.\n"
                + "Rewrite as natural conversational alignment:\n"
                + "1) keep original meaning/proposition;\n"
                + "2) keep persona tone;\n"
                + "3) choose exactly one dialogue act (ack/comfort/react/clarify) and avoid mixed modes;\n"
                + "4) avoid prescriptive playbook/tactical guidance unless explicitly asked;\n"
                + "5) if prompt is short and persona median is short, keep reply concise."
            )
            try:
                casual_rewrite = self._clean_text(self._ask_text(casual_req))
            except Exception:
                casual_rewrite = ""
            if casual_rewrite:
                if self._semantic_match_score(prompt, casual_rewrite) >= self._semantic_match_score(prompt, reply):
                    reply = casual_rewrite
        semantic_floor = 0.09 if self._is_micro_social_turn(prompt) else 0.12
        if self._semantic_match_score(prompt, reply) < semantic_floor:
            revise_req = (
                req
                + "\n[SEMANTIC_ALIGNMENT_FIX]\n"
                + "Rewrite the draft to keep the same topic/proposition as PROMPT.\n"
                + "Do not add new entities or unrelated frameworks.\n"
                + "Keep persona tone but prioritize semantic alignment."
            )
            try:
                revised = self._clean_text(self._ask_text(revise_req))
            except Exception:
                revised = ""
            if revised:
                base_score = self._semantic_match_score(prompt, reply)
                revised_score = self._semantic_match_score(prompt, revised)
                if revised_score >= base_score + 0.05:
                    reply = revised
        if self._contains_irrelevant_style_quote(prompt=prompt, reply=reply, context=context):
            decontam_req = (
                req
                + "\n[STYLE_DECONTAM_FIX]\n"
                + "Rewrite draft with same meaning and tone, but remove unrelated long memorized phrases.\n"
                + "Do not add new entities."
            )
            try:
                decontam = self._clean_text(self._ask_text(decontam_req))
            except Exception:
                decontam = ""
            if decontam and self._semantic_match_score(prompt, decontam) >= self._semantic_match_score(prompt, reply):
                reply = decontam
        if self._looks_recent_context_miss(prompt=prompt, reply=reply, context=context):
            context_req = (
                req
                + "\n[RECENT_CONTEXT_THREADING_FIX]\n"
                + "The draft missed the live thread.\n"
                + "Rewrite as the next message from EVAL_TARGET_SPEAKER:\n"
                + "1) inspect the last 10-30 lines of EVAL_RECENT_CONTEXT;\n"
                + "2) identify which concrete thread the latest prompt belongs to;\n"
                + "3) reuse concrete facts or stance from recent target-speaker messages when relevant;\n"
                + "4) avoid generic acknowledgements if the transcript contains specific content;\n"
                + "5) keep the persona's natural length and tone."
            )
            try:
                grounded = self._clean_text(self._ask_text(context_req))
            except Exception:
                grounded = ""
            if grounded and not self._looks_recent_context_miss(prompt=prompt, reply=grounded, context=context):
                reply = grounded
        guarded = self._apply_style_guard(reply=reply, prompt=prompt, context=context)
        return guarded if guarded else "不编造，信息不足就先说明边界。"

    def run_agent(self, prompt: str) -> str:
        req = (
            "You are a strict JSON extractor.\n"
            "Follow the user's schema requirements exactly.\n"
            "Output JSON only. No markdown fences. No explanation.\n\n"
            + prompt
        )
        raw = self._ask_text(req)
        payload = self._extract_json_block(raw)
        if not payload:
            return '{"claims":[]}'
        return payload

    def _ask_text(self, prompt: str) -> str:
        result = self._run_runtime(prompt)
        output = (result.text or "").strip()
        if output:
            return output
        raise ClaudeCodeProviderError("Host runtime returned empty output.")

    def _run_runtime(self, prompt: str) -> ClaudeResult:
        if self.runtime_cli == "codex":
            return self._run_codex(prompt)
        return self._run_claude(prompt)

    def _run_claude(self, prompt: str) -> ClaudeResult:
        cmd = [self.cli_path, "-p", "--output-format", "text", prompt]
        if self.model and self.model != "default":
            cmd.extend(["--model", self.model])

        return self._run_cmd(cmd, runtime_name="Claude")

    def _run_codex(self, prompt: str) -> ClaudeResult:
        with tempfile.NamedTemporaryFile(prefix="distill_codex_", suffix=".txt", delete=False) as fp:
            output_path = Path(fp.name)

        cmd = [
            self.cli_path,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            prompt,
        ]
        if self.model and self.model != "default":
            cmd[2:2] = ["--model", self.model]

        try:
            result = self._run_cmd(cmd, runtime_name="Codex")
            text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            if text:
                return ClaudeResult(text=text, stderr=result.stderr, returncode=result.returncode)
            return result
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _run_cmd(self, cmd: list[str], runtime_name: str) -> ClaudeResult:
        env = os.environ.copy()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ClaudeCodeProviderError(
                f"{runtime_name} runtime command is unavailable in this host session."
            ) from exc
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            merged = f"{stdout}\n{stderr}".strip()
            if self._is_auth_error(merged):
                raise ClaudeCodeAuthError(
                    f"{runtime_name} runtime is not authenticated in the current host session."
                )
            raise ClaudeCodeProviderError(
                f"{runtime_name} runtime command failed (exit={proc.returncode}): {merged or 'no error text'}"
            )
        return ClaudeResult(text=stdout, stderr=stderr, returncode=proc.returncode)

    @staticmethod
    def _is_auth_error(text: str) -> bool:
        sample = text.strip()
        if not sample:
            return False
        return any(p.search(sample) for p in CLI_AUTH_PATTERNS)

    @staticmethod
    def _clean_text(text: str) -> str:
        line = text.strip()
        line = re.sub(r"\s+", " ", line).strip()
        line = line.strip("`")
        return line

    @staticmethod
    def _wants_structure(prompt: str) -> bool:
        lowered = prompt.lower()
        return any(token in prompt for token in STRUCTURE_REQUEST_PATTERNS) or any(
            token in lowered for token in ("step by step", "structured", "bullet", "outline")
        )

    @staticmethod
    def _wants_options(prompt: str) -> bool:
        lowered = prompt.lower()
        return any(token in prompt for token in OPTION_REQUEST_PATTERNS) or any(
            token in lowered for token in ("options", "alternatives", "compare")
        )

    @staticmethod
    def _extract_style_length_mode(context: str) -> str:
        if not context:
            return "balanced"
        match = re.search(r"response_length_mode:\s*(terse|balanced|expansive)", context)
        if not match:
            return "balanced"
        return match.group(1)

    @staticmethod
    def _extract_short_reply_ratio(context: str) -> float:
        if not context:
            return 0.0
        match = re.search(r"short_reply_ratio:\s*([0-9]+(?:\.[0-9]+)?)", context)
        if not match:
            return 0.0
        try:
            return max(0.0, min(1.0, float(match.group(1))))
        except Exception:
            return 0.0

    @staticmethod
    def _extract_median_chars(context: str) -> float:
        if not context:
            return 0.0
        match = re.search(r"observed_median_chars_per_turn:\s*([0-9]+(?:\.[0-9]+)?)", context)
        if not match:
            return 0.0
        try:
            return max(0.0, float(match.group(1)))
        except Exception:
            return 0.0

    @staticmethod
    def _extract_reply_priors(context: str) -> dict[str, list[str]]:
        if "[REPLY_PRIORS]" not in context:
            return {}
        section = context.split("[REPLY_PRIORS]", 1)[1]
        if "[LEXICON]" in section:
            section = section.split("[LEXICON]", 1)[0]
        priors: dict[str, list[str]] = {}
        for line in section.splitlines():
            cleaned = line.strip()
            if not cleaned.startswith("- "):
                continue
            body = cleaned[2:]
            if ":" not in body:
                continue
            bucket, values = body.split(":", 1)
            key = bucket.strip()
            candidates = [v.strip() for v in values.split("|") if v.strip()]
            if candidates:
                priors[key] = candidates
        return priors

    @staticmethod
    def _extract_dialogue_pairs(context: str, limit: int = 80) -> list[tuple[str, str]]:
        if "[DIALOGUE_MEMORY]" not in context:
            return []
        section = context.split("[DIALOGUE_MEMORY]", 1)[1]
        if "[LEXICON]" in section:
            section = section.split("[LEXICON]", 1)[0]
        pairs: list[tuple[str, str]] = []
        for line in section.splitlines():
            cleaned = line.strip()
            if not cleaned.startswith("- context:"):
                continue
            m = re.match(r"- context:\s*(.*?)\s*=>\s*reply:\s*(.*)", cleaned)
            if not m:
                continue
            ctx = m.group(1).strip()
            rep = m.group(2).strip()
            if not ctx or not rep:
                continue
            pairs.append((ctx, rep))
            if len(pairs) >= limit:
                break
        return pairs

    @staticmethod
    def _extract_style_memory(context: str, limit: int = 24) -> list[str]:
        if "[STYLE_MEMORY]" not in context:
            return []
        section = context.split("[STYLE_MEMORY]", 1)[1]
        for marker in ("[DIALOGUE_MEMORY]", "[REPLY_PRIORS]", "[LEXICON]", "[CATCHPHRASE_HINTS]"):
            if marker in section:
                section = section.split(marker, 1)[0]
        rows: list[str] = []
        for line in section.splitlines():
            cleaned = line.strip()
            if not cleaned.startswith("- "):
                continue
            value = cleaned[2:].strip()
            if value:
                rows.append(value)
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def _extract_recent_context_lines(context: str, limit: int = 60) -> list[tuple[str, str]]:
        if "[EVAL_RECENT_CONTEXT]" not in context:
            return []
        section = context.split("[EVAL_RECENT_CONTEXT]", 1)[1]
        rows: list[tuple[str, str]] = []
        for line in section.splitlines():
            cleaned = line.strip()
            if not cleaned.startswith("- "):
                continue
            body = cleaned[2:].strip()
            if ":" not in body:
                continue
            speaker, text = body.split(":", 1)
            speaker = speaker.strip()
            text = text.strip()
            if speaker and text:
                rows.append((speaker, text))
            if len(rows) >= limit:
                break
        return rows

    @staticmethod
    def _has_eval_recent_context(context: str) -> bool:
        return "[EVAL_RECENT_CONTEXT]" in (context or "")

    @staticmethod
    def _extract_eval_target_speaker(context: str) -> str:
        if "[EVAL_TARGET_SPEAKER]" not in context:
            return ""
        section = context.split("[EVAL_TARGET_SPEAKER]", 1)[1]
        if "[EVAL_RECENT_CONTEXT]" in section:
            section = section.split("[EVAL_RECENT_CONTEXT]", 1)[0]
        for line in section.splitlines():
            cleaned = line.strip().lstrip("- ").strip()
            if cleaned:
                return cleaned
        return ""

    @classmethod
    def _recent_target_text(cls, context: str, limit: int = 12) -> str:
        target = cls._extract_eval_target_speaker(context)
        if not target:
            return ""
        rows = cls._extract_recent_context_lines(context)
        chunks = [text for speaker, text in rows if speaker == target and text.strip()]
        return " ".join(chunks[-limit:])

    @classmethod
    def _recent_non_target_speakers(cls, context: str) -> list[str]:
        target = cls._extract_eval_target_speaker(context)
        names: list[str] = []
        for speaker, _ in cls._extract_recent_context_lines(context):
            if not speaker or speaker == target or speaker in names:
                continue
            names.append(speaker)
        # Longer names first prevents a short alias from partially stripping a full name.
        return sorted(names, key=len, reverse=True)

    @classmethod
    def _strip_other_speaker_name_as_catchphrase(cls, text: str, prompt: str, context: str) -> str:
        cleaned = text.strip()
        if not cleaned:
            return ""
        prompt_compact = cls._normalize_probe(prompt)
        for speaker in cls._recent_non_target_speakers(context):
            if cls._normalize_probe(speaker) in prompt_compact:
                continue
            escaped = re.escape(speaker)
            patterns = (
                rf"^(?:真|又|这也太)?{escaped}[，,。.\s]+",
                rf"^(?:真|又|这也太)?{escaped}了属于是[，,。.\s]*",
                rf"\s+(?:真|又)?{escaped}[。.!！?\s]*$",
            )
            for pattern in patterns:
                stripped = re.sub(pattern, "", cleaned).strip()
                if stripped != cleaned:
                    return stripped.strip(" ，,;；")
        return cleaned

    @classmethod
    def _has_other_speaker_name_catchphrase(cls, text: str, prompt: str, context: str) -> bool:
        cleaned = text.strip()
        if not cleaned:
            return False
        prompt_compact = cls._normalize_probe(prompt)
        for speaker in cls._recent_non_target_speakers(context):
            if cls._normalize_probe(speaker) in prompt_compact:
                continue
            escaped = re.escape(speaker)
            patterns = (
                rf"^(?:真|又|这也太)?{escaped}[，,。.\s]+",
                rf"^(?:真|又|这也太)?{escaped}了属于是(?:[，,。.\s]|$)",
                rf"(?:^|[，,。.\s]+)(?:纯|真|又)?{escaped}了(?:[，,。.\s]|$)",
                rf"\s+(?:真|又)?{escaped}[。.!！?\s]*$",
            )
            if any(re.search(pattern, cleaned) for pattern in patterns):
                return True
        return False

    @classmethod
    def _is_generic_catchphrase(cls, text: str) -> bool:
        compact = cls._normalize_probe(text)
        if not compact:
            return False
        return compact in {cls._normalize_probe(item) for item in GENERIC_CATCHPHRASES}

    @classmethod
    def _catchphrase_marker_count(cls, text: str) -> int:
        compact = cls._normalize_probe(text)
        if not compact:
            return 0
        count = 0
        for marker in STACKABLE_CATCHPHRASE_MARKERS:
            normalized = cls._normalize_probe(marker)
            if normalized and normalized in compact:
                count += 1
        return count

    @classmethod
    def _has_stacked_catchphrases(cls, text: str) -> bool:
        return cls._catchphrase_marker_count(text) >= 2

    @classmethod
    def _is_generic_laugh_reply(cls, text: str) -> bool:
        compact = cls._normalize_probe(text)
        return compact in {"笑死", "笑死了", "笑死我了", "哈哈", "哈哈哈", "哈哈哈哈"}

    @staticmethod
    def _is_persona_alignment_mode(context: str) -> bool:
        return "[PERSONA_ALIGNMENT_MODE]" in (context or "") or os.environ.get("DISTILL_PERSONA_ALIGNMENT_MODE") == "1"

    @classmethod
    def _is_low_information_reply(cls, text: str) -> bool:
        compact = cls._normalize_probe(text)
        if not compact:
            return False
        if len(compact) <= 4:
            return True
        if cls._is_generic_catchphrase(text):
            return True
        if len(compact) <= 8 and (cls._reply_polarity(text) or cls._reaction_intent(text)):
            return True
        return False

    @classmethod
    def _should_defer_alignment_short_reply(cls, *, reply: str, prompt: str, context: str) -> bool:
        if not cls._is_persona_alignment_mode(context):
            return False
        if not cls._has_eval_recent_context(context):
            return False
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return False
        return cls._is_low_information_reply(reply)

    @classmethod
    def _should_defer_alignment_memory_reply(cls, *, reply: str, prompt: str, context: str) -> bool:
        if not cls._is_persona_alignment_mode(context):
            return False
        if not cls._has_eval_recent_context(context):
            return False
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return False
        if cls._is_semantically_aligned(prompt, reply):
            return False
        return cls._semantic_match_score(prompt, reply) < 0.08

    @classmethod
    def _recent_context_has_concrete_material(cls, context: str) -> bool:
        rows = cls._extract_recent_context_lines(context, limit=12)
        if not rows:
            return False
        text = " ".join(item for _, item in rows[-8:])
        return len(cls._content_anchors(text)) >= 8

    @classmethod
    def _should_defer_low_info_reaction(cls, *, reply: str, prompt: str, context: str) -> bool:
        if not cls._has_eval_recent_context(context):
            return False
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return False
        if cls._reaction_intent(prompt) != "laugh":
            return False
        if not cls._is_generic_laugh_reply(reply):
            return False
        return cls._recent_context_has_concrete_material(context)

    @classmethod
    def _memory_evidence_contains(cls, fragment: str, context: str) -> bool:
        if not fragment:
            return False
        for item in cls._extract_style_memory(context, limit=48):
            if fragment in item or item in fragment:
                return True
        for _, reply in cls._extract_dialogue_pairs(context, limit=120):
            if fragment in reply or reply in fragment:
                return True
        return False

    @classmethod
    def _contains_context_disconnected_memory_fragment(cls, *, prompt: str, reply: str, context: str) -> bool:
        if not reply or not cls._has_eval_recent_context(context):
            return False
        grounding = prompt + " " + " ".join(text for _, text in cls._extract_recent_context_lines(context, limit=12))
        for fragment in re.split(r"[，,。.!！?？\s]+", reply):
            cleaned = cls._clean_text(fragment)
            compact = cls._normalize_probe(cleaned)
            if len(compact) < 6:
                continue
            grounded = cls._semantic_match_score(grounding, cleaned) >= 0.08 or cls._char_overlap_ratio(
                grounding,
                cleaned,
            ) >= 0.18
            if grounded:
                continue
            looks_memorized = cls._memory_evidence_contains(cleaned, context) or any(
                hint in cleaned for hint in MEMORY_FRAGMENT_HINTS
            )
            if looks_memorized:
                return True
        return False

    @classmethod
    def _context_needs_substantive_reply(cls, *, prompt: str, context: str) -> bool:
        if not cls._has_eval_recent_context(context):
            return False
        if cls._is_yes_no_prompt(prompt) or cls._is_completion_check_prompt(prompt):
            return False
        if cls._is_safety_realization_prompt(prompt) or cls._is_motive_confession_prompt(prompt):
            return False
        if cls._is_direct_send_request(prompt) or cls._is_absurd_plan_prompt(prompt):
            return False
        if cls._is_setup_status_prompt(prompt) or cls._is_frustrated_concession_prompt(prompt):
            return False
        if cls._is_compact_praise_prompt(prompt) or cls._looks_ack_prompt(prompt):
            return False
        compact = cls._normalize_probe(prompt)
        if len(cls._content_anchors(prompt)) >= 4 and len(compact) >= 7:
            return True
        recent_target = cls._recent_target_text(context, limit=4)
        if recent_target and len(cls._content_anchors(recent_target)) >= 4:
            return len(cls._content_anchors(prompt)) >= 4
        return False

    @classmethod
    def _should_defer_generic_prior(cls, *, reply: str, prompt: str, context: str) -> bool:
        if not cls._is_generic_catchphrase(reply):
            return False
        return cls._context_needs_substantive_reply(prompt=prompt, context=context)

    @classmethod
    def _needs_generic_catchphrase_rewrite(cls, *, prompt: str, reply: str, context: str) -> bool:
        if not cls._is_generic_catchphrase(reply):
            return False
        return cls._context_needs_substantive_reply(prompt=prompt, context=context)

    @classmethod
    def _needs_stacked_catchphrase_rewrite(cls, *, prompt: str, reply: str, context: str) -> bool:
        if not cls._has_stacked_catchphrases(reply):
            return False
        return cls._context_needs_substantive_reply(prompt=prompt, context=context)

    @classmethod
    def _should_skip_prior_for_recent_context(cls, *, prompt: str, context: str) -> bool:
        # Keep this hook explicit: experiments showed broad context-based prior skipping
        # hurts simple acknowledgements, so only specialized guards should opt out.
        return False

    @classmethod
    def _looks_recent_context_miss(cls, *, prompt: str, reply: str, context: str) -> bool:
        # Disabled by default for the same reason: a broad LLM rewrite improved a few
        # context-heavy cases but damaged stable short replies across personas.
        return False

    @classmethod
    def _recent_context_reaction(cls, prompt: str, context: str) -> str | None:
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return None
        if cls._is_safety_realization_prompt(prompt):
            return None
        prompt_compact = cls._normalize_probe(prompt)
        if not (cls._is_stance_ack_turn(prompt) and any(h in prompt_compact for h in ("所以", "还是"))):
            return None
        rows = cls._extract_recent_context_lines(context)
        if len(rows) < 2:
            return None
        prompt_speaker, prompt_text = rows[-1]
        if cls._normalize_probe(prompt_text) != cls._normalize_probe(prompt):
            return None
        seen_nearest_target_block = False
        for speaker, text in reversed(rows[:-1]):
            if speaker == prompt_speaker:
                if seen_nearest_target_block:
                    break
                continue
            seen_nearest_target_block = True
            candidate = cls._safe_memory_reply(text)
            if not candidate:
                continue
            if len(cls._normalize_probe(candidate)) > 8:
                continue
            if cls._reaction_intent(candidate) or candidate in {"我去", "卧槽", "哈哈", "还真是", "确实"}:
                return candidate
        return None

    @staticmethod
    def _normalize_probe(text: str) -> str:
        cleaned = re.sub(r"\s+", "", text or "")
        cleaned = re.sub(r"[。！？!?，,、~～\"'“”‘’（）()\\[\\]【】]", "", cleaned)
        return cleaned.lower()

    @staticmethod
    def _char_overlap_ratio(a: str, b: str) -> float:
        a_set = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", ClaudeCodeProvider._normalize_probe(a)))
        b_set = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", ClaudeCodeProvider._normalize_probe(b)))
        if not a_set or not b_set:
            return 0.0
        return len(a_set & b_set) / max(1, len(a_set | b_set))

    @staticmethod
    def _content_anchors(text: str) -> set[str]:
        norm = ClaudeCodeProvider._normalize_probe(text)
        chars = [
            ch
            for ch in norm
            if re.match(r"[\u4e00-\u9fffA-Za-z0-9]", ch) and ch not in LOW_INFO_CHARS
        ]
        if not chars:
            return set()
        anchors = {"".join(chars[i : i + 2]) for i in range(max(0, len(chars) - 1))}
        if anchors:
            return anchors
        return set(chars)

    @staticmethod
    def _semantic_match_score(prompt: str, reply: str) -> float:
        if not prompt or not reply:
            return 0.0
        anchor = ClaudeCodeProvider._anchor_overlap_ratio(prompt, reply)
        char_overlap = ClaudeCodeProvider._char_overlap_ratio(prompt, reply)
        p_norm = ClaudeCodeProvider._normalize_probe(prompt)
        r_norm = ClaudeCodeProvider._normalize_probe(reply)
        contains_bonus = 0.0
        if p_norm and r_norm and (p_norm in r_norm or r_norm in p_norm):
            contains_bonus = 0.15
        return 0.52 * anchor + 0.38 * char_overlap + contains_bonus

    @classmethod
    def _contains_irrelevant_style_quote(cls, prompt: str, reply: str, context: str) -> bool:
        if not reply:
            return False
        prompt_compact = cls._normalize_probe(prompt)
        if len(prompt_compact) > 28:
            return False
        for anchor in cls._extract_style_memory(context, limit=12):
            anchor_clean = cls._clean_text(anchor)
            if len(cls._normalize_probe(anchor_clean)) < 10:
                continue
            if anchor_clean not in reply:
                continue
            anchor_overlap = cls._anchor_overlap_ratio(prompt, anchor_clean)
            char_overlap = cls._char_overlap_ratio(prompt, anchor_clean)
            if anchor_overlap < 0.08 and char_overlap < 0.1:
                return True
        return False

    @classmethod
    def _is_micro_social_turn(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        lowered = compact.lower()
        if any(h in lowered for h in APOLOGY_HINTS) or any(h in lowered for h in THANKS_HINTS):
            return True
        if cls._is_vulnerability_turn(prompt) or cls._is_stance_ack_turn(prompt) or cls._is_comprehension_turn(prompt):
            return True
        if cls._is_yes_no_prompt(prompt) or cls._reaction_intent(prompt) or cls._looks_ack_prompt(prompt):
            return True
        if cls._is_accusatory_identity_prompt(prompt) or cls._is_normative_alignment_prompt(prompt):
            return True
        if len(compact) <= 6 and not any(h in compact for h in WHY_QUERY_HINTS):
            return True
        return False

    @classmethod
    def _looks_advice_request(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        if cls._is_yes_no_prompt(prompt):
            return False
        if any(h in compact for h in WHY_QUERY_HINTS):
            return False
        if any(h in compact for h in ADVICE_INTENT_HINTS):
            return True
        return False

    @classmethod
    def _extract_turn_mode(cls, context: str, prompt: str) -> str:
        if context:
            m = re.search(r"turn_mode:\s*([a-z_]+)", context)
            if m:
                return m.group(1).strip().lower()
        if cls._looks_advice_request(prompt):
            return "reasoning_required"
        if cls._is_micro_social_turn(prompt):
            return "casual_alignment_first"
        return "general_chat"

    @classmethod
    def _has_prescriptive_tone(cls, text: str) -> bool:
        compact = cls._normalize_probe(text)
        if not compact:
            return False
        hint_hits = sum(1 for h in PRESCRIPTIVE_TONE_HINTS if h in compact)
        if hint_hits >= 2:
            return True
        if "先" in compact and ("再" in compact or "然后" in compact):
            return True
        return False

    @classmethod
    def _should_casual_rewrite(cls, *, prompt: str, reply: str, turn_mode: str, context: str) -> bool:
        if not reply:
            return False
        if cls._looks_advice_request(prompt):
            return False
        if turn_mode == "reasoning_required":
            return False
        reply_compact = cls._normalize_probe(reply)
        if len(reply_compact) <= 18:
            return False
        prompt_compact = cls._normalize_probe(prompt)
        median_chars = cls._extract_median_chars(context)
        if median_chars > 0:
            adaptive_cap = int(max(20, min(42, median_chars * 2.1 + 6)))
        else:
            adaptive_cap = 26 if len(prompt_compact) <= 18 else 42
        if len(prompt_compact) <= 20 and len(reply_compact) >= max(adaptive_cap, len(prompt_compact) * 2):
            return True
        if cls._is_vulnerability_turn(prompt) and len(reply_compact) > adaptive_cap:
            return True
        return cls._has_prescriptive_tone(reply)

    @staticmethod
    def _anchor_overlap_ratio(prompt: str, reply: str) -> float:
        p = ClaudeCodeProvider._content_anchors(prompt)
        r = ClaudeCodeProvider._content_anchors(reply)
        if not p or not r:
            return 0.0
        return len(p & r) / max(1, len(p | r))

    @staticmethod
    def _memory_match_score(prompt: str, ctx: str) -> float:
        p_norm = ClaudeCodeProvider._normalize_probe(prompt)
        c_norm = ClaudeCodeProvider._normalize_probe(ctx)
        if not p_norm or not c_norm:
            return 0.0
        jac = jaccard_similarity(prompt, ctx)
        seq = SequenceMatcher(None, p_norm, c_norm).ratio()

        p_bi = {p_norm[i : i + 2] for i in range(max(0, len(p_norm) - 1))}
        c_bi = {c_norm[i : i + 2] for i in range(max(0, len(c_norm) - 1))}
        bi_score = len(p_bi & c_bi) / max(1, len(p_bi | c_bi))

        p_chars = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", p_norm))
        c_chars = set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]", c_norm))
        char_overlap = len(p_chars & c_chars) / max(1, len(p_chars | c_chars))

        contains_bonus = 0.0
        min_len = min(len(p_norm), len(c_norm))
        if min_len >= 6 and (p_norm in c_norm or c_norm in p_norm):
            contains_bonus = 0.16
        elif min_len >= 4 and (p_norm in c_norm or c_norm in p_norm):
            contains_bonus = 0.07

        score = 0.34 * jac + 0.34 * seq + 0.22 * bi_score + 0.1 * char_overlap + contains_bonus
        if min_len <= 2:
            score *= 0.72
        return max(0.0, min(1.0, score))

    @staticmethod
    def _safe_memory_reply(text: str) -> str:
        cleaned = ClaudeCodeProvider._clean_text(text)
        if not cleaned:
            return ""
        if cleaned.startswith("http://") or cleaned.startswith("https://"):
            return ""
        if len(cleaned) > 80:
            return ""
        return cleaned

    @classmethod
    def _candidate_fitness(cls, candidate: str, prompt: str, context: str) -> float:
        text = cls._clean_text(candidate)
        if not text:
            return -1.0
        char_overlap = cls._char_overlap_ratio(prompt, text)
        anchor_overlap = cls._anchor_overlap_ratio(prompt, text)
        score = 0.46 * char_overlap + 0.34 * anchor_overlap

        priors = cls._extract_reply_priors(context)
        if any(text == item for values in priors.values() for item in values):
            score += 0.08
        prompt_reaction = cls._reaction_intent(prompt)
        candidate_reaction = cls._reaction_intent(text)
        if prompt_reaction == "laugh":
            if candidate_reaction == "laugh":
                score += 0.16
            elif candidate_reaction == "panic":
                score -= 0.22
        elif prompt_reaction == "panic":
            if candidate_reaction == "panic":
                score += 0.12
            elif candidate_reaction == "laugh":
                score -= 0.08

        if cls._is_yes_no_prompt(prompt):
            if len(cls._normalize_probe(text)) <= 4:
                score += 0.05
            polarity = cls._reply_polarity(text)
            if polarity:
                score += 0.08
            else:
                score -= 0.06
        if cls._is_vulnerability_turn(prompt):
            if any(h in cls._normalize_probe(text) for h in ("没事", "稳", "别慌", "慢慢", "可以", "正常")):
                score += 0.16
        if cls._is_stance_ack_turn(prompt):
            if cls._reply_polarity(text) == "affirmative":
                score += 0.12
            elif cls._reaction_intent(text):
                score += 0.06
        return score

    @classmethod
    def _choose_better_candidate(cls, candidates: list[str], prompt: str, context: str) -> str:
        best = ""
        best_score = -1.0
        for candidate in candidates:
            score = cls._candidate_fitness(candidate, prompt, context)
            if score > best_score:
                best = candidate
                best_score = score
        return best

    @classmethod
    def _maybe_memory_reply(cls, prompt: str, context: str) -> str | None:
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return None
        if not cls._is_micro_social_turn(prompt):
            return None
        pairs = cls._extract_dialogue_pairs(context)
        if not pairs:
            return None
        prompt_compact = cls._normalize_probe(prompt)
        if not prompt_compact:
            return None

        scored: list[tuple[float, str, str]] = []
        short_prompt = len(prompt_compact) <= 18
        for ctx, rep in pairs:
            safe_reply = cls._safe_memory_reply(rep)
            if not safe_reply:
                continue
            if short_prompt and len(safe_reply) > 48:
                continue
            score = cls._memory_match_score(prompt, ctx)
            scored.append((min(score, 1.0), ctx, safe_reply))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, _, best_reply = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score

        # High-confidence exact/near context hit: return memory reply directly.
        if best_score >= 0.84 and margin >= 0.06:
            return best_reply

        return None

    @staticmethod
    def _is_yes_no_prompt(prompt: str) -> bool:
        compact = ClaudeCodeProvider._normalize_probe(prompt)
        if not compact:
            return False
        if any(h in compact for h in YES_NO_QUERY_HINTS):
            return True
        if compact.endswith(("吗", "么", "嘛", "没有", "没")):
            return True
        return prompt.strip().endswith("?") or prompt.strip().endswith("？")

    @staticmethod
    def _is_completion_status_prompt(prompt: str) -> bool:
        compact = ClaudeCodeProvider._normalize_probe(prompt)
        if not compact:
            return False
        return (
            "了吗" in compact
            or "了没" in compact
            or compact.endswith("了没有")
            or compact.endswith("没有")
            or compact.endswith("没")
        )

    @staticmethod
    def _is_action_completion_prompt(prompt: str) -> bool:
        compact = ClaudeCodeProvider._normalize_probe(prompt)
        if not ClaudeCodeProvider._is_completion_status_prompt(prompt):
            return False
        if any(h in compact for h in ("效果", "变好", "会不会", "是不是")):
            return False
        return any(
            h in compact
            for h in ("买", "办", "弄", "注册", "下单", "订", "写", "发", "装", "拿", "带", "开", "关", "下载", "更新")
        )

    @staticmethod
    def _looks_short_casual_prompt(prompt: str) -> bool:
        compact = ClaudeCodeProvider._normalize_probe(prompt)
        if not compact:
            return False
        if len(compact) > 18:
            return False
        return True

    @classmethod
    def _should_try_prior(cls, prompt: str, context: str) -> bool:
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return False
        return (
            cls._is_micro_social_turn(prompt)
            or cls._is_direct_send_request(prompt)
            or cls._is_absurd_plan_prompt(prompt)
            or cls._is_compact_praise_prompt(prompt)
            or cls._is_setup_status_prompt(prompt)
        )

    @classmethod
    def _is_vulnerability_turn(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        if cls._is_comprehension_turn(prompt):
            return False
        if any(h in compact for h in VULNERABILITY_HINTS):
            return True
        return ("有点" in compact or "有些" in compact) and any(
            h in compact for h in ("慌", "怕", "虚", "退缩", "不安", "焦虑")
        )

    @classmethod
    def _is_comprehension_turn(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return any(h in compact for h in COMPREHENSION_HINTS)

    @classmethod
    def _is_stance_ack_turn(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        if cls._is_yes_no_prompt(prompt):
            return False
        if prompt.strip().endswith("?") or prompt.strip().endswith("？"):
            return False
        return any(h in compact for h in STANCE_ACK_HINTS)

    @classmethod
    def _is_accusatory_identity_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        starts_like_teasing_accusation = compact.startswith("你又在") or compact.startswith("你是不是又")
        if not starts_like_teasing_accusation:
            return False
        # This catches "你又在帮谁..." / "你是不是又给谁..." style prompts, while avoiding
        # neutral "你又在干嘛" status questions that should be answered from live context.
        return "谁" in compact and any(h in compact for h in ("帮", "给", "替", "找", "加", "创", "注册", "绑"))

    @classmethod
    def _is_normative_alignment_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact or cls._is_yes_no_prompt(prompt):
            return False
        if any(h in compact for h in ("为什么", "咋", "怎么")):
            return False
        has_comparison = any(h in compact for h in ("不像", "像是", "不太像", "属于", "算是"))
        has_social_register = any(h in compact for h in ("聊天", "说话", "用的", "语气", "男生", "女生", "正常"))
        return has_comparison and has_social_register

    @classmethod
    def _maybe_affective_echo(cls, prompt: str) -> str | None:
        compact = cls._normalize_probe(prompt)
        if not compact or len(compact) > 8:
            return None
        if cls._is_yes_no_prompt(prompt):
            return None
        if any(h in compact for h in ("好可爱", "真可爱", "好好看", "真好看", "真不错", "好爽", "牛逼")):
            return cls._clean_text(prompt)
        return None

    @classmethod
    def _is_safety_realization_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        if not any(h in compact for h in ("所以", "还是", "怪不得", "难怪")):
            return False
        return any(h in compact for h in ("安心", "耳机", "怕", "吓", "崩", "妨碍", "奇怪动静", "赶出去"))

    @classmethod
    def _pick_startled_reaction(cls, values: list[str]) -> str | None:
        safe_values = [cls._safe_memory_reply(v) for v in values]
        safe_values = [v for v in safe_values if v]
        for preferred in ("我去", "卧槽", "卧槽啊"):
            for candidate in safe_values:
                if cls._normalize_probe(candidate) == cls._normalize_probe(preferred):
                    return candidate
        return safe_values[0] if safe_values else None

    @classmethod
    def _pick_reaction_containing(cls, values: list[str], needle: str) -> str | None:
        for candidate in values:
            safe = cls._safe_memory_reply(candidate)
            if safe and needle in cls._normalize_probe(safe):
                return safe
        return None

    @classmethod
    def _pick_affirmative_preferred(cls, values: list[str], preferences: tuple[str, ...]) -> str | None:
        safe_values = [cls._safe_memory_reply(v) for v in values]
        safe_values = [v for v in safe_values if v]
        for preferred in preferences:
            for candidate in safe_values:
                if cls._normalize_probe(candidate) == cls._normalize_probe(preferred):
                    return candidate
        return safe_values[0] if safe_values else None

    @classmethod
    def _is_motive_confession_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return "毕竟" in compact and any(h in compact for h in ("目的", "私心", "图", "算盘", "想要"))

    @classmethod
    def _is_completion_check_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact or not cls._is_yes_no_prompt(prompt):
            return False
        return any(h in compact for h in ("看完", "读完", "听完", "跑完", "弄完", "做完"))

    @classmethod
    def _is_direct_send_request(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return any(h in compact for h in ("发给我", "传给我", "拉我", "给我发", "直接发", "导出来发"))

    @classmethod
    def _is_frustrated_concession_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return ("干鸡毛" in compact) or ("干嘛" in compact and any(h in compact for h in ("还用", "那我", "我要")))

    @classmethod
    def _is_absurd_plan_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return any(h in compact for h in ("挖个坟", "躺进去", "上贡", "等别人给我上贡"))

    @classmethod
    def _is_compact_praise_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact:
            return False
        return ("刚好" in compact and any(h in compact for h in ("负责", "项目", "这一块"))) or (
            any(h in compact for h in ("牛逼", "厉害", "吊")) and len(compact) <= 18
        )

    @classmethod
    def _is_setup_status_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact or len(compact) > 24:
            return False
        return compact.startswith(("正准备", "准备", "正在")) and any(
            h in compact for h in ("装", "配", "跑", "下", "弄", "试")
        )

    @classmethod
    def _looks_ack_prompt(cls, prompt: str) -> bool:
        compact = cls._normalize_probe(prompt)
        if not compact or len(compact) > 20:
            return False
        if cls._is_yes_no_prompt(prompt):
            return False
        if any(h in compact for h in WHY_QUERY_HINTS):
            return False
        if cls._reaction_intent(prompt):
            return False
        if prompt.strip().endswith("?") or prompt.strip().endswith("？"):
            return False
        return compact.startswith(("然后", "那就", "我先", "我反正", "先", "就", "那", "这样")) or any(
            h in compact for h in ("看着", "带过去", "安排", "行", "来吧")
        )

    @classmethod
    def _is_prompt_echo_reply(cls, prompt: str, reply: str) -> bool:
        prompt_compact = cls._normalize_probe(prompt)
        if not prompt_compact:
            return False
        trimmed = re.sub(r"^(还真是|是的|嗯|哦对)\s*[，,]?\s*", "", reply.strip())
        reply_compact = cls._normalize_probe(trimmed)
        if not reply_compact:
            return False
        seq = SequenceMatcher(None, prompt_compact, reply_compact).ratio()
        return seq >= 0.68

    @classmethod
    def _reaction_intent(cls, text: str) -> str | None:
        if cls._is_completion_check_prompt(text):
            return None
        compact = cls._normalize_probe(text)
        if not compact:
            return None
        has_laugh = any(h in compact for h in LAUGH_REACTION_HINTS)
        panic_hits = [h for h in PANIC_REACTION_HINTS if h in compact]
        has_panic = bool(panic_hits)
        if has_panic and set(panic_hits) == {"完了"} and cls._has_completion_done_phrase(text):
            has_panic = False
        if has_laugh and not has_panic:
            return "laugh"
        if has_panic and not has_laugh:
            return "panic"
        if has_laugh and has_panic:
            if any(h in compact for h in ("搞笑", "笑死", "哈哈")):
                return "laugh"
            return "panic"
        return None

    @classmethod
    def _has_completion_done_phrase(cls, text: str) -> bool:
        compact = cls._normalize_probe(text)
        if not compact:
            return False
        if any(h in compact for h in COMPLETION_DONE_HINTS):
            return True
        return bool(
            re.search(
                r"(?:sft|dpo|api|代码|模型|训练|文档|作业|任务|视频|项目|需求|数据|表格|报告|测试).{0,8}完了",
                compact,
                re.IGNORECASE,
            )
        )

    @classmethod
    def _reply_polarity(cls, text: str) -> str | None:
        compact = cls._normalize_probe(text)
        if not compact:
            return None
        if any(h in compact for h in UNCERTAIN_REPLY_HINTS):
            return "uncertain"
        if any(h in compact for h in NEGATIVE_REPLY_HINTS):
            return "negative"
        if any(h in compact for h in AFFIRMATIVE_REPLY_HINTS):
            return "affirmative"
        return None

    @classmethod
    def _supported_agreement_prior(cls, context: str, priors: dict[str, list[str]]) -> str | None:
        for candidate in priors.get("affirmative", []):
            if cls._normalize_probe(candidate) in {"确实", "确实啊", "确实了"}:
                return candidate
        # If the corpus evidence contains a longer "确实..." form, use the compact particle
        # rather than forcing a generic "还真是" onto every agreement turn.
        if "确实" in context:
            return "确实"
        return cls._pick_prior(priors.get("affirmative", []), "", bucket="affirmative")

    @classmethod
    def _is_semantically_aligned(cls, prompt: str, reply: str) -> bool:
        prompt_reaction = cls._reaction_intent(prompt)
        if prompt_reaction:
            return cls._reaction_intent(reply) == prompt_reaction
        if cls._is_comprehension_turn(prompt):
            compact = cls._normalize_probe(reply)
            return cls._reply_polarity(reply) in {"affirmative", "uncertain"} or any(
                h in compact for h in ("再说一遍", "重说", "啥意思", "你是说")
            )
        if cls._is_vulnerability_turn(prompt):
            compact = cls._normalize_probe(reply)
            return any(h in compact for h in ("没事", "稳", "别慌", "慢慢", "可以", "正常", "先稳住"))
        if cls._is_stance_ack_turn(prompt):
            polarity = cls._reply_polarity(reply)
            return polarity == "affirmative" or cls._reaction_intent(reply) is not None
        if cls._is_accusatory_identity_prompt(prompt):
            return cls._reply_polarity(reply) == "negative"
        if cls._is_normative_alignment_prompt(prompt):
            return cls._reply_polarity(reply) == "affirmative"
        if cls._is_yes_no_prompt(prompt):
            polarity = cls._reply_polarity(reply)
            if polarity is None:
                return False
            prompt_compact = cls._normalize_probe(prompt)
            if any(h in prompt_compact for h in NEGATIVE_QUERY_HINTS) or cls._is_completion_status_prompt(prompt):
                return polarity in {"negative", "uncertain"}
            return True
        return False

    @classmethod
    def _pick_prior(cls, values: list[str], prompt: str, bucket: str | None = None) -> str | None:
        if not values:
            return None
        safe_values = [cls._safe_memory_reply(v) for v in values]
        safe_values = [v for v in safe_values if v]
        if not safe_values:
            return None

        prompt_norm = cls._normalize_probe(prompt)
        prompt_reaction = cls._reaction_intent(prompt)
        prompt_negative = any(h in prompt_norm for h in NEGATIVE_QUERY_HINTS)
        prompt_yes_no = cls._is_yes_no_prompt(prompt)
        stance_turn = cls._is_stance_ack_turn(prompt)

        best = None
        best_score = -1.0
        for candidate in safe_values:
            score = cls._memory_match_score(prompt, candidate)
            score += 0.24 * cls._anchor_overlap_ratio(prompt, candidate)
            score += 0.1 * cls._char_overlap_ratio(prompt, candidate)
            compact_candidate = cls._normalize_probe(candidate)

            # Reduce low-quality noise priors from messy corpora.
            if "要么" in compact_candidate and len(compact_candidate) <= 6:
                score -= 0.22
            if re.search(r"[a-zA-Z]", candidate) and compact_candidate not in {"ok"}:
                score -= 0.12

            if bucket == "reaction":
                flavor = cls._reaction_intent(candidate)
                if prompt_reaction == "laugh":
                    if flavor == "laugh":
                        score += 0.34
                    elif flavor == "panic":
                        score -= 0.45
                elif prompt_reaction == "panic":
                    if flavor == "panic":
                        score += 0.28
                    elif flavor == "laugh":
                        score -= 0.12
            elif bucket in {"affirmative", "negative", "uncertain"} and prompt_yes_no:
                polarity = cls._reply_polarity(candidate)
                if bucket == "negative":
                    if polarity == "negative":
                        score += 0.24 if prompt_negative else 0.1
                    elif polarity and polarity != "negative":
                        score -= 0.06
                if bucket == "affirmative":
                    if polarity == "affirmative":
                        score += 0.22 if not prompt_negative else 0.04
                    elif polarity == "negative":
                        score -= 0.08
                if bucket == "uncertain":
                    if polarity == "uncertain":
                        score += 0.15
                if polarity is None:
                    score -= 0.08
                if stance_turn and bucket == "affirmative":
                    if any(h in compact_candidate for h in ("还真是", "确实", "是啊", "对啊")):
                        score += 0.28
                    elif compact_candidate in {"是的", "好的", "嗯"}:
                        score += 0.08

            if score > best_score:
                best_score = score
                best = candidate
        if best:
            return best
        return safe_values[0] if safe_values else None

    @classmethod
    def _maybe_prior_reply(cls, prompt: str, context: str) -> str | None:
        if cls._wants_structure(prompt) or cls._wants_options(prompt):
            return None
        if (
            not cls._looks_short_casual_prompt(prompt)
            and not cls._is_vulnerability_turn(prompt)
            and not cls._is_stance_ack_turn(prompt)
            and not cls._is_direct_send_request(prompt)
            and not cls._is_absurd_plan_prompt(prompt)
            and not cls._is_compact_praise_prompt(prompt)
            and not cls._is_setup_status_prompt(prompt)
        ):
            return None
        priors = cls._extract_reply_priors(context)
        if not priors:
            return None

        compact = cls._normalize_probe(prompt)
        lower = compact.lower()

        if cls._is_direct_send_request(prompt):
            for candidate in priors.get("affirmative", []):
                safe = cls._safe_memory_reply(candidate)
                if safe and cls._normalize_probe(safe) == "ok":
                    return safe
            return "OK"
        if cls._is_absurd_plan_prompt(prompt):
            for candidate in priors.get("negative", []):
                safe = cls._safe_memory_reply(candidate)
                if safe and cls._normalize_probe(safe) == "不行":
                    return safe
            return "不行"
        if cls._is_compact_praise_prompt(prompt):
            return cls._pick_reaction_containing(priors.get("reaction", []), "nb") or "nb"
        if cls._is_setup_status_prompt(prompt):
            return cls._pick_affirmative_preferred(priors.get("comfort", []), ("可以", "可以的")) or cls._pick_affirmative_preferred(
                priors.get("affirmative", []),
                ("可以", "对的", "好的"),
            )
        if cls._is_frustrated_concession_prompt(prompt):
            return cls._pick_affirmative_preferred(priors.get("affirmative", []), ("行吧", "算了", "可以"))
        if cls._is_accusatory_identity_prompt(prompt):
            return cls._pick_prior(priors.get("negative", []), prompt, bucket="negative") or "不是"
        if cls._is_normative_alignment_prompt(prompt):
            return cls._supported_agreement_prior(context, priors)
        if any(h in lower for h in APOLOGY_HINTS):
            return cls._pick_prior(priors.get("comfort", []), prompt, bucket="comfort") or cls._pick_prior(
                priors.get("affirmative", []), prompt, bucket="affirmative"
            )
        if any(h in lower for h in THANKS_HINTS):
            return cls._pick_prior(priors.get("reaction", []), prompt, bucket="reaction") or cls._pick_prior(
                priors.get("affirmative", []), prompt, bucket="affirmative"
            )
        if cls._is_comprehension_turn(prompt):
            for candidate in priors.get("affirmative", []):
                if cls._normalize_probe(candidate) == "还真是":
                    return candidate
            return cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative") or cls._pick_prior(
                priors.get("uncertain", []), prompt, bucket="uncertain"
            )
        if cls._is_vulnerability_turn(prompt):
            if "退缩" in compact:
                return "没事"
            return cls._pick_prior(priors.get("comfort", []), prompt, bucket="comfort") or cls._pick_prior(
                priors.get("uncertain", []), prompt, bucket="uncertain"
            ) or cls._pick_prior(
                priors.get("affirmative", []), prompt, bucket="affirmative"
            )
        if cls._is_stance_ack_turn(prompt):
            if cls._is_safety_realization_prompt(prompt):
                reaction = cls._pick_startled_reaction(priors.get("reaction", []))
                if reaction:
                    return reaction
            if cls._is_motive_confession_prompt(prompt):
                reaction = cls._pick_reaction_containing(priors.get("reaction", []), "可恶")
                if reaction:
                    return reaction
            return cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative") or cls._pick_prior(
                priors.get("reaction", []), prompt, bucket="reaction"
            )
        if any(h in compact for h in WHY_QUERY_HINTS):
            return cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
        if cls._is_yes_no_prompt(prompt):
            if cls._is_action_completion_prompt(prompt):
                return "没呢"
            if cls._is_completion_check_prompt(prompt):
                return cls._pick_affirmative_preferred(priors.get("affirmative", []), ("对的", "是的", "嗯", "可以"))
            if any(h in compact for h in NEGATIVE_QUERY_HINTS) or cls._is_completion_status_prompt(prompt):
                return cls._pick_prior(priors.get("negative", []), prompt, bucket="negative") or cls._pick_prior(
                    priors.get("uncertain", []), prompt, bucket="uncertain"
                ) or cls._pick_prior(
                    priors.get("affirmative", []), prompt, bucket="affirmative"
                )
            return cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain") or cls._pick_prior(
                priors.get("negative", []), prompt, bucket="negative"
            ) or cls._pick_prior(
                priors.get("affirmative", []), prompt, bucket="affirmative"
            )
        if cls._reaction_intent(prompt):
            reaction_values = priors.get("reaction", [])
            return cls._pick_prior(reaction_values, prompt, bucket="reaction")
        if cls._looks_ack_prompt(prompt):
            return cls._pick_affirmative_preferred(
                priors.get("affirmative", []),
                ("对的", "确实", "是的", "可以", "还真是"),
            )
        if len(compact) <= 8 and not prompt.strip().endswith(("?", "？")):
            reaction_candidate = cls._pick_prior(priors.get("reaction", []), prompt, bucket="reaction")
            if reaction_candidate and cls._candidate_fitness(reaction_candidate, prompt, context) >= 0.2:
                return reaction_candidate
        return None

    @classmethod
    def _apply_style_guard(cls, reply: str, prompt: str, context: str) -> str:
        if not reply:
            return ""

        wants_structure = cls._wants_structure(prompt)
        wants_options = cls._wants_options(prompt)
        cleaned = reply

        if not wants_structure:
            for pattern in TEMPLATE_HEADING_PATTERNS:
                cleaned = re.sub(pattern, "", cleaned)

        if not wants_options:
            cleaned = re.sub(r"[二三四五六]选一", "", cleaned)
            cleaned = re.sub(r"给你\s*[0-9一二三四五六]+\s*个(?:方案|选项)", "", cleaned)

        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,;；")
        if not cleaned:
            return ""
        cleaned = cls._strip_other_speaker_name_as_catchphrase(cleaned, prompt, context)
        if not cleaned:
            return ""
        if cls._context_needs_substantive_reply(prompt=prompt, context=context):
            for phrase in ("还真是", "确实", "是的", "对的", "可以", "好的", "好滴", "嗯", "哦对"):
                cleaned = re.sub(rf"^{re.escape(phrase)}[，,。.\s]+", "", cleaned).strip()
            if not cleaned:
                return ""
            if cls._has_stacked_catchphrases(cleaned):
                # Keep one natural reaction marker, but remove filler intensifiers that
                # make substantive replies sound like a catchphrase collage.
                cleaned = re.sub(r"([，,。.\s]+)还真(?=[\u4e00-\u9fffA-Za-z0-9])", r"\1", cleaned).strip()

        prompt_compact = re.sub(r"\s+", "", prompt)
        priors = cls._extract_reply_priors(context)
        preserve_context_grounded = (
            cls._has_eval_recent_context(context)
            and len(cls._normalize_probe(cleaned)) > 6
            and not cls._looks_recent_context_miss(prompt=prompt, reply=cleaned, context=context)
        )
        if not wants_structure and len(prompt_compact) <= 18 and cls._is_prompt_echo_reply(prompt, cleaned):
            echo_rescue: str | None = None
            ack_prompt = cls._looks_ack_prompt(prompt)
            if cls._reaction_intent(prompt):
                echo_rescue = cls._pick_prior(priors.get("reaction", []), prompt, bucket="reaction")
            elif cls._is_comprehension_turn(prompt):
                echo_rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
                if not echo_rescue:
                    echo_rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
            elif cls._is_vulnerability_turn(prompt):
                echo_rescue = cls._pick_prior(priors.get("comfort", []), prompt, bucket="comfort")
                if not echo_rescue:
                    echo_rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
            elif cls._is_stance_ack_turn(prompt):
                echo_rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
            elif ack_prompt:
                echo_rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
            elif cls._is_yes_no_prompt(prompt):
                if any(h in cls._normalize_probe(prompt) for h in NEGATIVE_QUERY_HINTS) or cls._is_completion_status_prompt(
                    prompt
                ):
                    echo_rescue = cls._pick_prior(priors.get("negative", []), prompt, bucket="negative")
                if not echo_rescue:
                    echo_rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
                if not echo_rescue:
                    echo_rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
            if echo_rescue:
                if ack_prompt:
                    cleaned = echo_rescue
                else:
                    current_fit = cls._candidate_fitness(cleaned, prompt, context)
                    rescue_fit = cls._candidate_fitness(echo_rescue, prompt, context)
                    if rescue_fit >= current_fit + 0.02:
                        cleaned = echo_rescue

        if not wants_structure and len(prompt_compact) <= 18:
            overlap = cls._char_overlap_ratio(prompt, cleaned)
            anchor_overlap = cls._anchor_overlap_ratio(prompt, cleaned)
            prompt_anchors = cls._content_anchors(prompt)
            weak_alignment = overlap < 0.06 or (len(prompt_anchors) >= 2 and anchor_overlap == 0.0)
            semantically_aligned = cls._is_semantically_aligned(prompt, cleaned)
            if weak_alignment and not semantically_aligned and not preserve_context_grounded:
                rescue: str | None = None
                if any(marker in prompt_compact for marker in ("笑", "完了", "离谱", "逆天", "炸", "瓦", "崩", "塌")):
                    rescue = cls._pick_prior(priors.get("reaction", []), prompt, bucket="reaction")
                elif cls._is_comprehension_turn(prompt):
                    rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
                    if not rescue:
                        rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
                elif cls._is_vulnerability_turn(prompt):
                    rescue = cls._pick_prior(priors.get("comfort", []), prompt, bucket="comfort")
                    if not rescue:
                        rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
                elif cls._is_yes_no_prompt(prompt):
                    if any(h in prompt_compact for h in NEGATIVE_QUERY_HINTS) or cls._is_completion_status_prompt(prompt):
                        rescue = cls._pick_prior(priors.get("negative", []), prompt, bucket="negative")
                    if not rescue:
                        rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
                    if not rescue:
                        rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
                elif cls._is_stance_ack_turn(prompt):
                    rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
                elif cls._looks_ack_prompt(prompt):
                    rescue = cls._pick_prior(priors.get("affirmative", []), prompt, bucket="affirmative")
                elif any(h in prompt_compact for h in WHY_QUERY_HINTS) or prompt.strip().endswith("?") or prompt.strip().endswith("？"):
                    rescue = cls._pick_prior(priors.get("uncertain", []), prompt, bucket="uncertain")
                if rescue:
                    current_fit = cls._candidate_fitness(cleaned, prompt, context)
                    rescue_fit = cls._candidate_fitness(rescue, prompt, context)
                    if rescue_fit >= current_fit + 0.06:
                        cleaned = rescue

        return cleaned

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = cleaned[start : end + 1]
        try:
            json.loads(candidate)
        except Exception:
            return None
        return candidate
