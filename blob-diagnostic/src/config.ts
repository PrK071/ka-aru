// Env-driven config. Loads .env manually (no extra dep needed).
import * as fs from "fs";
import * as path from "path";
import { parseAllowedHosts } from "./allowlist";

function loadDotEnv(): void {
  const p = path.resolve(process.cwd(), ".env");
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, "utf-8").split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("#")) continue;
    const eq = t.indexOf("=");
    if (eq < 0) continue;
    const k = t.slice(0, eq).trim();
    const v = t.slice(eq + 1).trim();
    if (!(k in process.env)) process.env[k] = v;
  }
}

export interface Config {
  targetUrl: string;
  allowedHosts: Set<string>;
  outputDir: string;
  timeoutMs: number;
  saveBlobs: boolean;
  report: boolean;
}

export function loadConfig(argv: string[]): Config {
  loadDotEnv();
  const targetUrl = process.env.TARGET_URL || "http://localhost:3000";
  return {
    targetUrl,
    allowedHosts: parseAllowedHosts(process.env.ALLOWED_HOSTS),
    outputDir: path.resolve(process.env.OUTPUT_DIR || "./out"),
    timeoutMs: Number(process.env.TIMEOUT_MS || 30000),
    saveBlobs: (process.env.SAVE_BLOBS || "true").toLowerCase() === "true",
    report: argv.includes("--report"),
  };
}
