import React, { useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, KeyRound, Mail, ScanSearch, ShieldAlert, ShieldCheck, Sparkles } from 'lucide-react';
import type { User } from '@supabase/supabase-js';
import { isSupabaseConfigured, supabase } from '../services/supabase';

interface AuthPageProps {
  user: User | null;
  onReturnAnalyzer: () => void;
}

export const AuthPage: React.FC<AuthPageProps> = ({ user, onReturnAnalyzer }) => {
  const authRequestInFlight = useRef(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleGoogleSignIn = async () => {
    if (!supabase || authRequestInFlight.current) return;
    authRequestInFlight.current = true;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const { error } = await supabase.auth.signInWithOAuth({
        provider: 'google',
        options: { redirectTo: window.location.origin },
      });
      if (error) throw error;
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : 'Google sign-in could not be started. Please check your connection and try again.';
      setErrorMessage(/unsupported provider|provider is not enabled/i.test(message)
        ? 'Google sign-in is disabled in Supabase. In your Supabase Dashboard, enable Google under Authentication → Sign In / Providers, add the Google OAuth client ID and secret, and register the Supabase callback URL in Google Cloud.'
        : `Google sign-in failed: ${message}`);
      setIsSubmitting(false);
      authRequestInFlight.current = false;
    }
  };

  const handleSignOut = async () => {
    if (!supabase || authRequestInFlight.current) return;
    authRequestInFlight.current = true;
    setIsSubmitting(true);
    setErrorMessage(null);
    try {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : 'Sign out failed. Please try again.');
    } finally {
      setIsSubmitting(false);
      authRequestInFlight.current = false;
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-story" aria-labelledby="auth-story-title">
        <span className="landing-eyebrow"><Sparkles size={14} /> FINANCIAL MESSAGE INTELLIGENCE</span>
        <h2 id="auth-story-title">Pause the pressure. See the evidence.</h2>
        <p>Sign in to continue to your analyzer. TrustLens checks what sources support and separately flags risky behavior in the message.</p>
        <div className="auth-signal-art" aria-hidden="true">
          <div className="auth-orbit orbit-one" />
          <div className="auth-orbit orbit-two" />
          <div className="auth-orbit orbit-three" />
          <div className="auth-orbit-core"><ShieldCheck size={36} /></div>
          <div className="auth-float-card fact"><ScanSearch size={15} /><span>Evidence check</span><strong>Grounded</strong></div>
          <div className="auth-float-card risk"><ShieldAlert size={15} /><span>Risk signals</span><strong>Separate</strong></div>
          <span className="auth-art-spark spark-one" />
          <span className="auth-art-spark spark-two" />
        </div>
        <div className="auth-story-note">
          <KeyRound size={16} />
          <span>Sign-in is required before analysis. Reports are not saved to an account yet.</span>
        </div>
      </section>

      <section className="auth-card" aria-labelledby="auth-card-title">
        {!isSupabaseConfigured ? (
          <div className="auth-setup-state">
            <div className="auth-card-icon"><KeyRound size={20} /></div>
            <span className="auth-kicker">SUPABASE SETUP REQUIRED</span>
            <h3 id="auth-card-title">Connect your Supabase project</h3>
            <p>Account access is not enabled until the project URL and publishable key are configured.</p>
            <pre>{'VITE_SUPABASE_URL=https://your-project.supabase.co\nVITE_SUPABASE_PUBLISHABLE_KEY=your-publishable-key'}</pre>
            <p className="auth-setup-hint">Add these values to <code>frontend/.env</code> and restart Vite. Google OAuth must also be enabled in your Supabase project.</p>
          </div>
        ) : user ? (
          <div className="auth-account-state">
            <div className="auth-card-icon success"><CheckCircle2 size={20} /></div>
            <span className="auth-kicker">ACCOUNT CONNECTED</span>
            <h3 id="auth-card-title">You’re signed in</h3>
            <p className="auth-account-email"><Mail size={15} /> {user.email}</p>
            {errorMessage && <p className="auth-error-message" role="alert">{errorMessage}</p>}
            <div className="auth-account-actions">
              <button type="button" className="btn btn-primary auth-submit" onClick={onReturnAnalyzer}>
                Open analyzer <ArrowRight size={16} />
              </button>
              <button type="button" className="auth-signout-button" onClick={handleSignOut} disabled={isSubmitting}>
                {isSubmitting ? 'Signing out…' : 'Sign out'}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="auth-card-icon"><ShieldCheck size={20} /></div>
            <span className="auth-kicker">SECURE ACCOUNT ACCESS</span>
            <h3 id="auth-card-title">Sign in or create your account</h3>
            <p className="auth-card-description">Continue securely with your Google account to access the TrustLens AI analyzer.</p>
            <button type="button" className="auth-google-button" onClick={handleGoogleSignIn} disabled={isSubmitting}>
              <GoogleMark /> {isSubmitting ? 'Connecting to Google…' : 'Continue with Google'} {!isSubmitting && <ArrowRight size={16} />}
            </button>
            {errorMessage && <p className="auth-error-message" role="alert">{errorMessage}</p>}
            <p className="auth-footnote">Google sign-in is the only sign-in method currently available in TrustLens AI.</p>
          </>
        )}
      </section>
    </main>
  );
};

const GoogleMark: React.FC = () => (
  <svg aria-hidden="true" viewBox="0 0 48 48" width="18" height="18">
    <path fill="#4285F4" d="M43.6 24.5c0-1.4-.1-2.8-.4-4.1H24v7.8h11a9.4 9.4 0 0 1-4.1 6.2v5.1h6.6c3.9-3.6 6.1-8.8 6.1-15Z" />
    <path fill="#34A853" d="M24 44c5.5 0 10.1-1.8 13.5-4.9l-6.6-5.1c-1.8 1.2-4 2-6.9 2-5.3 0-9.8-3.6-11.4-8.4H5.8v5.2A20 20 0 0 0 24 44Z" />
    <path fill="#FBBC05" d="M12.6 27.6a12 12 0 0 1 0-7.2v-5.2H5.8a20 20 0 0 0 0 17.6l6.8-5.2Z" />
    <path fill="#EA4335" d="M24 12c3 0 5.7 1 7.8 3.1l5.9-5.9A19.7 19.7 0 0 0 24 4 20 20 0 0 0 5.8 15.2l6.8 5.2C14.2 15.6 18.7 12 24 12Z" />
  </svg>
);

