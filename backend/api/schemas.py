"""TruthLens AI - API Schemas.

Defines all request and response schemas for API endpoints.
Phase 2 adds AnalyzeRequest and AnalyzeResponse alongside the
existing HealthResponse schema from Phase 1.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Phase 1 – Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Schema representing the health status and metadata of the application."""

    status: str = Field(
        default="ok",
        description="Operational status of the backend service (e.g., 'ok').",
        examples=["ok"],
    )
    app_name: str = Field(
        ...,
        description="Name of the application.",
        examples=["TruthLens AI"],
    )
    version: str = Field(
        ...,
        description="Current semantic version of the application.",
        examples=["0.1.0"],
    )
    environment: str = Field(
        ...,
        description="Active deployment or runtime environment.",
        examples=["development"],
    )


# ---------------------------------------------------------------------------
# Phase 2 – Analysis request
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Request body for POST /api/analyze."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=5_000,
        description="The financial claim, announcement, or suspicious message to analyse.",
        examples=[
            "RBI has announced that all bank accounts will be blocked tonight "
            "unless customers pay ₹500 for mandatory verification."
        ],
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_whitespace_only(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "The 'text' field must not be empty or contain only whitespace."
            )
        return v


# ---------------------------------------------------------------------------
# Phase 2 – Analysis response components
# ---------------------------------------------------------------------------


class AssertionOut(BaseModel):
    """Serialised form of an extracted assertion."""

    text: str
    assertion_type: str
    entities: List[str] = []


class EvidenceAssessmentOut(BaseModel):
    """How one evidence item relates to one extracted assertion."""

    evidence_url: str
    assertion_text: str
    relevance: str
    relationship: str
    explanation: str


class EvidenceItemOut(BaseModel):
    """Serialised form of a retrieved evidence item."""

    url: str
    title: str = ""
    excerpt: str = ""
    published_date: Optional[str] = None
    source_quality: str = "UNKNOWN"
    retrieval_success: bool = True
    evidence_origin: str = "search_snippet"
    search_snippet: Optional[str] = None
    page_fetch_error: Optional[str] = None
    retrieval_error: Optional[str] = None
    provider: Optional[str] = None
    target_assertion: Optional[str] = None
    assessments: List[EvidenceAssessmentOut] = Field(default_factory=list)


class ScamIndicatorOut(BaseModel):
    """Serialised scam indicator."""

    indicator_type: str
    matched_text: str
    explanation: str
    weight: int


class ScamAssessmentOut(BaseModel):
    """Serialised scam-risk assessment result."""

    score: int = Field(..., ge=0, le=100)
    category: str
    medium_threshold: int = 30
    high_threshold: int = 60
    indicators: List[ScamIndicatorOut] = []
    explanation: str = ""
    disclaimer: str = ""


class AssertionCoverageOut(BaseModel):
    assertion_text: str
    outcome: str
    relevant_sources: int = 0
    supporting_sources: int = 0
    contradicting_sources: int = 0


class EvidenceDiagnosticsOut(BaseModel):
    retrieval_outcome: str = "completed_insufficient"
    providers_attempted: List[str] = Field(default_factory=list)
    evidence_count: int = 0
    fetched_page_count: int = 0
    snippet_count: int = 0
    assertion_coverage: List[AssertionCoverageOut] = Field(default_factory=list)
    targeted_queries: List[Dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase 2 – Top-level analysis response
# ---------------------------------------------------------------------------


class AnalyzeResponse(BaseModel):
    """Full analysis result returned by POST /api/analyze.

    Actual values are always computed from the processing pipeline.
    This schema does not hard-code any specific verdict or score.
    """

    request_id: str = Field(
        ...,
        description="Unique identifier for this analysis request (UUID).",
    )
    status: str = Field(
        ...,
        description=(
            "'completed' – pipeline finished; "
            "'input_error' – request validation failed; "
            "'provider_unavailable' – search provider failed; "
            "'error' – unexpected internal failure."
        ),
    )
    original_text: str = Field(..., description="Verbatim submitted text.")
    claims: List[AssertionOut] = Field(
        default_factory=list,
        description="Individual factual assertions extracted from the submitted text.",
    )
    verdict: str = Field(
        ...,
        description=(
            "Factual-accuracy verdict: TRUE, FALSE, PARTIALLY_TRUE, UNVERIFIED, or ERROR. "
            "Based exclusively on retrieved evidence."
        ),
    )
    explanation: str = Field(
        default="",
        description="Evidence-grounded explanation of the verdict.",
    )
    evidence: List[EvidenceItemOut] = Field(
        default_factory=list,
        description="Retrieved evidence items with original source URLs.",
    )
    scam_assessment: ScamAssessmentOut = Field(
        ...,
        description=(
            "Independent scam-risk assessment. "
            "Separate from and not influenced by the factual verdict."
        ),
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Documented limitations that affect confidence in this result.",
    )
    processing_notes: List[str] = Field(
        default_factory=list,
        description="Informational processing notes (e.g. search provider fallback or skip events).",
    )
    evidence_diagnostics: EvidenceDiagnosticsOut = Field(default_factory=EvidenceDiagnosticsOut)


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Safe error response that never exposes internal details."""

    detail: str
    status_code: int
