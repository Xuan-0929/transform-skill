from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .evaluation import compare_eval, load_benchmark
from .extract import extract_profile_agentic
from .ingest import ingest_file
from .models import (
    CORE_SECTIONS,
    ClaimStatus,
    CorrectionNote,
    EvidenceClaim,
    PersonaProfile,
    SkillVersion,
)
from .providers import build_provider
from .repository import PersonaRepository
from .synthesize import render_skill_package
from .utils import canonical_skill_name, has_negation, jaccard_similarity, stable_hash, utc_now
from .validation import run_validation

DEFAULT_NEW_CORPUS_WEIGHT = 0.25


def _ensure_persona(repo: PersonaRepository, persona_id: str) -> None:
    if not repo.has_persona(persona_id):
        raise ValueError(f"Persona '{persona_id}' not found. Run `distill init {persona_id}` first.")


def ingest_corpus(
    repo: PersonaRepository,
    persona_id: str,
    input_path: Path,
    fmt: str,
    speaker_filter: str | None = None,
) -> dict:
    _ensure_persona(repo, persona_id)
    items = ingest_file(input_path, fmt, speaker_filter=speaker_filter)
    accepted = repo.append_corpus_items(persona_id, items)
    repo.append_audit(
        persona_id,
        {
            "event": "ingest",
            "input_path": str(input_path),
            "speaker_filter": speaker_filter,
            "detected_items": len(items),
            "accepted_items": accepted,
        },
    )
    return {"detected": len(items), "accepted": accepted}


def add_correction(repo: PersonaRepository, persona_id: str, section: str, instruction: str) -> CorrectionNote:
    _ensure_persona(repo, persona_id)
    if section not in CORE_SECTIONS:
        section = "beliefs_and_values"
    note = CorrectionNote(
        id=stable_hash(f"{persona_id}:{section}:{instruction}:{utc_now().isoformat()}", prefix="corr"),
        created_at=utc_now(),
        section=section,
        instruction=instruction,
    )
    repo.append_correction(persona_id, note)
    repo.append_audit(
        persona_id,
        {
            "event": "correction",
            "section": note.section,
            "note_id": note.id,
        },
    )
    return note


def _claim_conflict(a: EvidenceClaim, b: EvidenceClaim) -> bool:
    if a.section != b.section:
        return False
    if jaccard_similarity(a.claim, b.claim) < 0.5:
        return False
    return has_negation(a.claim) != has_negation(b.claim)


def _clamp_new_corpus_weight(new_corpus_weight: float) -> float:
    return max(0.0, min(1.0, float(new_corpus_weight)))


def _weighted_take_count(total_candidates: int, weight: float) -> int:
    if total_candidates <= 0 or weight <= 0:
        return 0
    keep = int(round(total_candidates * weight))
    if keep == 0:
        keep = 1
    return min(total_candidates, keep)


def _merge_ranked_strings(previous: list[str], fresh: list[str], limit: int, new_weight: float) -> list[str]:
    desired_new = _weighted_take_count(min(limit, len(fresh)), new_weight)
    merged: list[str] = []
    seen: set[str] = set()

    for value in previous:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        merged.append(cleaned)
        seen.add(cleaned)
        if len(merged) >= max(0, limit - desired_new):
            break

    for value in fresh:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        merged.append(cleaned)
        seen.add(cleaned)
        if len(merged) >= limit:
            break

    if len(merged) < limit:
        for value in previous:
            cleaned = value.strip()
            if not cleaned or cleaned in seen:
                continue
            merged.append(cleaned)
            seen.add(cleaned)
            if len(merged) >= limit:
                break
    return merged


def _merge_ranked_dict_pairs(
    previous: list[dict[str, str]],
    fresh: list[dict[str, str]],
    limit: int,
    new_weight: float,
) -> list[dict[str, str]]:
    desired_new = _weighted_take_count(min(limit, len(fresh)), new_weight)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()

    def add_pair(pair: dict[str, str]) -> bool:
        context = pair.get("context", "").strip()
        reply = pair.get("reply", "").strip()
        if not context or not reply:
            return False
        key = f"{context}|||{reply}"
        if key in seen:
            return False
        seen.add(key)
        merged.append({"context": context, "reply": reply})
        return True

    for pair in previous:
        if add_pair(pair) and len(merged) >= max(0, limit - desired_new):
            break
    for pair in fresh:
        if add_pair(pair) and len(merged) >= limit:
            break
    if len(merged) < limit:
        for pair in previous:
            if add_pair(pair) and len(merged) >= limit:
                break
    return merged


def _blend_expression_metrics(
    previous: dict[str, float | str],
    fresh: dict[str, float | str],
    new_weight: float,
) -> dict[str, float | str]:
    merged: dict[str, float | str] = {}
    for key in set(previous.keys()) | set(fresh.keys()):
        pv = previous.get(key)
        fv = fresh.get(key)
        if isinstance(pv, (int, float)) and isinstance(fv, (int, float)):
            merged[key] = round(float(pv) * (1 - new_weight) + float(fv) * new_weight, 3)
            continue
        merged[key] = pv if pv is not None else fv  # keep prior narrative unless missing
    return merged


def _merge_ranked_any(previous: list[Any], fresh: list[Any], limit: int, new_weight: float) -> list[Any]:
    desired_new = _weighted_take_count(min(limit, len(fresh)), new_weight)
    merged: list[Any] = []
    seen: set[str] = set()

    def model_key(obj: Any) -> str:
        if hasattr(obj, "id") and getattr(obj, "id", None):
            return str(getattr(obj, "id"))
        return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)

    for obj in previous:
        key = model_key(obj)
        if key in seen:
            continue
        seen.add(key)
        merged.append(obj)
        if len(merged) >= max(0, limit - desired_new):
            break
    for obj in fresh:
        key = model_key(obj)
        if key in seen:
            continue
        seen.add(key)
        merged.append(obj)
        if len(merged) >= limit:
            break
    if len(merged) < limit:
        for obj in previous:
            key = model_key(obj)
            if key in seen:
                continue
            seen.add(key)
            merged.append(obj)
            if len(merged) >= limit:
                break
    return merged


def _merge_profiles(
    previous: PersonaProfile,
    fresh: PersonaProfile,
    new_corpus_weight: float,
) -> tuple[PersonaProfile, list[str], int]:
    weight = _clamp_new_corpus_weight(new_corpus_weight)
    changed_sections: list[str] = []
    conflict_count = 0
    merged_sections: dict[str, list[EvidenceClaim]] = {}

    for section in CORE_SECTIONS:
        prev_claims = [c.model_copy(deep=True) for c in previous.sections.get(section, [])]
        new_claims = [c.model_copy(deep=True) for c in fresh.sections.get(section, [])]
        existing = {c.claim: idx for idx, c in enumerate(prev_claims)}
        section_changed = False
        additions_budget = _weighted_take_count(len(new_claims), weight)
        added = 0

        for claim in new_claims:
            if claim.claim in existing:
                prev_idx = existing[claim.claim]
                prev_claim = prev_claims[prev_idx]
                blended_conf = round(
                    prev_claim.confidence * (1 - weight * 0.35) + claim.confidence * (weight * 0.35),
                    3,
                )
                if abs(blended_conf - prev_claim.confidence) >= 0.01:
                    prev_claim.confidence = blended_conf
                    section_changed = True
                continue
            conflicts = [pc for pc in prev_claims if _claim_conflict(pc, claim)]
            if conflicts:
                conflict_count += 1
                # Low weight blocks conflict takeover to preserve old persona.
                if weight < 0.75:
                    continue
                claim.status = ClaimStatus.REVISED
                claim.conflicts_with = [pc.id for pc in conflicts]
                claim.tags = sorted(set(claim.tags + ["conflict", "weighted_new"]))
            if added >= additions_budget:
                continue
            claim.confidence = round(claim.confidence * (0.6 + 0.4 * weight), 3)
            prev_claims.append(claim)
            existing[claim.claim] = len(prev_claims) - 1
            added += 1
            section_changed = True

        merged_sections[section] = prev_claims
        if section_changed:
            changed_sections.append(section)

    merged_style_memory = _merge_ranked_strings(
        previous=previous.style_memory,
        fresh=fresh.style_memory,
        limit=260,
        new_weight=weight,
    )
    merged_signature = _merge_ranked_strings(
        previous=previous.signature_lexicon,
        fresh=fresh.signature_lexicon,
        limit=50,
        new_weight=weight,
    )
    merged_ctx_pairs = _merge_ranked_dict_pairs(
        previous=previous.context_reply_memory,
        fresh=fresh.context_reply_memory,
        limit=1600,
        new_weight=weight,
    )

    merged = PersonaProfile(
        persona_id=fresh.persona_id,
        version=fresh.version,
        generated_at=fresh.generated_at,
        sections=merged_sections,
        expression_metrics=_blend_expression_metrics(previous.expression_metrics, fresh.expression_metrics, weight),
        uncertainty_notes=_merge_ranked_strings(
            previous=previous.uncertainty_notes,
            fresh=fresh.uncertainty_notes,
            limit=24,
            new_weight=weight,
        ),
        signature_lexicon=merged_signature,
        style_memory=merged_style_memory,
        context_reply_memory=merged_ctx_pairs,
        model_cards=_merge_ranked_any(previous.model_cards, fresh.model_cards, limit=10, new_weight=weight),
        decision_rules=_merge_ranked_any(previous.decision_rules, fresh.decision_rules, limit=20, new_weight=weight),
        contradictions=_merge_ranked_any(
            previous.contradictions,
            fresh.contradictions,
            limit=40,
            new_weight=weight,
        ),
        known_answer_anchors=_merge_ranked_any(
            previous.known_answer_anchors,
            fresh.known_answer_anchors,
            limit=24,
            new_weight=weight,
        ),
        source_metrics={
            **previous.source_metrics,
            **fresh.source_metrics,
            "new_corpus_weight": round(weight, 3),
            "base_source_item_count": previous.source_item_count,
            "new_source_item_count": fresh.source_item_count,
        },
        source_item_count=previous.source_item_count + fresh.source_item_count,
    )
    return merged, changed_sections, conflict_count


def _state_pass_rate(repo: PersonaRepository, persona_id: str, stable_version: str | None) -> float | None:
    if not stable_version:
        return None
    prev_eval = repo.load_eval(persona_id, stable_version)
    if not prev_eval:
        return None
    return prev_eval.with_skill.pass_rate


def _finalize_version_state(
    repo: PersonaRepository,
    persona_id: str,
    version: str,
    passed: bool,
) -> dict:
    state = repo.load_state(persona_id)
    parent = state.current_version
    state.latest_version = version

    rollback = False
    if passed:
        state.current_version = version
        state.stable_version = version
    else:
        if state.stable_version:
            rollback = True
            state.current_version = state.stable_version
        elif state.current_version is None:
            state.current_version = version

    repo.save_state(persona_id, state)
    return {"parent_version": parent, "rollback": rollback, "state": state}


def _build_common(
    repo: PersonaRepository,
    persona_id: str,
    eval_suite: Path | None,
    merge_with_previous: bool,
) -> dict:
    _ensure_persona(repo, persona_id)
    items = repo.load_corpus_items(persona_id)
    if not items:
        raise ValueError("No corpus items found. Run ingest first.")

    state = repo.load_state(persona_id)
    previous_profile = None
    if merge_with_previous and state.current_version:
        previous_profile = repo.load_profile(persona_id, state.current_version)

    version = repo.next_version(persona_id)
    provider = build_provider()
    corrections = repo.load_corrections(persona_id)

    fresh_profile = extract_profile_agentic(
        persona_id=persona_id,
        version=version,
        items=items,
        corrections=corrections,
        provider=provider,
        target_speaker=persona_id,
        profile_mode="style_anchored_update" if previous_profile is not None else "friend_cold_start",
        style_anchor_profile=previous_profile,
    )

    if previous_profile is not None:
        profile, changed_sections, conflict_count = _merge_profiles(
            previous_profile,
            fresh_profile,
            new_corpus_weight=1.0,
        )
    else:
        profile, changed_sections, conflict_count = fresh_profile, CORE_SECTIONS[:], 0

    parent_version = state.current_version
    vdir = repo.version_dir(persona_id, version)
    skill_dir = vdir / "skill"
    skill_name = canonical_skill_name(persona_id)
    manifest = render_skill_package(
        profile,
        skill_dir,
        provider,
        persona_name=persona_id,
        skill_name=skill_name,
    )

    validation = run_validation(skill_dir, profile, {item.id for item in items} | {"style_memory"})

    benchmark = load_benchmark(eval_suite)
    previous_pass_rate = _state_pass_rate(repo, persona_id, state.stable_version)
    eval_comparison = compare_eval(
        benchmark=benchmark,
        profile=profile,
        provider=provider,
        previous_stable_pass_rate=previous_pass_rate,
    )

    status = "stable" if (validation.ok and eval_comparison.gate_passed) else "quarantined"
    state_result = _finalize_version_state(
        repo=repo,
        persona_id=persona_id,
        version=version,
        passed=(status == "stable"),
    )

    version_record = SkillVersion(
        version=version,
        parent_version=parent_version,
        created_at=utc_now(),
        status=status,
        changed_sections=changed_sections,
        eval_diff={
            "pass_rate_delta_vs_baseline": round(
                eval_comparison.with_skill.pass_rate - eval_comparison.baseline.pass_rate, 3
            ),
            "avg_score_delta_vs_baseline": round(
                eval_comparison.with_skill.avg_score - eval_comparison.baseline.avg_score, 3
            ),
            "token_growth_vs_baseline": round(
                eval_comparison.with_skill.avg_response_tokens
                / max(1.0, eval_comparison.baseline.avg_response_tokens),
                3,
            ),
            "previous_stable_pass_rate": previous_pass_rate if previous_pass_rate is not None else -1.0,
        },
    )

    manifest.update(
        {
            "parent_version": parent_version,
            "changed_sections": changed_sections,
            "conflict_count": conflict_count,
            "status": status,
            "gate_reasons": eval_comparison.reasons,
        }
    )

    repo.save_version_artifacts(
        persona_id=persona_id,
        version=version_record,
        profile=profile,
        manifest=manifest,
        validation={
            "schema_errors": validation.schema_errors,
            "consistency_errors": validation.consistency_errors,
            "conflicts": validation.conflicts,
            "ok": validation.ok,
        },
        eval_comparison=eval_comparison,
    )

    repo.append_audit(
        persona_id,
        {
            "event": "build" if not merge_with_previous else "update",
            "version": version,
            "status": status,
            "changed_sections": changed_sections,
            "rollback": state_result["rollback"],
            "distill_mode": "agent",
            "pass_rate": eval_comparison.with_skill.pass_rate,
            "baseline_pass_rate": eval_comparison.baseline.pass_rate,
        },
    )

    return {
        "version": version,
        "status": status,
        "changed_sections": changed_sections,
        "conflicts": conflict_count,
        "validation_ok": validation.ok,
        "validation_errors": validation.schema_errors + validation.consistency_errors,
        "gate_passed": eval_comparison.gate_passed,
        "gate_reasons": eval_comparison.reasons,
        "pass_rate": eval_comparison.with_skill.pass_rate,
        "baseline_pass_rate": eval_comparison.baseline.pass_rate,
        "rollback": state_result["rollback"],
        "distill_mode": "agent",
        "output_dir": str(vdir),
    }


def build_persona(
    repo: PersonaRepository,
    persona_id: str,
    eval_suite: Path | None,
) -> dict:
    return _build_common(
        repo,
        persona_id,
        eval_suite=eval_suite,
        merge_with_previous=False,
    )


def update_persona(
    repo: PersonaRepository,
    persona_id: str,
    eval_suite: Path | None,
    input_path: Path | None,
    fmt: str,
    speaker_filter: str | None,
    correction: str | None,
    correction_section: str,
    new_corpus_weight: float = DEFAULT_NEW_CORPUS_WEIGHT,
) -> dict:
    _ensure_persona(repo, persona_id)
    accepted_delta_items = []
    if input_path is not None:
        ingested_items = ingest_file(input_path, fmt, speaker_filter=speaker_filter)
        accepted_count, accepted_delta_items = repo.append_corpus_items_with_items(persona_id, ingested_items)
        repo.append_audit(
            persona_id,
            {
                "event": "ingest",
                "input_path": str(input_path),
                "speaker_filter": speaker_filter,
                "detected_items": len(ingested_items),
                "accepted_items": accepted_count,
            },
        )
    if correction:
        add_correction(repo, persona_id, correction_section, correction)

    # Weighted incremental update path:
    # if a current version exists and we are adding new corpus only,
    # distill from the delta corpus and blend with prior persona.
    state = repo.load_state(persona_id)
    if (
        input_path is not None
        and correction is None
        and state.current_version is not None
        and accepted_delta_items
    ):
        previous_profile = repo.load_profile(persona_id, state.current_version)
        version = repo.next_version(persona_id)
        provider = build_provider()
        corrections = repo.load_corrections(persona_id)
        fresh_profile = extract_profile_agentic(
            persona_id=persona_id,
            version=version,
            items=accepted_delta_items,
            corrections=corrections,
            provider=provider,
            target_speaker=persona_id,
            profile_mode="style_anchored_update",
            style_anchor_profile=previous_profile,
        )
        profile, changed_sections, conflict_count = _merge_profiles(
            previous=previous_profile,
            fresh=fresh_profile,
            new_corpus_weight=new_corpus_weight,
        )
        parent_version = state.current_version
        vdir = repo.version_dir(persona_id, version)
        skill_dir = vdir / "skill"
        skill_name = canonical_skill_name(persona_id)
        manifest = render_skill_package(
            profile,
            skill_dir,
            provider,
            persona_name=persona_id,
            skill_name=skill_name,
        )

        all_items = repo.load_corpus_items(persona_id)
        validation = run_validation(skill_dir, profile, {item.id for item in all_items} | {"style_memory"})
        benchmark = load_benchmark(eval_suite)
        previous_pass_rate = _state_pass_rate(repo, persona_id, state.stable_version)
        eval_comparison = compare_eval(
            benchmark=benchmark,
            profile=profile,
            provider=provider,
            previous_stable_pass_rate=previous_pass_rate,
        )

        status = "stable" if (validation.ok and eval_comparison.gate_passed) else "quarantined"
        state_result = _finalize_version_state(
            repo=repo,
            persona_id=persona_id,
            version=version,
            passed=(status == "stable"),
        )

        version_record = SkillVersion(
            version=version,
            parent_version=parent_version,
            created_at=utc_now(),
            status=status,
            changed_sections=changed_sections,
            eval_diff={
                "pass_rate_delta_vs_baseline": round(
                    eval_comparison.with_skill.pass_rate - eval_comparison.baseline.pass_rate, 3
                ),
                "avg_score_delta_vs_baseline": round(
                    eval_comparison.with_skill.avg_score - eval_comparison.baseline.avg_score, 3
                ),
                "token_growth_vs_baseline": round(
                    eval_comparison.with_skill.avg_response_tokens
                    / max(1.0, eval_comparison.baseline.avg_response_tokens),
                    3,
                ),
                "previous_stable_pass_rate": previous_pass_rate if previous_pass_rate is not None else -1.0,
            },
        )
        manifest.update(
            {
                "parent_version": parent_version,
                "changed_sections": changed_sections,
                "conflict_count": conflict_count,
                "status": status,
                "gate_reasons": eval_comparison.reasons,
                "new_corpus_weight": round(_clamp_new_corpus_weight(new_corpus_weight), 3),
                "delta_items": len(accepted_delta_items),
            }
        )
        repo.save_version_artifacts(
            persona_id=persona_id,
            version=version_record,
            profile=profile,
            manifest=manifest,
            validation={
                "schema_errors": validation.schema_errors,
                "consistency_errors": validation.consistency_errors,
                "conflicts": validation.conflicts,
                "ok": validation.ok,
            },
            eval_comparison=eval_comparison,
        )
        repo.append_audit(
            persona_id,
            {
                "event": "update",
                "version": version,
                "status": status,
                "changed_sections": changed_sections,
                "rollback": state_result["rollback"],
                "distill_mode": "agent",
                "pass_rate": eval_comparison.with_skill.pass_rate,
                "baseline_pass_rate": eval_comparison.baseline.pass_rate,
                "new_corpus_weight": round(_clamp_new_corpus_weight(new_corpus_weight), 3),
                "delta_items": len(accepted_delta_items),
            },
        )
        return {
            "version": version,
            "status": status,
            "changed_sections": changed_sections,
            "conflicts": conflict_count,
            "validation_ok": validation.ok,
            "validation_errors": validation.schema_errors + validation.consistency_errors,
            "gate_passed": eval_comparison.gate_passed,
            "gate_reasons": eval_comparison.reasons,
            "pass_rate": eval_comparison.with_skill.pass_rate,
            "baseline_pass_rate": eval_comparison.baseline.pass_rate,
            "rollback": state_result["rollback"],
            "distill_mode": "agent",
            "output_dir": str(vdir),
            "new_corpus_weight": round(_clamp_new_corpus_weight(new_corpus_weight), 3),
            "delta_items": len(accepted_delta_items),
        }

    return _build_common(
        repo,
        persona_id,
        eval_suite=eval_suite,
        merge_with_previous=True,
    )


def rollback_persona(repo: PersonaRepository, persona_id: str, version: str) -> dict:
    _ensure_persona(repo, persona_id)
    vdir = repo.version_dir(persona_id, version)
    if not vdir.exists():
        raise ValueError(f"Version '{version}' not found")
    state = repo.load_state(persona_id)
    state.current_version = version
    state.stable_version = version
    repo.save_state(persona_id, state)
    repo.append_audit(persona_id, {"event": "rollback", "to_version": version})
    return {"current_version": version}


def export_persona(repo: PersonaRepository, persona_id: str, target: str, version: str | None) -> dict:
    _ensure_persona(repo, persona_id)
    state = repo.load_state(persona_id)
    resolved_version = version or state.current_version
    if not resolved_version:
        raise ValueError("No current version available for export")

    src_skill = repo.version_dir(persona_id, resolved_version) / "skill"
    if not src_skill.exists():
        raise ValueError(f"Skill directory missing for {resolved_version}")
    skill_name = canonical_skill_name(persona_id)

    export_base = repo.persona_dir(persona_id) / "exports" / resolved_version
    export_base.mkdir(parents=True, exist_ok=True)
    exported: dict[str, str] = {}

    if target in {"agentskills", "both"}:
        dst = export_base / "agentskills" / skill_name
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src_skill, dst)
        exported["agentskills"] = str(dst)

    if target in {"codex", "both"}:
        dst = export_base / "codex" / skill_name
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src_skill, dst)
        meta = {
            "name": skill_name,
            "persona_display_name": persona_id,
            "version": resolved_version,
            "source": "persona-skill-distill",
        }
        (dst / "codex_skill.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        exported["codex"] = str(dst)

    repo.append_audit(
        persona_id,
        {
            "event": "export",
            "version": resolved_version,
            "target": target,
            "paths": exported,
        },
    )
    return {"version": resolved_version, "exports": exported}
