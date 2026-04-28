from __future__ import annotations

import json
from pathlib import Path

import typer

from .evaluation import compare_eval, load_benchmark
from .holdout import evaluate_multi_ref_holdout
from .providers import build_provider, resolve_runtime_spec
from .repository import PersonaRepository
from .utils import canonical_skill_name
from .workflow import (
    add_correction,
    build_persona,
    export_persona,
    ingest_corpus,
    rollback_persona,
    update_persona,
)

app = typer.Typer(help="Persona-to-skill distillation framework")


def _repo() -> PersonaRepository:
    return PersonaRepository(Path.cwd())


def _derive_persona_id(input_path: Path) -> str:
    stem = input_path.stem.strip() or "persona"
    return canonical_skill_name(stem)


@app.command()
def init(persona_id: str = typer.Argument(..., help="Persona identifier")) -> None:
    """Initialize a persona workspace."""
    repo = _repo()
    if repo.has_persona(persona_id):
        typer.echo(f"Persona '{persona_id}' already exists at {repo.persona_dir(persona_id)}")
        raise typer.Exit(code=0)

    state = repo.init_persona(persona_id)
    typer.echo(f"Initialized persona: {state.persona_id}")
    typer.echo(f"Workspace: {repo.persona_dir(persona_id)}")


@app.command()
def ingest(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False),
    fmt: str = typer.Option("auto", "--format", help="auto|text|json|csv"),
    speaker: str | None = typer.Option(None, "--speaker", help="Only ingest messages from this speaker"),
) -> None:
    """Ingest corpus file into persona storage."""
    repo = _repo()
    result = ingest_corpus(repo, persona, input_path.resolve(), fmt, speaker_filter=speaker)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def build(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    suite: Path | None = typer.Option(None, "--suite", help="Eval suite JSON path"),
) -> None:
    """Build a new distilled skill version from current corpus."""
    repo = _repo()
    result = build_persona(
        repo,
        persona,
        eval_suite=suite.resolve() if suite else None,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("run")
def run_cmd(
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False),
    persona: str | None = typer.Option(
        None,
        "--persona",
        help="Persona identifier. If omitted, auto-derived from input file name.",
    ),
    fmt: str = typer.Option("auto", "--format", help="auto|text|json|csv"),
    speaker: str | None = typer.Option(None, "--speaker", help="Only ingest messages from this speaker"),
    new_corpus_weight: float = typer.Option(
        0.25,
        "--new-corpus-weight",
        min=0.0,
        max=1.0,
        help="Weight of newly ingested corpus when updating an existing skill (0.0-1.0).",
    ),
    suite: Path | None = typer.Option(None, "--suite", help="Eval suite JSON path"),
    target: str = typer.Option("both", "--target", help="agentskills|codex|both|none"),
) -> None:
    """One-shot distillation: init (if needed) + ingest + build/update + optional export."""
    if target not in {"agentskills", "codex", "both", "none"}:
        raise typer.BadParameter("--target must be agentskills|codex|both|none")

    repo = _repo()
    resolved_input = input_path.resolve()
    persona_id = (persona or _derive_persona_id(resolved_input)).strip()

    created = False
    if not repo.has_persona(persona_id):
        repo.init_persona(persona_id)
        created = True

    result = update_persona(
        repo=repo,
        persona_id=persona_id,
        eval_suite=suite.resolve() if suite else None,
        input_path=resolved_input,
        fmt=fmt,
        speaker_filter=speaker,
        correction=None,
        correction_section="beliefs_and_values",
        new_corpus_weight=new_corpus_weight,
    )

    payload: dict[str, object] = {
        "persona": persona_id,
        "input": str(resolved_input),
        "created": created,
        **result,
    }
    if target != "none":
        payload["export"] = export_persona(repo, persona_id, target=target, version=result["version"])
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("eval")
def eval_cmd(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    suite: Path = typer.Option(..., "--suite", exists=True, file_okay=True, dir_okay=False),
    version: str | None = typer.Option(None, "--version", help="Target version, defaults to current"),
) -> None:
    """Run benchmark comparison (with_skill vs baseline) for a version."""
    repo = _repo()
    state = repo.load_state(persona)
    resolved_version = version or state.current_version
    if not resolved_version:
        raise typer.BadParameter("No version found. Build at least one version first.")

    profile = repo.load_profile(persona, resolved_version)
    provider = build_provider()
    benchmark = load_benchmark(suite.resolve())
    previous_rate = None
    if state.stable_version:
        prev_eval = repo.load_eval(persona, state.stable_version)
        previous_rate = prev_eval.with_skill.pass_rate if prev_eval else None

    comparison = compare_eval(benchmark, profile, provider, previous_stable_pass_rate=previous_rate)
    typer.echo(comparison.model_dump_json(indent=2))


@app.command("eval-holdout")
def eval_holdout_cmd(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    input_path: Path = typer.Option(..., "--input", exists=True, file_okay=True, dir_okay=False),
    speaker: str | None = typer.Option(None, "--speaker", help="Target speaker name in holdout corpus"),
    version: str | None = typer.Option(None, "--version", help="Target version, defaults to current"),
    max_cases: int = typer.Option(16, "--max-cases", help="Max context cases for evaluation"),
    min_refs: int = typer.Option(2, "--min-refs", help="Min reply variants per prompt context"),
    min_avg_similarity: float = typer.Option(0.2, "--min-avg", help="Pass threshold: agent avg similarity"),
    min_delta: float = typer.Option(0.12, "--min-delta", help="Pass threshold: delta vs baseline"),
    output_name: str = typer.Option(
        "holdout_eval_multi_ref.json",
        "--output",
        help="Output report file name under version directory",
    ),
) -> None:
    """Evaluate holdout similarity using multi-reference acceptable replies."""
    repo = _repo()
    state = repo.load_state(persona)
    resolved_version = version or state.current_version
    if not resolved_version:
        raise typer.BadParameter("No version found. Build at least one version first.")
    profile = repo.load_profile(persona, resolved_version)
    provider = build_provider()
    target_speaker = speaker or persona
    report = evaluate_multi_ref_holdout(
        profile=profile,
        provider=provider,
        holdout_path=input_path.resolve(),
        target_speaker=target_speaker,
        max_cases=max_cases,
        min_refs=min_refs,
        min_avg_similarity=min_avg_similarity,
        min_delta_vs_baseline=min_delta,
    )
    report_path = repo.version_dir(persona, resolved_version) / output_name
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {"version": resolved_version, "report_path": str(report_path), **report}
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def update(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    input_path: Path | None = typer.Option(None, "--input", exists=False, file_okay=True, dir_okay=False),
    fmt: str = typer.Option("auto", "--format", help="auto|text|json|csv"),
    speaker: str | None = typer.Option(None, "--speaker", help="Only ingest messages from this speaker"),
    new_corpus_weight: float = typer.Option(
        0.25,
        "--new-corpus-weight",
        min=0.0,
        max=1.0,
        help="Weight of newly ingested corpus when updating an existing skill (0.0-1.0).",
    ),
    suite: Path | None = typer.Option(None, "--suite", help="Eval suite JSON path"),
    correction: str | None = typer.Option(None, "--correction", help="Correction instruction text"),
    correction_section: str = typer.Option(
        "beliefs_and_values", "--correction-section", help="Target section for correction"
    ),
) -> None:
    """Update persona with new corpus and/or correction layer."""
    if input_path is None and not correction:
        raise typer.BadParameter("Provide --input and/or --correction for update.")

    repo = _repo()
    resolved_input = input_path.resolve() if input_path else None
    resolved_suite = suite.resolve() if suite else None
    result = update_persona(
        repo=repo,
        persona_id=persona,
        eval_suite=resolved_suite,
        input_path=resolved_input,
        fmt=fmt,
        speaker_filter=speaker,
        correction=correction,
        correction_section=correction_section,
        new_corpus_weight=new_corpus_weight,
    )
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def correction(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    text: str = typer.Option(..., "--text", help="Correction instruction"),
    section: str = typer.Option("beliefs_and_values", "--section", help="Target section"),
) -> None:
    """Append a correction note for next build/update."""
    repo = _repo()
    note = add_correction(repo, persona, section=section, instruction=text)
    typer.echo(note.model_dump_json(indent=2))


@app.command("doctor")
def doctor_cmd() -> None:
    """Show active distillation runtime."""
    resolved = resolve_runtime_spec()
    payload = {
        "runtime_mode": resolved,
        "single_path": True,
        "hints": [
            "Distillation is skill-runtime only: no local heuristic switch and no API config path.",
            "Run with `distill run --input <path> --target both` to generate/export artifacts.",
        ],
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command()
def rollback(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    to: str = typer.Option(..., "--to", help="Version to rollback to, e.g. v0001"),
) -> None:
    """Rollback current/stable pointer to an existing version."""
    repo = _repo()
    result = rollback_persona(repo, persona, to)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command()
def export(
    persona: str = typer.Option(..., "--persona", help="Persona identifier"),
    target: str = typer.Option("both", "--target", help="agentskills|codex|both"),
    version: str | None = typer.Option(None, "--version", help="Version to export"),
) -> None:
    """Export current skill version for Agent Skills and/or Codex consumers."""
    if target not in {"agentskills", "codex", "both"}:
        raise typer.BadParameter("--target must be agentskills|codex|both")

    repo = _repo()
    result = export_persona(repo, persona, target=target, version=version)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
