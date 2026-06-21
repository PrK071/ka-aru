import { describe, it, expect } from "vitest";
import {
  sanitizeUrl,
  sanitizeHeaders,
  isSensitiveHeader,
  presentSensitiveHeaderNames,
} from "../src/sanitizer";

describe("sanitizeUrl", () => {
  it("redacts sensitive query params", () => {
    const out = sanitizeUrl("https://x.test/a?token=abc&auth=zzz&page=2");
    expect(out).toContain("token=%5BREDACTED%5D");
    expect(out).toContain("auth=%5BREDACTED%5D");
    expect(out).toContain("page=2");
  });
  it("keeps non-sensitive params", () => {
    expect(sanitizeUrl("https://x.test/a?page=5&id=10")).toContain("page=5");
  });
  it("returns raw on invalid url", () => {
    expect(sanitizeUrl("blob:abc")).toBe("blob:abc");
  });
});

describe("headers", () => {
  it("flags sensitive header names", () => {
    expect(isSensitiveHeader("Cookie")).toBe(true);
    expect(isSensitiveHeader("authorization")).toBe(true);
    expect(isSensitiveHeader("Set-Cookie")).toBe(true);
    expect(isSensitiveHeader("Accept")).toBe(false);
  });
  it("redacts sensitive values but keeps names", () => {
    const out = sanitizeHeaders({ Cookie: "sess=secret", Accept: "text/html" });
    expect(out.Cookie).toBe("[REDACTED]");
    expect(out.Accept).toBe("text/html");
  });
  it("lists present sensitive names", () => {
    const names = presentSensitiveHeaderNames({ Authorization: "Bearer x", Accept: "*/*" });
    expect(names).toContain("Authorization");
    expect(names).not.toContain("Accept");
  });
});
