import React from 'react';
import { CheckCircle2, XCircle, AlertTriangle, HelpCircle, AlertOctagon, Scale, ShieldAlert } from 'lucide-react';
import type { FactualVerdict, ScamAssessment } from '../types';

interface VerdictPanelProps {
  verdict: FactualVerdict;
  explanation: string;
  assertionsCount: number;
  scamAssessment: ScamAssessment;
}

interface VerdictConfig {
  label: string;
  badgeClass: string;
  cardClass: string;
  description: string;
  icon: React.ReactNode;
}

const VERDICT_CONFIGS: Record<FactualVerdict, VerdictConfig> = {
  TRUE: {
    label: 'Factual / Confirmed',
    badgeClass: 'verdict-badge-true',
    cardClass: 'verdict-card-true',
    description: 'The core assertions in this claim are directly corroborated by authoritative official records.',
    icon: <CheckCircle2 className="verdict-icon-symbol" size={32} />,
  },
  FALSE: {
    label: 'False / Debunked',
    badgeClass: 'verdict-badge-false',
    cardClass: 'verdict-card-false',
    description: 'The claim contradicts documented regulatory facts, official circulars, or authoritative debunks.',
    icon: <XCircle className="verdict-icon-symbol" size={32} />,
  },
  PARTIALLY_TRUE: {
    label: 'Partially True / Distorted',
    badgeClass: 'verdict-badge-partial',
    cardClass: 'verdict-card-partial',
    description: 'Contains elements of truth combined with misleading context, altered figures, or exaggerated claims.',
    icon: <AlertTriangle className="verdict-icon-symbol" size={32} />,
  },
  UNVERIFIED: {
    label: 'Unverified / Inconclusive',
    badgeClass: 'verdict-badge-unverified',
    cardClass: 'verdict-card-unverified',
    description: 'Insufficient authoritative evidence exists to definitively confirm or refute this specific claim.',
    icon: <HelpCircle className="verdict-icon-symbol" size={32} />,
  },
  ERROR: {
    label: 'Analysis Incomplete',
    badgeClass: 'verdict-badge-error',
    cardClass: 'verdict-card-error',
    description: 'An unexpected processing condition prevented a conclusive factual determination.',
    icon: <AlertOctagon className="verdict-icon-symbol" size={32} />,
  },
};

export const VerdictPanel: React.FC<VerdictPanelProps> = ({
  verdict,
  explanation,
  assertionsCount,
  scamAssessment,
}) => {
  const config = VERDICT_CONFIGS[verdict] || VERDICT_CONFIGS.UNVERIFIED;
  const riskLevel = (scamAssessment.category || 'LOW').toUpperCase();
  const matchedSignals = scamAssessment.indicators
    .map((indicator) => indicator.indicator_type.replace(/_/g, ' '));
  const safetyTitle = riskLevel === 'HIGH'
    ? 'High scam risk — likely scam pattern'
    : riskLevel === 'MEDIUM'
      ? 'Caution — suspicious patterns detected'
      : 'No strong scam signals detected';
  const safetyMessage = riskLevel === 'HIGH'
    ? `Rule-based indicators matched: ${matchedSignals.join(', ') || 'multiple risk patterns'}. Treat this message as suspicious. Do not send money, open links, or share credentials; verify through official channels. This risk assessment does not prove the factual claim false.`
    : riskLevel === 'MEDIUM'
      ? `Rule-based indicators matched: ${matchedSignals.join(', ') || 'one or more risk patterns'}. Verify independently before acting. This risk assessment does not prove the factual claim false.`
      : 'The rules did not find strong scam patterns in this message. That does not prove it is safe; verify independently before acting.';

  return (
    <div className={`card verdict-panel ${config.cardClass}`}>
      <div className="verdict-header">
        <div className="verdict-headline-row">
          <div className="verdict-icon-box">{config.icon}</div>
          <div>
            <div className="verdict-label-row">
              <span className={`verdict-tag ${config.badgeClass}`}>{verdict}</span>
              <span className="verdict-title">{config.label}</span>
            </div>
            <p className="verdict-meta-summary">
              Grounded evaluation across {assertionsCount} extracted assertion{assertionsCount === 1 ? '' : 's'}.
            </p>
          </div>
        </div>

        <div className="verdict-status-indicator">
          <Scale size={18} />
          <span>Factual Verification Layer</span>
        </div>
      </div>

      <div className="verdict-explanation-box">
        <h4 className="explanation-title">Evidence-Grounded Explanation</h4>
        <p className="explanation-body">
          {explanation || config.description}
        </p>
      </div>

      {verdict === 'UNVERIFIED' && (
        <div className={`unverified-safety-callout unverified-safety-${riskLevel.toLowerCase()}`} role="status">
          {riskLevel === 'HIGH' ? <ShieldAlert size={18} /> : <HelpCircle size={18} />}
          <span>
            <strong>Independent safety assessment: {safetyTitle}.</strong>{' '}
            {safetyMessage}{' '}
            Factual status remains Unverified because retrieved evidence did not directly establish or refute the claim.
          </span>
        </div>
      )}
    </div>
  );
};
