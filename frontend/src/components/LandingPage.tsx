import React from 'react';
import { ArrowRight, BadgeCheck, BookOpenCheck, CircleHelp, ShieldAlert, ShieldCheck } from 'lucide-react';

interface LandingPageProps {
  onStartAnalysis: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onStartAnalysis }) => (
  <div className="landing-page">
    <section className="landing-hero" aria-labelledby="landing-title">
      <div className="landing-copy">
        <span className="landing-eyebrow"><ShieldCheck size={14} /> Financial message intelligence for India</span>
        <h2 id="landing-title">A warning can be unverified and still be dangerous.</h2>
        <p className="landing-lede">
          Check what the evidence says. See what the message is trying to make you do. Never confuse those two answers.
        </p>
        <div className="landing-actions">
          <button type="button" className="btn btn-primary landing-primary-action" onClick={onStartAnalysis}>
            Analyze a message <ArrowRight size={17} />
          </button>
          <a className="landing-secondary-action" href="#how-it-works">How it works</a>
        </div>
        <div className="landing-assurances" aria-label="Product assurances">
          <span><BadgeCheck size={15} /> Sign in before analyzing</span>
          <span><CircleHelp size={15} /> Uncertainty is shown honestly</span>
        </div>
      </div>

      <aside className="landing-visual" aria-label="Illustrative example of separate factual and safety assessments">
        <div className="landing-visual-topline">
          <span className="landing-preview-kicker">ILLUSTRATIVE MESSAGE CHECK</span>
          <span className="landing-visual-index">DEMO</span>
        </div>
        <div className="landing-message-label">FORWARDED BANK ALERT</div>
        <blockquote className="landing-message-quote">
          “Your account will be blocked tonight. Pay ₹500 now to avoid suspension.”
        </blockquote>

        <div className="landing-assessment-list">
          <div className="landing-assessment factual">
            <div className="landing-assessment-heading">
              <BookOpenCheck size={17} />
              <span>FACT CHECK</span>
              <strong className="landing-status-chip">UNVERIFIED</strong>
            </div>
            <p>No direct source found to confirm or refute this specific alert.</p>
          </div>
          <div className="landing-assessment safety">
            <div className="landing-assessment-heading">
              <ShieldAlert size={17} />
              <span>SCAM WARNING</span>
              <strong className="landing-status-chip">HIGH RISK</strong>
            </div>
            <p>Urgent threat + payment demand. Don't pay or share details.</p>
          </div>
        </div>
        <p className="landing-visual-footnote">Separate assessments. High scam risk does not prove the claim false.</p>
      </aside>
    </section>

    <section className="landing-principles" id="how-it-works" aria-labelledby="principles-title">
      <div className="landing-section-heading">
        <span className="landing-eyebrow">A SIMPLE, TRANSPARENT PROCESS</span>
        <h3 id="principles-title">From forwarded message to informed next step.</h3>
      </div>
      <div className="landing-principle-grid">
        <article className="landing-principle">
          <span className="landing-principle-number">01</span>
          <h4>Paste the message</h4>
          <p>Check a bank alert, investment promise, KYC notice, or forwarded financial claim.</p>
        </article>
        <article className="landing-principle">
          <span className="landing-principle-number">02</span>
          <h4>Review both answers</h4>
          <p>See what evidence supports, contradicts, or leaves uncertain, alongside independent behavior warnings.</p>
        </article>
        <article className="landing-principle">
          <span className="landing-principle-number">03</span>
          <h4>Verify before acting</h4>
          <p>Inspect source quality and coverage. Confirm urgent requests directly through official channels.</p>
        </article>
      </div>
    </section>

    <section className="landing-safety-note" aria-label="Safety and privacy reminder">
      <div className="landing-safety-icon"><ShieldAlert size={19} /></div>
      <p><strong>Pause when a message pressures you to act.</strong> Don't pay, open suspicious links, or share credentials. Never paste passwords, OTPs, or full bank details into the analyzer.</p>
      <button type="button" className="landing-text-action" onClick={onStartAnalysis}>Check a message <ArrowRight size={15} /></button>
    </section>

    <p className="landing-disclaimer">TruthLens AI is an automated assistance tool, not an official determination by RBI, SEBI, NPCI, or a bank. Search coverage varies, and results may be inconclusive. Verify consequential financial decisions through official channels.</p>
  </div>
);
