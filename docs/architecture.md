# TruthLens AI — System Architecture

## 1. Architectural Philosophy
TruthLens AI is designed with three inviolable engineering principles:

1. **Strict Evidence Grounding:** Claims are verified exclusively against retrieved, authoritative external evidence. The platform rejects pure generative synthesis as proof of truth.
2. **Dual-Track Orthogonality:** Factual truth and scam-risk indicators operate as distinct evaluation pipelines to prevent compromised classifications.
3. **Fail-Safe Transparency:** Network timeouts, search-provider disruptions, or missing evidence result in explicit, honest statuses (`UNVERIFIED` or provider degradation reports) rather than hallucinated completions.

---

## 2. Planned Modular Architecture

```
TruthLensAI/
│
├── backend/
│   ├── app.py                 # FastAPI application factory and startup
│   ├── config.py              # Environment configuration & settings
│   ├── requirements.txt       # Project dependencies
│   │
│   ├── api/                   # Interface Layer: Routes and Pydantic Schemas
│   ├── core/                  # Domain Layer: Extraction, Normalization & Orchestration
│   ├── services/              # Integration Layer: Retrieval, Search & LLM Gateways
│   ├── database/              # Persistence Layer: Verification History & Caching
│   └── tests/                 # Automated test suite
│
├── docs/                      # Architectural & Scope Specifications
└── frontend/                  # Web Presentation Layer (Planned Phase 8)
```

---

## 3. Subsystem Responsibilities

### A. API Layer (`backend/api`)
- **Routing & Controllers:** Exposes versioned REST endpoints (`/api/health`, and future verification endpoints).
- **Request / Response Serialization:** Uses Pydantic v2 schemas to enforce input validation and structured outputs.
- **Middleware & Error Handling:** Manages CORS, request timing, correlation IDs, and global HTTP exception mapping.

### B. Core Domain Layer (`backend/core`)
- **Domain Models:** Defines entities for Claims, Evidence Units, Stance Classifications, and Scam Indicators.
- **Claim Normalization Pipeline:** Dissects complex unstructured text into individual testable factual assertions.
- **Verification Engine:** Synthesizes evidence stances (supports, refutes, insufficient) into definitive verdict categories.
- **Scam-Risk Evaluation Engine:** Analyzes urgency cues, intimidation markers, and payment coercion patterns.

### C. Services & Integration Layer (`backend/services`)
- **Evidence Retrieval Service:** Queries search providers and indexed regulatory archives (prioritizing `.gov.in`, `rbi.org.in`, `sebi.gov.in`, `npci.org.in`, and official bank domains).
- **Authoritative Source Scraper:** Fetches and extracts textual content from verified financial portals while respecting robots.txt and rate limits.
- **AI / LLM Gateway:** Interfaces with model providers using structured output schemas; strictly constrained to reasoning over supplied evidence.
- **Link & Domain Safety Inspector:** Inspects URLs for spoofed top-level domains, URL shorteners, and known phishing patterns.

### D. Database Layer (`backend/database`)
- **Verification History:** Stores past verified claims for deduplication and public auditability (Phase 7).
- **Evidence Cache:** Caches retrieved official circulars and press releases to prevent repeated network overhead.
- **Audit Logging:** Maintains immutable logs of model prompts, retrieved passages, and calculated scores for explainability.

### E. Frontend Presentation Layer (`frontend/`)
- Modern, accessible web application (Phase 8).
- Claim submission console, visual stance badges, click-to-verify genuine source links, and scam risk gauges.

---

## 4. Planned Claim-to-Evidence-to-Verdict Workflow

```
[ User Input Claim / URL ]
            │
            ▼
┌────────────────────────────────────────┐
│ 1. Extraction & Normalization (Core)   │
│    - Split compound sentences          │
│    - Isolate atomic factual assertions │
└───────────────────┬────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│ 2. Evidence Retrieval (Services)       │
│    - Query targeted authoritative APIs │
│    - Prioritize RBI, SEBI, banks       │
│    - Filter untrusted domains          │
└───────────────────┬────────────────────┘
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
┌─────────────────┐   ┌──────────────────────┐
│ 3A. Stance      │   │ 3B. Scam-Risk Scan   │
│     Evaluation  │   │     (Core)           │
│     - Support   │   │     - Urgency score  │
│     - Contradict│   │     - Phishing links │
│     - Neutral   │   │     - Coercion check │
└────────┬────────┘   └──────────┬───────────┘
         │                       │
         └──────────┬────────────┘
                    │
                    ▼
┌────────────────────────────────────────┐
│ 4. Grounded Synthesis & Citation       │
│    - Derive Verdict (TRUE / FALSE /    │
│      PARTIALLY_TRUE / UNVERIFIED)      │
│    - Attach genuine clickable URLs     │
│    - Synthesize explainable summary    │
└───────────────────┬────────────────────┘
                    │
                    ▼
[ Structured Output / API Response ]
```

---

## 5. Implementation Status Matrix

| Component / Feature | Phase | Status | Notes |
| :--- | :---: | :---: | :--- |
| **FastAPI Backend Initialization** | Phase 1 | **Implemented** | Application factory, middleware, entrypoint |
| **Centralized Config (`config.py`)** | Phase 1 | **Implemented** | Environment-driven, safe defaults |
| **Health Check Route (`GET /api/health`)**| Phase 1 | **Implemented** | Operational status & metadata |
| **Health Schema (`HealthResponse`)** | Phase 1 | **Implemented** | Pydantic response contract |
| **Automated Health Test Suite** | Phase 1 | **Implemented** | Fast in-process test using TestClient |
| **Project & Scope Documentation** | Phase 1 | **Implemented** | Scope and architecture definitions |
| Claim Extraction & Normalization | Phase 2 | Planned | *Pending explicit Phase 2 approval* |
| Authoritative Evidence Retrieval | Phase 3 | Planned | *Pending explicit Phase 3 approval* |
| Evidence-Based Claim Verification | Phase 4 | Planned | *Pending explicit Phase 4 approval* |
| Scam-Risk Assessment Engine | Phase 5 | Planned | *Pending explicit Phase 5 approval* |
| Explanation Generation & Citations | Phase 6 | Planned | *Pending explicit Phase 6 approval* |
| Database & Verification History | Phase 7 | Planned | *Pending explicit Phase 7 approval* |
| Web Frontend Interface | Phase 8 | Planned | *Pending explicit Phase 8 approval* |
| Reliability & Stress Testing | Phase 9 | Planned | *Pending explicit Phase 9 approval* |
| Production Deployment | Phase 10 | Planned | *Pending explicit Phase 10 approval* |
