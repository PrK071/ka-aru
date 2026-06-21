import { describe, it, expect } from "vitest";
import { buildReport } from "../src/report";

describe("buildReport", () => {
  const md = buildReport({
    targetUrl: "http://localhost:3000",
    net: [
      {
        url: "http://localhost:3000/api/chapter?id=1",
        method: "GET",
        status: 200,
        contentType: "image/webp",
        contentLength: 1024,
        resourceType: "fetch",
        durationMs: 42,
        initiator: "http://localhost:3000/",
        sensitiveHeaders: ["Cookie"],
        startedDateTime: "2026-01-01T00:00:00.000Z",
        keywordHit: true,
      },
    ],
    blobs: [
      { ts: 1, kind: "createObjectURL", id: "blob#1", blobUrl: "blob:x", mime: "image/webp", size: 1024 },
      { ts: 2, kind: "blobHash", id: "blob#1", sha256: "deadbeefdeadbeefdeadbeef" },
    ],
    wsFrames: [],
    errors: [],
    savedFiles: [],
  });

  it("includes banner + target", () => {
    expect(md).toContain("diagnóstico autorizada");
    expect(md).toContain("http://localhost:3000");
  });
  it("lists keyword endpoint", () => {
    expect(md).toContain("/api/chapter");
  });
  it("redacts sensitive header names only", () => {
    expect(md).toContain("Cookie: [REDACTED]");
  });
  it("shows blob lifecycle + probable source by size", () => {
    expect(md).toContain("blob#1");
    expect(md).toContain("1024B");
  });
});
