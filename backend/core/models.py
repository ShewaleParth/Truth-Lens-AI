"""TruthLens AI - Core Domain Models.

Defines the canonical data structures shared across the processing pipeline:
claims, evidence units, verdict containers, and scam-assessment results.
These are plain Pydantic models — no business logic lives here.
"""

from __future__ import annotations

import enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Verdict(str, enum.Enum):
    """Factual-accuracy verdict categories.

    TRUE          – Material assertions are supported by authoritative evidence.
    FALSE         – Material assertions are directly contradicted by evidence.
    PARTIALLY_TRUE– Some assertions are supported; others are contradicted or
                    missing important context.
    UNVERIFIED    – Evidence is insufficient to reach a defensible conclusion.
    ERROR         – The verification pipeline could not complete (provider failure).
    """

    TRUE = "TRUE"
    FALSE = "FALSE"
    PARTIALLY_TRUE = "PARTIALLY_TRUE"
    UNVERIFIED = "UNVERIFIED"
    ERROR = "ERROR"


class RiskCategory(str, enum.Enum):
    """Scam-risk severity categories."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SourceQuality(str, enum.Enum):
    """Qualitative weight of a retrieved evidence source."""

    AUTHORITATIVE = "AUTHORITATIVE"   # Primary regulatory / government portal
    REPUTABLE = "REPUTABLE"           # Established news or professional body
    UNKNOWN = "UNKNOWN"               # Domain not in trusted lists
    REJECTED = "REJECTED"             # URL failed safety / format checks


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------


class Assertion(BaseModel):
    """A single, complete factual assertion extracted from submitted text."""

    text: str = Field(
        ...,
        description="Complete assertion text; coordinated facts may be expanded into equivalent complete propositions.",
    )
    assertion_type: str = Field(
        default="general",
        description=(
            "Semantic category: 'announcement', 'deadline', 'payment_demand', "
            "'account_action', 'regulatory', 'threat', 'general'."
        ),
    )
    entities: List[str] = Field(
        default_factory=list,
        description="Named entities detected in this assertion (organisations, amounts, etc.).",
    )


class ExtractedClaim(BaseModel):
    """Structured representation of a validated and normalised user submission."""

    original_text: str = Field(..., description="Verbatim user-submitted text.")
    normalised_text: str = Field(..., description="Whitespace-normalised version.")
    assertions: List[Assertion] = Field(
        default_factory=list,
        description="Individual factual assertions extracted from the text.",
    )
    language_hint: str = Field(
        default="en",
        description="Detected or assumed language code.",
    )
    word_count: int = Field(default=0, description="Word count of the normalised text.")
    char_count: int = Field(default=0, description="Character count of the normalised text.")


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


class EvidenceAssessment(BaseModel):
    """How one evidence item relates to one extracted assertion."""

    evidence_url: str
    assertion_text: str
    relevance: str
    relationship: str
    explanation: str


class EvidenceItem(BaseModel):
    """A single unit of retrieved external evidence."""

    url: str = Field(..., description="Source URL (validated before retrieval).")
    title: str = Field(default="", description="Page or article title.")
    excerpt: str = Field(
        default="",
        description="Relevant excerpt or search-result snippet. Never fabricated.",
    )
    published_date: Optional[str] = Field(
        default=None, description="Publication date string (ISO-8601 or free text)."
    )
    source_quality: SourceQuality = Field(
        default=SourceQuality.UNKNOWN,
        description="Qualitative assessment of the source's authority.",
    )
    retrieval_success: bool = Field(
        default=True,
        description="True when this evidence item was retrieved successfully.",
    )
    evidence_origin: str = Field(
        default="search_snippet",
        description="Whether excerpt text came from a search snippet or fetched page content.",
    )
    search_snippet: Optional[str] = Field(
        default=None,
        description="Original provider snippet retained when fetched page text is available.",
    )
    page_fetch_error: Optional[str] = Field(
        default=None,
        description="Why linked page text was not available when fetching was attempted.",
    )
    retrieval_error: Optional[str] = Field(
        default=None,
        description="Error description if retrieval failed.",
    )
    provider: Optional[str] = Field(
        default=None,
        description="Identifier of the search provider that supplied this evidence item.",
    )
    target_assertion: Optional[str] = Field(
        default=None,
        description="The assertion targeted when retrieving this item.",
    )
    assessments: List[EvidenceAssessment] = Field(
        default_factory=list,
        description="Per-assertion relevance and relationship assessments.",
    )


class EvidenceBundle(BaseModel):
    """Collection of evidence items gathered for a set of assertions."""

    items: List[EvidenceItem] = Field(default_factory=list)
    search_provider_used: str = Field(
        default="none",
        description="Identifier of the search provider used (or 'none' / 'mock').",
    )
    provider_error: Optional[str] = Field(
        default=None,
        description="Top-level provider error if the search call failed.",
    )
    total_retrieved: int = Field(default=0)
    total_deduplicated: int = Field(default=0)
    providers_attempted: List[str] = Field(
        default_factory=list,
        description="Search providers attempted during retrieval.",
    )
    provider_errors: List[str] = Field(
        default_factory=list,
        description="Non-fatal provider errors recorded during fallback.",
    )
    providers_skipped: List[str] = Field(
        default_factory=list,
        description="Configured providers skipped (e.g. missing API keys).",
    )
    targeted_queries: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Focused search queries mapped to target assertions.",
    )


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


class AssertionVerification(BaseModel):
    """Verification result for a single assertion."""

    assertion_text: str
    verdict: Verdict = Verdict.UNVERIFIED
    supporting_urls: List[str] = Field(default_factory=list)
    contradicting_urls: List[str] = Field(default_factory=list)
    explanation: str = ""
    evidence_assessments: List[EvidenceAssessment] = Field(default_factory=list)


class VerificationResult(BaseModel):
    """Aggregate verification outcome across all extracted assertions."""

    verdict: Verdict = Verdict.UNVERIFIED
    explanation: str = Field(
        default="",
        description="Concise, evidence-grounded explanation of the verdict.",
    )
    assertion_results: List[AssertionVerification] = Field(default_factory=list)
    supporting_evidence: List[EvidenceItem] = Field(default_factory=list)
    contradicting_evidence: List[EvidenceItem] = Field(default_factory=list)
    unresolved_assertions: List[str] = Field(
        default_factory=list,
        description="Assertions for which no relevant evidence was found.",
    )
    evidence_assessments: List[EvidenceAssessment] = Field(
        default_factory=list,
        description="Relevance and relationship assessments for retrieved evidence.",
    )
    limitations: List[str] = Field(
        default_factory=list,
        description="Documented limitations that affect confidence in this result.",
    )
    providers_attempted: List[str] = Field(default_factory=list)
    retrieval_outcome: str = "completed_insufficient"
    fetched_page_count: int = 0


class AssertionCoverage(BaseModel):
    assertion_text: str
    outcome: str
    relevant_sources: int = 0
    supporting_sources: int = 0
    contradicting_sources: int = 0


class EvidenceDiagnostics(BaseModel):
    retrieval_outcome: str = "completed_insufficient"
    providers_attempted: List[str] = Field(default_factory=list)
    evidence_count: int = 0
    fetched_page_count: int = 0
    snippet_count: int = 0
    assertion_coverage: List[AssertionCoverage] = Field(default_factory=list)
    targeted_queries: List[Dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Scam assessment
# ---------------------------------------------------------------------------


class ScamIndicator(BaseModel):
    """A single detected scam signal with its explanation."""

    indicator_type: str = Field(
        ...,
        description=(
            "Category: 'urgent_threat', 'payment_demand', 'credential_request', "
            "'suspicious_link', 'impersonation', 'app_install', 'transfer_request', "
            "'pressure_tactic', 'guaranteed_return'."
        ),
    )
    matched_text: str = Field(..., description="Fragment of text that triggered detection.")
    explanation: str = Field(..., description="Why this fragment is considered suspicious.")
    weight: int = Field(
        default=10,
        ge=0,
        le=40,
        description="Score contribution (0–40) of this individual indicator.",
    )


class ScamAssessment(BaseModel):
    """Result of the independent scam-risk evaluation."""

    score: int = Field(
        default=0,
        ge=0,
        le=100,
        description=(
            "Rule-based scam-risk score (0–100). "
            "Not a statistically calibrated probability."
        ),
    )
    category: RiskCategory = RiskCategory.LOW
    medium_threshold: int = 30
    high_threshold: int = 60
    indicators: List[ScamIndicator] = Field(default_factory=list)
    explanation: str = Field(default="")
    disclaimer: str = Field(
        default=(
            "This score is generated by deterministic rules. "
            "It does not constitute legal advice or a definitive scam determination."
        )
    )


# ---------------------------------------------------------------------------
# Top-level analysis result
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):
    """Complete result of analysing a submitted financial claim."""

    request_id: str = Field(..., description="Unique identifier for this analysis request.")
    status: str = Field(
        default="completed",
        description="'completed', 'error', 'provider_unavailable'.",
    )
    original_text: str
    claims: List[Assertion] = Field(default_factory=list)
    verdict: Verdict = Verdict.UNVERIFIED
    explanation: str = ""
    evidence: List[EvidenceItem] = Field(default_factory=list)
    scam_assessment: ScamAssessment = Field(default_factory=ScamAssessment)
    limitations: List[str] = Field(default_factory=list)
    processing_notes: List[str] = Field(
        default_factory=list,
        description="Non-error informational notes about the processing pipeline.",
    )
    evidence_diagnostics: EvidenceDiagnostics = Field(default_factory=EvidenceDiagnostics)
