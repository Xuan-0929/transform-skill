from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingest import ingest_file
from .providers import ModelProvider
from .repository import PersonaRepository
from .utils import canonical_skill_name
from .workflow import export_persona, update_persona

SUPPORTED_TARGETS = {"agentskills", "codex", "both", "none"}
SUPPORTED_MODES = {"update", "cold_start"}
SUPPORTED_RISKS = {"low", "medium", "high"}


@dataclass
class OrchestrationPlan:
    mode: str
    new_corpus_weight: float
    speaker_filter: str | None
    target: str
    risk_level: str
    rationale: str
    source: str
    raw: str


def _clamp_weight(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _parse_json_dict(raw: str) -> dict[str, Any]:
    payload = raw.strip()
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
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _default_plan(
    *,
    persona_exists: bool,
    requested_weight: float,
    requested_speaker: str | None,
    requested_target: str,
) -> OrchestrationPlan:
    return OrchestrationPlan(
        mode="update" if persona_exists else "cold_start",
        new_corpus_weight=_clamp_weight(requested_weight),
        speaker_filter=requested_speaker,
        target=requested_target,
        risk_level="medium",
        rationale="fallback plan: keep update-first defaults and explicit user inputs",
        source="fallback",
        raw="{}",
    )


def _to_plan(
    raw: str,
    *,
    persona_exists: bool,
    requested_weight: float,
    requested_speaker: str | None,
    requested_target: str,
) -> OrchestrationPlan:
    default = _default_plan(
        persona_exists=persona_exists,
        requested_weight=requested_weight,
        requested_speaker=requested_speaker,
        requested_target=requested_target,
    )
    data = _parse_json_dict(raw)
    if not data:
        return default

    mode = str(data.get("mode", default.mode)).strip().lower()
    if mode not in SUPPORTED_MODES:
        mode = default.mode
    if not persona_exists:
        mode = "cold_start"
    elif mode == "cold_start":
        # Existing persona should stay update-first by default.
        mode = "update"

    target = str(data.get("target", default.target)).strip().lower()
    if target not in SUPPORTED_TARGETS:
        target = default.target

    speaker_val = data.get("speaker_filter", requested_speaker)
    speaker_filter = str(speaker_val).strip() if speaker_val is not None else None
    if speaker_filter == "":
        speaker_filter = None

    weight = data.get("new_corpus_weight", requested_weight)
    try:
        resolved_weight = _clamp_weight(float(weight))
    except Exception:
        resolved_weight = default.new_corpus_weight

    risk_level = str(data.get("risk_level", default.risk_level)).strip().lower()
    if risk_level not in SUPPORTED_RISKS:
        risk_level = default.risk_level

    rationale = str(data.get("rationale", default.rationale)).strip() or default.rationale
    rationale = rationale[:240]

    resolved_target = target
    if requested_target in SUPPORTED_TARGETS and requested_target != "both":
        resolved_target = requested_target

    return OrchestrationPlan(
        mode=mode,
        new_corpus_weight=resolved_weight,
        speaker_filter=speaker_filter if requested_speaker is None else requested_speaker,
        target=resolved_target,
        risk_level=risk_level,
        rationale=rationale,
        source="agent",
        raw=raw,
    )


def _candidate_speakers(items: list[Any], limit: int = 8) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        speaker = getattr(item, "speaker", None) or "unknown"
        counts[speaker] = counts.get(speaker, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [{"speaker": name, "count": count} for name, count in ranked[:limit]]


def build_agent_plan(
    *,
    provider: ModelProvider,
    repo: PersonaRepository,
    input_path: Path,
    persona_id: str,
    fmt: str,
    requested_weight: float,
    requested_speaker: str | None,
    requested_target: str,
) -> tuple[OrchestrationPlan, dict[str, Any]]:
    resolved_path = input_path.resolve()
    persona_exists = repo.has_persona(persona_id)
    sampled = ingest_file(resolved_path, fmt, speaker_filter=None)
    candidate_speakers = _candidate_speakers(sampled)
    context = {
        "persona_id": persona_id,
        "canonical_skill_name": canonical_skill_name(persona_id),
        "persona_exists": persona_exists,
        "requested_weight": round(_clamp_weight(requested_weight), 3),
        "requested_speaker_filter": requested_speaker,
        "requested_target": requested_target,
        "detected_items": len(sampled),
        "candidate_speakers": candidate_speakers,
        "input_path": str(resolved_path),
    }

    prompt = (
        "You are Workflow-Orchestrator agent for persona distillation.\n"
        "Decide an execution plan for update-first distillation.\n"
        "Return STRICT JSON only with schema:\n"
        '{'
        '"mode":"update|cold_start",'
        '"new_corpus_weight":0.0,'
        '"speaker_filter":"string|null",'
        '"target":"agentskills|codex|both|none",'
        '"risk_level":"low|medium|high",'
        '"rationale":"short sentence"'
        '}\n'
        "Rules:\n"
        "- If persona_exists=true, prefer mode=update.\n"
        "- Keep new_corpus_weight in [0.05, 0.8] unless explicit reason.\n"
        "- Prefer speaker_filter from candidate_speakers when one speaker dominates.\n"
        "- Never output markdown.\n"
        f"Context:\n{json.dumps(context, ensure_ascii=False, indent=2)}\n"
    )

    try:
        raw = provider.run_agent(prompt)
    except Exception:
        raw = "{}"

    plan = _to_plan(
        raw,
        persona_exists=persona_exists,
        requested_weight=requested_weight,
        requested_speaker=requested_speaker,
        requested_target=requested_target,
    )
    return plan, context


def run_orchestrated_distill(
    *,
    repo: PersonaRepository,
    provider: ModelProvider,
    input_path: Path,
    persona: str | None,
    fmt: str,
    speaker: str | None,
    new_corpus_weight: float,
    suite: Path | None,
    target: str,
) -> dict[str, Any]:
    resolved_input = input_path.resolve()
    persona_id = (persona or canonical_skill_name(resolved_input.stem)).strip()
    if not persona_id:
        persona_id = canonical_skill_name(resolved_input.stem)
    if not persona_id:
        raise ValueError("Failed to resolve persona id from input. Provide --persona explicitly.")
    if target not in SUPPORTED_TARGETS:
        raise ValueError("--target must be agentskills|codex|both|none")

    plan, context = build_agent_plan(
        provider=provider,
        repo=repo,
        input_path=resolved_input,
        persona_id=persona_id,
        fmt=fmt,
        requested_weight=new_corpus_weight,
        requested_speaker=speaker,
        requested_target=target,
    )

    created = False
    if not repo.has_persona(persona_id):
        repo.init_persona(persona_id)
        created = True

    resolved_suite = suite.resolve() if suite else None
    result = update_persona(
        repo=repo,
        persona_id=persona_id,
        eval_suite=resolved_suite,
        input_path=resolved_input,
        fmt=fmt,
        speaker_filter=plan.speaker_filter,
        correction=None,
        correction_section="beliefs_and_values",
        new_corpus_weight=plan.new_corpus_weight,
    )

    execute_stage = "execute_update" if plan.mode == "update" else "execute_cold_start"

    payload: dict[str, Any] = {
        "persona": persona_id,
        "input": str(resolved_input),
        "created": created,
        "workflow_mode": "agent-led-script-exec",
        "plan": {
            "mode": plan.mode,
            "new_corpus_weight": plan.new_corpus_weight,
            "speaker_filter": plan.speaker_filter,
            "target": plan.target,
            "risk_level": plan.risk_level,
            "rationale": plan.rationale,
            "source": plan.source,
        },
        "stages": [
            {"name": "plan", "ok": True, "source": plan.source},
            {"name": execute_stage, "ok": True, "version": result["version"], "status": result["status"]},
        ],
        "plan_context": context,
        **result,
    }

    if plan.target != "none":
        payload["export"] = export_persona(repo, persona_id, target=plan.target, version=result["version"])
        payload["stages"].append({"name": "export", "ok": True, "target": plan.target})

    repo.append_audit(
        persona_id,
        {
            "event": "orchestrate",
            "mode": plan.mode,
            "source": plan.source,
            "risk_level": plan.risk_level,
            "new_corpus_weight": round(plan.new_corpus_weight, 3),
            "speaker_filter": plan.speaker_filter,
            "target": plan.target,
            "plan_raw": plan.raw[:2000],
            "version": result.get("version"),
            "status": result.get("status"),
        },
    )
    return payload
