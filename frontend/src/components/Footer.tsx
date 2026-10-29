import React from 'react';
import { ShieldCheck, AlertTriangle } from 'lucide-react';

export const Footer: React.FC = () => {
  return (
    <footer className="footer-container">
      <div className="footer-content">
        <div className="footer-disclaimer-card">
          <div className="disclaimer-header">
            <AlertTriangle size={18} className="disclaimer-alert-icon" />
            <h4 className="disclaimer-title">Responsible-Use & Regulatory Disclaimer</h4>
          </div>
          <p className="disclaimer-text">
            TrustLens AI is an open automated intelligence assistance system engineered for analyzing forwarded claims, viral misinformation, and coercive scam patterns.
            <strong> It is NOT an official statutory determination</strong> by the Reserve Bank of India (RBI), the Securities and Exchange Board of India (SEBI), the National Payments Corporation of India (NPCI), the Cyber Crime Portal, or any commercial bank.
            Always cross-reference critical financial decisions directly with primary regulatory portals (such as <a href="https://rbi.org.in" target="_blank" rel="noopener noreferrer">rbi.org.in</a> or <a href="https://sebi.gov.in" target="_blank" rel="noopener noreferrer">sebi.gov.in</a>) and report ongoing cyber fraud to <a href="https://cybercrime.gov.in" target="_blank" rel="noopener noreferrer">cybercrime.gov.in</a> or helpline 1930.
          </p>
        </div>

        <div className="footer-bottom-row">
          <div className="footer-brand">
            <ShieldCheck size={18} className="brand-sub-icon" />
            <span>TrustLens AI • Financial Misinformation & Scam Intelligence</span>
          </div>

          <div className="footer-meta">
            <span>Hackathon Submission Edition</span>
            <span className="dot-sep">•</span>
            <span>FastAPI + React TypeScript + Multi-Provider Search</span>
          </div>
        </div>
      </div>
    </footer>
  );
};
