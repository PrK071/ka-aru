// Minimal sanitized HAR 1.2 writer. Sensitive header values -> [REDACTED].
import * as fs from "fs";
import { sanitizeUrl, isSensitiveHeader } from "./sanitizer";

export interface HarEntryInput {
  url: string;
  method: string;
  status: number;
  reqHeaders: Record<string, string>;
  resHeaders: Record<string, string>;
  resourceType: string;
  contentType: string;
  contentLength: number;
  startedDateTime: string;
  durationMs: number;
}

function toHeaderArray(h: Record<string, string>) {
  return Object.entries(h).map(([name, value]) => ({
    name,
    value: isSensitiveHeader(name) ? "[REDACTED]" : value,
  }));
}

export class HarWriter {
  private entries: any[] = [];

  add(e: HarEntryInput): void {
    this.entries.push({
      startedDateTime: e.startedDateTime,
      time: e.durationMs,
      request: {
        method: e.method,
        url: sanitizeUrl(e.url),
        httpVersion: "HTTP/1.1",
        headers: toHeaderArray(e.reqHeaders),
        queryString: [],
        cookies: [],
        headersSize: -1,
        bodySize: -1,
      },
      response: {
        status: e.status,
        statusText: "",
        httpVersion: "HTTP/1.1",
        headers: toHeaderArray(e.resHeaders),
        cookies: [],
        content: { size: e.contentLength, mimeType: e.contentType },
        redirectURL: "",
        headersSize: -1,
        bodySize: e.contentLength,
      },
      cache: {},
      timings: { send: 0, wait: e.durationMs, receive: 0 },
      _resourceType: e.resourceType,
    });
  }

  write(filePath: string): void {
    const har = {
      log: {
        version: "1.2",
        creator: { name: "blob-diagnostic", version: "1.0.0" },
        entries: this.entries,
      },
    };
    fs.writeFileSync(filePath, JSON.stringify(har, null, 2), "utf-8");
  }
}
