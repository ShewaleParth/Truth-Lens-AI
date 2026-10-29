"""TruthLens AI - Evidence-Based Verdict Engine.

Compares extracted assertions against retrieved evidence and assigns
a factual-accuracy verdict.

Architecture
------------
This module contains only the *reasoning* logic — it receives pre-built
EvidenceBundle and ExtractedClaim objects and returns a VerificationResult.
It does not perform any network calls and has no external dependencies.

Verification strategy (deterministic evidence matching)
-------------------------------------------------------
The engine uses direct proposition-specific checks for supported policy facts
and conservative term/signal matching for other assertions. Source authority
affects whether a result can be decisive, but source authority or topical
keyword overlap alone never establishes a proposition.

Documented limitations of the baseline
---------------------------------------
- Cannot assess semantic similarity — only surface-level term overlap.
- Cannot evaluate context, date ranges, or jurisdiction nuances.
- Cannot distinguish between an authoritative statement and a news article
  quoting the same assertion.
- False assertion text that happens to appear in a result excerpt may
  incorrectly raise confidence.

An LLM-backed engine may be plugged in during a later phase by replacing
the private `_baseline_verify_assertion` function with a provider call
while keeping the public interface unchanged.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Tuple
from urllib.parse import urlparse

try:
    from backend.core.models import (
        Assertion,
        AssertionVerification,
        EvidenceBundle,
        EvidenceAssessment,
        EvidenceItem,
        ExtractedClaim,
        SourceQuality,
        VerificationResult,
        Verdict,
    )
except ModuleNotFoundError:
    from core.models import (  # type: ignore
        Assertion,
        AssertionVerification,
        EvidenceBundle,
        EvidenceAssessment,
        EvidenceItem,
        ExtractedClaim,
        SourceQuality,
        VerificationResult,
        Verdict,
    )


# Minimum token overlap used for non-decisive relevance labels only.
_MIN_TOKENS_TO_COMPARE = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_claims(
    claim: ExtractedClaim,
    evidence: EvidenceBundle,
) -> VerificationResult:
    """Compare extracted assertions against evidence and return a verdict.

    Args:
        claim:    Processed claim with normalised text and assertions.
        evidence: Retrieved evidence bundle (may be empty).

    Returns:
        VerificationResult with verdict, explanation, and per-assertion detail.
    """
    limitations: list[str] = _collect_limitations(evidence)
    usable_evidence = [e for e in evidence.items if e.retrieval_success]

    if evidence.provider_error:
        return VerificationResult(
            verdict=Verdict.ERROR,
            explanation=(
                f"Evidence retrieval failed: {evidence.provider_error}. "
                "Factual verification cannot proceed without evidence."
            ),
            limitations=limitations,
        )

    if not usable_evidence:
        return VerificationResult(
            verdict=Verdict.UNVERIFIED,
            explanation=(
                "No usable evidence was retrieved. "
                "The claim cannot be verified or refuted without supporting sources."
            ),
            limitations=limitations,
        )

    assertion_results: list[AssertionVerification] = []
    supporting_evidence: list[EvidenceItem] = []
    contradicting_evidence: list[EvidenceItem] = []
    unresolved_assertions: list[str] = []

    for assertion in claim.assertions:
        av = _baseline_verify_assertion(assertion, usable_evidence)
        assertion_results.append(av)
        if av.verdict == Verdict.UNVERIFIED:
            unresolved_assertions.append(assertion.text)
        for url in av.supporting_urls:
            item = _find_item_by_url(url, usable_evidence)
            if item and item not in supporting_evidence:
                supporting_evidence.append(item)
        for url in av.contradicting_urls:
            item = _find_item_by_url(url, usable_evidence)
            if item and item not in contradicting_evidence:
                contradicting_evidence.append(item)

    overall_verdict, explanation = _aggregate_verdict(
        assertion_results, supporting_evidence, contradicting_evidence, unresolved_assertions
    )

    evidence_assessments = [
        assessment
        for av in assertion_results
        for assessment in av.evidence_assessments
    ]
    return VerificationResult(
        verdict=overall_verdict,
        explanation=explanation,
        assertion_results=assertion_results,
        supporting_evidence=supporting_evidence,
        contradicting_evidence=contradicting_evidence,
        unresolved_assertions=unresolved_assertions,
        evidence_assessments=evidence_assessments,
        limitations=limitations,
    )


# ---------------------------------------------------------------------------
# Per-assertion verification (deterministic baseline)
# ---------------------------------------------------------------------------


def _extract_subject_role_target(text: str) -> tuple[str, str, str] | None:
    """Extract (subject, role, target) from relational assertions.

    Supports subject-first, target-possessive, and target-first central-bank
    phrasing, plus assertions describing a regulator's banking-system role.
    """
    t = text.lower().replace("’", "'")
    m = re.search(
        r"^(?:the\s+)?([A-Za-z0-9\s]+?)(?:\s*\([A-Za-z0-9\s]+\))?\s+"
        r"(?:is|serves as|acts as)\s+(?:the\s+)?"
        r"(central\s+bank(?:ing\s+system)?|regulatory\s+body|monetary\s+authority|apex\s+bank)\s+"
        r"(?:of|for)\s+(?:the\s+)?([A-Za-z0-9\s.'’]+?)(?:\s+(?:and|is|was|will)|\.|$)",
        t,
    )
    if m:
        subj = m.group(1).strip()
        role = "central bank" if "central bank" in m.group(2) else m.group(2).strip()
        target = m.group(3).strip()
        return (subj, role, target)

    # "The Reserve Bank of India is India's central bank."
    m_possessive = re.search(
        r"^(?:the\s+)?([A-Za-z0-9\s]+?)(?:\s*\([A-Za-z0-9\s]+\))?\s+"
        r"(?:is|serves as|acts as)\s+(?:the\s+)?"
        r"([A-Za-z][A-Za-z\s.'’]*?)['’]s\s+"
        r"(central\s+bank(?:ing\s+system)?|regulatory\s+body|monetary\s+authority|apex\s+bank)(?:\.|$)",
        t,
    )
    if m_possessive:
        subject = m_possessive.group(1).strip()
        target = m_possessive.group(2).strip()
        if target in {"country", "our country"} and "india" in subject:
            target = "india"
        role = "central bank" if "central bank" in m_possessive.group(3) else m_possessive.group(3).strip()
        return (subject, role, target)

    # "India's central bank is the Reserve Bank of India."
    m2 = re.search(
        r"^(?:the\s+)?([A-Za-z0-9\s.'’]+?)(?:'s|\s+of\s+)?\s*"
        r"(central\s+bank(?:ing\s+system)?|regulatory\s+body|monetary\s+authority|apex\s+bank)\s+"
        r"(?:is|serves as|acts as)\s+(?:the\s+)?([A-Za-z0-9\s]+?)"
        r"(?:\s*\([A-Za-z0-9\s]+\))?(?:\.|$)",
        t,
    )
    if m2:
        target = m2.group(1).strip()
        role = "central bank" if "central bank" in m2.group(2) else m2.group(2).strip()
        subj = m2.group(3).strip()
        return (subj, role, target)

    m_regulator = re.search(
        r"^(?:the\s+)?([A-Za-z0-9\s]+?)(?:\s*\([A-Za-z0-9\s]+\))?\s+"
        r"(?:is\s+)?(?:responsible\s+for\s+)?"
        r"(?:regulating|regulates|regulator(?:\s+and\s+supervisor)?\s+of)\s+"
        r"(?:the\s+)?(?:(?:country|india|nation)(?:['’]s)?\s+)?"
        r"(?:banking|financial)(?:\s+and\s+financial)?\s+system(?:\.|$)",
        t,
    )
    if m_regulator:
        subject = m_regulator.group(1).strip()
        target = "india" if "india" in subject or re.search(r"\brbi\b", subject) else "country"
        return (subject, "banking system regulator", target)

    return None


def _is_reliable_source(item: EvidenceItem) -> bool:
    return (
        item.page_fetch_error is None
        and item.source_quality in (SourceQuality.AUTHORITATIVE, SourceQuality.REPUTABLE)
    )


def _subject_matches_evidence(subject: str, item: EvidenceItem, evidence_text: str) -> bool:
    subject_tokens = _significant_tokens(subject)
    if subject_tokens and subject_tokens.issubset(_significant_tokens(evidence_text)):
        return True
    if "reserve bank of india" in subject or re.search(r"\brbi\b", subject):
        if re.search(r"\brbi\b", evidence_text):
            return True
        hostname = (urlparse(item.url).hostname or "").lower()
        return hostname == "rbi.org.in" or hostname.endswith(".rbi.org.in")
    return False


def _target_matches_evidence(
    target: str,
    evidence_text: str,
    item: EvidenceItem,
    role: str,
) -> bool:
    if target in {"us", "u.s.", "usa", "united states", "united states of america"}:
        return bool(re.search(r"\b(?:united states|u\.s\.a?\.?|usa)\b", evidence_text))
    if target in {"india", "republic of india"}:
        if re.search(r"\b(?:india|indian)\b", evidence_text):
            return True
        hostname = (urlparse(item.url).hostname or "").lower()
        return (
            role == "banking system regulator"
            and (hostname == "rbi.org.in" or hostname.endswith(".rbi.org.in"))
        )
    if target == "country":
        return bool(re.search(r"\bcountry(?:'s)?\b", evidence_text))
    return bool(target and target in evidence_text)


def _role_matches_evidence(role: str, evidence_text: str) -> bool:
    if role == "central bank":
        return bool(re.search(r"\bcentral\s+bank(?:ing\s+system)?\b", evidence_text))
    if role == "banking system regulator":
        return bool(
            re.search(
                r"\b(?:regulat\w*|supervis\w*)\b.{0,35}\b"
                r"(?:commercial\s+banks?|banking\s+(?:system|operations)|financial\s+system)\b",
                evidence_text,
            )
            or re.search(
                r"\b(?:banking\s+(?:system|operations)|financial\s+system)\b.{0,35}\b"
                r"(?:regulat\w*|supervis\w*)\b",
                evidence_text,
            )
            or re.search(
                r"\bregulat\w*\s+(?:organization|organisation|body)\s+(?:for|of)\s+"
                r".{0,30}\b(?:banking\s+system|financial\s+system)\b",
                evidence_text,
            )
        )
    return role in evidence_text


_AMOUNT_RE = re.compile(
    r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)(?:\s*(lakh|lakhs|lac|lacs|crore|crores|thousand|thousands))?"
    r"|\b(\d[\d,]*)\s*(lakh|lakhs|lac|lacs|crore|crores|thousand|thousands)\b",
    re.IGNORECASE,
)
_TEXT_AMOUNT_RE = re.compile(r"\bfive\s+(?:hundred\s+)?thousand\b|\bfive\s+lakhs?\b", re.IGNORECASE)


def _rupee_amounts(text: str) -> set[int]:
    """Normalize common numeric and textual Indian amount representations to rupees."""
    amounts: set[int] = set()
    multipliers = {
        "lakh": 100_000,
        "lakhs": 100_000,
        "lac": 100_000,
        "lacs": 100_000,
        "crore": 10_000_000,
        "crores": 10_000_000,
        "thousand": 1_000,
        "thousands": 1_000,
    }
    for match in _AMOUNT_RE.finditer(text):
        number = match.group(1) or match.group(3)
        unit = (match.group(2) or match.group(4) or "").lower()
        value = int(number.replace(",", ""))
        amounts.add(value * multipliers.get(unit, 1))
    for match in _TEXT_AMOUNT_RE.finditer(text):
        amounts.add(500_000)
    return amounts


_AMOUNT_ATTRIBUTE_RE = re.compile(
    r"^(?P<left>.+?)\s+"
    r"(?P<attribute>(?:(?:daily|monthly|annual|deposit|withdrawal|transaction|"
    r"maximum|minimum|insurance)\s+){0,2}"
    r"(?:limit|fee|amount|balance|threshold|capital|rate|coverage))\s+"
    r"(?:(?:is|are|was|were|of|at|to)\s+)?"
    r"(?P<value>(?:₹|rs\.?|inr)\s*[\d,]+(?:\s*(?:lakh|lakhs|lac|lacs|crore|crores|thousand|thousands))?"
    r"|\b[\d,]+\s*(?:lakh|lakhs|lac|lacs|crore|crores|thousand|thousands))\b[.!?]?$",
    re.IGNORECASE,
)


def _extract_amount_attribute_fact(text: str) -> tuple[str, str, int] | None:
    match = _AMOUNT_ATTRIBUTE_RE.match(text.strip())
    if not match:
        return None
    subject = re.sub(
        r"\b(?:has|have|requires?|sets?|charges?)\s+(?:a|an|the)?\s*$",
        "",
        match.group("left").strip(),
        flags=re.IGNORECASE,
    ).strip()
    subject = re.sub(r"^(?:the|a|an)\s+", "", subject, flags=re.IGNORECASE)
    values = _rupee_amounts(match.group("value"))
    if len(subject) < 2 or len(values) != 1:
        return None
    attribute = " ".join(match.group("attribute").lower().split())
    return subject, attribute, next(iter(values))


def _amount_attribute_relation(
    fact: tuple[str, str, int],
    evidence_text: str,
) -> tuple[bool, bool]:
    subject, attribute, claimed_value = fact
    subject_pattern = _subject_alias_pattern(subject)
    if not subject_pattern:
        return False, False
    supports = False
    contradicts = False
    for sentence in re.split(r"(?<=[.!?;])\s+", evidence_text):
        if not re.search(subject_pattern, sentence, re.IGNORECASE):
            continue
        evidence_fact = _extract_amount_attribute_fact(sentence)
        if not evidence_fact or evidence_fact[1] != attribute:
            continue
        if evidence_fact[2] == claimed_value:
            supports = True
        else:
            contradicts = True
    return supports, contradicts


def _insurance_limit_amounts(text: str) -> set[int]:
    """Extract amounts positioned after explicit insurance-limit wording."""
    values: set[int] = set()
    limit_markers = re.finditer(
        r"\b(?:maximum|up\s+to|upto|limit|not\s+exceed(?:ing)?)\b",
        text,
        re.IGNORECASE,
    )
    for marker in limit_markers:
        remaining = text[marker.end() :]
        boundary = re.search(r"[.!?;\n]", remaining)
        phrase = remaining[: boundary.start()] if boundary else remaining
        values.update(_rupee_amounts(phrase))
    return values


def _dicgc_assertion_kind(text: str) -> str | None:
    if not re.search(r"\bdicgc\b", text, re.IGNORECASE):
        return None
    has_amount = bool(_rupee_amounts(text)) and bool(
        re.search(r"\b(?:insur\w*|insurance|limit|maximum|upto|up\s+to)\b", text, re.IGNORECASE)
    )
    has_bank_category = bool(
        re.search(
            r"\b(?:commercial|co[\s-]?operative)\s+banks?\b",
            text,
            re.IGNORECASE,
        )
    )
    if has_amount and has_bank_category:
        return "compound"
    if has_bank_category and re.search(r"\b(?:insur\w*|insurance)\b", text, re.IGNORECASE):
        return "bank_category"
    if has_amount:
        return "insurance_limit"
    return None


def _dicgc_limit_evidence(assertion_text: str, evidence_text: str) -> tuple[bool, bool]:
    claimed_amounts = _rupee_amounts(assertion_text)
    evidence_amounts = _insurance_limit_amounts(evidence_text)
    insurance_context = bool(
        re.search(r"\b(?:insur\w*|deposit\s+insurance|coverage)\b", evidence_text, re.IGNORECASE)
    )
    limit_context = bool(
        re.search(
            r"\b(?:maximum|up\s+to|upto|limit|not\s+exceed(?:ing)?)\b",
            evidence_text,
            re.IGNORECASE,
        )
    )
    if not insurance_context or not limit_context or not claimed_amounts or not evidence_amounts:
        return False, False
    matching_limit = bool(claimed_amounts & evidence_amounts)
    return matching_limit, bool(evidence_amounts) and not matching_limit


def _dicgc_category_evidence(assertion_text: str, evidence_text: str) -> tuple[bool, bool]:
    category_match = re.search(
        r"\b(commercial|co[\s-]?operative)\s+banks?\b",
        assertion_text,
        re.IGNORECASE,
    )
    if not category_match:
        return False, False
    category_pattern = (
        r"\bcommercial\s+banks?\b"
        if category_match.group(1).lower() == "commercial"
        else r"\bco[\s-]?operative\s+banks?\b"
    )
    category_present = bool(re.search(category_pattern, evidence_text, re.IGNORECASE))
    insurance_context = bool(
        re.search(r"\b(?:insur\w*|deposit\s+insurance|coverage)\b", evidence_text, re.IGNORECASE)
    )
    if not category_present:
        return False, False

    denied = bool(
        re.search(
            r"(?:\b(?:not|never|no|excluded|exempt)\b.{0,60}" + category_pattern + r")|"
            r"(?:" + category_pattern + r".{0,60}\b(?:not\s+insured|not\s+covered|excluded|exempt)\b)",
            evidence_text,
            re.IGNORECASE,
        )
    )
    affirmed = insurance_context and bool(
        re.search(
            r"(?:\b(?:insur\w*|covered|coverage)\b.{0,100}" + category_pattern + r")|"
            r"(?:" + category_pattern + r".{0,100}\b(?:insur\w*|covered|coverage)\b)",
            evidence_text,
            re.IGNORECASE,
        )
    )
    return affirmed and not denied, denied and insurance_context


def _dicgc_evidence_relation(
    assertion: Assertion,
    evidence_text: str,
    assertion_kind: str,
) -> tuple[bool, bool]:
    if assertion_kind == "insurance_limit":
        return _dicgc_limit_evidence(assertion.text, evidence_text)
    if assertion_kind == "bank_category":
        return _dicgc_category_evidence(assertion.text, evidence_text)

    limit_support, limit_contradiction = _dicgc_limit_evidence(assertion.text, evidence_text)
    category_support, category_contradiction = _dicgc_category_evidence(assertion.text, evidence_text)
    return (
        limit_support and category_support,
        limit_contradiction or category_contradiction,
    )


_MONTHS = {
    month.lower(): index
    for index, month in enumerate(
        ("January", "February", "March", "April", "May", "June",
         "July", "August", "September", "October", "November", "December"),
        1,
    )
}
_DATE_PATTERNS = (
    re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"),
)


def _normalized_dates(text: str) -> set[str]:
    dates: set[str] = set()
    for pattern_index, pattern in enumerate(_DATE_PATTERNS):
        for match in pattern.finditer(text):
            try:
                if pattern_index == 0:
                    year, month, day = (int(part) for part in match.groups())
                elif pattern_index == 1:
                    day = int(match.group(1))
                    month = _MONTHS[match.group(2).lower()]
                    year = int(match.group(3))
                elif pattern_index == 2:
                    month = _MONTHS[match.group(1).lower()]
                    day = int(match.group(2))
                    year = int(match.group(3))
                else:
                    day, month, year = (int(part) for part in match.groups())
                dates.add(date(year, month, day).isoformat())
            except (ValueError, KeyError):
                continue
    return dates


def _canonical_location(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9 ]", " ", value.lower())
    normalized = " ".join(normalized.split())
    return {"bombay": "mumbai", "new delhi": "delhi"}.get(normalized, normalized)


def _subject_alias_pattern(subject: str) -> str | None:
    subject = subject.lower()
    if re.search(r"\b(?:rbi|reserve bank of india)\b", subject):
        return r"\b(?:rbi|reserve\s+bank\s+of\s+india)\b"
    if re.search(r"\bsebi\b|securities and exchange board", subject):
        return r"\b(?:sebi|securities\s+and\s+exchange\s+board(?:\s+of\s+india)?)\b"
    if re.search(r"\bdicgc\b|deposit insurance", subject):
        return r"\b(?:dicgc|deposit\s+insurance\s+and\s+credit\s+guarantee\s+corporation)\b"
    candidate = re.sub(r"^(?:the\s+)", "", subject.strip())
    if len(candidate) < 3:
        return None
    return r"\b" + re.escape(candidate) + r"\b"


def _extract_attribute_fact(text: str) -> tuple[str, str, str] | None:
    """Extract supported commencement-date or headquarters-location assertions."""
    commencement = re.search(
        r"^(?P<subject>.+?)\s+(?:commenced|began|started)\s+"
        r"(?:its\s+)?operations?\s+(?:on|in)\s+(?P<value>.+?)\s*[.!?]?$",
        text.strip(),
        re.IGNORECASE,
    )
    if commencement:
        value = commencement.group("value")
        dates = _normalized_dates(value)
        if len(dates) == 1:
            return "commencement_date", commencement.group("subject").strip(), next(iter(dates))

    headquarters = re.search(
        r"^(?P<subject>.+?)\s+(?:is\s+)?(?:headquartered\s+in|"
        r"headquarters?\s+(?:(?:is|are)\s+)?(?:located\s+)?in|"
        r"head\s+office\s+(?:(?:is|are)\s+)?(?:located\s+)?in|"
        r"(?:central\s+)?office\s+(?:is\s+)?located\s+in)\s+"
        r"(?P<value>[A-Za-z][A-Za-z .'-]*?)\s*[.!?]?$",
        text.strip(),
        re.IGNORECASE,
    )
    if headquarters:
        location = _canonical_location(headquarters.group("value"))
        if location:
            return "headquarters_location", headquarters.group("subject").strip(), location
    return None


def _attribute_evidence_relation(
    fact: tuple[str, str, str],
    evidence_text: str,
) -> tuple[bool, bool]:
    kind, subject, claimed_value = fact
    subject_pattern = _subject_alias_pattern(subject)
    if not subject_pattern:
        return False, False

    supports = False
    contradicts = False
    for sentence in re.split(r"(?<=[.!?;])\s+", evidence_text):
        if not re.search(subject_pattern, sentence, re.IGNORECASE):
            continue
        evidence_fact = _extract_attribute_fact(sentence)
        if not evidence_fact or evidence_fact[0] != kind:
            continue
        if evidence_fact[2] == claimed_value:
            supports = True
        else:
            contradicts = True
    return supports, contradicts


_ACTION_PATTERNS = {
    "account_block": re.compile(
        r"\b(?:block\w*|freez\w*|suspend\w*|clos\w*|deactivat\w*)\b.{0,50}"
        r"\b(?:bank\s+)?accounts?\b|\b(?:bank\s+)?accounts?\b.{0,50}"
        r"\b(?:block\w*|freez\w*|suspend\w*|clos\w*|deactivat\w*)\b",
        re.IGNORECASE,
    ),
}


def _action_fact(text: str) -> tuple[str, str] | None:
    subject_match = re.search(
        r"\b(RBI|SEBI|NPCI|IRDAI|Reserve Bank of India|Securities and Exchange Board of India)\b",
        text,
        re.IGNORECASE,
    )
    for action, pattern in _ACTION_PATTERNS.items():
        if pattern.search(text):
            subject = subject_match.group(1) if subject_match else "RBI"
            return action, subject
    return None


def _action_evidence_relation(
    assertion_text: str,
    fact: tuple[str, str],
    evidence_text: str,
    item: EvidenceItem | None = None,
) -> tuple[bool, bool]:
    action, subject = fact
    subject_pattern = _subject_alias_pattern(subject)
    action_pattern = _ACTION_PATTERNS[action]
    is_official_domain = bool(
        item
        and urlparse(item.url).hostname
        and any(d in (urlparse(item.url).hostname or "") for d in ("rbi.org.in", "pib.gov.in"))
    )
    if not is_official_domain:
        if not subject_pattern or not re.search(subject_pattern, evidence_text, re.IGNORECASE):
            if not re.search(r"\b(?:pib|rbi|bank\w*)\b", evidence_text, re.IGNORECASE):
                return False, False

    # Compare proposition details within one sentence. Combining a title and an
    # excerpt used to let a generic official page about account freezes prove a
    # specific announcement to block *all* accounts tonight.
    claim_is_universal = bool(re.search(r"\b(?:all|every|each)\b", assertion_text, re.IGNORECASE))
    claim_deadlines = {
        match.group(0).lower()
        for match in re.finditer(
            r"\b(?:today|tonight|tomorrow|immediately|by\s+midnight|within\s+\d+\s+(?:hours?|days?))\b",
            assertion_text,
            re.IGNORECASE,
        )
    }
    claim_needs_announcement = bool(
        re.search(r"\b(?:announc\w*|issu\w*|circular|notice|order|directive)\b", assertion_text, re.IGNORECASE)
    )
    claim_asserts_future = bool(re.search(r"\b(?:will|shall|going\s+to)\b", assertion_text, re.IGNORECASE))
    claimed_dates = _normalized_dates(assertion_text)
    claimed_amounts = _rupee_amounts(assertion_text)
    passage = item.excerpt if item and item.excerpt else evidence_text
    sentences = re.split(r"(?<=[.!?;])\s+", passage)
    for index, sentence in enumerate(sentences):
        if not action_pattern.search(sentence):
            previous = sentences[index - 1] if index > 0 else ""
            refers_to_previous_claim = bool(
                re.search(r"\b(?:this|the)\s+(?:claim|message|post|rumou?r)\b", sentence, re.IGNORECASE)
                and action_pattern.search(previous)
                and re.search(r"\b(?:claim\w*|alleg\w*|rumou?r|viral\s+(?:message|post))\b", previous, re.IGNORECASE)
                and _token_overlap(_significant_tokens(assertion_text), previous) >= 0.35
            )
            previous_debunk = bool(
                refers_to_previous_claim
                and re.search(r"\b(?:fake|false|fabricated|misleading|untrue|debunked|hoax|fictitious)\b", sentence, re.IGNORECASE)
            )
            previous_denial = bool(
                refers_to_previous_claim
                and re.search(r"\bno\s+such\s+(?:circular|notice|order|directive|announcement)\b", sentence, re.IGNORECASE)
            )
            if previous_debunk or previous_denial:
                return False, True
            continue

        denial_phrase = bool(
            re.search(
                r"\bno\s+such\s+(?:circular|notice|order|directive|announcement|scheme)\b"
                r"|\b(?:has|have|had)\s+(?:issued|released)\s+no\s+such\b"
                r"|\b(?:has|have|had)\s+not\s+(?:issued|announced|ordered|directed|released)\b.{0,60}\b(?:any\s+)?(?:such\s+)?(?:circular|notice|order|directive)\b",
                sentence,
                re.IGNORECASE,
            )
        )
        direct_no_block = bool(
            re.search(
                r"\b(?:not|never)\s+(?:be\s+)?(?:blocked|frozen|suspended|closed|deactivated)\b"
                r"|\bno\s+(?:bank\s+)?accounts?\b.{0,50}\b(?:will\s+be\s+)?"
                r"(?:blocked|frozen|suspended|closed|deactivated)\b"
                r"|\b(?:does\s+not|never)\b.{0,50}\b(?:block|freeze|suspend)\w*\b.{0,40}\b(?:bank\s+)?accounts?\b",
                sentence,
                re.IGNORECASE,
            )
        )
        fact_check_debunk = bool(
            re.search(
                r"\b(?:fake(?:\s+news)?|false|fabricated|misleading|untrue|debunked|hoax|fictitious)\b",
                sentence,
                re.IGNORECASE,
            )
            and re.search(r"\b(?:claim|message|post|rumou?r|notice|circular|news|alleg\w*)\w*\b", sentence, re.IGNORECASE)
            and _token_overlap(_significant_tokens(assertion_text), sentence) >= 0.35
        )
        if direct_no_block or (denial_phrase and action_pattern.search(sentence)) or fact_check_debunk:
            return False, True

        # A sentence reporting what a viral message claims is not itself
        # evidence that the reported event happened.
        if re.search(r"\b(?:claim\w*|alleg\w*|rumou?r|viral\s+(?:message|post))\b", sentence, re.IGNORECASE):
            continue

        evidence_dates = _normalized_dates(sentence)
        evidence_amounts = _rupee_amounts(sentence)
        if claimed_dates and not claimed_dates.issubset(evidence_dates):
            continue
        if claimed_amounts and not claimed_amounts.issubset(evidence_amounts):
            continue
        if claim_is_universal and not re.search(r"\b(?:all|every|each)\b", sentence, re.IGNORECASE):
            continue
        if claim_deadlines and not claim_deadlines.issubset(
            {m.group(0).lower() for m in re.finditer(
                r"\b(?:today|tonight|tomorrow|immediately|by\s+midnight|within\s+\d+\s+(?:hours?|days?))\b",
                sentence,
                re.IGNORECASE,
            )}
        ):
            continue

        # A tentative or conditional possibility is not proof of an asserted
        # order. Likewise, a different authority's order cannot establish that
        # the named regulator issued the notice.
        hedged_or_conditional = bool(
            re.search(r"\b(?:may|might|could|can|sometimes|at\s+times|occasionally)\b", sentence, re.IGNORECASE)
            or re.search(r"\b(?:based\s+on|pursuant\s+to|under)\b.{0,70}\b(?:order|direction|instruction|authority|authorities)\b", sentence, re.IGNORECASE)
        )
        if hedged_or_conditional:
            continue
        if claim_needs_announcement and not re.search(
            r"\b(?:announc\w*|issu\w*|circular|notice|order|directive|press\s+release)\b",
            sentence,
            re.IGNORECASE,
        ):
            continue
        if claim_asserts_future and not re.search(
            r"\b(?:will|shall|going\s+to|is\s+scheduled\s+to|are\s+scheduled\s+to)\b",
            sentence,
            re.IGNORECASE,
        ):
            continue
        return True, False

    return False, False


def _payment_demand_fact(text: str) -> tuple[set[int], bool] | None:
    amounts = _rupee_amounts(text)
    has_payment = bool(re.search(r"\b(?:pay|payment|fee|charge|deposit|transfer)\b", text, re.IGNORECASE))
    if amounts or has_payment:
        is_verification = bool(re.search(r"\b(?:verif\w*|mandatory|account)\b", text, re.IGNORECASE))
        return amounts, is_verification
    return None


def _payment_demand_evidence_relation(
    assertion_text: str,
    fact: tuple[set[int], bool],
    evidence_text: str,
    item: EvidenceItem | None = None,
) -> tuple[bool, bool]:
    claimed_amounts, is_verification = fact
    subject_pattern = r"\b(?:rbi|reserve\s+bank\s+of\s+india|bank\w*|pib)\b"
    is_official_domain = bool(
        item
        and urlparse(item.url).hostname
        and any(d in (urlparse(item.url).hostname or "") for d in ("rbi.org.in", "pib.gov.in"))
    )
    if not re.search(subject_pattern, evidence_text, re.IGNORECASE) and not is_official_domain:
        return False, False

    # Guard: if evidence is exclusively about currency notes/banknotes and not about fees/verification
    if re.search(r"\b(?:currency\s+notes?|banknotes?|star\s+series)\b", evidence_text, re.IGNORECASE) and not re.search(
        r"\b(?:fee|charge|payment|verif\w*)\b", evidence_text, re.IGNORECASE
    ):
        return False, False

    denial_fee = bool(
        re.search(
            r"\b(?:does\s+not|never)\s+(?:ask|demand|require|charge)\b.{0,50}\b(?:fee|charge|payment|money)\b"
            r"|\bno\s+(?:fee|charge|payment)\b.{0,50}\b(?:is\s+required|for\s+verification|to\s+verify)\b"
            r"|\b(?:has|have|had)\s+not\s+(?:mandated|asked|demanded|authorized|authorised)\b.{0,50}\b(?:any\s+)?(?:fee|payment)\b",
            evidence_text,
            re.IGNORECASE,
        )
    )

    evidence_amounts = _rupee_amounts(evidence_text)
    fee_in_evidence = bool(claimed_amounts & evidence_amounts) or bool(
        re.search(r"\b(?:fee|charge|payment|money)\b.{0,40}\b(?:verification|verify|mandatory)\b", evidence_text, re.IGNORECASE)
    )
    fact_check_debunk = any(
        re.search(r"\b(?:fake(?:\s+news)?|false|fabricated|misleading|untrue|debunked|hoax|scam|fraud|fictitious)\b", sent, re.IGNORECASE)
        for sent in re.split(r"(?<=[.!?;])\s+", evidence_text)
    ) and (
        fee_in_evidence
        and re.search(r"\b(?:claim|message|post|rumou?r|notice|circular|news|alleg\w*)\w*\b", evidence_text, re.IGNORECASE)
    )

    if denial_fee or fact_check_debunk:
        return False, True

    if claimed_amounts and not claimed_amounts.issubset(evidence_amounts):
        return False, False
    if is_verification and not re.search(r"\b(?:verif\w*|mandatory)\b", evidence_text, re.IGNORECASE):
        return False, False
    if re.search(r"\b(?:mandat\w*|requir\w*|charg\w*|fee\s+of)\b", evidence_text, re.IGNORECASE):
        return True, False

    return False, False


def _baseline_verify_assertion(
    assertion: Assertion,
    evidence_items: list[EvidenceItem],
) -> AssertionVerification:
    """Apply deterministic term-overlap, signal-phrase, and entity-relation matching.

    Generic phrase or keyword overlap never establishes a decisive result.
    Specialized policy, relationship, date, location, and account-action
    handlers require a direct match to the assertion's subject and predicate.
    """
    assertion_tokens = _significant_tokens(assertion.text)
    if len(assertion_tokens) < _MIN_TOKENS_TO_COMPARE:
        return AssertionVerification(
            assertion_text=assertion.text,
            verdict=Verdict.UNVERIFIED,
            explanation="Assertion is too short to compare against evidence reliably.",
        )

    support_urls: list[str] = []
    contradict_urls: list[str] = []
    evidence_assessments: list[EvidenceAssessment] = []
    best_support_score = 0.0
    best_contradict_score = 0.0

    # Check if assertion is a relational statement: Subject is Role of Target
    rel = _extract_subject_role_target(assertion.text)
    dicgc_kind = _dicgc_assertion_kind(assertion.text)
    attribute_fact = _extract_attribute_fact(assertion.text)
    amount_attribute_fact = _extract_amount_attribute_fact(assertion.text)
    action = _action_fact(assertion.text)
    payment_demand = _payment_demand_fact(assertion.text)

    # Prioritize AUTHORITATIVE sources (e.g. regulatory/government portals)
    sorted_items = sorted(
        evidence_items,
        key=lambda item: 0 if item.source_quality == SourceQuality.AUTHORITATIVE else 1,
    )

    for item in sorted_items:
        combined = f"{item.title}. {item.excerpt}".lower()
        overlap = _token_overlap(assertion_tokens, combined)

        if dicgc_kind:
            if _is_reliable_source(item):
                supports, contradicts = _dicgc_evidence_relation(
                    assertion, combined, dicgc_kind
                )
                if supports:
                    support_urls.append(item.url)
                    best_support_score = max(best_support_score, overlap)
                if contradicts:
                    contradict_urls.append(item.url)
                    best_contradict_score = max(best_contradict_score, overlap)
            continue

        if attribute_fact:
            if _is_reliable_source(item):
                supports, contradicts = _attribute_evidence_relation(
                    attribute_fact, combined
                )
                if supports:
                    support_urls.append(item.url)
                if contradicts:
                    contradict_urls.append(item.url)
            continue

        if amount_attribute_fact:
            if _is_reliable_source(item):
                supports, contradicts = _amount_attribute_relation(
                    amount_attribute_fact, combined
                )
                if supports:
                    support_urls.append(item.url)
                if contradicts:
                    contradict_urls.append(item.url)
            continue

        if action:
            if _is_reliable_source(item):
                supports, contradicts = _action_evidence_relation(
                    assertion.text, action, combined, item=item
                )
                if supports:
                    support_urls.append(item.url)
                if contradicts:
                    contradict_urls.append(item.url)
            continue

        if payment_demand:
            if _is_reliable_source(item):
                supports, contradicts = _payment_demand_evidence_relation(
                    assertion.text, payment_demand, combined, item=item
                )
                if supports:
                    support_urls.append(item.url)
                if contradicts:
                    contradict_urls.append(item.url)
            continue

        # 1. Relational Entity Verification (e.g. "X is the central bank of Y")
        if rel:
            subj, role, target = rel
            if not _is_reliable_source(item):
                continue
            # Normalize target country references
            target_norm = "united states" if ("united states" in target or target in ("usa", "u.s.", "us")) else target
            target_norm = "india" if "india" in target else target_norm

            role_in_text = _role_matches_evidence(role, combined)
            target_in_text = _target_matches_evidence(target_norm, combined, item, role)

            # A. Check for alternative holder of the unique role in the target country
            # E.g. Claim asserts "RBI is central bank of United States", but evidence states
            # "The Federal Reserve, the central bank of the United States..."
            # Only flag contradiction when a well-known NAMED central bank distinct from subject is present.
            if role_in_text and target_in_text:
                _KNOWN_CB_RE = re.compile(
                    r"\b(federal\s+reserve(?:\s+system)?|bank\s+of\s+england|european\s+central\s+bank"
                    r"|bank\s+of\s+japan|people\'?s\s+bank\s+of\s+china|reserve\s+bank\s+of\s+australia"
                    r"|swiss\s+national\s+bank|bank\s+of\s+canada|bank\s+of\s+korea|bank\s+of\s+russia"
                    r"|reserve\s+bank\s+of\s+new\s+zealand)\b"
                )
                m_other = _KNOWN_CB_RE.search(combined)
                if m_other:
                    matched_holder = m_other.group(1).strip()
                    holder_clean = re.sub(r"\s+", " ", matched_holder).strip().lower()
                    subj_clean = re.sub(r"\s+", " ", subj).strip().lower()
                    if holder_clean not in subj_clean and subj_clean not in holder_clean:
                        # A distinct known central bank is named for the target country!
                        contradict_urls.append(item.url)
                        if overlap > best_contradict_score:
                            best_contradict_score = overlap
                        continue

            # B. Check for direct support: Subject MUST be affirmed as Role of Target
            # (e.g. "Reserve Bank of India ... is the central bank of India")
            if role_in_text and target_in_text:
                if _subject_matches_evidence(subj, item, combined):
                    denied_role = re.search(
                        r"\b(?:is|are|was|were)\s+(?:not|never)\s+(?:the\s+)?"
                        r"(?:central\s+bank|regulatory\s+body|monetary\s+authority|"
                        r"apex\s+bank|responsible\s+for\s+regulating)\b",
                        combined,
                    )
                    if denied_role:
                        contradict_urls.append(item.url)
                        if overlap > best_contradict_score:
                            best_contradict_score = overlap
                    else:
                        support_urls.append(item.url)
                        if overlap > best_support_score:
                            best_support_score = overlap
                    continue

            # If it was a relational claim, the relational checks above are authoritative.
            # Do NOT fall through to general keyword matching which might match tokens independently.
            continue

        # Unsupported assertion structures remain unresolved. Generic phrases
        # such as "confirms", "fact check", or "false" are never decisive.

    for item in sorted_items:
        if item.url in support_urls and item.url in contradict_urls:
            relevance = "relevant"
            relationship = "conflicting"
            explanation = "The source contains both supporting and contradicting signals."
        elif item.url in support_urls:
            relevance = "relevant"
            relationship = "supports"
            explanation = "The source supports this assertion."
        elif item.url in contradict_urls:
            relevance = "relevant"
            relationship = "contradicts"
            explanation = "The source contradicts this assertion."
        else:
            item_overlap = _token_overlap(assertion_tokens, f"{item.title} {item.excerpt}")
            relevance = "contextual" if item_overlap >= 0.2 else "irrelevant"
            relationship = "contextual" if relevance == "contextual" else "none"
            explanation = (
                "The source shares claim context but does not establish the assertion."
                if relevance == "contextual"
                else "The source does not provide meaningful evidence for this assertion."
            )
        evidence_assessments.append(
            EvidenceAssessment(
                evidence_url=item.url,
                assertion_text=assertion.text,
                relevance=relevance,
                relationship=relationship,
                explanation=explanation,
            )
        )

    if contradict_urls and support_urls:
        return AssertionVerification(
            assertion_text=assertion.text,
            verdict=Verdict.UNVERIFIED,
            supporting_urls=support_urls,
            contradicting_urls=contradict_urls,
            explanation=(
                "Reliable evidence materially conflicts about this assertion. "
                "The available sources do not support a defensible forced verdict."
            ),
            evidence_assessments=evidence_assessments,
        )
    if contradict_urls:
        return AssertionVerification(
            assertion_text=assertion.text,
            verdict=Verdict.FALSE,
            contradicting_urls=contradict_urls,
            explanation=(
                "Evidence directly contradicts this assertion with relevant debunking or conflicting authoritative facts."
            ),
            evidence_assessments=evidence_assessments,
        )
    if support_urls:
        return AssertionVerification(
            assertion_text=assertion.text,
            verdict=Verdict.TRUE,
            supporting_urls=support_urls,
            explanation=(
                "Evidence contains relevant authoritative support confirming this assertion."
            ),
            evidence_assessments=evidence_assessments,
        )

    return AssertionVerification(
        assertion_text=assertion.text,
        verdict=Verdict.UNVERIFIED,
        explanation=(
            "Available evidence does not provide sufficient direct overlap to verify or refute this assertion. "
            "Retrieved sources discuss related topics or general advisories without directly addressing this claim."
        ),
        evidence_assessments=evidence_assessments,
    )


# ---------------------------------------------------------------------------
# Aggregate verdict across assertions
# ---------------------------------------------------------------------------


def _aggregate_verdict(
    results: list[AssertionVerification],
    supporting: list[EvidenceItem],
    contradicting: list[EvidenceItem],
    unresolved: list[str],
) -> Tuple[Verdict, str]:
    if not results:
        return Verdict.UNVERIFIED, (
            "No assertions could be extracted and individually verified."
        )

    verdict_counts: dict[Verdict, int] = {v: 0 for v in Verdict}
    for r in results:
        verdict_counts[r.verdict] += 1

    total = len(results)
    n_true = verdict_counts[Verdict.TRUE]
    n_false = verdict_counts[Verdict.FALSE]
    n_partial = verdict_counts[Verdict.PARTIALLY_TRUE]
    n_unverified = verdict_counts[Verdict.UNVERIFIED]
    n_error = verdict_counts[Verdict.ERROR]

    if n_error == total:
        return Verdict.ERROR, "Verification could not complete due to provider errors."

    if n_unverified == total:
        if any("materially conflicts" in result.explanation for result in results):
            return Verdict.UNVERIFIED, (
                "Reliable evidence materially conflicts about one or more assertions. "
                "The available sources do not support a defensible forced verdict."
            )
        return Verdict.UNVERIFIED, (
            "Insufficient evidence to verify or refute any of the extracted assertions. "
            "Retrieved sources do not directly confirm or contradict the claim."
        )

    if n_unverified > 0:
        if any("materially conflicts" in result.explanation for result in results):
            return Verdict.UNVERIFIED, (
                "Reliable evidence materially conflicts or leaves a material assertion unresolved. "
                "The available sources do not support a defensible forced verdict."
            )
        return Verdict.UNVERIFIED, (
            f"{n_true} assertion(s) are supported and {n_false} are contradicted, but "
            f"{n_unverified} material assertion(s) remain unresolved. "
            "Insufficient direct evidence remains for a decisive overall verdict."
        )

    # Every material assertion must be directly contradicted to call the whole claim false.
    if n_false == total:
        return Verdict.FALSE, (
            f"Evidence directly contradicts {n_false} of {total} assertion(s). "
            "Reliable evidence establishes that all extracted material assertions are false."
        )

    # Every material assertion must be supported, without an unresolved contradiction.
    if n_true == total:
        return Verdict.TRUE, (
            f"Evidence supports {n_true} of {total} assertion(s). "
            "No contradicting evidence was found."
        )

    if n_true > 0 and n_false > 0:
        return Verdict.PARTIALLY_TRUE, (
            f"Evidence shows mixed findings: supports {n_true} assertion(s) "
            f"and contradicts {n_false} assertion(s). "
            "The claim contains a mix of supported and contradicted elements."
        )

    if n_partial > 0 and n_true + n_false + n_partial == total:
        return Verdict.PARTIALLY_TRUE, (
            f"Evidence supports {n_true} assertion(s) and partially supports {n_partial} assertion(s). "
            "The claim is not fully established."
        )

    return Verdict.UNVERIFIED, (
        f"Available evidence is inconclusive for the extracted assertions "
        f"({n_unverified} unverified and {n_partial} partially supported of {total}). "
        "Every material assertion must be established before the claim can be confirmed."
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_STOP_WORDS = frozenset(
    "a an the is are was were be been being have has had do does did will "
    "would could should may might must shall can of in on at to for with by "
    "from and or but not that this these those it its all any some such no "
    "if as so also just then than when where who which whom what how".split()
)


def _normalize_text(text: str) -> str:
    """Normalize text and currency symbols."""
    return re.sub(r"₹", "rs ", text.lower())


def _stem_token(token: str) -> str:
    """Apply lightweight stemming for common inflections."""
    t = token.lower()
    if t in ("paid", "payment", "payments", "pays"):
        return "pay"
    if t in ("blocked", "blocking", "blocks"):
        return "block"
    if t in ("accounts", "account"):
        return "account"
    if t in ("announced", "announcing", "announcement", "announces"):
        return "announc"
    if t in ("verification", "verified", "verifies", "verifying"):
        return "verifi"
    if t.endswith("ing") and len(t) > 5:
        return t[:-3]
    if t.endswith("ed") and len(t) > 4:
        return t[:-2]
    if t.endswith("es") and len(t) > 4:
        return t[:-2]
    if t.endswith("s") and len(t) > 3:
        return t[:-1]
    return t


def _significant_tokens(text: str) -> frozenset[str]:
    """Return lowercase stemmed non-stop-word tokens of length ≥ 3."""
    normalized = _normalize_text(text)
    raw_tokens = re.findall(r"[a-z0-9]+", normalized)
    return frozenset(_stem_token(t) for t in raw_tokens if t not in _STOP_WORDS and len(t) >= 3)


def _token_overlap(assertion_tokens: frozenset[str], evidence_text: str) -> float:
    """Return fraction of assertion tokens present in evidence_text."""
    if not assertion_tokens:
        return 0.0
    normalized = _normalize_text(evidence_text)
    evidence_tokens = frozenset(_stem_token(t) for t in re.findall(r"[a-z0-9]+", normalized))
    matches = assertion_tokens & evidence_tokens
    return len(matches) / len(assertion_tokens)


def _find_item_by_url(url: str, items: list[EvidenceItem]) -> EvidenceItem | None:
    for item in items:
        if item.url == url:
            return item
    return None


def _collect_limitations(evidence: EvidenceBundle) -> list[str]:
    limitations: list[str] = [
        "Factual verification uses deterministic proposition checks for supported fact patterns. "
        "Other claim structures remain UNVERIFIED; this is not a general semantic fact-checking model.",
    ]
    if evidence.provider_error:
        limitations.append(
            f"The search provider reported an error: {evidence.provider_error}. "
            "Evidence coverage may be incomplete."
        )
    failed = [e for e in evidence.items if not e.retrieval_success]
    if failed:
        limitations.append(
            f"{len(failed)} evidence item(s) could not be retrieved successfully and were excluded from verification."
        )
    snippet_count = sum(item.evidence_origin != "fetched_page" for item in evidence.items if item.retrieval_success)
    if snippet_count:
        limitations.append(
            f"{snippet_count} evidence item(s) use search-provider snippets because linked page text was unavailable or not fetched."
        )
    fetch_failures = sum(bool(item.page_fetch_error) for item in evidence.items)
    if fetch_failures:
        limitations.append(
            f"Page text could not be checked for {fetch_failures} candidate source(s); their search snippets were retained as weaker evidence."
        )
    if evidence.search_provider_used in ("none", "mock"):
        limitations.append(
            "No live search provider is configured. "
            "Evidence was not retrieved from the internet."
        )
    return limitations
