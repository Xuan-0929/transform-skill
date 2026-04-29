from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .models import CorrectionNote, CorpusItem, EvalComparison, PersonaProfile, PersonaState, SkillVersion
from .utils import utc_now


class PersonaRepository:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self.base_dir = self.root / ".distill" / "personas"

    def persona_dir(self, persona_id: str) -> Path:
        return self.base_dir / persona_id

    def list_personas(self) -> list[str]:
        if not self.base_dir.exists():
            return []
        personas: list[str] = []
        for item in self.base_dir.iterdir():
            if not item.is_dir():
                continue
            if (item / "state.json").exists():
                personas.append(item.name)
        return sorted(personas)

    def _state_path(self, persona_id: str) -> Path:
        return self.persona_dir(persona_id) / "state.json"

    def _corpus_path(self, persona_id: str) -> Path:
        return self.persona_dir(persona_id) / "corpus" / "items.jsonl"

    def _corrections_path(self, persona_id: str) -> Path:
        return self.persona_dir(persona_id) / "corrections" / "notes.jsonl"

    def versions_dir(self, persona_id: str) -> Path:
        return self.persona_dir(persona_id) / "versions"

    def init_persona(self, persona_id: str) -> PersonaState:
        pdir = self.persona_dir(persona_id)
        (pdir / "corpus").mkdir(parents=True, exist_ok=True)
        (pdir / "corrections").mkdir(parents=True, exist_ok=True)
        (pdir / "versions").mkdir(parents=True, exist_ok=True)
        (pdir / "exports").mkdir(parents=True, exist_ok=True)
        (pdir / "audit").mkdir(parents=True, exist_ok=True)
        state = PersonaState(persona_id=persona_id, created_at=utc_now())
        self.save_state(persona_id, state)
        return state

    def has_persona(self, persona_id: str) -> bool:
        return self._state_path(persona_id).exists()

    def load_state(self, persona_id: str) -> PersonaState:
        path = self._state_path(persona_id)
        return PersonaState.model_validate_json(path.read_text(encoding="utf-8"))

    def save_state(self, persona_id: str, state: PersonaState) -> None:
        self._state_path(persona_id).write_text(
            state.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def append_corpus_items(self, persona_id: str, items: Iterable[CorpusItem]) -> int:
        accepted, _ = self.append_corpus_items_with_items(persona_id, items)
        return accepted

    def append_corpus_items_with_items(
        self, persona_id: str, items: Iterable[CorpusItem]
    ) -> tuple[int, list[CorpusItem]]:
        path = self._corpus_path(persona_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_items = self.load_corpus_items(persona_id)
        existing_ids = {i.source_message_id for i in existing_items if i.source_message_id}
        existing_composite = {
            f"{i.source}|{i.speaker}|{i.timestamp.isoformat() if i.timestamp else ''}|{i.content_hash}"
            for i in existing_items
        }
        accepted = 0
        accepted_items: list[CorpusItem] = []
        with path.open("a", encoding="utf-8") as f:
            for item in items:
                if item.source_message_id and item.source_message_id in existing_ids:
                    continue
                composite = (
                    f"{item.source}|{item.speaker}|"
                    f"{item.timestamp.isoformat() if item.timestamp else ''}|{item.content_hash}"
                )
                if composite in existing_composite:
                    continue
                f.write(item.model_dump_json() + "\n")
                if item.source_message_id:
                    existing_ids.add(item.source_message_id)
                existing_composite.add(composite)
                accepted += 1
                accepted_items.append(item)
        return accepted, accepted_items

    def load_corpus_items(self, persona_id: str) -> list[CorpusItem]:
        path = self._corpus_path(persona_id)
        if not path.exists():
            return []
        items: list[CorpusItem] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            items.append(CorpusItem.model_validate_json(line))
        return items

    def append_correction(self, persona_id: str, note: CorrectionNote) -> None:
        path = self._corrections_path(persona_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(note.model_dump_json() + "\n")

    def load_corrections(self, persona_id: str) -> list[CorrectionNote]:
        path = self._corrections_path(persona_id)
        if not path.exists():
            return []
        notes: list[CorrectionNote] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            notes.append(CorrectionNote.model_validate_json(line))
        return notes

    def list_versions(self, persona_id: str) -> list[str]:
        vdir = self.versions_dir(persona_id)
        if not vdir.exists():
            return []
        return sorted(p.name for p in vdir.iterdir() if p.is_dir() and p.name.startswith("v"))

    def next_version(self, persona_id: str) -> str:
        versions = self.list_versions(persona_id)
        if not versions:
            return "v0001"
        return f"v{int(versions[-1][1:]) + 1:04d}"

    def version_dir(self, persona_id: str, version: str) -> Path:
        return self.versions_dir(persona_id) / version

    def load_profile(self, persona_id: str, version: str) -> PersonaProfile:
        path = self.version_dir(persona_id, version) / "profile.json"
        return PersonaProfile.model_validate_json(path.read_text(encoding="utf-8"))

    def load_eval(self, persona_id: str, version: str) -> EvalComparison | None:
        path = self.version_dir(persona_id, version) / "eval_comparison.json"
        if not path.exists():
            return None
        return EvalComparison.model_validate_json(path.read_text(encoding="utf-8"))

    def save_version_artifacts(
        self,
        persona_id: str,
        version: SkillVersion,
        profile: PersonaProfile,
        manifest: dict,
        validation: dict,
        eval_comparison: EvalComparison,
    ) -> Path:
        vdir = self.version_dir(persona_id, version.version)
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "profile.json").write_text(profile.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "skill_version.json").write_text(version.model_dump_json(indent=2), encoding="utf-8")
        (vdir / "persona_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (vdir / "validation_report.json").write_text(
            json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (vdir / "eval_comparison.json").write_text(
            eval_comparison.model_dump_json(indent=2), encoding="utf-8"
        )
        return vdir

    def append_audit(self, persona_id: str, payload: dict) -> None:
        path = self.persona_dir(persona_id) / "audit" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        enriched = {"created_at": utc_now().isoformat(), **payload}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(enriched, ensure_ascii=False) + "\n")

    def load_audit_events(self, persona_id: str, limit: int | None = None) -> list[dict]:
        path = self.persona_dir(persona_id) / "audit" / "events.jsonl"
        if not path.exists():
            return []
        events: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                events.append(row)
        if limit is not None and limit > 0:
            return events[-limit:]
        return events
