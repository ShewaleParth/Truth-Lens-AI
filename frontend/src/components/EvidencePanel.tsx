import React, { useState } from 'react';
import { ExternalLink, BookOpen, Shield, Globe, Calendar, Database, AlertCircle } from 'lucide-react';
import type { EvidenceItem } from '../types';

interface EvidencePanelProps {
  evidence: EvidenceItem[];
}

export const EvidencePanel: React.FC<EvidencePanelProps> = ({ evidence }) => {
  const [filter, setFilter] = useState<'relevant' | 'context' | 'all'>('relevant');
  const isRelevant = (item: EvidenceItem) => item.assessments?.some((assessment) =>
    assessment.relevance === 'relevant' ||
    assessment.relationship === 'supports' ||
    assessment.relationship === 'contradicts' ||
    assessment.relationship === 'conflicting'
  ) ?? false;
  const isContext = (item: EvidenceItem) => !isRelevant(item) && Boolean(
    item.assessments?.some((assessment) => assessment.relevance === 'contextual')
  );
  const relevantCount = evidence.filter(isRelevant).length;
  const contextCount = evidence.filter(isContext).length;
  const shownEvidence = filter === 'relevant'
    ? evidence.filter(isRelevant)
    : filter === 'context'
      ? evidence.filter(isContext)
      : evidence;

  const getQualityBadge = (quality: string) => {
    const q = (quality || 'UNKNOWN').toUpperCase();
    switch (q) {
      case 'AUTHORITATIVE':
        return (
          <span className="quality-badge quality-authoritative">
            <Shield size={12} /> Official / Regulatory
          </span>
        );
      case 'REPUTABLE':
        return (
          <span className="quality-badge quality-reputable">
            <Globe size={12} /> Reputable Media / Org
          </span>
        );
      case 'LOW':
        return (
          <span className="quality-badge quality-low">
            <AlertCircle size={12} /> Low Credibility Source
          </span>
        );
      case 'UNKNOWN':
      default:
        return (
          <span className="quality-badge quality-unknown">
            General Web Source
          </span>
        );
    }
  };

  return (
    <div className="card evidence-panel">
      <div className="panel-header-row">
        <div className="panel-title-group">
          <BookOpen size={20} className="panel-icon" />
          <h3 className="panel-title">Retrieved Evidence & Sources</h3>
        </div>
        <span className="count-badge">{relevantCount} relevant / {evidence.length} total</span>
      </div>

      <p className="panel-subtitle">
        Traceable search results are assessed individually for relevance and whether they support, contradict, or only contextualize each assertion.
      </p>

      {evidence.length === 0 ? (
        <div className="empty-evidence-notice">
          <AlertCircle size={20} className="empty-icon" />
          <div>
            <h4 className="empty-title">No Relevant External Evidence Retrieved</h4>
            <p className="empty-desc">
              No sources were retrieved for this analysis. Without relevant supporting or contradicting evidence, the system marks the claim as <em>UNVERIFIED</em> rather than guessing.
            </p>
          </div>
        </div>
      ) : (
        <>
          <div className="evidence-filter-row" role="group" aria-label="Filter evidence sources">
            <button type="button" aria-pressed={filter === 'relevant'} className={filter === 'relevant' ? 'active' : ''} onClick={() => setFilter('relevant')}>
              Relevant <span>{relevantCount}</span>
            </button>
            <button type="button" aria-pressed={filter === 'context'} className={filter === 'context' ? 'active' : ''} onClick={() => setFilter('context')}>
              Context <span>{contextCount}</span>
            </button>
            <button type="button" aria-pressed={filter === 'all'} className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>
              All results <span>{evidence.length}</span>
            </button>
          </div>

          {shownEvidence.length === 0 ? (
            <div className="empty-evidence-notice">
              <AlertCircle size={20} className="empty-icon" />
              <div>
                <h4 className="empty-title">No relevant sources found</h4>
                <p className="empty-desc">
                  Search returned {evidence.length} result{evidence.length === 1 ? '' : 's'}, but none directly supports or contradicts the extracted claims. The factual verdict remains unverified. Use “All results” to inspect the search snippets.
                </p>
              </div>
            </div>
          ) : (
        <div className="evidence-list">
          {shownEvidence.map((item, idx) => {
            const hasUrl = Boolean(item.url && item.url.startsWith('http'));
            let domain = '';
            try {
              if (item.url) {
                const parsed = new URL(item.url);
                domain = parsed.hostname;
              }
            } catch {
              domain = item.url;
            }

            return (
              <article key={idx} className="evidence-card">
                <div className="evidence-top-row">
                  <div className="evidence-badges">
                    {getQualityBadge(item.source_quality)}

                    {item.provider && (
                      <span className="provider-badge" title={`Retrieved via ${item.provider}`}>
                        <Database size={11} /> {item.provider}
                      </span>
                    )}

                    <span
                      className="provider-badge"
                      title={item.evidence_origin === 'fetched_page'
                        ? 'Excerpt text was extracted from the linked page.'
                        : 'This is a search-provider snippet; the linked page was not fetched.'}
                    >
                      {item.evidence_origin === 'fetched_page' ? 'Fetched page content' : 'Search snippet only'}
                    </span>

                    {item.published_date && (
                      <span className="date-badge">
                        <Calendar size={11} /> {item.published_date}
                      </span>
                    )}
                  </div>

                  {domain && (
                    <span className="source-domain">{domain}</span>
                  )}
                </div>

                {item.assessments && item.assessments.length > 0 && (
                  <div className="evidence-assessments" aria-label="Evidence relationship assessments">
                    {item.assessments.map((assessment, assessmentIndex) => {
                      const label = assessment.relationship === 'supports'
                        ? 'Supports'
                        : assessment.relationship === 'contradicts'
                          ? 'Contradicts'
                          : assessment.relationship === 'conflicting'
                            ? 'Conflicting'
                            : assessment.relevance === 'irrelevant'
                              ? 'Irrelevant'
                              : 'Context only';

                      return (
                        <span
                          key={`${assessment.evidence_url}-${assessmentIndex}`}
                          className={`evidence-assessment evidence-assessment-${assessment.relationship}`}
                          title={`${assessment.assertion_text}: ${assessment.explanation}`}
                        >
                          {label}: {assessment.assertion_text}
                        </span>
                      );
                    })}
                  </div>
                )}

                <h4 className="evidence-title">
                  {item.title ? item.title : 'Untitled Source Reference'}
                </h4>

                {item.excerpt ? (
                  <p className="evidence-excerpt">
                    "{item.excerpt}"
                  </p>
                ) : (
                  <p className="evidence-excerpt-placeholder">
                    No excerpt provided by search snippet.
                  </p>
                )}

                {item.evidence_origin === 'fetched_page' && item.search_snippet && (
                  <details className="evidence-snippet-details">
                    <summary>Original search snippet</summary>
                    <p className="evidence-excerpt">"{item.search_snippet}"</p>
                  </details>
                )}

                <div className="evidence-footer">
                  {hasUrl ? (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="source-link"
                      title={item.url}
                    >
                      <span>Visit Original Source</span>
                      <ExternalLink size={14} />
                    </a>
                  ) : (
                    <span className="source-link-disabled">URL not available</span>
                  )}

                  {!item.retrieval_success && item.retrieval_error && (
                    <span className="retrieval-warning" title={item.retrieval_error}>
                      Retrieval note: {item.retrieval_error}
                    </span>
                  )}
                  {item.page_fetch_error && (
                    <span className="retrieval-warning" title={item.page_fetch_error}>
                      Page text not checked; retained search snippet only.
                    </span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
          )}
        </>
      )}
    </div>
  );
};
