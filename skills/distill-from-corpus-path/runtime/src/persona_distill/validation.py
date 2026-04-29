from __future__ import annotations

import re
import shutil
import subprocess
from itertools import combinations
from pathlib import Path

import yaml

from .models import PersonaProfile, ValidationReport
from .utils import has_negation, jaccard_similarity


REQUIRED_FILES = [
    "SKILL.md",
    "references/persona-profile.md",
    "references/decision-heuristics.md",
    "references/style-memory.md",
    "references/context-reply-memory.md",
    "references/model-cards.md",
    "references/contradictions.md",
    "references/skill-blueprint.md",
    "examples/usage.md",
]

NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_HEADINGS = [
    "## 角色扮演规则（最重要）",
    "## 触发条件",
    "## 回答工作流（Agentic Protocol）",
    "## 身份卡",
    "## 核心心智模型",
    "## 决策启发式",
    "## 表达DNA",
    "## 价值观与反模式",
    "## 输出契约",
    "## 质量检查清单",
    "## 诚实边界",
    "## 研究与蒸馏审计",
    "## 附录：调研与证据索引",
]


def _frontmatter_end_index(skill_text: str) -> int:
    if not skill_text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end_idx = skill_text.find("\n---\n", 4)
    if end_idx == -1:
        raise ValueError("SKILL.md frontmatter is not closed")
    return end_idx


def _parse_frontmatter(skill_text: str) -> dict:
    end_idx = _frontmatter_end_index(skill_text)
    raw = skill_text[4:end_idx]
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ValueError("SKILL.md frontmatter must parse to a dictionary")
    return data


def _skill_body(skill_text: str) -> str:
    end_idx = _frontmatter_end_index(skill_text)
    return skill_text[end_idx + len("\n---\n") :]


def _skills_ref_validate(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    exe = shutil.which("skills-ref")
    if not exe:
        return errors

    proc = subprocess.run(
        [exe, "validate", str(skill_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        text = (proc.stderr or proc.stdout or "skills-ref validation failed").strip()
        errors.append(text)
    return errors


def validate_skill_structure(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    for rel in REQUIRED_FILES:
        if not (skill_dir / rel).exists():
            errors.append(f"Missing required file: {rel}")
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        return errors
    try:
        skill_text = skill_path.read_text(encoding="utf-8")
        frontmatter = _parse_frontmatter(skill_text)
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    name = frontmatter.get("name")
    if not name:
        errors.append("frontmatter.name is required")
    elif not isinstance(name, str):
        errors.append("frontmatter.name must be a string")
    else:
        if len(name) > 64:
            errors.append("frontmatter.name must be <= 64 characters")
        if not NAME_PATTERN.match(name):
            errors.append("frontmatter.name must match ^[a-z0-9]+(?:-[a-z0-9]+)*$")
        parent_name = skill_dir.name
        if parent_name != "skill" and name != parent_name:
            errors.append("frontmatter.name must match parent directory name for exported skill packages")

    description = frontmatter.get("description")
    if not description:
        errors.append("frontmatter.description is required")
    elif not isinstance(description, str):
        errors.append("frontmatter.description must be a string")
    else:
        if len(description) > 1024:
            errors.append("frontmatter.description must be <= 1024 characters")
        if "use this skill when" not in description.lower():
            errors.append("frontmatter.description should use imperative trigger phrasing: 'Use this skill when...'")

    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, str):
            errors.append("frontmatter.compatibility must be a string when provided")
        elif len(compatibility) > 500:
            errors.append("frontmatter.compatibility must be <= 500 characters")

    metadata = frontmatter.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            errors.append("frontmatter.metadata must be a map when provided")
        else:
            for key, value in metadata.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    errors.append("frontmatter.metadata must be a map of string keys to string values")
                    break

    body = _skill_body(skill_text)
    if len(body.splitlines()) > 900:
        errors.append("SKILL.md body should stay under 900 lines for progressive disclosure")
    for heading in REQUIRED_HEADINGS:
        if heading not in body:
            errors.append(f"SKILL.md missing required section heading: {heading}")
    upper_body = body.upper()
    if "MUST" not in upper_body:
        errors.append("SKILL.md must include explicit MUST constraints")
    if "MUST NOT" not in upper_body:
        errors.append("SKILL.md must include explicit MUST NOT constraints")
    checklist_items = [line for line in body.splitlines() if line.strip().startswith("- [ ] ")]
    if len(checklist_items) < 3:
        errors.append("SKILL.md quality checklist should include at least 3 checkbox items")
    if body.count("### 模型") < 2:
        errors.append("SKILL.md should contain at least 2 explicit mental-model subsections")
    if "Known-answer" not in body and "已知问题锚点" not in body:
        errors.append("SKILL.md should include known-answer anchors for validation")

    errors.extend(_skills_ref_validate(skill_dir))
    return errors


def detect_conflicts(profile: PersonaProfile) -> list[str]:
    conflicts: list[str] = []
    for section, claims in profile.sections.items():
        for left, right in combinations(claims, 2):
            sim = jaccard_similarity(left.claim, right.claim)
            if sim < 0.45:
                continue
            if has_negation(left.claim) != has_negation(right.claim):
                conflicts.append(
                    f"{section}: potential conflict between {left.id} and {right.id}"
                )
    return conflicts


def validate_consistency(profile: PersonaProfile, item_ids: set[str]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    for section, claims in profile.sections.items():
        for claim in claims:
            if not claim.evidence:
                errors.append(f"{section}/{claim.id}: missing evidence")
                continue
            for evidence in claim.evidence:
                if evidence.item_id == "correction_layer":
                    continue
                if evidence.item_id not in item_ids:
                    errors.append(
                        f"{section}/{claim.id}: evidence item_id {evidence.item_id} not found in corpus"
                    )

    if len(profile.model_cards) < 2:
        errors.append("profile.model_cards should contain at least 2 retained models")
    if len(profile.decision_rules) < 5:
        errors.append("profile.decision_rules should contain at least 5 rules")
    if profile.context_reply_memory and len(profile.known_answer_anchors) == 0:
        errors.append("known_answer_anchors should not be empty when context_reply_memory exists")

    conflicts = detect_conflicts(profile)
    return errors, conflicts


def run_validation(skill_dir: Path, profile: PersonaProfile, item_ids: set[str]) -> ValidationReport:
    schema_errors = validate_skill_structure(skill_dir)
    consistency_errors, conflicts = validate_consistency(profile, item_ids)
    return ValidationReport(
        schema_errors=schema_errors,
        consistency_errors=consistency_errors,
        conflicts=conflicts,
    )
