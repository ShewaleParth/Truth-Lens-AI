/**
 * TruthLens AI - Centralized API Client
 *
 * Interfaces directly with FastAPI backend endpoints:
 * - GET  /api/health
 * - POST /api/analyze
 */

import type { AnalyzeResponse, HealthResponse } from '../types';
import { supabase } from './supabase';

// Empty means same-origin (unified Docker deployment). Vite dev proxies /api.
// Vercel deployments must set VITE_API_BASE_URL to the deployed API origin.
const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '');

export class ApiClientError extends Error {
  statusCode?: number;

  constructor(message: string, statusCode?: number) {
    super(message);
    this.name = 'ApiClientError';
    this.statusCode = statusCode;
  }
}

/**
 * Health check endpoint: GET /api/health
 */
export async function checkBackendHealth(timeoutMs = 5000): Promise<HealthResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/health`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
      signal: controller.signal,
    });

    clearTimeout(timer);

    if (!response.ok) {
      throw new ApiClientError(
        `Backend health check failed with status ${response.status}`,
        response.status
      );
    }

    const data = await response.json();
    return data as HealthResponse;
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof ApiClientError) {
      throw err;
    }
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiClientError('Backend health check timed out. Service may be slow or unreachable.');
    }
    throw new ApiClientError(
      `Cannot connect to the backend${API_BASE_URL ? ` at ${API_BASE_URL}` : ''}. Ensure the FastAPI service is running.`
    );
  }
}

/**
 * Analysis endpoint: POST /api/analyze
 */
export async function analyzeClaim(text: string, timeoutMs = 25000): Promise<AnalyzeResponse> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new ApiClientError('Claim text cannot be empty or contain only whitespace.', 400);
  }

  if (trimmed.length > 5000) {
    throw new ApiClientError(
      `Input exceeds maximum allowed length of 5,000 characters (current: ${trimmed.length}).`,
      400
    );
  }

  if (!supabase) {
    throw new ApiClientError('Authentication is not configured. Please contact the application administrator.', 503);
  }

  let accessToken: string | undefined;
  try {
    const { data, error } = await supabase.auth.getSession();
    if (error) throw error;
    accessToken = data.session?.access_token;
  } catch {
    throw new ApiClientError('Could not restore your sign-in session. Sign in again and retry.', 401);
  }
  if (!accessToken) {
    throw new ApiClientError('Your sign-in session is missing or expired. Sign in again to analyze a claim.', 401);
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ text: trimmed }),
      signal: controller.signal,
    });

    clearTimeout(timer);

    let data: any;
    try {
      data = await response.json();
    } catch {
      throw new ApiClientError(
        `Invalid server response (HTTP ${response.status}). Expected JSON format.`,
        response.status
      );
    }

    if (!response.ok) {
      const detail = data?.detail || `Analysis request failed with status code ${response.status}.`;
      throw new ApiClientError(detail, response.status);
    }

    // Basic structural validation to ensure UI safety
    if (!data.request_id || !data.verdict || !data.scam_assessment) {
      throw new ApiClientError('Server returned an unexpected or incomplete analysis schema.');
    }

    return data as AnalyzeResponse;
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof ApiClientError) {
      throw err;
    }
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiClientError(
        'The analysis request timed out. Search retrieval or evidence processing took longer than expected.'
      );
    }
    throw new ApiClientError(
      `Network connection failed. Unable to communicate with the TruthLens backend${API_BASE_URL ? ` at ${API_BASE_URL}` : ''}.`
    );
  }
}
