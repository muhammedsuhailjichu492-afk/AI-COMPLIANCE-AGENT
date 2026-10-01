

from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class FileInfo(BaseModel):
    id: str
    filename: str
    kind: str  # "policy" | "document"
    chunks: int
    uploaded_at: str


class ComplianceGap(BaseModel):
    issue: str
    related_policy_snippet: str
    severity: str  # "high" | "medium" | "low"
    recommendation: str


class RiskReport(BaseModel):
    id: str
    document_id: str
    document_name: str
    generated_at: str
    overall_compliance_score: int = Field(..., ge=0, le=100)
    risk_level: str  # "low" | "medium" | "high" | "critical"
    summary: str
    gaps: List[ComplianceGap]
    strengths: List[str]
    policies_referenced: List[str]


class AnalyzeRequest(BaseModel):
    document_id: str
    focus_query: Optional[str] = None  # optional extra instruction, e.g. "focus on data retention"


class AskRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
