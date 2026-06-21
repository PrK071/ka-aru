// Structured JSON logger. Writes NDJSON to file + pretty line to stdout.
import * as fs from "fs";

export type LogLevel = "info" | "warn" | "error" | "debug";

export class Logger {
  private stream: fs.WriteStream;

  constructor(filePath: string) {
    this.stream = fs.createWriteStream(filePath, { flags: "a" });
  }

  log(level: LogLevel, event: string, data: Record<string, unknown> = {}): void {
    const rec = { ts: new Date().toISOString(), level, event, ...data };
    this.stream.write(JSON.stringify(rec) + "\n");
    const tag = level.toUpperCase().padEnd(5);
    // eslint-disable-next-line no-console
    console.log(`[${rec.ts}] ${tag} ${event}`, Object.keys(data).length ? data : "");
  }

  info(e: string, d?: Record<string, unknown>) { this.log("info", e, d); }
  warn(e: string, d?: Record<string, unknown>) { this.log("warn", e, d); }
  error(e: string, d?: Record<string, unknown>) { this.log("error", e, d); }
  debug(e: string, d?: Record<string, unknown>) { this.log("debug", e, d); }

  close(): Promise<void> {
    return new Promise((res) => this.stream.end(res));
  }
}
