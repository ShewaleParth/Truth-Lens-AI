import React from 'react';
import { Activity, ShieldCheck, Sparkles } from 'lucide-react';

export const LoadingScreen: React.FC = () => (
  <main className="boot-screen" role="status" aria-live="polite" aria-label="Loading TrustLens">
    <div className="boot-ambient boot-ambient-one" />
    <div className="boot-ambient boot-ambient-two" />
    <div className="boot-grid-texture" />
    <section className="boot-content">
      <div className="boot-brand">
        <span className="boot-brand-mark"><ShieldCheck size={25} /></span>
        <span>TRUSTLENS <b>AI</b></span>
      </div>
      <div className="boot-visual" aria-hidden="true">
        <div className="boot-ring ring-outer" />
        <div className="boot-ring ring-inner" />
        <div className="boot-core"><ShieldCheck size={42} /></div>
        <span className="boot-orbit-dot dot-a" />
        <span className="boot-orbit-dot dot-b" />
        <span className="boot-orbit-dot dot-c" />
        <span className="boot-scan-line" />
      </div>
      <span className="boot-overline"><Sparkles size={13} /> INTELLIGENCE WORKSPACE</span>
      <h1>Clarity before action.</h1>
      <p>Restoring your secure session and preparing the claim analyzer.</p>
      <div className="boot-progress" aria-hidden="true"><span /></div>
      <div className="boot-status"><Activity size={14} /><span>Preparing your workspace</span><i /></div>
    </section>
  </main>
);

