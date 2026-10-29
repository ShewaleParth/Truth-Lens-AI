# TruthLens AI — Project Scope and Boundaries

## 1. Project Overview
TruthLens AI is an AI-powered financial misinformation and scam intelligence platform engineered to evaluate suspicious financial announcements, regulatory claims, banking alerts, payment requests, and potential financial fraud.

---

## 2. Target Users
1. **Retail Banking and Digital Payment Consumers:** Everyday citizens who receive alarming, confusing, or urgent messages regarding bank account freezes, KYC deadlines, or payment demands.
2. **Elderly and Digitally Vulnerable Populations:** Individuals disproportionately targeted by social engineering, panic-inducing threats, and phishing scams.
3. **Fact-Checkers and Financial Journalists:** Professionals investigating viral rumors, doctored government circulars, and syndicated misinformation campaigns.
4. **Fraud Risk and Compliance Teams:** Financial institutions and consumer advocacy groups monitoring emergent scam narratives and deceptive patterns.

---

## 3. Supported Initial Use Cases
The platform focuses on high-impact financial misinformation vectors:

- **Purported Central Bank and Regulatory Directives:** Claims attributing sweeping decrees, account freezes, currency demonetization, or new levies to institutions such as the Reserve Bank of India (RBI), Securities and Exchange Board of India (SEBI), or Ministry of Finance.
- **Urgent Account Blocking and KYC Threats:** Deceptive messages claiming bank accounts, debit cards, or net banking access will be permanently suspended unless immediate action or fee payment is completed.
- **Mandatory Verification and Fee Demands:** Communications soliciting upfront fees, security deposits, or verification charges under the guise of official regulatory compliance.
- **Fraudulent Subsidies, Grants, and Loan Waivers:** Viral messages announcing unverified government relief schemes, instant low-interest loans, or lottery winnings requiring registration fees.
- **Deceptive Payment Links and Phishing Vectors:** SMS, WhatsApp, and email messages featuring suspicious short links or spoofed banking portals.

---

## 4. Intended Verdict Categories
Every evaluated claim will be mapped to an explicit, evidence-backed verdict:

| Verdict Category | Definition | Evidence Requirement |
| :--- | :--- | :--- |
| **`TRUE`** | The claim accurately reflects reality and official policy. | Directly corroborated by authoritative, primary regulatory or banking sources. |
| **`FALSE`** | The claim is demonstrably false, fabricated, or previously debunked. | Directly contradicted by official records or confirmed non-existent by regulators. |
| **`PARTIALLY_TRUE`** | Contains an authentic core but incorporates inaccurate details (e.g., incorrect dates, fees, or penalties). | Authoritative source validates the base event but refutes secondary attributes. |
| **`MISLEADING`** | Technically accurate fragments presented out of context to convey a false or alarming impression. | Contextual analysis demonstrates deliberate omission or distortion. |
| **`UNVERIFIED`** | Available evidence is insufficient to confirm or disprove the claim. | Default verdict whenever credible sources yield no corroboration or contradiction. |

> **Critical Rule:** The system must never hallucinate evidence, cite nonexistent sources, or declare a claim true or false based purely on LLM parametric confidence. When evidence is inadequate, the verdict must strictly remain **`UNVERIFIED`**.

---

## 5. Factual Verification vs. Scam-Risk Assessment
TruthLens AI enforces a strict architectural separation between **Factual Accuracy** and **Scam-Risk Assessment**:

```
                       Input Message / Claim
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
       Factual Verification             Scam-Risk Assessment
  (Is the claim historically /       (Does the message exhibit
   regulatorily accurate?)            fraudulent mechanics?)
                 │                               │
                 ▼                               ▼
   Evidence from Official Sources    Behavioral Heuristics & Signals:
   - Primary regulatory portals       - Artificial panic / deadlines
   - Gazette notifications            - Unofficial payment gateways
   - Official press releases          - Impersonation patterns
                 │                               │
                 ▼                               ▼
     Verdict: TRUE / FALSE /           Risk Level: LOW / MEDIUM /
       PARTIALLY_TRUE / UNVERIFIED       HIGH / CRITICAL
```

### Why Separation is Mandatory:
- **Scenario A:** A scammer sends an authentic RBI notification excerpt, but attaches an unofficial payment link for "processing."
  - *Factual Verification:* PARTIALLY TRUE (the circular excerpt is real).
  - *Scam-Risk Assessment:* CRITICAL (the payment destination is fraudulent).
- **Scenario B:** A user misremembers a bank holiday date with no deceptive intent.
  - *Factual Verification:* FALSE (banks are open that day).
  - *Scam-Risk Assessment:* LOW (no phishing links, credentials harvesting, or financial harm indicators).

Conflating these two dimensions leads to dangerous false negatives where users fall victim to hybrid scams.

---

## 6. Explicit Limitations and Out-of-Scope Features
To maintain reliability, legal compliance, and domain focus, the following areas are strictly out of scope:

1. **No Financial or Investment Advice:** TruthLens AI does not evaluate stock picks, recommend financial products, or offer personalized investment guidance.
2. **No Banking Transaction Services:** The platform does not reverse transactions, unfreeze accounts, or act as an intermediary for customer dispute resolution.
3. **No Law Enforcement Operations:** The platform does not trace IP addresses, arrest fraudsters, or recover stolen funds.
4. **No Zero-Evidence Private Disputes:** The system cannot arbitrate private peer-to-peer transaction disputes where no public or regulatory trail exists.
5. **No Multimodal Ingestion in Phase 1:** Voice recording analysis, deepfake video verification, and image OCR are slated for future phases; Phase 1 targets backend foundation and text claims.
6. **No Guaranteed Real-Time Zero-Day Coverage:** Novel scams executed before any public or regulatory reporting will be responsibly classified as `UNVERIFIED` until verified evidence surfaces.
