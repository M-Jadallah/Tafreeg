function cookie(name: string) {
  return (
    document.cookie
      .split('; ')
      .find((value) => value.startsWith(`${name}=`))
      ?.split('=')
      .slice(1)
      .join('=') || ''
  );
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : 'حدث خطأ');
    this.status = status;
    this.detail = detail;
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || 'GET').toUpperCase();
  const headers = new Headers(options.headers);

  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    headers.set('X-CSRF-Token', decodeURIComponent(cookie('csrf_token')));
  }

  const response = await fetch(`/api${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });

  const isAuthenticationEndpoint = path.startsWith('/auth/');

  // Never force a browser-level reload. ProtectedLayout handles session loss
  // with React Router so the page cannot enter a refresh/redirect loop.
  if (response.status === 401 && !isAuthenticationEndpoint) {
    window.dispatchEvent(new Event('auth:unauthorized'));
    throw new ApiError(401, 'انتهت الجلسة');
  }

  if (!response.ok) {
    let detail: unknown = response.statusText;

    try {
      const body = await response.json();
      detail = body.detail ?? body;
    } catch {
      // Keep the HTTP status text for non-JSON responses.
    }

    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export const post = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const put = <T>(path: string, body: unknown) =>
  api<T>(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  });

export const del = <T>(path: string, body?: unknown) =>
  api<T>(path, {
    method: 'DELETE',
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export function formatBytes(bytes?: number) {
  if (!bytes) return '0 ب';

  const units = ['ب', 'ك.ب', 'م.ب', 'ج.ب', 'ت.ب'];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );

  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

export function formatDuration(seconds?: number) {
  if (!seconds) return '—';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = Math.floor(seconds % 60);

  return [hours, minutes, remainingSeconds]
    .filter((_, index) => index > 0 || hours > 0)
    .map((value) => String(value).padStart(2, '0'))
    .join(':');
}
