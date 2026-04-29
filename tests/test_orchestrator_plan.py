from persona_distill.orchestrator import _to_plan


def test_plan_fallback_on_invalid_json() -> None:
    plan = _to_plan(
        "not-json",
        persona_exists=False,
        requested_weight=0.25,
        requested_speaker=None,
        requested_target="both",
    )
    assert plan.source == "fallback"
    assert plan.mode == "cold_start"
    assert plan.new_corpus_weight == 0.25
    assert plan.target == "both"


def test_existing_persona_keeps_update_mode() -> None:
    raw = """{"mode":"cold_start","new_corpus_weight":0.6,"target":"codex","risk_level":"high","rationale":"x"}"""
    plan = _to_plan(
        raw,
        persona_exists=True,
        requested_weight=0.25,
        requested_speaker=None,
        requested_target="both",
    )
    assert plan.source == "agent"
    assert plan.mode == "update"
    assert plan.target == "codex"


def test_explicit_target_override_wins() -> None:
    raw = """{"mode":"update","new_corpus_weight":0.5,"target":"codex","risk_level":"medium","rationale":"ok"}"""
    plan = _to_plan(
        raw,
        persona_exists=True,
        requested_weight=0.25,
        requested_speaker=None,
        requested_target="none",
    )
    assert plan.target == "none"


def test_weight_is_clamped() -> None:
    raw = """{"mode":"update","new_corpus_weight":9.9,"target":"both","risk_level":"medium","rationale":"ok"}"""
    plan = _to_plan(
        raw,
        persona_exists=True,
        requested_weight=0.25,
        requested_speaker=None,
        requested_target="both",
    )
    assert plan.new_corpus_weight == 1.0
