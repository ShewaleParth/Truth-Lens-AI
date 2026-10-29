"""TruthLens AI - Scam Detector.

Independently assesses scam-risk indicators in a financial message using
deterministic, rule-based scoring.  This module is entirely separate from
factual verification (verdict_engine.py) and must never be used as a
substitute for it.

How the score is computed
--------------------------
Each pattern family has an assigned weight (0–40).  The raw score is the
sum of all triggered weights, clamped to 100.  The category thresholds are:
  LOW    → 0–29
  MEDIUM → 30–59
  HIGH   → 60–100

Documented limitations
----------------------
- Keyword rules may produce false positives for legitimate urgency (e.g.
  a real bank deadline notice that uses the word "tonight").
- Absence of detected indicators does NOT mean a message is safe.
- Score is not a probability and should not be presented as one.
- Non-English text may not trigger rules that rely on English keywords.
- The score is advisory; it does not constitute legal or regulatory advice.
"""

from __future__ import annotations

import re
from typing import List

try:
    from backend.core.models import ScamAssessment, ScamIndicator, RiskCategory
except ModuleNotFoundError:
    from core.models import ScamAssessment, ScamIndicator, RiskCategory  # type: ignore


# ---------------------------------------------------------------------------
# Rule definitions
# ---------------------------------------------------------------------------
# Each rule: (indicator_type, weight, patterns, explanation_template)
# The patterns list uses OR semantics — any match fires the rule.
# A rule fires at most once per message regardless of how many patterns match.

_RULES: list[tuple[str, int, list[str], str]] = [
    (
        "payment_demand",
        35,
        [
            r"\b(?:deposit\s+(?:an?\s+amount\s+of\s+)?(?:₹|rs\.?|inr|\d+)|pay(?:ment)?|transfer|send|remit)\b.{0,50}(?:₹|rs\.?|inr|\d{2,})",
            r"(?:₹|rs\.?|inr)\s*[\d,]+\b.{0,50}\b(?:fee|charge|fine|penalty|payment|transfer|remittance|cost|verification)\b",
            # Verification by itself is not a payment demand. Requiring a
            # monetary term prevents legitimate KYC wording from adding a
            # payment indicator when no money is requested.
            r"\b(?:mandatory|compulsory|required)\b.{0,30}\b(?:fee|charge|payment|transfer)\b",
        ],
        "The message contains a demand for payment, which is a strong scam indicator "
        "when combined with urgency or threats.",
    ),
    (
        "urgent_threat",
        30,
        [
            r"\b(?:tonight|immediately|right\s+now|urgent(?:ly)?|asap)\b",
            r"\b(?:account\s+(?:will\s+be|be)\s+(?:blocked|frozen|suspended|closed|deactivated))\b",
            r"\b(?:within\s+\d+\s+(?:hours?|minutes?)|last\s+chance|final\s+notice)\b",
            r"\b(?:or\s+else|otherwise|unless\s+you|failure\s+to)\b",
        ],
        "The message uses artificial urgency or threats designed to pressure the "
        "recipient into acting without verification.",
    ),
    (
        "credential_request",
        40,
        [
            r"\b(?:otp|one\s+time\s+password)\b",
            r"\b(?:pin|password|passcode)\b",
            r"\b(?:cvv|card\s+(?:number|details|expiry))\b",
            r"\b(?:net\s*banking\s+(?:login|credentials?|id|password))\b",
            r"\b(?:aadhaar\s+(?:number|otp)|pan\s+(?:number|card\s+(?:number|details)))\b",
            r"\buser\s*(?:id|name)\s+(?:and\s+)?password\b",
        ],
        "The message requests sensitive credentials (OTP, PIN, password, card details, "
        "Aadhaar, PAN). Legitimate organisations never request these unsolicited.",
    ),
    (
        "suspicious_link",
        25,
        [
            r"https?://(?!(?:www\.)?(?:rbi\.org\.in|sebi\.gov\.in|npci\.org\.in|"
            r"sbi\.co\.in|hdfcbank\.com|icicibank\.com|axisbank\.com|"
            r"incometax\.gov\.in|india\.gov\.in|mygov\.in|mospi\.gov\.in))"
            r"[^\s]{10,}",
            r"\bbit\.ly/\S+|\btinyurl\.com/\S+|\bgoo\.gl/\S+",
            r"\bclick\s+(?:here|below|link|now)\b",
            r"www\.[a-z0-9-]{2,30}(?:\.xyz|\.top|\.club|\.online|\.site|\.info)\b",
        ],
        "The message contains a link that does not point to a known authoritative "
        "domain, or uses a URL shortener. Such links frequently lead to phishing pages.",
    ),
    (
        "impersonation",
        30,
        [
            r"\b(?:this|the)\s+message\s+is\s+from\s+(?:the\s+)?"
            r"(?:rbi|reserve\s+bank\s+of\s+india|sebi|securities\s+and\s+exchange\s+board|"
            r"npci|national\s+payments\s+corporation|income\s+tax\s+(?:department|authority)|"
            r"it\s+department|ministry\s+of\s+finance|government\s+of\s+india)\b",
            r"\b(?:we\s+are|we\s+represent|on\s+behalf\s+of|speaking\s+for)\s+(?:the\s+)?"
            r"(?:rbi|reserve\s+bank\s+of\s+india|sebi|securities\s+and\s+exchange\s+board|"
            r"npci|national\s+payments\s+corporation|income\s+tax\s+(?:department|authority)|"
            r"it\s+department|ministry\s+of\s+finance|government\s+of\s+india)\b",
            r"\b(?:official|verified)\s+(?:rbi|sebi|npci|income\s+tax|government\s+of\s+india)"
            r"\s+(?:message|notice|call|account)\b",
            r"\b(?:sbi|hdfc|icici|axis|kotak|pnb|bank\s+of\s+baroda)\b.{0,30}"
            r"\b(?:official|authorised|verified|head\s+office)\b",
        ],
        "The message explicitly claims to represent a regulatory body, government "
        "institution, or bank. A factual mention of an institution alone is not an indicator.",
    ),
    (
        "app_install",
        30,
        [
            r"\b(?:download|install|click\s+to\s+install)\b.{0,40}\b(?:app|application|apk)\b",
            r"\bteam\s*viewer\b|\bany\s*desk\b|\bquick\s*support\b",
            r"\bscreen\s+share\b|\bremote\s+access\b",
        ],
        "The message asks the recipient to install an application or grant remote "
        "access. This is a common vector for fraudulent fund transfers.",
    ),
    (
        "transfer_request",
        35,
        [
            r"\b(?:transfer|send|deposit|credit)\b.{0,50}\b(?:account|upi|wallet|neft|rtgs|imps)\b",
            r"\b(?:beneficiary|recipient)\s+account\b",
            r"\b(?:scan\s+(?:and\s+)?pay|pay\s+using\s+upi)\b",
        ],
        "The message instructs the recipient to transfer funds to a specific account "
        "or UPI address, which is a hallmark of financial scams.",
    ),
    (
        "pressure_tactic",
        20,
        [
            r"\b(?:do\s+not\s+(?:ignore|delay|miss)|act\s+(?:now|fast|immediately))\b",
            r"\b(?:limited\s+time|offer\s+expires?|only\s+\d+\s+(?:spots?|seats?|slots?))\b",
            r"\b(?:you\s+have\s+been\s+selected|you\s+are\s+(?:lucky|chosen|eligible))\b",
        ],
        "The message uses pressure or scarcity tactics to manipulate the recipient "
        "into acting quickly without independent verification.",
    ),
    (
        "guaranteed_return",
        25,
        [
            r"\b(?:guaranteed|assured|risk.?free)\b.{0,30}\b(?:return|profit|income|earning)\b",
            r"\b(?:\d{2,3}\s*%\s*(?:per\s+(?:month|annum|year)|p\.?a\.?))\b",
            r"\b(?:double|triple)\b.{0,20}\b(?:money|investment|amount|fund)\b",
        ],
        "The message promises guaranteed or unusually high financial returns, which is "
        "a common feature of investment scams.",
    ),
]

# ---------------------------------------------------------------------------
# Category thresholds
# ---------------------------------------------------------------------------
MEDIUM_RISK_THRESHOLD = 30
HIGH_RISK_THRESHOLD = 60


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assess_scam_risk(text: str) -> ScamAssessment:
    """Evaluate the submitted text for scam-risk indicators.

    Args:
        text: Normalised (or raw) text to assess.

    Returns:
        ScamAssessment with score, category, detected indicators, and disclaimer.

    This function is independent of factual verification and must not be
    used to determine factual truth or falsehood of claims.
    """
    indicators: list[ScamIndicator] = []
    raw_score = 0

    for indicator_type, weight, patterns, explanation in _RULES:
        matched_fragment = _first_match(text, patterns)
        if matched_fragment:
            indicators.append(
                ScamIndicator(
                    indicator_type=indicator_type,
                    matched_text=matched_fragment[:200],  # truncate for safety
                    explanation=explanation,
                    weight=weight,
                )
            )
            raw_score += weight

    final_score = min(raw_score, 100)
    category = _score_to_category(final_score)
    explanation = _build_explanation(final_score, category, indicators)

    return ScamAssessment(
        score=final_score,
        category=category,
        medium_threshold=MEDIUM_RISK_THRESHOLD,
        high_threshold=HIGH_RISK_THRESHOLD,
        indicators=indicators,
        explanation=explanation,
        disclaimer=(
            "This risk score is generated by deterministic pattern-matching rules. "
            "It is advisory only and does not constitute legal or financial advice, "
            "or a definitive determination that this message is or is not a scam. "
            "Absence of detected indicators does not guarantee the message is safe."
        ),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _first_match(text: str, patterns: list[str]) -> str | None:
    """Return the first matched string from the text for any pattern, or None."""
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def _score_to_category(score: int) -> RiskCategory:
    if score >= HIGH_RISK_THRESHOLD:
        return RiskCategory.HIGH
    if score >= MEDIUM_RISK_THRESHOLD:
        return RiskCategory.MEDIUM
    return RiskCategory.LOW


def _build_explanation(
    score: int, category: RiskCategory, indicators: list[ScamIndicator]
) -> str:
    if not indicators:
        return (
            f"No scam indicators were detected by the rule-based assessment "
            f"(score: {score}/100, category: {category.value}). "
            "This does not guarantee the message is safe; novel tactics may not "
            "be captured by current rules."
        )

    indicator_names = ", ".join(i.indicator_type.replace("_", " ") for i in indicators)
    return (
        f"Scam-risk score: {score}/100 — category {category.value}. "
        f"Detected indicator(s): {indicator_names}. "
        "Each detected pattern independently contributes to the score. "
        "Review the 'indicators' list for detailed explanations."
    )
