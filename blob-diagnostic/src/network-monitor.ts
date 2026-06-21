// Observes fetch/xhr/image/media/websocket network flow via Playwright.
// Records sanitized metadata only. No request/response mutation, no replay.
import type { Page, Request, Response, WebSocket } from "playwright";
import { Logger } from "./logger";
import { HarWriter } from "./har-writer";
import { sanitizeUrl, sanitizeHeaders, presentSensitiveHeaderNames } from "./sanitizer";

const KEYWORDS = ["capitulo", "chapter", "info", "read", "image"];
const WATCHED = new Set(["fetch", "xhr", "image", "media", "websocket"]);

export interface NetRecord {
  url: string;
  method: string;
  status: number;
  contentType: string;
  contentLength: number;
  resourceType: string;
  durationMs: number;
  initiator: string;
  sensitiveHeaders: string[];
  startedDateTime: string;
  keywordHit: boolean;
}

export class NetworkMonitor {
  public records: NetRecord[] = [];
  public wsFrames: { url: string; dir: string; size: number; binary: boolean }[] = [];
  private starts = new Map<Request, number>();

  constructor(private page: Page, private log: Logger, private har: HarWriter) {}

  attach(): void {
    this.page.on("request", (req) => this.starts.set(req, Date.now()));
    this.page.on("requestfailed", (req) =>
      this.log.warn("requestFailed", { url: sanitizeUrl(req.url()), error: req.failure()?.errorText })
    );
    this.page.on("response", (res) => this.onResponse(res).catch(() => { /* ignore */ }));
    this.page.on("websocket", (ws) => this.onWebSocket(ws));
  }

  private async onResponse(res: Response): Promise<void> {
    const req = res.request();
    const rtype = req.resourceType();
    if (!WATCHED.has(rtype)) return;

    const t0 = this.starts.get(req) ?? Date.now();
    const reqHeaders = await safeHeaders(req);
    const resHeaders = await safeHeaders(res);
    const url = req.url();
    const ct = resHeaders["content-type"] || "";
    const cl = Number(resHeaders["content-length"] || 0);
    const rec: NetRecord = {
      url: sanitizeUrl(url),
      method: req.method(),
      status: res.status(),
      contentType: ct,
      contentLength: cl,
      resourceType: rtype,
      durationMs: Date.now() - t0,
      initiator: safeInitiator(req),
      sensitiveHeaders: [
        ...presentSensitiveHeaderNames(reqHeaders),
        ...presentSensitiveHeaderNames(resHeaders).map((h) => "res:" + h),
      ],
      startedDateTime: new Date(t0).toISOString(),
      keywordHit: KEYWORDS.some((k) => url.toLowerCase().includes(k)),
    };
    this.records.push(rec);
    this.har.add({
      url,
      method: rec.method,
      status: rec.status,
      reqHeaders: sanitizeHeaders(reqHeaders),
      resHeaders: sanitizeHeaders(resHeaders),
      resourceType: rtype,
      contentType: ct,
      contentLength: cl,
      startedDateTime: rec.startedDateTime,
      durationMs: rec.durationMs,
    });
    this.log.info("response", {
      url: rec.url,
      method: rec.method,
      status: rec.status,
      type: rtype,
      contentType: ct,
      contentLength: cl,
      ms: rec.durationMs,
      sensitiveHeaders: rec.sensitiveHeaders,
      keywordHit: rec.keywordHit,
    });
  }

  private onWebSocket(ws: WebSocket): void {
    const url = sanitizeUrl(ws.url());
    this.log.info("wsOpen", { url });
    ws.on("framereceived", (d) => this.recordFrame(url, "recv", d.payload));
    ws.on("framesent", (d) => this.recordFrame(url, "sent", d.payload));
    ws.on("close", () => this.log.info("wsClose", { url }));
  }

  private recordFrame(url: string, dir: string, payload: string | Buffer): void {
    const binary = Buffer.isBuffer(payload);
    const size = binary ? (payload as Buffer).length : Buffer.byteLength(payload as string);
    this.wsFrames.push({ url, dir, size, binary });
    this.log.debug("wsFrame", { url, dir, size, binary });
  }
}

async function safeHeaders(o: Request | Response): Promise<Record<string, string>> {
  try {
    return await o.allHeaders();
  } catch {
    return {};
  }
}

function safeInitiator(req: Request): string {
  try {
    // Playwright doesn't expose full initiator; use frame URL as proxy.
    return sanitizeUrl(req.frame().url());
  } catch {
    return "";
  }
}
