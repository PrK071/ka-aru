// Hard hostname allowlist. Off-list = refuse. No "run anywhere" escape hatch.

const ALWAYS_ALLOWED = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

export function parseAllowedHosts(raw: string | undefined): Set<string> {
  const set = new Set<string>(ALWAYS_ALLOWED);
  if (raw) {
    for (const h of raw.split(",")) {
      const t = h.trim().toLowerCase();
      if (t) set.add(t);
    }
  }
  return set;
}

export function hostnameOf(url: string): string {
  // Throws on invalid URL -> caller treats as not allowed.
  return new URL(url).hostname.toLowerCase();
}

export function isHostAllowed(url: string, allowed: Set<string>): boolean {
  let host: string;
  try {
    host = hostnameOf(url);
  } catch {
    return false;
  }
  return allowed.has(host);
}

export function assertAllowed(url: string, allowed: Set<string>): void {
  if (!isHostAllowed(url, allowed)) {
    const host = (() => {
      try {
        return hostnameOf(url);
      } catch {
        return "<invalid-url>";
      }
    })();
    throw new Error(
      `Refused: host "${host}" not in allowlist. Allowed: ${[...allowed].join(", ")}`
    );
  }
}
