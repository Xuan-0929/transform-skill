from pathlib import Path

from persona_distill.repository import PersonaRepository
from persona_distill.semantic_commands import SemanticRequest, normalize_intent, run_semantic_command


def test_normalize_intent_aliases() -> None:
    assert normalize_intent("create-friend") == "friend-create"
    assert normalize_intent("UPDATE_FRIEND") == "friend-update"
    assert normalize_intent("list") == "friend-list"


def test_friend_list_empty(tmp_path: Path) -> None:
    repo = PersonaRepository(tmp_path)
    payload = run_semantic_command(
        repo=repo,
        provider=None,
        request=SemanticRequest(intent="friend-list"),
    )
    assert payload["semantic_intent"] == "friend-list"
    assert payload["count"] == 0
    assert payload["friends"] == []


def test_friend_correct_and_history(tmp_path: Path) -> None:
    repo = PersonaRepository(tmp_path)
    repo.init_persona("laojin")

    correct_payload = run_semantic_command(
        repo=repo,
        provider=None,
        request=SemanticRequest(
            intent="friend-correct",
            persona="laojin",
            correction_text="少一点说教，多一点哥们口吻。",
            correction_section="expression_dna",
        ),
    )
    assert correct_payload["semantic_intent"] == "friend-correct"
    assert correct_payload["persona"] == "laojin"
    assert correct_payload["correction"]["section"] == "expression_dna"

    history_payload = run_semantic_command(
        repo=repo,
        provider=None,
        request=SemanticRequest(
            intent="friend-history",
            persona="laojin",
            history_limit=10,
        ),
    )
    assert history_payload["semantic_intent"] == "friend-history"
    assert history_payload["history_count"] >= 1
    assert any(event.get("event") == "correction" for event in history_payload["history"])

def test_friend_list_hides_backup_persona_directories(tmp_path: Path) -> None:
    repo = PersonaRepository(tmp_path)
    repo.init_persona("jc")
    repo.init_persona("jc.backup-20260501-151505")

    payload = run_semantic_command(
        repo=repo,
        provider=None,
        request=SemanticRequest(intent="friend-list"),
    )

    assert payload["count"] == 1
    assert [friend["persona"] for friend in payload["friends"]] == ["jc"]

