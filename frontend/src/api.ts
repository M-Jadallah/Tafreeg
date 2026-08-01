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

async function readErrorDetail(response: Response): Promise<unknown> {
  let detail: unknown = response.statusText;

  try {
    const body = await response.json();
    detail = body.detail ?? body;
  } catch {
    // Keep the HTTP status text for non-JSON responses.
  }

  return detail;
}

function handleUnauthorized(path: string, response: Response) {
  const isAuthenticationEndpoint = path.startsWith('/auth/');

  if (response.status === 401 && !isAuthenticationEndpoint) {
    window.dispatchEvent(new Event('auth:unauthorized'));
    throw new ApiError(401, 'انتهت الجلسة');
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

  handleUnauthorized(path, response);

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
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

function filenameFromDisposition(value: string | null, fallback: string) {
  if (!value) return fallback;

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const regularMatch = value.match(/filename="?([^";]+)"?/i);
  return regularMatch?.[1] || fallback;
}

function hasZipLocalHeader(bytes: Uint8Array) {
  if (bytes.length < 4) return false;

  return (
    bytes[0] === 0x50 &&
    bytes[1] === 0x4b &&
    ((bytes[2] === 0x03 && bytes[3] === 0x04) ||
      (bytes[2] === 0x05 && bytes[3] === 0x06) ||
      (bytes[2] === 0x07 && bytes[3] === 0x08))
  );
}

function hasZipEndOfCentralDirectory(bytes: Uint8Array) {
  // EOCD can be followed by a ZIP comment of at most 65,535 bytes.
  const minimumIndex = Math.max(0, bytes.length - 65_557);

  for (let index = bytes.length - 22; index >= minimumIndex; index -= 1) {
    if (
      bytes[index] === 0x50 &&
      bytes[index + 1] === 0x4b &&
      bytes[index + 2] === 0x05 &&
      bytes[index + 3] === 0x06
    ) {
      return true;
    }
  }

  return false;
}

function assertValidZip(bytes: Uint8Array) {
  if (bytes.byteLength < 22 || !hasZipLocalHeader(bytes) || !hasZipEndOfCentralDirectory(bytes)) {
    throw new ApiError(
      502,
      'وصل ملف ZIP ناقص أو غير صالح. أعد المحاولة، وإن تكرر الخطأ راجع سجل خدمة API.',
    );
  }
}

export async function downloadPost(
  path: string,
  body: unknown,
  fallbackFilename: string,
): Promise<void> {
  const headers = new Headers({
    'Content-Type': 'application/json',
    'X-CSRF-Token': decodeURIComponent(cookie('csrf_token')),
  });

  const response = await fetch(`/api${path}`, {
    method: 'POST',
    body: JSON.stringify(body),
    headers,
    credentials: 'include',
  });

  handleUnauthorized(path, response);

  if (!response.ok) {
    throw new ApiError(response.status, await readErrorDetail(response));
  }

  const contentType = (response.headers.get('Content-Type') || '').toLowerCase();
  if (!contentType.includes('application/zip')) {
    throw new ApiError(502, 'الخادم لم يُرجع ملف ZIP كما هو متوقع');
  }

  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const declaredLength = Number(response.headers.get('Content-Length'));

  if (
    Number.isFinite(declaredLength) &&
    declaredLength > 0 &&
    declaredLength !== bytes.byteLength
  ) {
    throw new ApiError(
      502,
      `اكتمل تنزيل ${bytes.byteLength} بايت من أصل ${declaredLength} بايت فقط`,
    );
  }

  assertValidZip(bytes);

  const filename = filenameFromDisposition(
    response.headers.get('Content-Disposition'),
    fallbackFilename,
  );
  const blob = new Blob([buffer], { type: 'application/zip' });
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');

  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();

  // Keep the Blob URL alive long enough for large downloads to start reliably.
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
}

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
