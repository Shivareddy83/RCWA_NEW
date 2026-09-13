export type ApiErrorShape = { status: number; message: string; requestId?: string };

export class ApiError extends Error implements ApiErrorShape {
  status: number;
  requestId?: string;
  constructor(status: number, message: string, requestId?: string) {
    super(message); this.name = 'ApiError'; this.status = status; this.requestId = requestId;
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;

export function setToken(token: string): void { accessToken = token; }
export function getToken(): string | null { return accessToken; }
export function clearToken(): void { accessToken = null; }

function safeErrorMessage(status: number, authenticatedSession: boolean): string {
  if (status === 400) return 'The request could not be processed.';
  if (status === 401) return authenticatedSession ? 'Session expired or unauthorized.' : 'Invalid email or password.';
  if (status === 403) return 'You do not have permission for this action.';
  if (status === 404) return 'Resource not found.';
  if (status === 409) return 'The requested resource already exists.';
  if (status === 422) return 'The request could not be validated.';
  if (status === 429) return 'Too many requests. Please try again shortly.';
  if (status >= 500) return 'The backend is temporarily unavailable. Please try again.';
  return 'The request could not be completed.';
}

export function baseUrl(): string {
  // Browser requests use the same origin so production traffic always goes through Caddy.
  // The env value remains available for non-browser/build tooling.
  if (typeof window !== 'undefined') return '/api/v1';
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${baseUrl()}/auth/refresh`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' } });
      if (!response.ok) return null;
      const data = await response.json() as { access_token?: string };
      if (!data.access_token) return null;
      setToken(data.access_token);
      return data.access_token;
    } catch { return null; }
    finally { refreshInFlight = null; }
  })();
  return refreshInFlight;
}

export async function tryRestoreSession(): Promise<boolean> {
  const token = await refreshAccessToken();
  return Boolean(token);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const hadAuthenticatedSession = Boolean(token);
  const headers = new Headers(options.headers);
  if (options.body && !headers.has('Content-Type') && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const requestId = typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : undefined;
  if (requestId) headers.set('X-Request-ID', requestId);

  async function execute(currentHeaders: Headers): Promise<Response> {
    return fetch(`${baseUrl()}${path}`, { ...options, headers: currentHeaders, credentials: 'include' });
  }

  let response: Response;
  try { response = await execute(headers); }
  catch { throw new ApiError(0, 'Unable to connect to the backend. Please try again.', requestId); }

  if (response.status === 401 && path !== '/auth/login' && path !== '/auth/refresh' && path !== '/auth/mfa/verify-login') {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      const retryHeaders = new Headers(options.headers);
      if (options.body && !retryHeaders.has('Content-Type') && !(options.body instanceof FormData)) retryHeaders.set('Content-Type', 'application/json');
      retryHeaders.set('Authorization', `Bearer ${refreshed}`);
      if (requestId) retryHeaders.set('X-Request-ID', requestId);
      try { response = await execute(retryHeaders); }
      catch { throw new ApiError(0, 'Unable to connect to the backend. Please try again.', requestId); }
    } else if (hadAuthenticatedSession) {
      clearToken();
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('rcaa:auth-expired'));
    }
  }

  const responseRequestId = response.headers.get('x-request-id') || requestId || undefined;
  if (!response.ok) {
    if (response.status === 401 && hadAuthenticatedSession && path !== '/auth/login') {
      clearToken();
      if (typeof window !== 'undefined') window.dispatchEvent(new Event('rcaa:auth-expired'));
    }
    throw new ApiError(response.status, safeErrorMessage(response.status, hadAuthenticatedSession), responseRequestId);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return await response.json() as T;
  return await response.text() as T;
}
