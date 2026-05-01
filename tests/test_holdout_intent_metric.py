from __future__ import annotations

from persona_distill.holdout import _intent_compat_score


def test_intent_compat_matches_same_bucket() -> None:
    score = _intent_compat_score("不知道", ["不好说", "看情况"])
    assert score == 1.0


def test_intent_compat_matches_reaction_family_without_exact_phrase() -> None:
    score = _intent_compat_score("哈哈", ["完了", "卧槽"])
    assert score == 0.7


def test_intent_compat_is_neutral_when_references_have_no_clear_intent() -> None:
    score = _intent_compat_score("随便说一句", ["这题太难了", "我在路上"])
    assert score == 0.5


def test_intent_compat_matches_comfort_bucket() -> None:
    score = _intent_compat_score("正常，先稳住", ["没事"])
    assert score == 1.0


def test_intent_compat_matches_affirmative_for_quitesure_ack() -> None:
    score = _intent_compat_score("还真是", ["确实！"])
    assert score == 1.0


def test_intent_bucket_treats_budui_as_negative_not_affirmative() -> None:
    assert _intent_compat_score("不对", ["对的"]) == 0.0
    assert _intent_compat_score("不对", ["不是"]) == 1.0
