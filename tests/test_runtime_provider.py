from __future__ import annotations

import pytest

from persona_distill.providers.claude_code import ClaudeCodeProvider, resolve_runtime_cli
from persona_distill.providers.factory import build_provider, resolve_runtime_spec


def test_resolve_runtime_cli_prefers_codex_in_codex_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_SHELL", "1")
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"codex", "claude"} else None

    monkeypatch.setattr("persona_distill.providers.claude_code.shutil.which", _which)
    assert resolve_runtime_cli("auto") == "codex"


def test_resolve_runtime_cli_prefers_claude_in_generic_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CODEX_SHELL", raising=False)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    def _which(name: str) -> str | None:
        return f"/usr/bin/{name}" if name in {"codex", "claude"} else None

    monkeypatch.setattr("persona_distill.providers.claude_code.shutil.which", _which)
    assert resolve_runtime_cli("auto") == "claude"


def test_resolve_runtime_cli_rejects_invalid_value() -> None:
    with pytest.raises(ValueError):
        resolve_runtime_cli("invalid")


def test_resolve_runtime_spec_reflects_runtime_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_RUNTIME_CLI", "codex")
    assert resolve_runtime_spec() == "runtime:skill/codex"


def test_build_provider_uses_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISTILL_RUNTIME_CLI", "codex")
    monkeypatch.setenv("DISTILL_MODEL", "gpt-5.5")
    monkeypatch.setenv("DISTILL_RUNTIME_TIMEOUT_SEC", "123")
    provider = build_provider()
    assert getattr(provider, "runtime_cli") == "codex"
    assert provider.model == "gpt-5.5"
    assert getattr(provider, "timeout_sec") == 123


def test_generate_response_strips_report_shell_when_not_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(
        provider,
        "_ask_text",
        lambda _: "结论：今晚吃面。理由很简单：快。现在就执行：去点单。",
    )
    reply = provider.generate_response("晚上吃什么", "ctx")
    assert "结论：" not in reply
    assert "理由很简单：" not in reply
    assert "现在就执行：" not in reply
    assert "今晚吃面" in reply


def test_generate_response_preserves_structure_when_user_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(
        provider,
        "_ask_text",
        lambda _: "结论：先吃点热的。理由很简单：你现在需要先补能量。",
    )
    reply = provider.generate_response("请分步骤回答晚上吃什么", "ctx")
    assert "结论：" in reply
    assert "理由很简单：" in reply


def test_generate_response_does_not_hard_clip_short_prompt_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(
        provider,
        "_ask_text",
        lambda _: "先吃点热的别空腹扛着。真没时间就随便点个快的先垫一口。"
        "你要是想我再给你按预算细分也行。",
    )
    context = "[STYLE_PROFILE]\n- response_length_mode: terse"
    reply = provider.generate_response("吃啥", context)
    assert "先吃点热的别空腹扛着" in reply
    assert "预算细分" in reply


def test_generate_response_keeps_model_decided_length(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(
        provider,
        "_ask_text",
        lambda _: "你要是想细说也行。第一步先把目标定死。第二步把约束列出来。第三步再选方案。",
    )
    context = "[STYLE_PROFILE]\n- length_policy: 回复长度由对话语义与人格机制共同决定，不做固定字数约束"
    reply = provider.generate_response("咋整", context)
    assert reply.count("。") >= 3


def test_generate_response_prefers_memory_reply_when_context_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("_ask_text should not be called when memory retrieval hits")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[DIALOGUE_MEMORY]\n"
        "- context: 荞麦地太搞笑了 => reply: 笑死我了\n"
        "- context: 她之前跟你说了没有 => reply: 不是\n"
        "[LEXICON]\n"
        "还真是, 启动\n"
    )
    reply = provider.generate_response("荞麦地太搞笑了", context)
    assert reply == "笑死我了"


def test_generate_response_memory_retrieval_skips_when_user_wants_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(provider, "_ask_text", lambda _: "结论：先说重点。")
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[DIALOGUE_MEMORY]\n"
        "- context: 荞麦地太搞笑了 => reply: 笑死我了\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = provider.generate_response("请分步骤回答荞麦地太搞笑了", context)
    assert "结论：" in reply


def test_pick_prior_prefers_laugh_reaction_for_laugh_prompt() -> None:
    picked = ClaudeCodeProvider._pick_prior(
        ["卧槽", "🍬完了", "哈哈", "优势完了"],
        "荞麦地太搞笑了",
        bucket="reaction",
    )
    assert picked == "哈哈"


def test_style_guard_keeps_semantically_aligned_laugh_reply() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[REPLY_PRIORS]\n"
        "- reaction: 卧槽 | 哈哈 | 🍬完了\n"
        "[LEXICON]\n"
        "笑死\n"
    )
    guarded = ClaudeCodeProvider._apply_style_guard("笑死我了", "荞麦地太搞笑了", context)
    assert guarded == "笑死我了"


def test_maybe_prior_reply_handles_ack_prompt() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "- short_reply_ratio: 0.62\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 好滴 | 好的\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("然后战士装看着出", context)
    assert reply in {"是的", "好滴", "好的"}


def test_maybe_prior_reply_handles_wa_like_panic_prompt() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "- short_reply_ratio: 0.62\n"
        "[REPLY_PRIORS]\n"
        "- reaction: 哈哈 | 完了 | 卧槽\n"
        "[LEXICON]\n"
        "完了\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("小孩姐打上瓦了", context)
    assert reply in {"完了", "卧槽"}


def test_maybe_prior_reply_prefers_negative_for_completion_status_prompt() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "- short_reply_ratio: 0.62\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 好滴\n"
        "- negative: 没呢 | 不是\n"
        "- uncertain: 难说 | 不知道\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("买网线了吗", context)
    assert reply == "没呢"


def test_action_completion_prompt_does_not_catch_effect_question() -> None:
    assert ClaudeCodeProvider._is_action_completion_prompt("买网线了吗")
    assert not ClaudeCodeProvider._is_action_completion_prompt("这么快就有效果了吗")


def test_maybe_prior_reply_prefers_comfort_for_vulnerability_turn() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "- short_reply_ratio: 0.62\n"
        "[REPLY_PRIORS]\n"
        "- comfort: 没事 | 稳住 | 可以的\n"
        "- uncertain: 难说\n"
        "- affirmative: 是的\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("现在车力来了有点退缩", context)
    assert reply == "没事"


def test_maybe_prior_reply_prefers_real_ack_for_comprehension_turn() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 还真是 | 好的\n"
        "- uncertain: 难说\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("没看懂帰", context)
    assert reply == "还真是"


def test_recent_context_reaction_uses_previous_target_short_reply() -> None:
    context = (
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 我听说有人考崩了会发出奇怪动静妨碍别人考试\n"
        "- 脸接大招: 我去\n"
        "- 脸接大招: 我感觉这种会被赶出去\n"
        "- The Xuan: 所以还是有耳机安心一点\n"
    )
    picked = ClaudeCodeProvider._recent_context_reaction("所以还是有耳机安心一点", context)
    assert picked is None


def test_recent_context_reaction_ignores_non_continuation_ack() -> None:
    context = (
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 太搞笑了这个\n"
        "- 脸接大招: 我去\n"
        "- The Xuan: 同道中人\n"
    )
    picked = ClaudeCodeProvider._recent_context_reaction("同道中人", context)
    assert picked is None


def test_recent_context_reaction_stops_at_nearest_target_block() -> None:
    context = (
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 梦里啥都有\n"
        "- 脸接大招: 还真是\n"
        "- The Xuan: 西安一共就仨学校\n"
        "- 脸接大招: 还有耳机\n"
        "- The Xuan: 是的\n"
        "- The Xuan: 我听说有人考崩了会发出奇怪动静妨碍别人考试\n"
        "- The Xuan: 所以还是有耳机安心一点\n"
    )
    picked = ClaudeCodeProvider._recent_context_reaction("所以还是有耳机安心一点", context)
    assert picked is None


def test_extract_recent_context_lines_keeps_more_than_twenty_rows() -> None:
    rows = "\n".join(f"- A: 前置{i}" for i in range(25))
    context = f"[EVAL_RECENT_CONTEXT]\n{rows}"
    picked = ClaudeCodeProvider._extract_recent_context_lines(context)
    assert len(picked) == 25
    assert picked[-1] == ("A", "前置24")


def test_accusatory_identity_prompt_prefers_short_negative_prior() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 还真是\n"
        "- negative: 不是 | 没有\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("你又在帮谁创QQ号", context)
    assert reply == "不是"


def test_generate_response_uses_accusatory_negative_without_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("_ask_text should not be called for high-confidence accusatory prior")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 还真是\n"
        "- negative: 不是 | 没有\n"
    )
    assert provider.generate_response("你又在帮谁创QQ号", context) == "不是"


def test_style_guard_preserves_context_grounded_reply_when_runtime_generates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    monkeypatch.setattr(provider, "_ask_text", lambda _: "我这个境外势力怎么都加载不出来")
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 还真是 | 是的\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 刚刚在农\n"
        "- The Xuan: 一秒猜出队友\n"
        "- 脸接大招: 输出日语的时候不太会\n"
        "- The Xuan: 居然没关评论区\n"
    )

    monkeypatch.setattr(provider, "_should_try_prior", lambda **_: False)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)

    reply = provider.generate_response("居然没关评论区", context)
    assert reply == "我这个境外势力怎么都加载不出来"


def test_maybe_prior_reply_uses_startled_reaction_for_safety_realization() -> None:
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 还真是 | 是的\n"
        "- reaction: 笑死我了 | 我去 | 卧槽\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("所以还是有耳机安心一点", context)
    assert reply == "我去"


def test_maybe_prior_reply_uses_reaction_for_motive_confession() -> None:
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 还真是 | 也行\n"
        "- reaction: 可恶！ | 我去\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("毕竟我玩这个游戏也有我的目的的", context)
    assert reply == "可恶！"


def test_generate_response_can_echo_short_affective_prompt_without_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("_ask_text should not be called for a high-confidence affective echo")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    assert provider.generate_response("好可爱啊", "[REPLY_PRIORS]\n- affirmative: 还真是") == "好可爱啊"


def test_maybe_prior_reply_handles_completion_check_as_affirmative() -> None:
    context = "[REPLY_PRIORS]\n- affirmative: 还真是 | 对的 | 确实\n- uncertain: 不知道\n"
    assert ClaudeCodeProvider._maybe_prior_reply("看完了？", context) == "对的"


def test_maybe_prior_reply_handles_direct_send_request() -> None:
    context = "[REPLY_PRIORS]\n- affirmative: 还真是 | 可以\n"
    assert ClaudeCodeProvider._maybe_prior_reply("你做了什么牛逼的工作流直接发给我", context) == "OK"


def test_maybe_prior_reply_handles_frustrated_concession() -> None:
    context = "[REPLY_PRIORS]\n- affirmative: 还真是 | 行吧 | 可以\n"
    assert ClaudeCodeProvider._maybe_prior_reply("那我还用你的干鸡毛", context) == "行吧"


def test_maybe_prior_reply_refuses_absurd_plan() -> None:
    context = "[REPLY_PRIORS]\n- negative: 不是 | 没有吧\n"
    assert ClaudeCodeProvider._maybe_prior_reply("我打算挖个坟躺进去等别人给我上贡", context) == "不行"


def test_maybe_prior_reply_uses_compact_praise_for_coincidence() -> None:
    context = "[REPLY_PRIORS]\n- reaction: 完了\n"
    assert ClaudeCodeProvider._maybe_prior_reply("她刚好负责这个项目的这一块", context) == "nb"


def test_maybe_prior_reply_acknowledges_setup_status() -> None:
    context = "[REPLY_PRIORS]\n- comfort: 可以 | 可以的\n- affirmative: 还真是\n"
    assert ClaudeCodeProvider._maybe_prior_reply("正准备装brew", context) == "可以"


def test_normative_alignment_prompt_can_use_evidence_backed_agreement() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- observed_median_chars_per_turn: 9.0\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 还真是 | 那确实难\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    reply = ClaudeCodeProvider._maybe_prior_reply("想我了这三个字不像是男生聊天用的", context)
    assert reply == "确实"


def test_style_guard_replaces_prompt_echo_with_ack_prior() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- response_length_mode: terse\n"
        "- short_reply_ratio: 0.62\n"
        "[REPLY_PRIORS]\n"
        "- affirmative: 是的 | 好滴 | 好的\n"
        "[LEXICON]\n"
        "还真是\n"
    )
    guarded = ClaudeCodeProvider._apply_style_guard("还真是战士装看着出", "然后战士装看着出", context)
    assert guarded in {"是的", "好滴", "好的"}


def test_is_semantically_aligned_for_completion_prompt_rejects_blind_affirmative() -> None:
    assert not ClaudeCodeProvider._is_semantically_aligned("买网线了吗", "是的")
    assert ClaudeCodeProvider._is_semantically_aligned("买网线了吗", "没呢")


def test_should_try_prior_prefers_only_short_or_intent_prompts() -> None:
    assert ClaudeCodeProvider._should_try_prior("小孩姐打上瓦了", "ctx")
    assert not ClaudeCodeProvider._should_try_prior("这个煞笔尊他语和自谦语怎么这么多啊", "ctx")
    assert not ClaudeCodeProvider._should_try_prior("真到说话的时候就想不起来用了", "ctx")


def test_generate_response_skips_prior_for_non_short_content_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str, __: str) -> str | None:
        raise AssertionError("_maybe_prior_reply should be skipped for non-short content prompt")

    monkeypatch.setattr(provider, "_maybe_prior_reply", _should_not_call)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_ask_text", lambda _: "这类语法系统性很强，先抓高频再回填细节。")

    reply = provider.generate_response("这个煞笔尊他语和自谦语怎么这么多啊", "ctx")
    assert "系统性" in reply


def test_maybe_memory_reply_only_for_micro_social_turn() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- length_policy: 回复长度由对话语义与人格机制共同决定，不做固定字数约束\n"
        "[DIALOGUE_MEMORY]\n"
        "- context: 荞麦地太搞笑了 => reply: 笑死我了\n"
        "- context: 真到说话的时候就想不起来用了 => reply: 还真是\n"
        "[LEXICON]\n"
        "还真是, 启动\n"
    )
    short_hit = ClaudeCodeProvider._maybe_memory_reply("荞麦地太搞笑了", context)
    long_skip = ClaudeCodeProvider._maybe_memory_reply("真到说话的时候就想不起来用了", context)
    assert short_hit in {"笑死我了", "还真是"}
    assert long_skip is None


def test_generate_response_rewrites_over_prescriptive_for_non_advice_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    calls = {"n": 0}

    def _fake_ask(_: str) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return "先稳住再撤，不要硬刚，先看位置和技能，等对方失误再反打。"
        return "还真是，太拼命了。"

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)

    out = provider.generate_response("太拼命了", "ctx")
    assert out == "还真是，太拼命了。"


def test_should_casual_rewrite_uses_median_chars_adaptive_cap() -> None:
    context = (
        "[STYLE_PROFILE]\n"
        "- observed_median_chars_per_turn: 9.0\n"
        "- observed_short_reply_ratio: 0.62\n"
    )
    assert ClaudeCodeProvider._should_casual_rewrite(
        prompt="原来是个梗",
        reply="还真是，不过这个梗背后还有好多历史背景，我给你慢慢展开讲清楚。",
        turn_mode="casual_alignment_first",
        context=context,
    )


def test_completion_done_phrase_is_not_panic_reaction() -> None:
    assert ClaudeCodeProvider._reaction_intent("一天把我之前便秘了两周的sft跑完了") is None
    assert not ClaudeCodeProvider._should_try_prior("一天把我之前便秘了两周的sft跑完了", "ctx")


def test_completion_done_phrase_does_not_pick_reaction_prior() -> None:
    context = "[REPLY_PRIORS]\n- reaction: 完了 | 卧槽\n- affirmative: 对的\n"
    assert ClaudeCodeProvider._maybe_prior_reply("一天把我之前便秘了两周的sft跑完了", context) is None


def test_generate_response_prompt_instructs_live_context_thread_reconstruction(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    captured = {}

    def _capture(prompt: str) -> str:
        captured["prompt"] = prompt
        return "那我为什么不用现成工具"

    monkeypatch.setattr(provider, "_ask_text", _capture)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)

    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 这是用来实现什么的\n"
        "- 极客小猪: 可以选择多种画笔线条的画板\n"
    )
    provider.generate_response("可以选择多种画笔线条的画板", context)

    assert "first reconstruct the active thread" in captured["prompt"]
    assert "do not answer the latest line as a helpful assistant" in captured["prompt"]
    assert "target speaker's last stated side wins" in captured["prompt"]
    assert "defend or clarify that stance" in captured["prompt"]


def test_generate_response_defers_generic_prior_when_recent_context_is_content_rich(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    calls = {"n": 0}

    def _fake_ask(_: str) -> str:
        calls["n"] += 1
        return "我这个境外势力怎么都加载不出来"

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 还真是 | 确实\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 输出日语的时候不太会\n"
        "- The Xuan: 居然没关评论区\n"
    )

    reply = provider.generate_response("居然没关评论区", context)

    assert reply == "我这个境外势力怎么都加载不出来"
    assert calls["n"] >= 1


def test_generate_response_rewrites_generic_catchphrase_when_context_needs_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    replies = iter(["还真是", "我这个境外势力怎么都加载不出来"])

    monkeypatch.setattr(provider, "_ask_text", lambda _: next(replies))
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 输出日语的时候不太会\n"
        "- The Xuan: 居然没关评论区\n"
    )

    reply = provider.generate_response("居然没关评论区", context)

    assert reply == "我这个境外势力怎么都加载不出来"


def test_style_guard_strips_redundant_generic_prefix_for_substantive_eval_reply() -> None:
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 感觉用ai做filter还是过滤的不够彻底\n"
    )

    reply = ClaudeCodeProvider._apply_style_guard(
        "还真是，AI filter只能粗筛，最好再加规则验一下。",
        "感觉用ai做filter还是过滤的不够彻底",
        context,
    )

    assert reply == "AI filter只能粗筛，最好再加规则验一下。"


def test_generate_response_prompt_treats_previous_target_question_as_follow_up() -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    captured = {}

    def _capture(prompt: str) -> str:
        captured["prompt"] = prompt
        return "那我为什么不用现成工具"

    provider._ask_text = _capture  # type: ignore[method-assign]
    provider._maybe_memory_reply = lambda **_: None  # type: ignore[method-assign]
    provider._maybe_prior_reply = lambda **_: None  # type: ignore[method-assign]
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 这是用来实现什么的\n"
        "- 极客小猪: 可以选择多种画笔线条的画板\n"
    )

    provider.generate_response("可以选择多种画笔线条的画板", context)

    assert "If the target speaker's previous turn was a question" in captured["prompt"]
    assert "respond as their follow-up after hearing the answer" in captured["prompt"]


def test_generate_response_keeps_compact_setup_ack_in_recent_context(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("setup acknowledgement should use compact prior")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    context = (
        "[REPLY_PRIORS]\n"
        "- comfort: 可以 | 可以的\n"
        "- affirmative: 对的\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 正准备装brew\n"
    )

    assert provider.generate_response("正准备装brew", context) == "可以"


def test_generate_response_keeps_low_information_ack_prior_in_recent_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("low-information acknowledgement should keep compact prior")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 还真是 | 确实\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 原来是个梗\n"
    )

    assert provider.generate_response("原来是个梗", context) == "还真是"


def test_generate_response_handles_such_ack_as_affirmative_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")

    def _should_not_call(_: str) -> str:
        raise AssertionError("obvious acknowledgement should use compact prior")

    monkeypatch.setattr(provider, "_ask_text", _should_not_call)
    context = (
        "[REPLY_PRIORS]\n"
        "- affirmative: 对的 | 确实\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 这样不至于分心\n"
    )

    assert provider.generate_response("这样不至于分心", context) == "对的"


def test_reply_polarity_treats_budui_as_negative() -> None:
    assert ClaudeCodeProvider._reply_polarity("不对") == "negative"


def test_maybe_prior_reply_prefers_duide_for_such_ack_over_huanzhenshi() -> None:
    context = "[REPLY_PRIORS]\n- affirmative: 还真是 | 对的 | 确实\n"
    assert ClaudeCodeProvider._maybe_prior_reply("这样不至于分心", context) == "对的"


def test_alignment_mode_defers_low_information_prior_for_persona_mechanism(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    calls = {"n": 0}

    def _fake_ask(_: str) -> str:
        calls["n"] += 1
        return "没事，先别硬上。"

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    context = (
        "[PERSONA_ALIGNMENT_MODE]\n"
        "- prefer persona mechanism over exact short reply\n"
        "[REPLY_PRIORS]\n"
        "- comfort: 没事 | 可以的\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 现在车力来了有点退缩\n"
    )

    reply = provider.generate_response("现在车力来了有点退缩", context)

    assert reply == "没事，先别硬上。"
    assert calls["n"] >= 1


def test_generate_response_prompt_preserves_latest_explicit_target_stance_in_alignment_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    captured = {}

    def _capture(prompt: str) -> str:
        captured["prompt"] = prompt
        return "玩家自己抽的啊"

    monkeypatch.setattr(provider, "_ask_text", _capture)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[PERSONA_ALIGNMENT_MODE]\n"
        "- prefer persona mechanism over exact short reply\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 傻逼的不是玩家是厂商啊\n"
        "- 极客小猪: 傻逼的是玩家不是厂商啊\n"
        "- 脸接大招: 搞这么个抽卡系统\n"
    )

    provider.generate_response("搞这么个抽卡系统", context)

    assert "latest explicit stance" in captured["prompt"]
    assert "keep the same polarity" in captured["prompt"]


def test_generate_response_rewrites_stacked_catchphrases_in_substantive_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    prompts: list[str] = []
    replies = iter([
        "卧槽，还真敢开啊，评论区不得直接启动。",
        "我这个境外势力怎么都加载不出来",
    ])

    def _fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 输出日语的时候不太会\n"
        "- The Xuan: 居然没关评论区\n"
    )

    reply = provider.generate_response("居然没关评论区", context)

    assert reply == "我这个境外势力怎么都加载不出来"
    assert any("STACKED_CATCHPHRASE_FIX" in prompt for prompt in prompts)


def test_style_guard_reduces_redundant_stacked_catchphrase_prefix() -> None:
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 输出日语的时候不太会\n"
        "- The Xuan: 居然没关评论区\n"
    )

    reply = ClaudeCodeProvider._apply_style_guard(
        "卧槽，还真敢开啊，评论区不得直接启动。",
        "居然没关评论区",
        context,
    )

    assert reply == "卧槽，敢开啊，评论区不得直接启动。"


def test_alignment_mode_defers_context_disconnected_memory_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    calls = {"n": 0}

    def _fake_ask(_: str) -> str:
        calls["n"] += 1
        return "这都误闯天家了，先看谁买单。"

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: "圣诞节没人陪我过")
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[PERSONA_ALIGNMENT_MODE]\n"
        "- prefer persona mechanism over exact sentence reuse\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 误闯天家\n"
    )

    reply = provider.generate_response("误闯天家", context)

    assert reply == "这都误闯天家了，先看谁买单。"
    assert calls["n"] == 1


def test_style_guard_strips_other_speaker_name_used_as_catchphrase() -> None:
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 我到了\n"
        "- The Xuan: 666\n"
    )

    reply = ClaudeCodeProvider._apply_style_guard(
        "脸接大招，执行力还挺强。",
        "666",
        context,
    )

    assert reply == "执行力还挺强。"


def test_style_guard_strips_other_speaker_name_from_stacked_opening() -> None:
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 坐廉航\n"
        "- The Xuan: 哈哈\n"
    )

    reply = ClaudeCodeProvider._apply_style_guard(
        "真脸接大招，便宜是真便宜，坐完也是真想骂。",
        "哈哈",
        context,
    )

    assert reply == "便宜是真便宜，坐完也是真想骂。"


def test_style_guard_strips_trailing_other_speaker_name_as_catchphrase() -> None:
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 坐廉航\n"
        "- The Xuan: 哈哈\n"
    )

    reply = ClaudeCodeProvider._apply_style_guard(
        "真的，省那点钱不值。 脸接大招。",
        "哈哈",
        context,
    )

    assert reply == "真的，省那点钱不值。"


def test_alignment_prompt_grounds_meme_reactions_without_explaining_too_much(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    captured: dict[str, str] = {}

    def _capture(prompt: str) -> str:
        captured["prompt"] = prompt
        return "这人无敌了，真文明。"

    monkeypatch.setattr(provider, "_ask_text", _capture)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[PERSONA_ALIGNMENT_MODE]\n"
        "- prefer persona mechanism over exact sentence reuse\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 好文明的玩笑\n"
        "- 脸接大招: 笑死我了\n"
    )

    provider.generate_response("笑死我了", context)

    assert "for laugh/meme reactions" in captured["prompt"]
    assert "one tiny concrete reason" in captured["prompt"]


def test_generate_response_defers_generic_laugh_prior_when_context_has_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    calls = {"n": 0}

    def _fake_ask(_: str) -> str:
        calls["n"] += 1
        return "第二排第一个还行，剩下确实有点神。"

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    context = (
        "[REPLY_PRIORS]\n"
        "- reaction: 笑死我了 | 哈哈\n"
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 第二排第一个不像卡通\n"
        "- The Xuan: 气笑了\n"
    )

    reply = provider.generate_response("气笑了", context)

    assert reply == "第二排第一个还行，剩下确实有点神。"
    assert calls["n"] >= 1


def test_generate_response_rewrites_generic_laugh_draft_when_context_has_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    prompts: list[str] = []
    replies = iter(["笑死我了", "第二排第一个还行，剩下确实有点神。"])

    def _fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "脸接大招\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 第二排第一个不像卡通\n"
        "- The Xuan: 气笑了\n"
    )

    reply = provider.generate_response("气笑了", context)

    assert reply == "第二排第一个还行，剩下确实有点神。"
    assert any("LOW_INFO_REACTION_FIX" in prompt for prompt in prompts)


def test_generate_response_rewrites_other_speaker_name_catchphrase_in_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    prompts: list[str] = []
    replies = iter(["还真是，纯脸接大招了", "我问问pwb"])

    def _fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- 脸接大招: 明天烧鸟可以再拉人\n"
        "- The Xuan: 66\n"
    )

    reply = provider.generate_response("66", context)

    assert reply == "我问问pwb"
    assert any("SPEAKER_NAME_CATCHPHRASE_FIX" in prompt for prompt in prompts)


def test_generate_response_rewrites_context_disconnected_memory_fragment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = ClaudeCodeProvider(cli_path="codex", runtime_cli="codex")
    prompts: list[str] = []
    replies = iter([
        "还真是，8000一瓶，圣诞节没人陪我过",
        "还真是，8000一瓶已经不是人间局了",
    ])

    def _fake_ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    monkeypatch.setattr(provider, "_ask_text", _fake_ask)
    monkeypatch.setattr(provider, "_maybe_memory_reply", lambda **_: None)
    monkeypatch.setattr(provider, "_maybe_prior_reply", lambda **_: None)
    context = (
        "[EVAL_TARGET_SPEAKER]\n"
        "极客小猪\n"
        "[EVAL_RECENT_CONTEXT]\n"
        "- The Xuan: 赫莲娜8000一瓶\n"
        "- 脸接大招: 误闯天家\n"
    )

    reply = provider.generate_response("误闯天家", context)

    assert reply == "还真是，8000一瓶已经不是人间局了"
    assert any("DISCONNECTED_FRAGMENT_FIX" in prompt for prompt in prompts)
