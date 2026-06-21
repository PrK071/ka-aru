import { describe, it, expect } from "vitest";
import { parseAllowedHosts, isHostAllowed, assertAllowed } from "../src/allowlist";

describe("allowlist", () => {
  it("always allows localhost + 127.0.0.1", () => {
    const a = parseAllowedHosts(undefined);
    expect(isHostAllowed("http://localhost:3000", a)).toBe(true);
    expect(isHostAllowed("http://127.0.0.1:8080/x", a)).toBe(true);
  });

  it("allows hosts from env list", () => {
    const a = parseAllowedHosts("staging.exemplo.local, foo.test");
    expect(isHostAllowed("https://staging.exemplo.local/page", a)).toBe(true);
    expect(isHostAllowed("https://foo.test", a)).toBe(true);
  });

  it("refuses off-list hosts", () => {
    const a = parseAllowedHosts("staging.exemplo.local");
    expect(isHostAllowed("https://sakuramangas.org/", a)).toBe(false);
    expect(isHostAllowed("https://google.com", a)).toBe(false);
  });

  it("refuses invalid URLs", () => {
    const a = parseAllowedHosts(undefined);
    expect(isHostAllowed("not a url", a)).toBe(false);
  });

  it("assertAllowed throws off-list", () => {
    const a = parseAllowedHosts(undefined);
    expect(() => assertAllowed("https://evil.example", a)).toThrow(/not in allowlist/);
    expect(() => assertAllowed("http://localhost", a)).not.toThrow();
  });
});
