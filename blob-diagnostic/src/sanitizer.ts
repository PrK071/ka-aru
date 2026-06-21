// Strip sensitive query params + redact sensitive header VALUES.
// Sensitive header/credential values are NEVER recorded. Names only.

const SENSITIVE_HEADERS = new Set([
  "cookie",
  "set-cookie",
  "authorization",
  "proxy-authorization",
  "x-csrf-token",
  "x-xsrf-token",
  "csrf-token",
  "x-api-key",
  "api-key",
  "x-auth-token",
  "x-signature",
  "signature",
  "x-verification-key",
  "x-amz-security-token",
]);

const SENSITIVE_QUERY_KEYS = [
  "token",
  "auth",
  "key",
  "sig",
  "signature",
  "session",
  "password",
  "pwd",
  "secret",
  "access_token",
  "id_token",
  "apikey",
  "api_key",
];

export function isSensitiveHeader(name: string): boolean {
  return SENSITIVE_HEADERS.has(name.toLowerCase());
}

export function sanitizeUrl(raw: string): string {
  try {
    const u = new URL(raw);
    for (const [k] of [...u.searchParams.entries()]) {
      const lk = k.toLowerCase();
      if (SENSITIVE_QUERY_KEYS.some((s) => lk.includes(s))) {
        u.searchParams.set(k, "[REDACTED]");
      }
    }
    return u.toString();
  } catch {
    return raw;
  }
}

// Returns header map with sensitive VALUES replaced by [REDACTED].
// Keys (names) preserved so you can SEE which sensitive headers were present.
export function sanitizeHeaders(
  headers: Record<string, string>
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [name, value] of Object.entries(headers)) {
    out[name] = isSensitiveHeader(name) ? "[REDACTED]" : value;
  }
  return out;
}

// List of sensitive header names that were present (no values).
export function presentSensitiveHeaderNames(
  headers: Record<string, string>
): string[] {
  return Object.keys(headers).filter(isSensitiveHeader);
}
