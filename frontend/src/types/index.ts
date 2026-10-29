/**
 * TruthLens AI - Frontend TypeScript Definitions
 * Strictly aligned with backend API schemas (backend/api/schemas.py).
 */

export type FactualVerdict = 'TRUE' | 'FALSE' | 'PARTIALLY_TRUE' | 'UNVERIFIED' | 'ERROR';

export type ScamCategory = 'HIGH' | 'MEDIUM' | 'LOW';

export type SourceQuality = 'AUTHORITATIVE' | 'REPUTABLE' | 'UNKNOWN' | 'LOW';

export interface Assertion {
  text: string;
  assertion_type: string;
  entities: string[];
}

export interface EvidenceItem {
  url: string;
  title: string;
  excerpt: string;
  published_date?: string | null;
  source_quality: SourceQuality | string;
  retrieval_success: boolean;
  evidence_origin?: 'search_snippet' | 'fetched_page' | string;
  search_snippet?: string | null;
  page_fetch_error?: string | null;
  retrieval_error?: string | null;
  provider?: string | null;
  assessments?: EvidenceAssessment[];
}

export interface EvidenceAssessment {
  evidence_url: string;
  assertion_text: string;
  relevance: 'relevant' | 'contextual' | 'irrelevant' | string;
  relationship: 'supports' | 'contradicts' | 'conflicting' | 'contextual' | 'none' | string;
  explanation: string;
}

export interface ScamIndicator {
  indicator_type: string;
  matched_text: string;
  explanation: string;
  weight: number;
}

export interface ScamAssessment {
  score: number;
  category: ScamCategory | string;
  medium_threshold: number;
  high_threshold: number;
  indicators: ScamIndicator[];
  explanation: string;
  disclaimer: string;
}

export interface AssertionEvidenceCoverage {
  assertion_text: string;
  outcome: string;
  relevant_sources: number;
  supporting_sources: number;
  contradicting_sources: number;
}

export interface EvidenceDiagnostics {
  retrieval_outcome: string;
  providers_attempted: string[];
  evidence_count: number;
  fetched_page_count: number;
  snippet_count: number;
  assertion_coverage: AssertionEvidenceCoverage[];
  targeted_queries?: { query: string; assertion_text: string }[];
}

export interface AnalyzeResponse {
  request_id: string;
  status: 'completed' | 'input_error' | 'provider_unavailable' | 'error' | string;
  original_text: string;
  claims: Assertion[];
  verdict: FactualVerdict;
  explanation: string;
  evidence: EvidenceItem[];
  scam_assessment: ScamAssessment;
  limitations: string[];
  processing_notes: string[];
  evidence_diagnostics: EvidenceDiagnostics;
}

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  environment: string;
}

export interface ApiError {
  detail: string;
  status_code?: number;
}
