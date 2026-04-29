from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass

from .base import ModelProvider


CLI_AUTH_PATTERNS = [
    re.compile(r"not logged in", re.IGNORECASE),
    re.compile(r"please run /login", re.IGNORECASE),
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


class ClaudeCodeProvider(ModelProvider):
    """Runtime provider that delegates content operations to local Claude Code CLI."""

    def __init__(self, cli_path: str = "claude", model: str | None = None, timeout_sec: int = 90) -> None:
        super().__init__(provider="claude_code", model=model or "default")
        self.cli_path = cli_path
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
        result = self._run_claude(prompt)
        output = (result.text or "").strip()
        if output:
            return output
        raise ClaudeCodeProviderError("Claude runtime returned empty output.")

    def _run_claude(self, prompt: str) -> ClaudeResult:
        cmd = [self.cli_path, "-p", "--output-format", "text", prompt]
        if self.model and self.model != "default":
            cmd.extend(["--model", self.model])

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
                "Claude runtime command is unavailable in this host session."
            ) from exc
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            merged = f"{stdout}\n{stderr}".strip()
            if self._is_auth_error(merged):
                raise ClaudeCodeAuthError(
                    "Claude runtime is not authenticated in the current host session."
                )
            raise ClaudeCodeProviderError(
                f"Claude runtime command failed (exit={proc.returncode}): {merged or 'no error text'}"
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
