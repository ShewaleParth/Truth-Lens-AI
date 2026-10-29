import React from 'react';
import { ShieldAlert, AlertTriangle, ShieldCheck, Info, Flame, Target } from 'lucide-react';
import type { ScamAssessment } from '../types';

interface ScamRiskPanelProps {
  assessment: ScamAssessment;
}

export const ScamRiskPanel: React.FC<ScamRiskPanelProps> = ({ assessment }) => {
  const { score, category, indicators, explanation, disclaimer } = assessment;
  const mediumThreshold = assessment.medium_threshold ?? 30;
  const highThreshold = assessment.high_threshold ?? 60;

  const normalizedCategory = (category || 'LOW').toUpperCase();

  const getCategoryConfig = (cat: string) => {
    switch (cat) {
      case 'HIGH':
        return {
          label: 'High Scam Risk',
          badgeClass: 'risk-badge-high',
          gaugeColor: 'var(--color-false)',
          icon: <ShieldAlert className="risk-icon high" size={28} />,
          summary: 'Multiple rule-based scam indicators matched. Exercise caution and verify independently.',
        };
      case 'MEDIUM':
        return {
          label: 'Moderate Risk',
          badgeClass: 'risk-badge-medium',
          gaugeColor: 'var(--color-partial)',
          icon: <AlertTriangle className="risk-icon medium" size={28} />,
          summary: 'One or more rule-based indicators matched; this score is heuristic, not a probability.',
        };
      case 'LOW':
      default:
        return {
          label: 'Low Risk',
          badgeClass: 'risk-badge-low',
          gaugeColor: 'var(--color-true)',
          icon: <ShieldCheck className="risk-icon low" size={28} />,
          summary: 'Few or no deceptive or coercive patterns identified in the submitted text.',
        };
    }
  };

  const catConfig = getCategoryConfig(normalizedCategory);

  return (
    <div className="card scam-panel">
      <div className="scam-header">
        <div className="scam-title-row">
          <div className="scam-icon-box">{catConfig.icon}</div>
          <div>
            <div className="scam-meta-row">
              <span className={`risk-category-badge ${catConfig.badgeClass}`}>
                {normalizedCategory} RISK
              </span>
              <span className="risk-score-display">Heuristic score: <strong>{score}</strong> / 100</span>
            </div>
            <p className="scam-subtitle">{catConfig.summary}</p>
          </div>
        </div>

        {/* Visual Score Meter */}
        <div className="risk-meter-container">
          <div className="risk-meter-bar-track">
            <div
              className="risk-meter-bar-fill"
              style={{
                width: `${Math.min(100, Math.max(0, score))}%`,
                backgroundColor: catConfig.gaugeColor,
              }}
            />
          </div>
          <div className="risk-meter-ticks">
            <span className="risk-meter-tick-start">0 Low</span>
            <span style={{ left: `${mediumThreshold}%` }}>{mediumThreshold} Moderate</span>
            <span style={{ left: `${highThreshold}%` }}>{highThreshold} High</span>
            <span className="risk-meter-tick-end">100</span>
          </div>
        </div>
      </div>

      {/* Assessment narrative */}
      {explanation && (
        <div className="scam-explanation-box">
          <h4 className="section-subheading">
            <Info size={16} /> Risk Analysis Summary
          </h4>
          <p className="scam-explanation-text">{explanation}</p>
        </div>
      )}

      {/* Detected Scam Indicators */}
      <div className="indicators-section">
        <h4 className="section-subheading">
          <Target size={16} /> Detected Behavioral Indicators ({indicators.length})
        </h4>

        {indicators.length === 0 ? (
          <p className="no-indicators-note">
            No coercive patterns, payment demands, or phishing URLs were matched.
          </p>
        ) : (
          <div className="indicators-grid">
            {indicators.map((indicator, idx) => (
              <div key={idx} className="indicator-card">
                <div className="indicator-top-row">
                  <span className="indicator-type-tag">
                    <Flame size={12} className="flame-icon" />
                    {indicator.indicator_type.replace(/_/g, ' ')}
                  </span>
                  <span className="indicator-weight-badge">
                    +{indicator.weight} pts
                  </span>
                </div>

                {indicator.matched_text && (
                  <div className="indicator-match">
                    <span className="match-label">Matched:</span>
                    <code className="match-quote">"{indicator.matched_text}"</code>
                  </div>
                )}

                <p className="indicator-desc">{indicator.explanation}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Disclaimer */}
      {disclaimer && (
        <div className="scam-disclaimer-box">
          <Info size={14} className="disclaimer-icon" />
          <p className="scam-disclaimer-text">{disclaimer}</p>
        </div>
      )}
    </div>
  );
};
