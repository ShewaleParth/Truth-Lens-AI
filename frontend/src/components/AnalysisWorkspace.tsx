import React, { useState } from 'react';
import { Search, Loader2, Sparkles, X, AlertCircle } from 'lucide-react';

interface AnalysisWorkspaceProps {
  onAnalyze: (text: string) => void;
  isLoading: boolean;
  disabled: boolean;
  initialText?: string;
}

const DEMO_SAMPLES = [
  {
    label: 'Demo 1: Deposit Insurance - True',
    text: 'DICGC insures bank deposits up to ₹5 lakh per depositor per bank, including principal and interest.',
    tag: 'True claim',
  },
  {
    label: 'Demo 2: Deposit Insurance - False',
    text: 'DICGC insures bank deposits up to ₹10 lakh per depositor per bank, including principal and interest.',
    tag: 'False claim',
  },
  {
    label: 'Demo 3: KYC Phishing Alert',
    text: 'Your SBI NetBanking will be suspended today. Verify your KYC immediately at http://sbi-kyc-update.xyz.',
    tag: 'Phishing',
  },
  {
    label: 'Demo 4: Guaranteed Return Scam',
    text: 'A SEBI-approved scheme guarantees 100% daily profit. Send ₹5,000 by UPI within one hour to double your money.',
    tag: 'Investment scam',
  },
];

const MAX_CHARS = 5000;

export const AnalysisWorkspace: React.FC<AnalysisWorkspaceProps> = ({
  onAnalyze,
  isLoading,
  disabled,
  initialText = '',
}) => {
  const [inputText, setInputText] = useState(initialText);
  const [validationError, setValidationError] = useState<string | null>(null);

  const trimmedLength = inputText.trim().length;
  const isOverLimit = inputText.length > MAX_CHARS;

  const handleSubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (isLoading || disabled) return;

    if (!inputText.trim()) {
      setValidationError('Please enter a financial claim or forwarded message to analyze.');
      return;
    }

    if (isOverLimit) {
      setValidationError(`Input length exceeds ${MAX_CHARS.toLocaleString()} characters.`);
      return;
    }

    setValidationError(null);
    onAnalyze(inputText.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSelectSample = (sampleText: string) => {
    setInputText(sampleText);
    setValidationError(null);
  };

  const handleClear = () => {
    setInputText('');
    setValidationError(null);
  };

  return (
    <section className="card workspace-card">
      <div className="workspace-header">
        <div className="workspace-title-group">
          <h2 className="section-title">Claim & Message Intelligence Analyzer</h2>
          <p className="section-description">
            Submit any financial claim, WhatsApp viral message, KYC suspension alert, or investment offer to verify its factual accuracy and evaluate scam risk.
          </p>
        </div>

        <div className="demo-selector-group">
          <span className="demo-label">
            <Sparkles size={14} className="accent-icon" /> Test Scenarios:
          </span>
          <div className="demo-chips">
            {DEMO_SAMPLES.map((sample, idx) => (
              <button
                key={idx}
                type="button"
                className="demo-chip"
                onClick={() => handleSelectSample(sample.text)}
                disabled={isLoading}
                title={sample.text}
              >
                <span className="demo-chip-name">{sample.label}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="workspace-form">
        <div className="textarea-container">
          <textarea
            id="claim-input"
            className={`claim-textarea ${validationError || isOverLimit ? 'has-error' : ''}`}
            rows={5}
            placeholder="Paste forwarded WhatsApp alert, SMS, Telegram investment promise, or official claim here... (e.g., 'RBI announces ₹500 fee for account re-verification' or 'Guaranteed 50% monthly returns by SEBI approved fund')"
            value={inputText}
            onChange={(e) => {
              setInputText(e.target.value);
              if (validationError) setValidationError(null);
            }}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            maxLength={MAX_CHARS + 500}
            aria-label="Financial claim or suspicious message"
          />

          {inputText && (
            <button
              type="button"
              className="clear-input-btn"
              onClick={handleClear}
              title="Clear input"
              aria-label="Clear input text"
            >
              <X size={16} />
            </button>
          )}
        </div>

        {validationError && (
          <div className="validation-error-box">
            <AlertCircle size={16} />
            <span>{validationError}</span>
          </div>
        )}

        <p className="input-privacy-note">For your safety, don't paste passwords, OTPs, or full bank details.</p>

        <div className="workspace-actions">
          <div className="character-counter">
            <span className={isOverLimit ? 'counter-danger' : 'counter-normal'}>
              {inputText.length.toLocaleString()}
            </span>
            <span className="counter-max"> / {MAX_CHARS.toLocaleString()} characters</span>
            <span className="keyboard-hint">Press <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to submit</span>
          </div>

          <button
            type="submit"
            id="analyze-submit-button"
            className="btn btn-primary"
            disabled={isLoading || disabled || trimmedLength === 0 || isOverLimit}
          >
            {isLoading ? (
              <>
                <Loader2 className="spin-icon" size={18} />
                <span>Running Pipeline...</span>
              </>
            ) : (
              <>
                <Search size={18} />
                <span>Analyze Claim</span>
              </>
            )}
          </button>
        </div>
      </form>
    </section>
  );
};
