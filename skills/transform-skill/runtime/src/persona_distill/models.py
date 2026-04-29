from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CORE_SECTIONS = [
    "beliefs_and_values",
    "mental_models",
    "decision_heuristics",
    "expression_dna",
    "anti_patterns_and_limits",
]


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    REVISED = "revised"
    SUPERSEDED = "superseded"


class CorpusItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    speaker: str = "unknown"
    timestamp: datetime | None = None
    content: str
    content_hash: str
    source_message_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    quality_score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    start: int = 0
    end: int = 0
    excerpt: str


class EvidenceClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    section: str
    claim: str
    confidence: float = 0.5
    evidence: list[EvidenceSpan] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    status: ClaimStatus = ClaimStatus.ACTIVE
    conflicts_with: list[str] = Field(default_factory=list)


class ModelCard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    definition: str
    sees_first: str
    filters_out: str
    reframes: str
    evidence_anchors: list[str] = Field(default_factory=list)
    failure_mode: str
    gates: dict[str, bool] = Field(default_factory=dict)
    confidence: float = 0.5
    source_claim_id: str | None = None


class DecisionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rule: str
    condition: str
    action: str
    rationale: str
    boundary: str
    evidence_anchor: str = ""
    confidence: float = 0.5


class ContradictionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: str
    description: str
    evidence: list[str] = Field(default_factory=list)


class PersonaProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    version: str
    generated_at: datetime
    sections: dict[str, list[EvidenceClaim]] = Field(default_factory=dict)
    expression_metrics: dict[str, float | str] = Field(default_factory=dict)
    uncertainty_notes: list[str] = Field(default_factory=list)
    signature_lexicon: list[str] = Field(default_factory=list)
    style_memory: list[str] = Field(default_factory=list)
    context_reply_memory: list[dict[str, str]] = Field(default_factory=list)
    model_cards: list[ModelCard] = Field(default_factory=list)
    decision_rules: list[DecisionRule] = Field(default_factory=list)
    contradictions: list[ContradictionItem] = Field(default_factory=list)
    known_answer_anchors: list[dict[str, str]] = Field(default_factory=list)
    source_metrics: dict[str, float | int | str] = Field(default_factory=dict)
    source_item_count: int = 0


class SkillVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    parent_version: str | None = None
    created_at: datetime
    status: str = "candidate"
    changed_sections: list[str] = Field(default_factory=list)
    eval_diff: dict[str, float] = Field(default_factory=dict)


class PersonaState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    created_at: datetime
    current_version: str | None = None
    stable_version: str | None = None
    latest_version: str | None = None


class CorrectionNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    created_at: datetime
    section: str
    instruction: str


class EvalAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    value: str | float
    critical: bool = False


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    expected_output: str | None = None
    assertions: list[EvalAssertion] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


class EvalBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "default"
    cases: list[EvalCase]


class EvalCaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    passed: bool
    critical_passed: bool
    score: float
    failures: list[str] = Field(default_factory=list)
    response: str


class EvalRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str
    pass_rate: float
    critical_pass_rate: float
    avg_score: float
    avg_response_tokens: float
    avg_response_chars: float
    case_results: list[EvalCaseResult]


class EvalComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    with_skill: EvalRunResult
    baseline: EvalRunResult
    gate_passed: bool
    reasons: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_errors: list[str] = Field(default_factory=list)
    consistency_errors: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.schema_errors and not self.consistency_errors
