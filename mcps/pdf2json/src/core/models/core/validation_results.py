"""Validation result models for workflow intermediate states."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    severity: str  # "error", "warning", "info"
    type: str
    equipment_id: Optional[str] = None
    node_id: Optional[str] = None
    edge_id: Optional[str] = None
    description: str
    suggestion: Optional[str] = None


class TopologyValidationResult(BaseModel):
    """Result from topology validation."""

    validation_status: str  # "passed", "passed_with_warnings", "needs_review", "failed"
    issues: list[ValidationIssue]
    auto_fixed: list[str] = Field(default_factory=list)
    needs_human_review: list[str] = Field(default_factory=list)


class ConsistencyIssue(BaseModel):
    severity: str  # "error", "warning", "info"
    type: str
    source: str
    description: str
    affected_ids: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None


class ConsistencyReport(BaseModel):
    """Consistency check report."""

    is_consistent: bool
    issues: list[ConsistencyIssue]
    auto_fixable: list[str] = Field(default_factory=list)
    fixed_issues: list[str] = Field(default_factory=list)
