"""TruthLens AI - Verification Service.

Top-level orchestrator that coordinates the full analysis pipeline for a
submitted financial claim.

Pipeline stages
---------------
1. Input validation and claim processing (claim_processor)
2. Evidence retrieval (evidence_retriever)
3. Factual verification (verdict_engine)
4. Independent scam-risk assessment (scam_detector)
5. Result assembly (AnalysisResult)

This module enforces the mandatory separation between factual verification
and scam-risk assessment.  A scam-risk score does not influence the factual
verdict, and a factual verdict does not influence the scam-risk score.

Error handling
--------------
Provider failures (search errors, network timeouts) are captured in
AnalysisResult.status and AnalysisResult.processing_notes.
They never result in an unhandled exception reaching the API layer.
"""

from __future__ import annotations

import uuid
from typing import Optional

try:
    from backend.core.claim_processor import ClaimProcessingError, process_claim
    from backend.core.models import (
        AnalysisResult,
        AssertionCoverage,
        Verdict,
        ScamAssessment,
        EvidenceAssessment,
        EvidenceDiagnostics,
        EvidenceBundle,
        VerificationResult,
    )
    from backend.core.scam_detector import assess_scam_risk
    from backend.core.verdict_engine import verify_claims
    from backend.services.evidence_retriever import retrieve_evidence
except ModuleNotFoundError:
    from core.claim_processor import ClaimProcessingError, process_claim  # type: ignore
    from core.models import AnalysisResult, AssertionCoverage, Verdict, ScamAssessment, EvidenceAssessment, EvidenceBundle, EvidenceDiagnostics, VerificationResult  # type: ignore
    from core.scam_detector import assess_scam_risk  # type: ignore
    from core.verdict_engine import verify_claims  # type: ignore
    from services.evidence_retriever import retrieve_evidence  # type: ignore


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyse_claim(raw_text: str) -> AnalysisResult:
    """Run the complete analysis pipeline and return a structured AnalysisResult.

    Args:
        raw_text: The raw financial claim or message submitted by the user.

    Returns:
        AnalysisResult — always returned, never raises to the caller.
        status is:
          'completed'             – Pipeline finished normally.
          'input_error'           – Input failed validation.
          'provider_unavailable'  – Search provider could not retrieve evidence.
          'error'                 – Unexpected internal failure.
    """
    request_id = str(uuid.uuid4())
    processing_notes: list[str] = []

    # ── Stage 1: Input validation and claim extraction ────────────────────
    try:
        claim = process_claim(raw_text)
    except ClaimProcessingError as exc:
        return AnalysisResult(
            request_id=request_id,
            status="input_error",
            original_text=raw_text,
            verdict=Verdict.UNVERIFIED,
            explanation=str(exc),
            limitations=["Input validation failed; analysis could not proceed."],
        )
    except Exception as exc:  # noqa: BLE001
        return AnalysisResult(
            request_id=request_id,
            status="error",
            original_text=raw_text,
            verdict=Verdict.ERROR,
            explanation="An unexpected error occurred during claim processing.",
            limitations=["Internal claim-processing failure; no factual verdict was produced."],
        )

    # ── Stage 2: Evidence retrieval ───────────────────────────────────────
    evidence_bundle: EvidenceBundle
    try:
        evidence_bundle = retrieve_evidence(claim)
        if getattr(evidence_bundle, "providers_skipped", None):
            for ps in evidence_bundle.providers_skipped:
                processing_notes.append(f"Search provider skipped: {ps}.")
        if getattr(evidence_bundle, "provider_errors", None):
            for pe in evidence_bundle.provider_errors:
                processing_notes.append(f"Search provider fallback: {pe}.")
        if evidence_bundle.provider_error:
            processing_notes.append(
                f"Search provider reported an error: {evidence_bundle.provider_error}"
            )
        if evidence_bundle.search_provider_used in ("none", "mock"):
            processing_notes.append(
                "No live search provider is configured. "
                "Evidence retrieval was skipped; results are limited."
            )
    except Exception as exc:  # noqa: BLE001
        evidence_bundle = EvidenceBundle(
            provider_error=f"Retrieval exception: {type(exc).__name__}: {exc}",
            search_provider_used="error",
        )
        processing_notes.append(
            f"Evidence retrieval failed with an unexpected error: {type(exc).__name__}"
        )

    # ── Stage 3: Factual verification ────────────────────────────────────
    try:
        verification = verify_claims(claim, evidence_bundle)
    except Exception as exc:  # noqa: BLE001
        verification = VerificationResult(
            verdict=Verdict.ERROR,
            explanation=f"Verification pipeline failed: {type(exc).__name__}",
            limitations=["Unexpected error in verdict engine."],
        )
        processing_notes.append("Verdict engine encountered an unexpected error.")

    # ── Stage 4: Scam-risk assessment (independent) ───────────────────────
    scam_assessment_failed = False
    try:
        scam_result = assess_scam_risk(claim.normalised_text)
    except Exception as exc:  # noqa: BLE001
        scam_assessment_failed = True
        scam_result = ScamAssessment(
            score=0,
            explanation=f"Scam assessment failed: {type(exc).__name__}",
            disclaimer=(
                "Scam assessment could not complete due to an internal error. "
                "Do not treat absence of a score as a safety indicator."
            ),
        )
        processing_notes.append("Scam detector encountered an unexpected error.")

    # ── Stage 5: Assemble result ──────────────────────────────────────────
    assessments_by_url: dict[str, list[EvidenceAssessment]] = {}
    for assessment in verification.evidence_assessments:
        assessments_by_url.setdefault(assessment.evidence_url, []).append(assessment)
    all_evidence = [
        item.model_copy(update={"assessments": assessments_by_url.get(item.url, [])})
        for item in evidence_bundle.items
    ]
    status = _determine_status(evidence_bundle, verification.verdict)
    if scam_assessment_failed:
        status = "error"

    all_limitations = list(verification.limitations)
    if processing_notes:
        all_limitations.extend(processing_notes)

    return AnalysisResult(
        request_id=request_id,
        status=status,
        original_text=claim.original_text,
        claims=claim.assertions,
        verdict=verification.verdict,
        explanation=verification.explanation,
        evidence=all_evidence,
        scam_assessment=scam_result,
        limitations=all_limitations,
        processing_notes=processing_notes,
        evidence_diagnostics=_build_evidence_diagnostics(evidence_bundle, verification),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _determine_status(evidence: EvidenceBundle, verdict: Verdict) -> str:
    if evidence.search_provider_used == "error":
        return "error"
    if verdict == Verdict.ERROR:
        return "error"
    if evidence.provider_error and not evidence.items:
        return "provider_unavailable"
    return "completed"


def _build_evidence_diagnostics(
    evidence: EvidenceBundle,
    verification: VerificationResult,
) -> EvidenceDiagnostics:
    assertion_coverage: list[AssertionCoverage] = []
    for result in verification.assertion_results:
        assessments = result.evidence_assessments
        assertion_coverage.append(
            AssertionCoverage(
                assertion_text=result.assertion_text,
                outcome=result.verdict.value.lower(),
                relevant_sources=sum(item.relevance == "relevant" for item in assessments),
                supporting_sources=sum(item.relationship == "supports" for item in assessments),
                contradicting_sources=sum(item.relationship == "contradicts" for item in assessments),
            )
        )

    all_resolved = bool(verification.assertion_results) and all(
        result.verdict != Verdict.UNVERIFIED for result in verification.assertion_results
    )
    if evidence.provider_error and not evidence.items:
        outcome = "provider_unavailable"
    elif not evidence.items:
        outcome = "completed_no_results"
    elif all_resolved:
        outcome = "completed_with_coverage"
    else:
        outcome = "completed_insufficient"

    return EvidenceDiagnostics(
        retrieval_outcome=outcome,
        providers_attempted=evidence.providers_attempted,
        evidence_count=len(evidence.items),
        fetched_page_count=sum(item.evidence_origin == "fetched_page" for item in evidence.items),
        snippet_count=sum(item.evidence_origin != "fetched_page" for item in evidence.items),
        assertion_coverage=assertion_coverage,
        targeted_queries=getattr(evidence, "targeted_queries", []),
    )
