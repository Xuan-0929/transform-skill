from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .base import ModelProvider


CLI_AUTH_PATTERNS = [
    re.compile(r"not logged in", re.IGNORECASE),
    re.compile(r"\blogin\b", re.IGNORECASE),
    re.compile(r"authentication", re.IGNORECASE),
    re.compile(r"please run /login", re.IGNORECASE),
    re.compile(r"please run .* login", re.IGNORECASE),
    re.compile(r"loggedin['\":\s]*false", re.IGNORECASE),
]


class ClaudeCodeProviderError(RuntimeError):
    pass


class ClaudeCodeAuthError(ClaudeCodeProviderError):
    pass


@dataclass
class ClaudeResult:
    text: str
    stderr: str
    returncode: int


def resolve_runtime_cli(preference: str = "auto") -> str:
    normalized = (preference or "auto").strip().lower()
    if normalized not in {"auto", "claude", "codex"}:
        raise ValueError("DISTILL_RUNTIME_CLI must be one of: auto, claude, codex.")
    if normalized in {"claude", "codex"}:
        return normalized

    codex_available = shutil.which("codex") is not None
    claude_available = shutil.which("claude") is not None

    # Prefer host-native CLI when running in Codex desktop/CLI environments.
    if os.environ.get("CODEX_SHELL") == "1" or os.environ.get("CODEX_THREAD_ID"):
        if codex_available:
            return "codex"

    # Backward-compatible fallback order for generic shell contexts.
    if claude_available:
        return "claude"
    if codex_available:
        return "codex"
    return "claude"


class ClaudeCodeProvider(ModelProvider):
    """Runtime provider that delegates content operations to host CLI runtime."""

    def __init__(
        self,
        cli_path: str | None = None,
        runtime_cli: str = "auto",
        model: str | None = None,
        timeout_sec: int = 90,
    ) -> None:
        self.runtime_cli = resolve_runtime_cli(runtime_cli)
        resolved_cli = (cli_path or self.runtime_cli).strip()
        provider_name = f"{self.runtime_cli}_cli"
        super().__init__(provider=provider_name, model=model or "default")
        self.cli_path = resolved_cli
        self.timeout_sec = max(20, int(timeout_sec))

    def refine_claim(self, section: str, candidate: str) -> str:
        prompt = (
            "You are a strict claim refiner for persona distillation.\n"
            f"SECTION: {section}\n"
            "Task:\n"
            "1) Rewrite the claim into compact transferable language.\n"
            "2) Keep original intent.\n"
            "3) Avoid copying chat trivia.\n"
            "Output rules:\n"
            "- Return plain text only.\n"
            "- Max 180 characters.\n"
            "- No markdown.\n\n"
            f"Candidate:\n{candidate}\n"
        )
        refined = self._ask_text(prompt)
        cleaned = self._clean_text(refined)
        if cleaned:
            return cleaned[:180]
        fallback = self._clean_text(candidate)
        return fallback[:180] or "信息不足，先补证据再判断。"

    def summarize_section(self, section: str, claims: list[str]) -> str:
        if not claims:
            return "No strong signal found."
        prompt = (
            "Summarize persona claims as one compact operational sentence.\n"
            f"SECTION: {section}\n"
            "Constraints:\n"
            "- Chinese output\n"
            "- max 80 chars\n"
            "- no markdown\n\n"
            "Claims:\n"
            + "\n".join(f"- {c}" for c in claims[:12])
        )
        text = self._clean_text(self._ask_text(prompt))
        return text[:80] if text else "No strong signal found."

    def generate_response(self, prompt: str, context: str) -> str:
        req = (
            "You are emulating a distilled persona.\n"
            "Respond to the user prompt using provided persona context.\n"
            "Rules:\n"
            "- stay concise\n"
            "- do not fabricate unknown facts\n"
            "- if asked to fabricate, explicitly refuse and mention boundary\n"
            "- plain text only\n\n"
            f"[PROMPT]\n{prompt}\n\n"
            f"[PERSONA_CONTEXT]\n{context}\n"
        )
        reply = self._clean_text(self._ask_text(req))
        return reply[:220] if reply else "不编造，信息不足就先说明边界。"

    def run_agent(self, prompt: str) -> str:
        req = (
            "You are a strict JSON extractor.\n"
            "Follow the user's schema requirements exactly.\n"
            "Output JSON only. No markdown fences. No explanation.\n\n"
            + prompt
        )
        raw = self._ask_text(req)
        payload = self._extract_json_block(raw)
        if not payload:
            return '{"claims":[]}'
        return payload

    def _ask_text(self, prompt: str) -> str:
        result = self._run_runtime(prompt)
        output = (result.text or "").strip()
        if output:
            return output
        raise ClaudeCodeProviderError("Host runtime returned empty output.")

    def _run_runtime(self, prompt: str) -> ClaudeResult:
        if self.runtime_cli == "codex":
            return self._run_codex(prompt)
        return self._run_claude(prompt)

    def _run_claude(self, prompt: str) -> ClaudeResult:
        cmd = [self.cli_path, "-p", "--output-format", "text", prompt]
        if self.model and self.model != "default":
            cmd.extend(["--model", self.model])

        return self._run_cmd(cmd, runtime_name="Claude")

    def _run_codex(self, prompt: str) -> ClaudeResult:
        with tempfile.NamedTemporaryFile(prefix="distill_codex_", suffix=".txt", delete=False) as fp:
            output_path = Path(fp.name)

        cmd = [
            self.cli_path,
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            prompt,
        ]
        if self.model and self.model != "default":
            cmd[2:2] = ["--model", self.model]

        try:
            result = self._run_cmd(cmd, runtime_name="Codex")
            text = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
            if text:
                return ClaudeResult(text=text, stderr=result.stderr, returncode=result.returncode)
            return result
        finally:
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _run_cmd(self, cmd: list[str], runtime_name: str) -> ClaudeResult:
        env = os.environ.copy()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ClaudeCodeProviderError(
                f"{runtime_name} runtime command is unavailable in this host session."
            ) from exc
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            merged = f"{stdout}\n{stderr}".strip()
            if self._is_auth_error(merged):
                raise ClaudeCodeAuthError(
                    f"{runtime_name} runtime is not authenticated in the current host session."
                )
            raise ClaudeCodeProviderError(
                f"{runtime_name} runtime command failed (exit={proc.returncode}): {merged or 'no error text'}"
            )
        return ClaudeResult(text=stdout, stderr=stderr, returncode=proc.returncode)

    @staticmethod
    def _is_auth_error(text: str) -> bool:
        sample = text.strip()
        if not sample:
            return False
        return any(p.search(sample) for p in CLI_AUTH_PATTERNS)

    @staticmethod
    def _clean_text(text: str) -> str:
        line = text.strip()
        line = re.sub(r"\s+", " ", line).strip()
        line = line.strip("`")
        return line

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        if cleaned.startswith("{") and cleaned.endswith("}"):
            return cleaned
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = cleaned[start : end + 1]
        try:
            json.loads(candidate)
        except Exception:
            return None
        return candidate
