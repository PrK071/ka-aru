// Markdown report generator. All URLs/headers already sanitized upstream.
import * as fs from "fs";
import { NetRecord } from "./network-monitor";

export interface BlobEvent {
  ts: number;
  kind: string;
  id?: string;
  blobUrl?: string;
  mime?: string;
  size?: number;
  sha256?: string;
  stack?: string;
  className?: string | null;
}

export interface ReportInput {
  targetUrl: string;
  net: NetRecord[];
  blobs: BlobEvent[];
  wsFrames: { url: string; dir: string; size: number; binary: boolean }[];
  errors: string[];
  savedFiles: { id: string; file: string; sha256: string }[];
}

// Best-effort link: a blobHash sha256 has no direct tie to a network response
// (bytes may be transformed in-page). We correlate by content-length proximity.
function probableSources(blob: BlobEvent, net: NetRecord[]): string[] {
  if (!blob.size) return [];
  return net
    .filter((n) => n.contentLength > 0 && Math.abs(n.contentLength - blob.size!) <= 64)
    .map((n) => `${n.method} ${n.url} (${n.contentLength}B)`)
    .slice(0, 3);
}

export function buildReport(inp: ReportInput): string {
  const L: string[] = [];
  L.push(`# Blob Diagnostic Report`);
  L.push(``);
  L.push(`> Ferramenta de diagnóstico autorizada. Somente localhost/ALLOWED_HOSTS.`);
  L.push(``);
  L.push(`**Target:** ${inp.targetUrl}`);
  L.push(`**Generated:** ${new Date().toISOString()}`);
  L.push(``);

  L.push(`## Load Timeline (network)`);
  L.push(``);
  L.push(`| time | type | method | status | content-type | bytes | ms |`);
  L.push(`|------|------|--------|--------|--------------|-------|----|`);
  for (const n of inp.net) {
    L.push(`| ${n.startedDateTime.split("T")[1] ?? ""} | ${n.resourceType} | ${n.method} | ${n.status} | ${n.contentType} | ${n.contentLength} | ${n.durationMs} |`);
  }
  L.push(``);

  L.push(`## Endpoints (keyword hits: capitulo/chapter/info/read/image)`);
  L.push(``);
  const hits = inp.net.filter((n) => n.keywordHit);
  if (!hits.length) L.push(`_none_`);
  for (const n of hits) L.push(`- \`${n.method}\` ${n.url}`);
  L.push(``);

  L.push(`## MIME types observed`);
  L.push(``);
  const mimes = new Map<string, number>();
  for (const n of inp.net) mimes.set(n.contentType || "?", (mimes.get(n.contentType || "?") || 0) + 1);
  for (const [m, c] of mimes) L.push(`- ${m}: ${c}`);
  L.push(``);

  L.push(`## Blob URL lifecycle`);
  L.push(``);
  const created = inp.blobs.filter((b) => b.kind === "createObjectURL");
  const revoked = inp.blobs.filter((b) => b.kind === "revokeObjectURL");
  L.push(`- created: ${created.length}, revoked: ${revoked.length}`);
  L.push(``);
  L.push(`| id | mime | size | sha256 (short) | probable source(s) |`);
  L.push(`|----|------|------|----------------|--------------------|`);
  for (const b of created) {
    const hash = inp.blobs.find((x) => x.kind === "blobHash" && x.id === b.id)?.sha256 || "";
    const src = probableSources(b, inp.net).join("<br>") || "—";
    L.push(`| ${b.id} | ${b.mime || ""} | ${b.size || 0} | ${hash.slice(0, 16)} | ${src} |`);
  }
  L.push(``);

  if (inp.savedFiles.length) {
    L.push(`## Saved blob files`);
    L.push(``);
    for (const s of inp.savedFiles) L.push(`- ${s.id} -> \`${s.file}\` (sha256 ${s.sha256.slice(0, 16)})`);
    L.push(``);
  }

  if (inp.wsFrames.length) {
    L.push(`## WebSocket frames`);
    L.push(``);
    L.push(`| url | dir | size | binary |`);
    L.push(`|-----|-----|------|--------|`);
    for (const f of inp.wsFrames) L.push(`| ${f.url} | ${f.dir} | ${f.size} | ${f.binary} |`);
    L.push(``);
  }

  L.push(`## Sensitive headers present (names only, values [REDACTED])`);
  L.push(``);
  const names = new Set<string>();
  for (const n of inp.net) n.sensitiveHeaders.forEach((h) => names.add(h));
  if (!names.size) L.push(`_none_`);
  for (const h of names) L.push(`- ${h}: [REDACTED]`);
  L.push(``);

  L.push(`## Errors`);
  L.push(``);
  if (!inp.errors.length) L.push(`_none_`);
  for (const e of inp.errors) L.push(`- ${e}`);
  L.push(``);

  return L.join("\n");
}

export function writeReport(filePath: string, inp: ReportInput): void {
  fs.writeFileSync(filePath, buildReport(inp), "utf-8");
}
