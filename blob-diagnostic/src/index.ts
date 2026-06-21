// Authorized Blob-URL diagnostic. localhost/ALLOWED_HOSTS only.
// No bypass. No webdriver tampering. No credential capture. No scraper.
import * as fs from "fs";
import * as path from "path";
import * as crypto from "crypto";
import { chromium } from "playwright";
import { loadConfig } from "./config";
import { assertAllowed } from "./allowlist";
import { Logger } from "./logger";
import { HarWriter } from "./har-writer";
import { NetworkMonitor } from "./network-monitor";
import { installInstrumentation } from "./browser-instrumentation";
import { BlobEvent, writeReport } from "./report";

const BANNER = "Ferramenta de diagnóstico autorizada. Somente localhost/ALLOWED_HOSTS.";

function extFromMime(mime: string): string {
  if (mime.includes("png")) return "png";
  if (mime.includes("webp")) return "webp";
  if (mime.includes("gif")) return "gif";
  if (mime.includes("jpeg") || mime.includes("jpg")) return "jpg";
  return "bin";
}

async function main(): Promise<void> {
  // eslint-disable-next-line no-console
  console.log("=".repeat(60) + "\n" + BANNER + "\n" + "=".repeat(60));

  const cfg = loadConfig(process.argv.slice(2));

  // HARD allowlist gate BEFORE any navigation.
  assertAllowed(cfg.targetUrl, cfg.allowedHosts);

  fs.mkdirSync(cfg.outputDir, { recursive: true });
  const blobDir = path.join(cfg.outputDir, "blobs");
  fs.mkdirSync(blobDir, { recursive: true });

  const log = new Logger(path.join(cfg.outputDir, "events.ndjson"));
  log.info("start", { target: cfg.targetUrl, allowed: [...cfg.allowedHosts] });

  const har = new HarWriter();
  const blobs: BlobEvent[] = [];
  const errors: string[] = [];
  const savedFiles: { id: string; file: string; sha256: string }[] = [];

  const browser = await chromium.launch({ headless: false });
  const context = await browser.newContext();

  // Binding: metadata events from instrumented page.
  await context.exposeFunction("__blobDiag", (payload: string) => {
    try {
      const ev = JSON.parse(payload) as BlobEvent;
      blobs.push(ev);
      log.info("blobEvent", ev as unknown as Record<string, unknown>);
    } catch (e) {
      errors.push("blobDiag parse: " + String(e));
    }
  });

  // Binding: optional blob bytes -> save file (allowlisted origin only).
  await context.exposeFunction("__blobBytes", (id: string, b64: string, mime: string) => {
    if (!cfg.saveBlobs) return;
    try {
      const buf = Buffer.from(b64, "base64");
      const sha = crypto.createHash("sha256").update(buf).digest("hex");
      const file = path.join(blobDir, `${id.replace(/[^\w.#-]/g, "_")}.${extFromMime(mime)}`);
      fs.writeFileSync(file, buf);
      savedFiles.push({ id, file, sha256: sha });
      log.info("blobSaved", { id, file, sha256: sha, bytes: buf.length });
    } catch (e) {
      errors.push("blobBytes save: " + String(e));
    }
  });

  const page = await context.newPage();
  await installInstrumentation(page, cfg.saveBlobs);

  const monitor = new NetworkMonitor(page, log, har);
  monitor.attach();

  page.on("console", (m) => log.debug("pageConsole", { type: m.type(), text: m.text() }));
  page.on("pageerror", (e) => { errors.push("pageerror: " + e.message); log.error("pageError", { message: e.message }); });

  try {
    await page.goto(cfg.targetUrl, { waitUntil: "domcontentloaded", timeout: cfg.timeoutMs });
    await page.waitForLoadState("networkidle", { timeout: cfg.timeoutMs }).catch(() => log.warn("networkidleTimeout"));
    // settle window for late blobs
    await page.waitForTimeout(2000);
  } catch (e) {
    errors.push("navigation: " + String(e));
    log.error("navigationError", { error: String(e) });
  }

  // Artifacts
  har.write(path.join(cfg.outputDir, "session.har"));
  if (cfg.report) {
    writeReport(path.join(cfg.outputDir, "report.md"), {
      targetUrl: cfg.targetUrl,
      net: monitor.records,
      blobs,
      wsFrames: monitor.wsFrames,
      errors,
      savedFiles,
    });
    log.info("reportWritten");
  }

  log.info("summary", {
    requests: monitor.records.length,
    blobsCreated: blobs.filter((b) => b.kind === "createObjectURL").length,
    filesSaved: savedFiles.length,
    errors: errors.length,
  });

  await context.close();
  await browser.close();
  await log.close();
  // eslint-disable-next-line no-console
  console.log(`Done. Artifacts in ${cfg.outputDir}`);
}

main().catch((e) => {
  // eslint-disable-next-line no-console
  console.error("FATAL:", e.message);
  process.exit(1);
});
