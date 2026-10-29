# TruthLens AI

> **Financial Misinformation & Scam Intelligence Platform for Indian Communications**
>
> Automated AI-assisted intelligence system that evaluates forwarded financial claims, viral messages, and suspicious communications against authoritative regulatory records while independently scoring behavioral scam risk.

---

## 1. Project Overview & Problem Statement

Financial fraud, viral WhatsApp misinformation, and phishing scams targeting Indian citizens have reached epidemic proportions. Scammers systematically exploit:
- **Artificial Urgency & Fear**: "All bank accounts blocked tonight unless verified."
- **Institutional Impersonation**: Citing the Reserve Bank of India (RBI), SEBI, NPCI, or Income Tax Department to demand immediate compliance.
- **Deceptive Financial Promises**: Fraudulent investment schemes promising guaranteed daily/monthly doubling.
- **Malicious Links & Coercive Demands**: Phishing portals, APK downloads (fake SBI/YONO apps), and unverified UPI handles.

**TruthLens AI** counters this by introducing a dual-engine analysis architecture that:
1. Decomposes complex forwarded messages into testable factual assertions.
2. Retrieves external evidence from regulatory repositories (`rbi.org.in`, `dicgc.org.in`, `sebi.gov.in`, `pib.gov.in`, `npci.org.in`).
3. Determines an evidence-grounded factual verdict without hallucinations.
4. **Independently** assesses behavioral scam risk based on coercive urgency, extortion, and phishing indicators.
5. Honestly communicates uncertainty by returning `UNVERIFIED` whenever authoritative records are inconclusive.

---

## 2. Key Features

- **Decoupled Dual Intelligence**: Factual truth and scam danger are evaluated independently. A claim can be factually unverified while exhibiting extreme scam risk.
- **Multi-Provider Search with Evidence-Based Fallback**: Uses assertion-focused searches and continues to configured fallback providers when retrieved evidence does not resolve every material assertion.
- **Authoritative Domain Grounding**: Special indexing and quality tiering for official Indian regulatory portals.
- **Transparent Evidence Boundaries**: Search snippets and fetched page text retain distinct provenance; failed page fetches remain weaker snippet evidence and are disclosed in the result.
- **Conservative Fact Matching**: Direct subject, predicate, and claimed-value relationships are required for decisive verdicts; missing or conflicting evidence remains unverified.
- **Deterministic Scam Risk Engine**: Rule-based heuristic scoring (0–100) identifying payment demands, urgent deadlines, credential harvesting, APK downloads, and impersonation.
- **Executive Dark-Mode Dashboard**: Clean React 19 + TypeScript interface built with modern CSS variables, interactive risk meter, decomposed assertion breakdown, and traceable source links.
- **Pre-loaded Hackathon Demo Scenarios**: Interactive 1-click test chips demonstrating official policy verification, extortion scams, guaranteed return fraud, and ungrounded rumors.

---

## 3. Architecture & Technology Stack

```
   ┌────────────────────────────────────────────────────────────┐
   │              React 19 + TypeScript Frontend                │
   │      (Vite • Executive Dashboard • Pure Modern CSS)        │
   └─────────────────────────────┬──────────────────────────────┘
                                 │ HTTP / JSON
                                 ▼
   ┌────────────────────────────────────────────────────────────┐
   │                     FastAPI Backend                        │
   │               (Pydantic v2 • Python 3.12)                  │
   └───────────────┬────────────────────────────┬───────────────┘
                   │                            │
                   ▼                            ▼
   ┌───────────────────────────────┐ ┌──────────────────────────┐
   │     Factual Engine Layer      │ │     Scam Risk Engine     │
   │ 1. Claim Decomposer           │ │ 1. Coercive Urgency      │
   │ 2. Multi-Provider Retrieval   │ │ 2. Payment Demands       │
   │    (Serper API / DuckDuckGo)  │ │ 3. Impersonation (RBI)   │
   │ 3. Quality & Relevance Filter │ │ 4. Credential Harvesting │
   │ 4. Grounded Verdict Decision  │ │ 5. Phishing / APK Links  │
   │    (TRUE/FALSE/PARTIAL/UNVER) │ │ Deterministic Score: 0-100
   └───────────────────────────────┘ └──────────────────────────┘
```

### Technologies Used:
- **Backend**: Python 3.12, FastAPI, Pydantic v2, HTTPX, Uvicorn, BeautifulSoup4.
- **Frontend**: React 19, TypeScript, Vite 8, Lucide React icons, Modern Vanilla CSS.
- **Search Providers**: Serper.dev (Google Search API), DuckDuckGo Search (HTML/Lite fallback).
- **Testing**: Pytest, Unittest, Oxlint.
- **Deployment**: Multi-stage Docker, Docker Compose, Static Single-Port Serving.

---

## 4. Repository Structure

```
TruthLensAI/
├── Dockerfile                  # Multi-stage production container build
├── docker-compose.yml          # Containerized deployment orchestration
├── pytest.ini                  # Pytest configuration
├── README.md                   # Complete documentation
│
├── backend/
│   ├── .env.example            # Environment template (placeholders only)
│   ├── .gitignore              # Backend secret & cache exclusions
│   ├── app.py                  # FastAPI application entry & static mount
│   ├── config.py               # Pydantic Settings & provider configuration
│   ├── requirements.txt        # Python production dependencies
│   ├── api/
│   │   ├── routes.py           # GET /api/health and POST /api/analyze
│   │   └── schemas.py          # Request and response Pydantic models
│   ├── core/
│   │   ├── claim_processor.py  # Decomposes messages into assertions & entities
│   │   ├── models.py           # Core domain dataclasses & enums
│   │   ├── scam_detector.py    # Independent rule-based scam risk engine
│   │   └── verdict_engine.py   # Grounded factual accuracy evaluation
│   ├── services/
│   │   ├── evidence_retriever.py  # Serper & DuckDuckGo retrieval providers
│   │   ├── source_fetcher.py      # SSRF-protected page content fetcher
│   │   └── verification_service.py # End-to-end pipeline coordinator
│   └── tests/
│       ├── test_backend.py     # Automated unit & regression tests
│       ├── test_health.py      # Health endpoint test suite
│       └── e2e_live_integration.py # Opt-in authenticated live integration script
│
└── frontend/
    ├── .env.example            # Frontend environment template
    ├── package.json            # Node dependencies (React 19, Vite, Lucide)
    ├── vite.config.ts          # Vite build configuration
    ├── index.html              # HTML entry with typography & metadata
    └── src/
        ├── App.tsx             # Main application orchestrator
        ├── App.css             # Executive dashboard styling
        ├── index.css           # Core design system tokens & resets
        ├── types/              # TypeScript schema definitions
        ├── services/api.ts     # Centralized HTTP API client
        └── components/
            ├── Header.tsx      # Branding & live backend health status
            ├── AnalysisWorkspace.tsx # Claim input & quick-demo test chips
            ├── VerdictPanel.tsx # Factual accuracy verdict & explanation
            ├── ScamRiskPanel.tsx # Risk gauge, score, & detected indicators
            ├── AssertionsPanel.tsx # Decomposed statements & entities
            ├── EvidencePanel.tsx # Retrieved sources with external links
            ├── DiagnosticsPanel.tsx # Pipeline status, limitations & audit notes
            └── Footer.tsx      # Regulatory non-endorsement disclaimer
```

---

## 5. Getting Started & Local Installation

### Prerequisites
- Python 3.11 or 3.12
- Node.js 20+ and npm 10+
- (Optional) Serper API key from [serper.dev](https://serper.dev) for live Google search

### 1. Backend Setup
```powershell
# From repository root
cd backend

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and supply SERPER_API_KEY if testing live search
```

Start the backend server:
```bash
# From project root
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
```
Verify backend health:
```bash
curl http://127.0.0.1:8000/api/health
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
The frontend will start at `http://127.0.0.1:5173`. It connects automatically to `http://127.0.0.1:8000`.

---

## 6. Running Tests

### Unit & Regression Test Suite (Offline)
The automated test suite runs completely offline without requiring API keys or network access:
```bash
python -m pytest backend/tests/ -v
```
The complete suite is run by `.github/workflows/ci.yml`. Do not treat an old local test count as current; use the actual CI run result.

### Frontend Compilation & Linting
```bash
cd frontend
npm run lint
npm run build
```
**Current Frontend Status**: 0 lint errors, production bundle compiled cleanly in `frontend/dist`.

### Live E2E Integration Test Suite
This script sends real analysis requests and may use configured search-provider quota. It requires a short-lived Supabase access token from the normal Google sign-in flow and an explicit opt-in:
```powershell
$env:RUN_LIVE_API_TESTS = '1'
$env:TRUTHLENS_ACCESS_TOKEN = '<short-lived user access token>'
python backend/tests/e2e_live_integration.py
```
Never commit the token. Other opt-in live scripts are documented in `manual_tests/README.md`.

---

## 7. API Reference

### Health Check
- **Endpoint**: `GET /api/health`
- **Response**:
```json
{
  "status": "ok",
  "app_name": "TruthLens AI",
  "version": "0.1.0",
  "environment": "development"
}
```

### Claim Analysis
- **Endpoint**: `POST /api/analyze`
- **Request Body**:
```json
{
  "text": "RBI has announced that all bank accounts will be blocked tonight unless customers pay ₹500 for mandatory verification."
}
```
- **Response Shape**:
```json
{
  "request_id": "9b9a403f-b034-450d-bf14-eef961cb7bce",
  "status": "completed",
  "original_text": "...",
  "claims": [
    {
      "text": "RBI has announced that all bank accounts will be blocked tonight",
      "assertion_type": "regulatory",
      "entities": ["ORG:RBI", "DEADLINE:tonight"]
    }
  ],
  "verdict": "UNVERIFIED",
  "explanation": "Insufficient authoritative evidence exists to verify or refute this specific claim.",
  "evidence": [
    {
      "url": "https://www.rbi.org.in/...",
      "title": "RBI Common Person Portal",
      "excerpt": "...",
      "source_quality": "AUTHORITATIVE",
      "provider": "serper",
      "evidence_origin": "search_snippet",
      "assessments": [
        {
          "evidence_url": "https://www.rbi.org.in/...",
          "assertion_text": "RBI has announced that all bank accounts will be blocked tonight",
          "relevance": "contextual",
          "relationship": "contextual",
          "explanation": "The source shares claim context but does not establish the assertion."
        }
      ]
    }
  ],
  "scam_assessment": {
    "score": 95,
    "category": "HIGH",
    "indicators": [
      {
        "indicator_type": "payment_demand",
        "matched_text": "Rs 500",
        "explanation": "The message contains a demand for payment...",
        "weight": 35
      }
    ],
    "explanation": "High scam probability due to artificial urgency...",
    "disclaimer": "This score is an automated behavioral indicator..."
  },
  "limitations": [],
  "processing_notes": []
}
```

`evidence_origin` distinguishes search-provider snippets from text extracted from a fetched page. Search results may support a proposition when the snippet directly states it, but the linked page is not represented as fetched or independently checked.

---

## 8. Hackathon Demonstration Scenarios

| Scenario | Input Claim | Expected Factual Verdict | Expected Scam Risk | Key Behavioral Indicators |
|---|---|---|---|---|
| **Demo 1: Fake RBI Fee & Account Block** | *"RBI has announced that all bank accounts will be blocked tonight unless customers pay ₹500 for mandatory verification."* | `UNVERIFIED` (honest evidence boundary) | `HIGH` (95/100) | Extortion fee (`₹500`), Urgent deadline (`tonight`), Impersonation (`RBI`) |
| **Demo 2: SEBI Doubling Ponzi Scheme** | *"Urgent SEBI approved investment scheme guarantees 100% daily profit. Send ₹5,000 via UPI within 1 hour to double your money."* | `UNVERIFIED` | `HIGH` (100/100) | Guaranteed returns, UPI transfer request, 1-hour urgency, SEBI impersonation |
| **Demo 3: Official DICGC Deposit Insurance** | *"Under DICGC rules framed by RBI, bank deposits are insured up to ₹5 lakh per depositor across commercial and cooperative banks."* | Depends on whether official evidence establishes each extracted policy assertion | `LOW` | Regulatory reference without coercive demands |
| **Demo 4: Inconclusive Viral Rumor** | *"Government is planning a secret surprise demonetization announcement next Monday at midnight."* | `UNVERIFIED` | `LOW` / `MEDIUM` | Honest refusal to fabricate when records are silent |

---

## 9. Production Deployment

### Single-Port Unified Deployment (Docker)
The production Docker build compiles the React frontend and packages it inside the FastAPI backend. FastAPI automatically serves the static bundle at `/` while servicing API requests at `/api/*`.

```bash
# Build container
docker build -t truthlens-ai .

# Run container
docker run -p 8000:8000 --env-file backend/.env truthlens-ai
```
Visit `http://localhost:8000` to interact with the full dashboard.

---

## 10. Responsible-Use & Regulatory Disclaimer

TruthLens AI is an automated AI assistance tool engineered for educational, hackathon, and intelligence assistance purposes. **It is NOT an official statutory determination** by the Reserve Bank of India (RBI), the Securities and Exchange Board of India (SEBI), the National Payments Corporation of India (NPCI), the Cyber Crime Reporting Portal, or any banking institution. Always confirm regulatory matters through official portals (`rbi.org.in`, `sebi.gov.in`) and report cyber fraud to `cybercrime.gov.in` or emergency helpline **1930**.
