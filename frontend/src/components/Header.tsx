import React from 'react';
import { ShieldCheck, Activity, RefreshCw, CheckCircle2, WifiOff, Sun, Moon, UserRound } from 'lucide-react';
import type { HealthResponse } from '../types';

type Theme = 'dark' | 'light';
type Page = 'analyzer' | 'auth';

interface HeaderProps {
  activePage: Page;
  onNavigate: (page: Page) => void;
  userEmail: string | null;
  theme: Theme;
  onToggleTheme: () => void;
  health: HealthResponse | null;
  healthLoading: boolean;
  healthError: string | null;
  onRefreshHealth: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activePage,
  onNavigate,
  userEmail,
  theme,
  onToggleTheme,
  health,
  healthLoading,
  healthError,
  onRefreshHealth,
}) => {
  return (
    <header className="header-container">
      <div className="header-content">
        <div className="brand-group">
          <div className="brand-icon-wrapper">
            <ShieldCheck className="brand-icon" size={28} />
          </div>
          <div>
            <div className="brand-title-row">
              <h1 className="brand-title">TrustLens <span className="brand-accent">AI</span></h1>
              <span className="badge-beta">INTELLIGENCE PLATFORM</span>
            </div>
            <p className="brand-subtitle">
              Financial Misinformation & Scam Intelligence for Indian Forwarded Claims
            </p>
          </div>
        </div>

        <div className="header-status-group">
          <nav className="primary-navigation" aria-label="Main navigation">
            <button type="button" aria-current={activePage === 'analyzer' ? 'page' : undefined} className={activePage === 'analyzer' ? 'active' : ''} onClick={() => onNavigate('analyzer')}>
              Analyzer
            </button>
            <button type="button" aria-current={activePage === 'auth' ? 'page' : undefined} className={activePage === 'auth' ? 'active' : ''} onClick={() => onNavigate('auth')}>
              <UserRound size={15} /> {userEmail ? 'Account' : 'Sign in'}
            </button>
          </nav>
          <button
            type="button"
            className="theme-toggle"
            onClick={onToggleTheme}
            aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            <span>{theme === 'dark' ? 'Light' : 'Dark'} mode</span>
          </button>
          <div className={`status-pill ${health ? 'status-online' : healthError ? 'status-offline' : 'status-checking'}`}>
            {healthLoading ? (
              <RefreshCw className="spin-icon" size={14} />
            ) : health ? (
              <CheckCircle2 size={14} className="status-dot-icon online" />
            ) : healthError ? (
              <WifiOff size={14} className="status-dot-icon offline" />
            ) : (
              <Activity size={14} className="status-dot-icon" />
            )}

            <div className="status-details">
              <span className="status-label">
                {healthLoading ? 'Connecting...' : health ? 'Backend Online' : 'Backend Offline'}
              </span>
              {health && (
                <span className="status-meta">
                  v{health.version} • {health.environment}
                </span>
              )}
            </div>

            <button
              onClick={onRefreshHealth}
              disabled={healthLoading}
              title="Refresh connection status"
              className="refresh-btn"
              aria-label="Refresh Backend Status"
            >
              <RefreshCw size={12} className={healthLoading ? 'spin-icon' : ''} />
            </button>
          </div>
        </div>
      </div>
    </header>
  );
};
