import React, { useState, useEffect } from 'react';
import type { User } from '@supabase/supabase-js';
import {
  Header,
} from './components/Header';
import { AnalysisWorkspace } from './components/AnalysisWorkspace';
import { LoadingScreen } from './components/LoadingScreen';
import { VerdictPanel } from './components/VerdictPanel';
import { ScamRiskPanel } from './components/ScamRiskPanel';
import { AssertionsPanel } from './components/AssertionsPanel';
import { EvidencePanel } from './components/EvidencePanel';
import { DiagnosticsPanel } from './components/DiagnosticsPanel';
import { Footer } from './components/Footer';
import { AuthPage } from './components/AuthPage';
import { checkBackendHealth, analyzeClaim, ApiClientError } from './services/api';
import { supabase } from './services/supabase';
import type { AnalyzeResponse, HealthResponse } from './types';
import {
  AlertTriangle,
  RotateCcw,
  BrainCircuit,
  ArrowLeft,
  BookOpen,
  ClipboardList,
  Terminal,
} from 'lucide-react';
import './App.css';

type ResultTab = 'overview' | 'evidence' | 'diagnostics';
type Theme = 'dark' | 'light';
type AppPage = 'analyzer' | 'auth';

const getInitialTheme = (): Theme => {
  try {
    const savedTheme = window.localStorage.getItem('truthlens-theme');
    if (savedTheme === 'light' || savedTheme === 'dark') return savedTheme;
  } catch {
    // Storage may be disabled; continue with the operating-system preference.
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
};

export const App: React.FC = () => {
  const [currentPage, setCurrentPage] = useState<AppPage>('auth');
  const [isBooting, setIsBooting] = useState(true);
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [authUser, setAuthUser] = useState<User | null>(null);

  useEffect(() => {
    let isMounted = true;
    const startedAt = Date.now();
    const subscription = supabase?.auth.onAuthStateChange((event, session) => {
      setAuthUser(session?.user ?? null);
      if (event === 'SIGNED_IN') {
        setCurrentPage('analyzer');
        setIsBooting(false);
      } else if (event === 'SIGNED_OUT') {
        setCurrentPage('auth');
      }
    }).data.subscription;

    const initializeSession = async () => {
      let user: User | null = null;
      try {
        if (supabase) {
          const { data } = await supabase.auth.getSession();
          user = data.session?.user ?? null;
        }
      } catch {
        // If session restoration fails, start at sign-in.
      }
      if (!isMounted) return;
      setAuthUser(user);
      setCurrentPage(user ? 'analyzer' : 'auth');
      const remainingSplashTime = Math.max(0, 900 - (Date.now() - startedAt));
      window.setTimeout(() => {
        if (isMounted) setIsBooting(false);
      }, remainingSplashTime);
    };

    void initializeSession();
    return () => {
      isMounted = false;
      subscription?.unsubscribe();
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const pageBackground = window.getComputedStyle(document.documentElement).getPropertyValue('--bg-app').trim();
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', pageBackground);
    try {
      window.localStorage.setItem('truthlens-theme', theme);
    } catch {
      // The selected theme still applies for this session when storage is unavailable.
    }
  }, [theme]);

  // Backend health state
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState<boolean>(true);
  const [healthError, setHealthError] = useState<string | null>(null);

  // Analysis state
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [lastSubmittedText, setLastSubmittedText] = useState<string>('');
  const [activeResultTab, setActiveResultTab] = useState<ResultTab>('overview');

  // Manual health refresh handler
  const handleManualRefresh = async () => {
    setHealthLoading(true);
    try {
      const data = await checkBackendHealth();
      setHealth(data);
      setHealthError(null);
    } catch (err: unknown) {
      setHealth(null);
      if (err instanceof ApiClientError) {
        setHealthError(err.message);
      } else if (err instanceof Error) {
        setHealthError(err.message);
      } else {
        setHealthError('Unable to reach TruthLens AI backend service.');
      }
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    let isMounted = true;

    const runHealthCheck = async () => {
      try {
        const data = await checkBackendHealth();
        if (isMounted) {
          setHealth(data);
          setHealthError(null);
          setHealthLoading(false);
        }
      } catch (err: unknown) {
        if (isMounted) {
          setHealth(null);
          if (err instanceof ApiClientError) {
            setHealthError(err.message);
          } else if (err instanceof Error) {
            setHealthError(err.message);
          } else {
            setHealthError('Unable to reach TruthLens AI backend service.');
          }
          setHealthLoading(false);
        }
      }
    };

    runHealthCheck();
    const interval = setInterval(runHealthCheck, 30000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, []);

  // Execute analysis
  const handleAnalyze = async (text: string) => {
    setCurrentPage('analyzer');
    setIsAnalyzing(true);
    // Do not leave a previous verdict visible if this request fails. API errors
    // are shown in the entry flow and must not be mistaken for a fresh verdict.
    setResult(null);
    setAnalysisError(null);
    setLastSubmittedText(text);
    setActiveResultTab('overview');

    try {
      const data = await analyzeClaim(text);
      setResult(data);
      setAnalysisError(null);
    } catch (err: unknown) {
      if (err instanceof ApiClientError) {
        setAnalysisError(err.message);
      } else if (err instanceof Error) {
        setAnalysisError(err.message);
      } else {
        setAnalysisError('An unexpected error occurred during analysis.');
      }
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleRetry = () => {
    if (lastSubmittedText) {
      handleAnalyze(lastSubmittedText);
    }
  };

  const handleReset = () => {
    setCurrentPage('analyzer');
    setResult(null);
    setAnalysisError(null);
    setActiveResultTab('overview');
    window.scrollTo(0, 0);
  };

  const handleNavigate = (page: AppPage) => {
    if (page === 'analyzer' && !authUser) {
      setCurrentPage('auth');
      window.scrollTo(0, 0);
      return;
    }
    setCurrentPage(page);
    window.scrollTo(0, 0);
  };

  const relevantSourceCount = result?.evidence.filter((item) =>
    item.assessments?.some((assessment) =>
      assessment.relevance === 'relevant' ||
      assessment.relationship === 'supports' ||
      assessment.relationship === 'contradicts' ||
      assessment.relationship === 'conflicting'
    )
  ).length ?? 0;

  if (isBooting) return <LoadingScreen />;

  return (
    <div className="app-layout">
      <Header
        activePage={currentPage}
        onNavigate={handleNavigate}
        userEmail={authUser?.email ?? null}
        theme={theme}
        onToggleTheme={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
        health={health}
        healthLoading={healthLoading}
        healthError={healthError}
        onRefreshHealth={handleManualRefresh}
      />

      <main className="main-content">
        <div className="container">
          {/* Top Banner if Backend is completely offline */}
          {healthError && (
            <div className="alert-banner alert-warning" role="alert">
              <AlertTriangle size={18} className="alert-banner-icon" />
              <div className="alert-banner-text">
                <strong>Backend Unavailable:</strong> {healthError}
                <span className="alert-subtext"> (Ensure <code>python -m uvicorn backend.app:app</code> is running on port 8000)</span>
              </div>
              <button onClick={handleManualRefresh} className="btn-sm btn-outline">
                <RotateCcw size={12} /> Retry
              </button>
            </div>
          )}

          {currentPage === 'auth' && (
            <AuthPage
              user={authUser}
              onReturnAnalyzer={() => handleNavigate('analyzer')}
            />
          )}

          {currentPage === 'analyzer' && !result && !isAnalyzing && (
            <>
              {/* Analysis entry page */}
              <div className="analysis-page-intro">
                <span className="features-badge">FINANCIAL MESSAGE CHECK</span>
                <h2>Check a claim before you act</h2>
                <p>Paste a forwarded message or financial claim. We’ll show what the evidence supports and flag common scam patterns.</p>
              </div>

              <AnalysisWorkspace
                onAnalyze={handleAnalyze}
                isLoading={isAnalyzing}
                disabled={isAnalyzing}
                initialText={lastSubmittedText}
              />

              {analysisError && (
                <div className="alert-banner alert-error" role="alert">
                  <AlertTriangle size={20} className="alert-banner-icon" />
                  <div className="alert-banner-text">
                    <h4 className="alert-error-title">Analysis Failed</h4>
                    <p className="alert-error-desc">{analysisError}</p>
                    <p className="alert-error-hint">Your text is still in the input. You can edit it or retry.</p>
                  </div>
                  <button onClick={handleRetry} className="btn-sm btn-error-retry">
                    <RotateCcw size={14} /> Retry Analysis
                  </button>
                </div>
              )}
            </>
          )}

          {isAnalyzing && currentPage === 'analyzer' && (
            <div className="card loading-card">
              <div className="loading-pipeline">
                <div className="pipeline-spinner-wrapper">
                  <div className="pipeline-pulse-circle"></div>
                  <BrainCircuit size={36} className="pipeline-center-icon spin-slow" />
                </div>
                <h3 className="loading-title">Checking the claim and its sources</h3>
                <p className="loading-sub">
                  Searching relevant sources, assessing evidence, and checking for scam indicators. This can take a few seconds.
                </p>
                <div className="pipeline-steps">
                  <div className="step-item active"><span className="step-num">1</span><span className="step-label">Extract claims</span></div>
                  <div className="step-divider active"></div>
                  <div className="step-item active"><span className="step-num">2</span><span className="step-label">Search evidence</span></div>
                  <div className="step-divider active"></div>
                  <div className="step-item active"><span className="step-num">3</span><span className="step-label">Assess risk</span></div>
                </div>
              </div>
            </div>
          )}

          {/* Results live on their own screen; details are grouped by task. */}
          {result && !isAnalyzing && currentPage === 'analyzer' && (
            <div className="results-container">
              <div className="results-header-bar">
                <div className="results-heading-group">
                  <button onClick={handleReset} className="btn btn-secondary-subtle results-back-button">
                    <ArrowLeft size={15} /> New analysis
                  </button>
                  <div>
                    <h2 className="results-heading">Analysis results</h2>
                    <span className="results-request-id">Request <code>{result.request_id}</code></span>
                  </div>
                </div>
                <span className={`result-coverage-status ${result.evidence_diagnostics.retrieval_outcome}`}>
                  {result.evidence_diagnostics.retrieval_outcome === 'completed_with_coverage'
                    ? 'Evidence found'
                    : result.evidence_diagnostics.retrieval_outcome === 'provider_unavailable'
                      ? 'Search unavailable'
                      : result.evidence_diagnostics.retrieval_outcome === 'completed_no_results'
                        ? 'No search results'
                        : 'Evidence limited'}
                </span>
              </div>

              <div className="submitted-claim-card">
                <span className="submitted-claim-label">ANALYZED MESSAGE</span>
                <p>{result.original_text}</p>
              </div>

              <div className="result-metrics-row" aria-label="Evidence summary">
                <div><strong>{relevantSourceCount}</strong><span>relevant sources</span></div>
                <div><strong>{result.evidence_diagnostics.fetched_page_count}</strong><span>pages checked</span></div>
                <div><strong>{result.evidence_diagnostics.providers_attempted.length}</strong><span>search providers</span></div>
              </div>

              <div className="result-tabs" role="tablist" aria-label="Analysis result sections">
                <button role="tab" id="tab-overview" aria-selected={activeResultTab === 'overview'} aria-controls="panel-overview" className={activeResultTab === 'overview' ? 'active' : ''} onClick={() => setActiveResultTab('overview')}>
                  <ClipboardList size={16} /> Overview
                </button>
                <button role="tab" id="tab-evidence" aria-selected={activeResultTab === 'evidence'} aria-controls="panel-evidence" className={activeResultTab === 'evidence' ? 'active' : ''} onClick={() => setActiveResultTab('evidence')}>
                  <BookOpen size={16} /> Evidence <span className="tab-count">{result.evidence.length}</span>
                </button>
                <button role="tab" id="tab-diagnostics" aria-selected={activeResultTab === 'diagnostics'} aria-controls="panel-diagnostics" className={activeResultTab === 'diagnostics' ? 'active' : ''} onClick={() => setActiveResultTab('diagnostics')}>
                  <Terminal size={16} /> Diagnostics
                </button>
              </div>

              {activeResultTab === 'overview' && (
                <section id="panel-overview" role="tabpanel" aria-labelledby="tab-overview" className="result-tab-panel">
                  <div className="dashboard-grid">
                    <VerdictPanel
                      verdict={result.verdict}
                      explanation={result.explanation}
                      assertionsCount={result.claims.length}
                      scamAssessment={result.scam_assessment}
                    />
                    <ScamRiskPanel assessment={result.scam_assessment} />
                  </div>
                  <AssertionsPanel claims={result.claims} />
                </section>
              )}

              {activeResultTab === 'evidence' && (
                <section id="panel-evidence" role="tabpanel" aria-labelledby="tab-evidence" className="result-tab-panel">
                  <EvidencePanel evidence={result.evidence} />
                </section>
              )}

              {activeResultTab === 'diagnostics' && (
                <section id="panel-diagnostics" role="tabpanel" aria-labelledby="tab-diagnostics" className="result-tab-panel">
                  <DiagnosticsPanel
                    requestId={result.request_id}
                    status={result.status}
                    limitations={result.limitations}
                    processingNotes={result.processing_notes}
                    evidenceDiagnostics={result.evidence_diagnostics}
                  />
                </section>
              )}
            </div>
          )}

        </div>
      </main>

      <Footer />
    </div>
  );
};

export default App;
