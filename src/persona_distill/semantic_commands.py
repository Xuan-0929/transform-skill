from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .orchestrator import run_orchestrated_distill
from .providers import resolve_runtime_spec
from .repository import PersonaRepository
from .utils import canonical_skill_name
from .workflow import add_correction, export_persona, rollback_persona

SUPPORTED_SEMANTIC_INTENTS = {
    "friend-create",
    "friend-update",
    "friend-list",
    "friend-history",
    "friend-rollback",
    "friend-export",
    "friend-correct",
    "friend-doctor",
}

INTENT_ALIASES = {
    "create-friend": "friend-create",
    "friend-create": "friend-create",
    "create": "friend-create",
    "cold-start": "friend-create",
    "cold_start": "friend-create",
    "update-friend": "friend-update",
    "friend-update": "friend-update",
    "update": "friend-update",
    "list-friends": "friend-list",
    "friend-list": "friend-list",
    "list": "friend-list",
    "friend-history": "friend-history",
    "history": "friend-history",
    "friend-rollback": "friend-rollback",
    "rollback": "friend-rollback",
    "friend-export": "friend-export",
    "export": "friend-export",
    "friend-correct": "friend-correct",
    "correct": "friend-correct",
    "correction": "friend-correct",
    "doctor": "friend-doctor",
    "friend-doctor": "friend-doctor",
}

LLM_REQUIRED_INTENTS = {"friend-create", "friend-update"}


def normalize_intent(raw: str) -> str:
    normalized = (raw or "").strip().lower().replace("_", "-")
    intent = INTENT_ALIASES.get(normalized, normalized)
    if intent not in SUPPORTED_SEMANTIC_INTENTS:
        supported = ", ".join(sorted(SUPPORTED_SEMANTIC_INTENTS))
        raise ValueError(f"Unsupported intent '{raw}'. Supported intents: {supported}")
    return intent


def intent_requires_llm(intent: str) -> bool:
    return normalize_intent(intent) in LLM_REQUIRED_INTENTS


@dataclass
class SemanticRequest:
    intent: str
    input_path: Path | None = None
    persona: str | None = None
    fmt: str = "auto"
    speaker: str | None = None
    new_corpus_weight: float = 0.25
    suite: Path | None = None
    target: str = "both"
    to_version: str | None = None
    correction_text: str | None = None
    correction_section: str = "beliefs_and_values"
    history_limit: int = 20


def _resolve_persona_id(persona: str | None, input_path: Path | None) -> str:
    if persona and persona.strip():
        return persona.strip()
    if input_path is not None:
        stem = input_path.stem.strip() or "friend"
        return canonical_skill_name(stem)
    raise ValueError("Missing persona id. Provide --persona or include --input for auto-derive.")


def _list_friends(repo: PersonaRepository) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for persona in repo.list_personas():
        state = repo.load_state(persona)
        rows.append(
            {
                "persona": persona,
                "current_version": state.current_version,
                "stable_version": state.stable_version,
                "latest_version": state.latest_version,
                "created_at": state.created_at.isoformat(),
            }
        )
    return {"count": len(rows), "friends": rows}


def run_semantic_command(
    *,
    repo: PersonaRepository,
    provider: Any | None,
    request: SemanticRequest,
) -> dict[str, Any]:
    intent = normalize_intent(request.intent)

    if intent == "friend-list":
        payload = _list_friends(repo)
        return {"semantic_intent": intent, **payload}

    if intent == "friend-doctor":
        payload = {
            "semantic_intent": intent,
            "runtime_mode": resolve_runtime_spec(),
            "llm_required_intents": sorted(LLM_REQUIRED_INTENTS),
            "local_only_intents": sorted(SUPPORTED_SEMANTIC_INTENTS - LLM_REQUIRED_INTENTS),
            "hints": [
                "Distillation uses host runtime CLI (Codex in Codex, Claude in Claude Code).",
                "Use friend-create/friend-update when you want distillation.",
                "Use friend-list/friend-history/friend-rollback/friend-export/friend-correct for maintenance.",
            ],
        }
        return payload

    persona_id = _resolve_persona_id(request.persona, request.input_path)

    if intent == "friend-history":
        if not repo.has_persona(persona_id):
            raise ValueError(f"Persona '{persona_id}' not found.")
        state = repo.load_state(persona_id)
        events = repo.load_audit_events(persona_id, limit=max(1, request.history_limit))
        return {
            "semantic_intent": intent,
            "persona": persona_id,
            "state": {
                "current_version": state.current_version,
                "stable_version": state.stable_version,
                "latest_version": state.latest_version,
            },
            "history_count": len(events),
            "history": events,
        }

    if intent == "friend-rollback":
        if not request.to_version:
            raise ValueError("friend-rollback requires --to.")
        result = rollback_persona(repo, persona_id, request.to_version)
        return {"semantic_intent": intent, "persona": persona_id, **result}

    if intent == "friend-export":
        result = export_persona(repo, persona_id, target=request.target, version=request.to_version)
        return {"semantic_intent": intent, "persona": persona_id, **result}

    if intent == "friend-correct":
        if not request.correction_text:
            raise ValueError("friend-correct requires --text.")
        note = add_correction(
            repo,
            persona_id,
            section=request.correction_section,
            instruction=request.correction_text,
        )
        return {
            "semantic_intent": intent,
            "persona": persona_id,
            "correction": note.model_dump(mode="json"),
        }

    if request.input_path is None:
        raise ValueError(f"{intent} requires --input.")
    if provider is None:
        raise ValueError(f"{intent} requires an active LLM provider runtime.")

    if intent == "friend-create" and repo.has_persona(persona_id):
        raise ValueError(
            f"Persona '{persona_id}' already exists. Use friend-update for incremental evolution."
        )
    if intent == "friend-update" and not repo.has_persona(persona_id):
        raise ValueError(
            f"Persona '{persona_id}' does not exist yet. Use friend-create for cold-start distillation."
        )

    result = run_orchestrated_distill(
        repo=repo,
        provider=provider,
        input_path=request.input_path.resolve(),
        persona=persona_id,
        fmt=request.fmt,
        speaker=request.speaker,
        new_corpus_weight=request.new_corpus_weight,
        suite=request.suite.resolve() if request.suite else None,
        target=request.target,
    )
    return {
        "semantic_intent": intent,
        "persona": persona_id,
        "requested_mode": "cold_start" if intent == "friend-create" else "update",
        **result,
    }
