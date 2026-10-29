"""TruthLens AI - Claim Processing Module.

Accepts a raw financial text submission, validates it, normalises formatting,
and extracts individual factual assertions using deterministic rule-based patterns.

No LLM is used here. The extraction strategy is fully deterministic.
This is clearly documented and does not pretend to provide deep semantic NLP.

Limitations (documented, not hidden):
- Cannot reliably parse complex compound sentences beyond the defined patterns.
- Assertion classification relies on keyword matching; it may miss novel phrasings.
- Non-English and mixed-script text is accepted but keyword rules may not fire.
- Extraction quality degrades for very long or highly informal text.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

try:
    from backend.core.models import Assertion, ExtractedClaim
    from backend.config import get_settings
except ModuleNotFoundError:
    from core.models import Assertion, ExtractedClaim  # type: ignore
    from config import get_settings  # type: ignore


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_INPUT_LENGTH: int = 5_000   # characters
MIN_MEANINGFUL_LENGTH: int = 10  # characters after normalisation


# Assertion-type classification rules.
# Ordered from most specific to most general — first match wins.
_ASSERTION_RULES: list[tuple[str, list[str]]] = [
    (
        "regulatory",
        [
            r"\b(?:rbi|sebi|npci|irdai|pfrda|ministry of finance|government of india|"
            r"finance minister|income tax|gst|fema)\b",
        ],
    ),
    (
        "announcement",
        [
            r"\b(?:announc(?:ed?|ing|ement)|notif(?:ied?|ication)|declared?|"
            r"issued?|circular|press release|gazette)\b",
        ],
    ),
    (
        "account_action",
        [
            r"\b(?:block(?:ed?|ing)|freez(?:ed?|ing)|suspend(?:ed?|ing)|"
            r"clos(?:ed?|ing)|deactivat(?:ed?|ing)|disabl(?:ed?|ing))\b",
            r"\b(?:bank account|savings account|current account|demat account)\b",
        ],
    ),
    (
        "payment_demand",
        [
            r"(?:₹|rs\.?|inr)\s*[\d,]+",
            r"\b(?:pay(?:ment)?|fee|charge|fine|penalty|deposit|transfer)\b",
            r"\b(?:upi|neft|rtgs|imps)\b",
        ],
    ),
    (
        "credential_request",
        [
            r"\b(?:otp|pin|password|cvv|card\s+number|aadhaar|pan\s+(?:number|card)|"
            r"net\s+banking|login\s+credentials?)\b",
        ],
    ),
    (
        "deadline",
        [
            r"\b(?:tonight|today|tomorrow|immediately|within\s+\d+\s+(?:hours?|minutes?|days?))\b",
            r"\b(?:by\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)|deadline|last\s+date|expire?s?)\b",
        ],
    ),
    (
        "threat",
        [
            r"\b(?:unless|otherwise|or\s+else|will\s+be\s+(?:blocked|frozen|suspended|penalised?))\b",
            r"\b(?:legal\s+action|arrest|police|court|fir)\b",
        ],
    ),
]

# Named-entity capture patterns (for annotation, not classification).
_ENTITY_PATTERNS: list[tuple[str, str]] = [
    ("ORG", r"\b(?:rbi|sebi|npci|irdai|sbi|hdfc|icici|axis|kotak|pnb|bob|nse|bse)\b"),
    ("CURRENCY", r"(?:₹|rs\.?|inr)\s*[\d,]+(?:\s*(?:lakh|crore|thousand|hundred))?"),
    ("DEADLINE", r"\b(?:tonight|today|tomorrow|immediately|within\s+\d+\s+(?:hours?|days?))\b"),
    ("PHONE", r"\b(?:\+91[-\s]?)?\d{10}\b"),
    ("URL_LIKE", r"https?://\S+|www\.\S+"),
]

_ABBREVIATIONS = frozenset({"e.g.", "i.e.", "mr.", "mrs.", "ms.", "dr.", "prof.", "vs.", "etc.", "rs."})

_EXPLICIT_CLAUSE_RE = re.compile(
    r"^(?:(?:all|the|a|an|each|these|those|every)\s+)?"
    r"[A-Za-z][A-Za-z0-9'’-]*(?:\s+[A-Za-z][A-Za-z0-9'’-]*){0,4}\s+"
    r"(?:\([^)]{1,30}\)\s*)?"
    r"(?:is|are|was|were|has|have|had|will|would|must|can|could|should|"
    r"announced|issued|insures?|covers?|includes?|requires?|states?|"
    r"commenced|began|started|headquartered|located)\b",
    re.IGNORECASE,
)

_DICGC_COMPOUND_COVERAGE_RE = re.compile(
    r"^(?P<subject_predicate>.*?\b(?:bank\s+)?deposits?\s+are\s+insured)"
    r"(?P<limit_clause>.*?\bper\s+depositor)\s+across\s+"
    r"(?P<categories>[^.!?।]+?\bbanks?)\s*[.!?।]?$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class ClaimProcessingError(ValueError):
    """Raised when the submitted claim cannot be processed."""


def process_claim(raw_text: str) -> ExtractedClaim:
    """Validate, normalise, and extract structured assertions from raw text.

    Args:
        raw_text: The user-submitted financial claim or message.

    Returns:
        ExtractedClaim containing the original text, normalised form,
        and extracted assertions.

    Raises:
        ClaimProcessingError: For empty, whitespace-only, or excessively long input.
    """
    _validate_input(raw_text)
    normalised = _normalise(raw_text)
    assertions = _extract_assertions(normalised)
    return ExtractedClaim(
        original_text=raw_text,
        normalised_text=normalised,
        assertions=assertions,
        language_hint=_detect_language_hint(normalised),
        word_count=len(normalised.split()),
        char_count=len(normalised),
    )


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


def _validate_input(text: str) -> None:
    """Raise ClaimProcessingError for invalid inputs."""
    if not isinstance(text, str):
        raise ClaimProcessingError("Input must be a string.")

    if not text or not text.strip():
        raise ClaimProcessingError(
            "Input is empty or contains only whitespace. "
            "Please provide a financial claim or message to analyse."
        )

    stripped = text.strip()
    if len(stripped) < MIN_MEANINGFUL_LENGTH:
        raise ClaimProcessingError(
            f"Input is too short (minimum {MIN_MEANINGFUL_LENGTH} characters). "
            "Please provide a more complete claim."
        )

    if len(stripped) > MAX_INPUT_LENGTH:
        raise ClaimProcessingError(
            f"Input exceeds the maximum allowed length of {MAX_INPUT_LENGTH} characters "
            f"(submitted: {len(stripped)} characters). "
            "Please shorten the text or submit individual claims separately."
        )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Apply whitespace and Unicode normalisation without altering meaning."""
    # Normalise Unicode to NFC (canonical composition)
    text = unicodedata.normalize("NFC", text)
    # Collapse internal whitespace (tabs, multiple spaces) to single space
    text = re.sub(r"[ \t]+", " ", text)
    # Normalise line endings
    text = re.sub(r"\r\n|\r", "\n", text)
    # Remove leading/trailing whitespace from each line and the whole string
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = text.strip()
    return text


# ---------------------------------------------------------------------------
# Assertion extraction
# ---------------------------------------------------------------------------


def _split_into_sentences(text: str) -> list[str]:
    """Split normalised text into candidate sentence units."""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    sentences: list[str] = []
    for line in lines:
        start = 0
        for match in re.finditer(r"[.!?।]+(?=\s|$)", line):
            punctuation_end = match.end()
            if line[match.start()] == ".":
                before = line[:punctuation_end].rstrip().lower()
                if any(before.endswith(abbreviation) for abbreviation in _ABBREVIATIONS):
                    continue
                if (
                    match.start() > 0
                    and match.end() < len(line)
                    and line[match.start() - 1].isdigit()
                    and line[match.end()].isdigit()
                ):
                    continue
            candidate = line[start:punctuation_end].strip()
            if candidate:
                sentences.append(candidate)
            start = match.end()
        remainder = line[start:].strip()
        if remainder:
            sentences.append(remainder)
    return sentences


def _split_compound_assertions(sentence: str) -> list[str]:
    """Split only coordinated clauses that each retain an explicit predicate."""
    fragments = re.split(
        r"\s+(?:also|additionally|furthermore|moreover)\s+",
        sentence,
        flags=re.IGNORECASE,
    )
    if len(fragments) > 1 and not all(
        _EXPLICIT_CLAUSE_RE.match(fragment.strip()) for fragment in fragments
    ):
        fragments = [sentence]
    if len(fragments) == 1:
        coordinated = re.split(r"\s+and\s+", sentence, flags=re.IGNORECASE)
        if len(coordinated) > 1 and all(_EXPLICIT_CLAUSE_RE.match(part.strip()) for part in coordinated):
            fragments = coordinated
        elif len(coordinated) == 2 and _EXPLICIT_CLAUSE_RE.match(coordinated[0].strip()):
            first_clause = coordinated[0].strip()
            second_clause = coordinated[1].strip()
            subject_match = re.match(
                r"^(?P<subject>.+?)\s+(?:is|are|was|were|has|have|had)\b",
                first_clause,
                re.IGNORECASE,
            )
            subject_match = re.match(
                r"^(?P<subject>.+?)\s+(?:commenced|began|started)\s+",
                first_clause,
                re.IGNORECASE,
            ) or subject_match
            if subject_match and re.match(
                r"^(?:is|are|was|were)\s+(?:not\s+)?(?:headquartered|located)\b",
                second_clause,
                re.IGNORECASE,
            ):
                fragments = [
                    first_clause,
                    f"{subject_match.group('subject')} {second_clause}",
                ]
            elif subject_match and re.match(
                r"^(?:is|are|was|were)\s+(?:not\s+)?"
                r"(?:responsible|accountable|the\s+primary|the\s+sole)\b",
                second_clause,
                re.IGNORECASE,
            ):
                fragments = [
                    first_clause,
                    f"{subject_match.group('subject')} {second_clause}",
                ]
    return [fragment.strip() for fragment in fragments if len(fragment.strip()) > 4]


def _expand_dicgc_coverage(sentence: str) -> list[str] | None:
    """Separate a coordinated bank list into complete DICGC coverage assertions."""
    if not re.search(r"\bdicgc\b", sentence, re.IGNORECASE):
        return None
    match = _DICGC_COMPOUND_COVERAGE_RE.match(sentence.strip())
    if not match:
        return None

    categories = re.split(r"\s*(?:,|and)\s*", match.group("categories").strip(), flags=re.IGNORECASE)
    categories = [category.strip() for category in categories if category.strip()]
    if not categories:
        return None

    normalized_categories: list[str] = []
    for category in categories:
        if not re.search(r"\bbanks?\b", category, re.IGNORECASE):
            category = f"{category} banks"
        normalized_categories.append(category)

    subject_predicate = match.group("subject_predicate").strip()
    limit_clause = match.group("limit_clause").strip()
    limit_assertion = f"{subject_predicate} {limit_clause}."
    category_assertions = [
        f"{subject_predicate} across {category}."
        for category in normalized_categories
    ]
    return [limit_assertion, *category_assertions]


def _expand_compound_allegation(sentence: str) -> list[tuple[str, str]] | None:
    """Decompose compound regulatory announcements and threats into typed assertions.

    Extracts:
    1. Alleged announcement / notice
    2. Account-blocking action
    3. Deadline
    4. Payment demand / condition
    """
    text = sentence.strip().rstrip(".!?।")
    account_action_match = re.search(
        r"\b(?:(?:all|the|any)\s+)?(?:bank\s+)?accounts?\s+(?:will\s+be\s+|are\s+being\s+|to\s+be\s+)"
        r"(?:blocked|frozen|suspended|closed|deactivated)\b",
        text,
        re.IGNORECASE,
    )
    if not account_action_match:
        account_action_match = re.search(
            r"\b(?:block(?:ed|ing)?|freeze|freezing|suspend(?:ed|ing)?)\s+(?:all\s+)?(?:bank\s+)?accounts?\b",
            text,
            re.IGNORECASE,
        )
    if not account_action_match:
        return None

    announcement_match = re.match(
        r"^(?P<subject>[A-Za-z0-9\s\(\)]+?)\s+(?:has\s+|have\s+)?(?:announced|declared|notified|warned|issued\s+(?:a\s+)?(?:circular|notice|order|directive))\s+(?:that\s+)?(?P<body_clause>.+)$",
        text,
        re.IGNORECASE,
    )
    unless_match = re.search(r"\s+\b(?:unless|or\s+else|otherwise)\b\s+", text, re.IGNORECASE)
    deadline_match = re.search(
        r"\b(tonight|today|tomorrow|immediately|by\s+midnight|within\s+\d+\s+(?:hours?|days?))\b",
        text,
        re.IGNORECASE,
    )

    if not announcement_match and not unless_match:
        return None

    assertions: list[tuple[str, str]] = []
    if announcement_match:
        subject = announcement_match.group("subject").strip()
        body = announcement_match.group("body_clause").strip()
    else:
        subject = ""
        body = text

    if unless_match:
        parts = re.split(r"\s+\b(?:unless|or\s+else|otherwise)\b\s+", body, flags=re.IGNORECASE, maxsplit=1)
        action_clause = parts[0].strip()
        condition_clause = parts[1].strip() if len(parts) > 1 else ""
    else:
        action_clause = body
        condition_clause = ""

    detected_deadline = ""
    base_action = action_clause
    if deadline_match and deadline_match.group(1).lower() in action_clause.lower():
        detected_deadline = deadline_match.group(1).strip()
        base_action = re.sub(r"\b" + re.escape(detected_deadline) + r"\b", "", action_clause, flags=re.IGNORECASE)
        base_action = " ".join(base_action.split()).strip()

    base_action_text = base_action[0].upper() + base_action[1:] if base_action else action_clause

    if subject:
        ann_type = "regulatory" if re.search(r"\b(?:rbi|sebi|npci|irdai|pfrda)\b", subject, re.IGNORECASE) else "announcement"
        assertions.append(
            (f"{subject} has announced that {base_action.lower() if base_action else action_clause.lower()}.", ann_type)
        )
    assertions.append((f"{base_action_text.rstrip('.')}.", "account_action"))
    if detected_deadline:
        assertions.append((f"{base_action_text.rstrip('.')} {detected_deadline.lower()}.", "deadline"))

    if condition_clause:
        cond = condition_clause.rstrip(".!?")
        payment_match = re.search(r"(?:₹|rs\.?|inr)\s*[\d,]+|\b(?:pay|payment|fee|charge)\b", cond, re.IGNORECASE)
        if payment_match:
            if re.match(r"^(?:customers?|users?|account\s+holders?|people|citizens?)\b", cond, re.IGNORECASE):
                sub_cond = re.sub(
                    r"^(customers?|users?|account\s+holders?|people|citizens?)\s+(?:must\s+|have\s+to\s+|pay\b)",
                    r"\1 must pay ",
                    cond,
                    flags=re.IGNORECASE,
                )
                sub_cond = re.sub(r"\s+", " ", sub_cond).strip()
                assertions.append((f"{sub_cond[0].upper() + sub_cond[1:]}.", "payment_demand"))
            elif re.search(r"\b(?:is\s+paid|be\s+paid)\b", cond, re.IGNORECASE):
                amounts = re.findall(r"(?:₹|rs\.?|inr)\s*[\d,]+", cond, re.IGNORECASE)
                amt_str = amounts[0] if amounts else "the fee"
                assertions.append((f"Customers must pay {amt_str}.", "payment_demand"))
            else:
                assertions.append((f"Customers must {cond.lower()}.", "payment_demand"))
        else:
            assertions.append((f"{cond[0].upper() + cond[1:]}.", "general"))

    return assertions


def _classify_assertion(text_lower: str) -> str:
    """Return the most specific assertion type matching the text."""
    for assertion_type, patterns in _ASSERTION_RULES:
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return assertion_type
    return "general"


def _extract_entities(text: str) -> list[str]:
    """Return a deduplicated list of named-entity strings found in text."""
    found: list[str] = []
    for label, pattern in _ENTITY_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            tag = f"{label}:{m.group(0).strip()}"
            if tag not in found:
                found.append(tag)
    return found


def _extract_assertions(normalised_text: str) -> list[Assertion]:
    """Decompose normalised text into a list of typed assertions."""
    sentences = _split_into_sentences(normalised_text)
    seen: set[str] = set()
    assertions: list[Assertion] = []

    for sentence in sentences:
        dicgc_assertions = _expand_dicgc_coverage(sentence)
        compound_allegations = _expand_compound_allegation(sentence)

        if dicgc_assertions:
            typed_fragments: list[tuple[str, str | None]] = [(f, None) for f in dicgc_assertions]
        elif compound_allegations:
            typed_fragments = [(t, kind) for t, kind in compound_allegations]
        else:
            fragments = _split_compound_assertions(sentence)
            if not fragments:
                fragments = [sentence]
            typed_fragments = [(f, None) for f in fragments]

        # If splitting created fragments that start with a verb without subject (e.g. "is responsible for..."),
        # extract the primary subject from the first fragment so the fragment is self-contained.
        primary_subject = ""
        m_subj = re.match(
            r"^(?:The\s+)?([A-Za-z0-9\s\(\)]+?)\s+(?:is|was|are|were|has|have|will|announced|commenced|began|started)\b",
            typed_fragments[0][0],
            re.IGNORECASE,
        )
        if m_subj:
            primary_subject = m_subj.group(1).strip()

        for idx, (fragment, explicit_type) in enumerate(typed_fragments):
            cleaned_frag = fragment.strip()
            # If a subsequent fragment starts with a predicate verb and lacks a subject, prepend the subject
            if idx > 0 and primary_subject and re.match(r"^(?:is|are|was|were|has|have|will|can)\b", cleaned_frag, re.IGNORECASE):
                cleaned_frag = f"{primary_subject} {cleaned_frag}"

            key = cleaned_frag.lower().strip()
            if key in seen or len(key) < 4:
                continue
            seen.add(key)

            assertion_type = explicit_type or _classify_assertion(key)
            entities = _extract_entities(cleaned_frag)

            assertions.append(
                Assertion(
                    text=cleaned_frag,
                    assertion_type=assertion_type,
                    entities=entities,
                )
            )

    return assertions


# ---------------------------------------------------------------------------
# Language hint
# ---------------------------------------------------------------------------

# Simple heuristic: if Devanagari characters are present, suggest Hindi
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _detect_language_hint(text: str) -> str:
    """Return a rough language hint based on script detection."""
    if _DEVANAGARI_RE.search(text):
        return "hi"
    return "en"
