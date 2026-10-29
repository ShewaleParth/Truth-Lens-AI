import React, { useState } from 'react';
import { AlertCircle, Terminal, ChevronDown, ChevronUp, Cpu, Info } from 'lucide-react';
import type { EvidenceDiagnostics } from '../types';

interface DiagnosticsPanelProps {
  requestId: string;
  status: string;
  limitations: string[];
  processingNotes: string[];
  evidenceDiagnostics: EvidenceDiagnostics;
}

export const DiagnosticsPanel: React.FC<DiagnosticsPanelProps> = ({
  requestId,
  status,
  limitations,
  processingNotes,
  evidenceDiagnostics,
}) => {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="card diagnostics-panel">
      <div
        className="diagnostics-toggle-row"
        onClick={() => setIsOpen(!isOpen)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsOpen(!isOpen);
          }
        }}
        aria-expanded={isOpen}
      >
        <div className="diagnostics-title-group">
          <Terminal size={18} className="diagnostics-icon" />
          <h3 className="diagnostics-title">Pipeline Diagnostics & Analysis Scope</h3>
          <span className="status-badge-mono">Status: {status}</span>
        </div>

        <div className="toggle-action">
          <span className="toggle-text">{isOpen ? 'Hide Details' : 'Show Details'}</span>
          {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </div>

      {isOpen && (
        <div className="diagnostics-content">
          <div className="diagnostics-meta-bar">
            <span>Request ID: <code>{requestId}</code></span>
            <span>Execution Status: <code>{status}</code></span>
            <span>Evidence retrieval: <code>{evidenceDiagnostics.retrieval_outcome.replace(/_/g, ' ')}</code></span>
            <span>Providers attempted: <code>{evidenceDiagnostics.providers_attempted.join(', ') || 'none'}</code></span>
            <span>
              Sources: <code>{evidenceDiagnostics.evidence_count}</code>
              {' '}(<code>{evidenceDiagnostics.fetched_page_count}</code> fetched pages,{' '}
              <code>{evidenceDiagnostics.snippet_count}</code> snippets)
            </span>
          </div>

          <div className="diagnostics-block">
            <h4 className="diagnostics-subheading">
              <Info size={15} /> Assertion Evidence Coverage
            </h4>
            {evidenceDiagnostics.assertion_coverage.length === 0 ? (
              <p className="diagnostics-empty-note">No assertions were available to assess.</p>
            ) : (
              <ul className="diagnostics-list">
                {evidenceDiagnostics.assertion_coverage.map((coverage, idx) => (
                  <li key={idx} className="diagnostics-item">
                    <span>
                      <strong>{coverage.outcome.toUpperCase()}</strong> — {coverage.assertion_text}
                      {' '}({coverage.relevant_sources} relevant, {coverage.supporting_sources} supporting,{' '}
                      {coverage.contradicting_sources} contradicting)
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="diagnostics-block">
            <h4 className="diagnostics-subheading">
              <Info size={15} /> Search Queries
            </h4>
            {evidenceDiagnostics.targeted_queries?.length ? (
              <ul className="diagnostics-list">
                {evidenceDiagnostics.targeted_queries.map((targetedQuery, idx) => (
                  <li key={`${targetedQuery.query}-${idx}`} className="diagnostics-item query-diagnostic-item">
                    <code>{targetedQuery.query}</code>
                    <span>Target: {targetedQuery.assertion_text}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="diagnostics-empty-note">Query details were not returned by the backend.</p>
            )}
          </div>

          {/* Limitations */}
          <div className="diagnostics-block">
            <h4 className="diagnostics-subheading">
              <AlertCircle size={15} /> Documented Limitations
            </h4>
            {limitations.length === 0 ? (
              <p className="diagnostics-empty-note">
                No pipeline limitations recorded for this analysis.
              </p>
            ) : (
              <ul className="diagnostics-list">
                {limitations.map((lim, idx) => (
                  <li key={idx} className="diagnostics-item">
                    <Info size={13} className="bullet-icon" />
                    <span>{lim}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Processing Notes */}
          <div className="diagnostics-block">
            <h4 className="diagnostics-subheading">
              <Cpu size={15} /> Processing & Provider Audit Notes
            </h4>
            {processingNotes.length === 0 ? (
              <p className="diagnostics-empty-note">
                Search provider completed without fallback or skip events.
              </p>
            ) : (
              <ul className="diagnostics-list">
                {processingNotes.map((note, idx) => (
                  <li key={idx} className="diagnostics-item mono-item">
                    <code>{note}</code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
