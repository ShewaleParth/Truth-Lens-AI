"""TruthLens AI - API Routes.

Phase 1: GET /api/health  (preserved unchanged)
Phase 2: POST /api/analyze

The /api/analyze endpoint accepts a financial claim, runs the full
analysis pipeline, and returns a structured result containing:
- Extracted assertions
- Factual verdict with evidence-grounded explanation
- Retrieved evidence with real source URLs
- Independent scam-risk assessment
- Processing limitations and notes

Error semantics:
- 422: Pydantic input validation failure (malformed request).
- 400: Application-level input error (empty text, too long, etc.).
- 503: Search provider unavailable (analysis result still returned).
- 500: Unexpected internal error (safe message only, no stack traces).

Structured logging is used for all requests; no submitted claim text is
logged at INFO level by default.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

try:
    from backend.api.auth import require_authenticated_user
    from backend.api.rate_limit import analysis_rate_limiter
    from backend.api.schemas import (
        AnalyzeRequest,
        AnalyzeResponse,
        AssertionCoverageOut,
        AssertionOut,
        EvidenceDiagnosticsOut,
        EvidenceItemOut,
        ErrorResponse,
        HealthResponse,
        ScamAssessmentOut,
        ScamIndicatorOut,
    )
    from backend.config import get_settings
    from backend.services.verification_service import analyse_claim
except ModuleNotFoundError:
    from api.auth import require_authenticated_user  # type: ignore
    from api.rate_limit import analysis_rate_limiter  # type: ignore
    from api.schemas import (  # type: ignore
        AnalyzeRequest,
        AnalyzeResponse,
        AssertionCoverageOut,
        AssertionOut,
        EvidenceDiagnosticsOut,
        EvidenceItemOut,
        ErrorResponse,
        HealthResponse,
        ScamAssessmentOut,
        ScamIndicatorOut,
    )
    from config import get_settings  # type: ignore
    from services.verification_service import analyse_claim  # type: ignore

logger = logging.getLogger(__name__)
router = APIRouter()


async def require_analysis_access(user_id: str = Depends(require_authenticated_user)) -> str:
    """Authenticate and apply the configured per-user analysis limit."""
    settings = get_settings()
    analysis_rate_limiter.check(
        user_id,
        settings.ANALYZE_RATE_LIMIT_REQUESTS,
        settings.ANALYZE_RATE_LIMIT_WINDOW_SECONDS,
    )
    return user_id


# ---------------------------------------------------------------------------
# Health endpoint (Phase 1 — preserved)
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service Health Check",
    description="Returns operational status and application metadata.",
    tags=["System"],
)
async def health_check() -> HealthResponse:
    """Return backend operational status and environment metadata."""
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
    )


# ---------------------------------------------------------------------------
# Analysis endpoint (Phase 2)
# ---------------------------------------------------------------------------


@router.post(
    "/analyze",
    response_model=AnalyzeResponse,
    status_code=status.HTTP_200_OK,
    summary="Analyse a Financial Claim",
    description=(
        "Accepts a financial claim or suspicious message, extracts factual "
        "assertions, retrieves authoritative evidence, evaluates factual accuracy, "
        "and independently assesses scam risk. "
        "Returns UNVERIFIED when evidence is insufficient — it does not fabricate "
        "evidence or verdicts."
    ),
    tags=["Analysis"],
    responses={
        401: {"model": ErrorResponse, "description": "Valid Supabase access token required"},
        400: {"model": ErrorResponse, "description": "Invalid input (empty, too long, etc.)"},
        422: {"description": "Request body failed schema validation"},
        429: {"model": ErrorResponse, "description": "Per-user analysis limit reached"},
        503: {"model": ErrorResponse, "description": "Authentication or search provider unavailable"},
        500: {"model": ErrorResponse, "description": "Unexpected internal error"},
    },
)
async def analyze(
    request: Request,
    body: AnalyzeRequest,
    _user_id: str = Depends(require_analysis_access),
) -> AnalyzeResponse:
    """Run the full analysis pipeline and return a structured result.

    The factual verdict and scam-risk score are always computed independently.
    Neither influences the other.
    """
    req_id_hint = str(uuid.uuid4())[:8]
    logger.info(
        "Analysis request received",
        extra={"request_id_hint": req_id_hint, "text_length": len(body.text)},
    )

    try:
        result = await run_in_threadpool(analyse_claim, body.text)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Unexpected error in analysis pipeline",
            extra={"request_id_hint": req_id_hint, "error": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Analysis could not be completed due to an internal processing error.",
        ) from exc

    if result.status == "error":
        logger.error(
            "Analysis pipeline returned an internal error",
            extra={"request_id": result.request_id, "request_id_hint": req_id_hint},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Analysis could not be completed due to an internal processing error.",
        )

    # Handle input-level errors from the pipeline
    if result.status == "input_error":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.explanation or "Input validation failed.",
        )

    # Map domain model → API schema
    response = _map_to_response(result)

    logger.info(
        "Analysis completed",
        extra={
            "request_id": result.request_id,
            "verdict": result.verdict,
            "scam_category": result.scam_assessment.category,
            "status": result.status,
        },
    )

    return response


# ---------------------------------------------------------------------------
# Domain model → API schema mapping
# ---------------------------------------------------------------------------


def _map_to_response(result: Any) -> AnalyzeResponse:
    """Convert an AnalysisResult domain model to the API response schema."""
    return AnalyzeResponse(
        request_id=result.request_id,
        status=result.status,
        original_text=result.original_text,
        claims=[
            AssertionOut(
                text=a.text,
                assertion_type=a.assertion_type,
                entities=a.entities,
            )
            for a in result.claims
        ],
        verdict=result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict),
        explanation=result.explanation,
        evidence=[
            EvidenceItemOut(
                url=e.url,
                title=e.title,
                excerpt=e.excerpt,
                published_date=e.published_date,
                source_quality=e.source_quality.value if hasattr(e.source_quality, "value") else str(e.source_quality),
                retrieval_success=e.retrieval_success,
                evidence_origin=e.evidence_origin,
                search_snippet=e.search_snippet,
                page_fetch_error=e.page_fetch_error,
                retrieval_error=e.retrieval_error,
                provider=e.provider,
                assessments=[
                    {
                        "evidence_url": a.evidence_url,
                        "assertion_text": a.assertion_text,
                        "relevance": a.relevance,
                        "relationship": a.relationship,
                        "explanation": a.explanation,
                    }
                    for a in e.assessments
                ],
            )
            for e in result.evidence
        ],
        scam_assessment=ScamAssessmentOut(
            score=result.scam_assessment.score,
            category=result.scam_assessment.category.value
            if hasattr(result.scam_assessment.category, "value")
            else str(result.scam_assessment.category),
            medium_threshold=result.scam_assessment.medium_threshold,
            high_threshold=result.scam_assessment.high_threshold,
            indicators=[
                ScamIndicatorOut(
                    indicator_type=i.indicator_type,
                    matched_text=i.matched_text,
                    explanation=i.explanation,
                    weight=i.weight,
                )
                for i in result.scam_assessment.indicators
            ],
            explanation=result.scam_assessment.explanation,
            disclaimer=result.scam_assessment.disclaimer,
        ),
        limitations=result.limitations,
        processing_notes=result.processing_notes,
        evidence_diagnostics=EvidenceDiagnosticsOut(
            retrieval_outcome=result.evidence_diagnostics.retrieval_outcome,
            providers_attempted=result.evidence_diagnostics.providers_attempted,
            evidence_count=result.evidence_diagnostics.evidence_count,
            fetched_page_count=result.evidence_diagnostics.fetched_page_count,
            snippet_count=result.evidence_diagnostics.snippet_count,
            assertion_coverage=[
                AssertionCoverageOut(
                    assertion_text=coverage.assertion_text,
                    outcome=coverage.outcome,
                    relevant_sources=coverage.relevant_sources,
                    supporting_sources=coverage.supporting_sources,
                    contradicting_sources=coverage.contradicting_sources,
                )
                for coverage in result.evidence_diagnostics.assertion_coverage
            ],
            targeted_queries=result.evidence_diagnostics.targeted_queries,
        ),
    )
