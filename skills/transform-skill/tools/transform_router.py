#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from persona_distill.providers import build_provider
from persona_distill.repository import PersonaRepository
from persona_distill.semantic_commands import (
    SemanticRequest,
    intent_requires_llm,
    normalize_intent,
    run_semantic_command,
)

ACTION_TO_INTENT = {
    "create": "friend-create",
    "update": "friend-update",
    "list": "friend-list",
    "history": "friend-history",
    "rollback": "friend-rollback",
    "export": "friend-export",
    "correct": "friend-correct",
    "doctor": "friend-doctor",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="transform-skill prompt+tools router")
    parser.add_argument("--action", required=True, choices=sorted(ACTION_TO_INTENT.keys()))
    parser.add_argument("--workspace-root", default=".", help="persona workspace root")
    parser.add_argument("--runtime-root", default="", help="resolved runtime root (for diagnostics)")
    parser.add_argument("--input", dest="input_path", default="", help="corpus input path")
    parser.add_argument("--friend-id", dest="friend_id", default="", help="stable friend persona id")
    parser.add_argument("--target-speaker", dest="target_speaker", default="", help="speaker filter")
    parser.add_argument("--new-corpus-weight", type=float, default=0.25)
    parser.add_argument("--target", default="both", choices=["agentskills", "codex", "both", "none"])
    parser.add_argument("--to-version", default="", help="target version for rollback/export")
    parser.add_argument("--correction-text", default="", help="correction text for correct action")
    parser.add_argument("--correction-section", default="beliefs_and_values")
    parser.add_argument("--history-limit", type=int, default=20)
    parser.add_argument("--format", default="auto", choices=["auto", "text", "json", "csv"])
    parser.add_argument("--suite", default="", help="optional eval suite path")
    return parser


def _to_request(args: argparse.Namespace) -> SemanticRequest:
    intent = normalize_intent(ACTION_TO_INTENT[args.action])
    input_path = Path(args.input_path).resolve() if args.input_path else None
    suite_path = Path(args.suite).resolve() if args.suite else None
    return SemanticRequest(
        intent=intent,
        input_path=input_path,
        persona=args.friend_id or None,
        fmt=args.format,
        speaker=args.target_speaker or None,
        new_corpus_weight=args.new_corpus_weight,
        suite=suite_path,
        target=args.target,
        to_version=args.to_version or None,
        correction_text=args.correction_text or None,
        correction_section=args.correction_section,
        history_limit=max(1, args.history_limit),
    )


def _payload(
    *,
    args: argparse.Namespace,
    request: SemanticRequest,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "entrypoint": "transform-skill",
        "action": args.action,
        "runtime_root": args.runtime_root or None,
        "workspace_root": str(Path(args.workspace_root).resolve()),
        "request": {
            "semantic_intent": request.intent,
            "friend_id": request.persona,
            "input": str(request.input_path) if request.input_path else None,
            "target_speaker": request.speaker,
            "new_corpus_weight": request.new_corpus_weight,
            "target": request.target,
        },
        **result,
    }


def main() -> int:
    args = _parser().parse_args()

    repo = PersonaRepository(Path(args.workspace_root).resolve())
    request = _to_request(args)
    provider = build_provider() if intent_requires_llm(request.intent) else None

    result = run_semantic_command(repo=repo, provider=provider, request=request)
    print(json.dumps(_payload(args=args, request=request, result=result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
