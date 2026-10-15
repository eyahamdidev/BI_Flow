"""Frozen request/response contracts (spec section 2.2).

Bump CONTRACT_VERSION on ANY change. Each service pins biflow-contracts==X.Y.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "0.1"

Status = Literal["ok", "partial", "error"]
ErrorCode = Literal[
    "BAD_INPUT", "SCHEMA_MISMATCH", "UNSUPPORTED_SOURCE", "MODEL_UNAVAILABLE", "TIMEOUT", "INTERNAL"
]
ArtifactKind = Literal["parquet", "csv", "duckdb", "json", "html", "md", "png"]


class Artifact(BaseModel):
    name: str
    kind: ArtifactKind
    path: str = Field(description="relative to DATA_DIR")
    rows: int | None = None
    sha256: str | None = None
    label: str | None = None


class LLMCall(BaseModel):
    prompt_id: str  # e.g. "analyst.narrative@v2"
    model: str
    provider: str
    tokens: int | None = None
    ms: int | None = None
    cache_hit: bool = False


class LineageEvent(BaseModel):
    event_id: str
    run_id: str
    ts: str
    agent: str
    step: str
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    rule: str | None = None
    rows_affected: int | None = None
    method: Literal["deterministic", "ml", "llm_assisted"] = "deterministic"
    params: dict[str, Any] = {}
    llm: dict[str, Any] | None = None


class RunRequest(BaseModel):
    request_id: str
    run_id: str
    dataset: str
    mode: str
    config_ref: str | None = None
    inputs: dict[str, str] = {}
    options: dict[str, Any] = {}
    lang: Literal["en", "fr"] = "en"
    trace_parent: str | None = None


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str


class RunResponse(BaseModel):
    request_id: str
    run_id: str
    module: str
    status: Status
    outputs: list[Artifact] = []
    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    lineage_events: list[LineageEvent] = []
    llm_calls: list[LLMCall] = []
    latency_ms: int = 0
    error: ErrorInfo | None = None


class MetaResponse(BaseModel):
    module: str
    contract_version: str = CONTRACT_VERSION
    modes: list[str]
    models: dict[str, str] = {}
    prompt_versions: dict[str, str] = {}
    lineage_steps: list[str] = []  # step names this module emits (used by BO2 completeness test)
    mock: bool = False


class EvalResponse(BaseModel):
    module: str
    status: Status
    metrics: dict[str, Any] = {}
    notes: list[str] = []


class Insight(BaseModel):
    id: str
    kpi_id: str
    type: Literal["trend", "anomaly", "driver", "recommendation"]
    period: str | None = None
    severity: Literal["info", "review", "high"] = "info"
    facts: dict[str, Any] = {}
    narrative: str = ""
    rule_id: str | None = None
    source: Literal["rule", "model", "both"] = "rule"
