import type { Page } from "playwright";

// Injected BEFORE page scripts. Wraps Blob-related APIs to observe how binary
// responses become Blob URLs. Originals preserved via Reflect.apply (correct `this`).
// Records METADATA + SHA-256 only. Blob bytes forwarded only when saveBlobs=true.
// No bypass, no webdriver tampering, no credential capture.

declare global {
  interface Window {
    __blobDiag: (payload: string) => void;
    __blobBytes: (id: string, b64: string, mime: string) => void;
  }
}

function initScript(saveBlobs: boolean): void {
  const emit = (ev: Record<string, unknown>) => {
    try {
      window.__blobDiag(JSON.stringify({ ts: Date.now(), ...ev }));
    } catch {
      /* binding not ready */
    }
  };

  const stack = () => {
    try {
      return new Error().stack?.split("\n").slice(2, 6).join(" | ") ?? "";
    } catch {
      return "";
    }
  };

  const sha256 = async (buf: ArrayBuffer): Promise<string> => {
    try {
      const d = await crypto.subtle.digest("SHA-256", buf);
      return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
    } catch {
      return "";
    }
  };

  let blobSeq = 0;

  // --- URL.createObjectURL ---
  const origCreate = URL.createObjectURL.bind(URL);
  URL.createObjectURL = function (obj: Blob | MediaSource): string {
    const url = Reflect.apply(origCreate, URL, [obj]) as string;
    if (obj instanceof Blob) {
      const id = "blob#" + ++blobSeq;
      emit({
        kind: "createObjectURL",
        id,
        blobUrl: url,
        mime: obj.type,
        size: obj.size,
        stack: stack(),
      });
      // SHA-256 (+ optional bytes) async, non-blocking.
      obj.arrayBuffer().then(async (ab) => {
        const hash = await sha256(ab);
        emit({ kind: "blobHash", id, blobUrl: url, sha256: hash, size: ab.byteLength });
        if (saveBlobs) {
          let bin = "";
          const bytes = new Uint8Array(ab);
          for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
          try { window.__blobBytes(id, btoa(bin), obj.type || "application/octet-stream"); } catch { /* */ }
        }
      });
    }
    return url;
  };

  // --- URL.revokeObjectURL ---
  const origRevoke = URL.revokeObjectURL.bind(URL);
  URL.revokeObjectURL = function (url: string): void {
    emit({ kind: "revokeObjectURL", blobUrl: url, stack: stack() });
    return Reflect.apply(origRevoke, URL, [url]);
  };

  // --- Response.prototype.blob (metadata only, use clone to not consume) ---
  const origBlob = Response.prototype.blob;
  Response.prototype.blob = function (this: Response): Promise<Blob> {
    let info: { url?: string; status?: number; type?: string } = {};
    try { info = { url: this.url, status: this.status, type: this.headers.get("content-type") || "" }; } catch { /* */ }
    emit({ kind: "responseBlob", ...info });
    return Reflect.apply(origBlob, this, []);
  };

  // --- window.fetch (metadata only) ---
  const origFetch = window.fetch;
  window.fetch = function (this: typeof window, ...args: Parameters<typeof fetch>): Promise<Response> {
    const input = args[0];
    const url = typeof input === "string" ? input : (input as Request).url ?? String(input);
    const method = (args[1]?.method) || (typeof input !== "string" ? (input as Request).method : "GET") || "GET";
    const t0 = performance.now();
    emit({ kind: "fetchStart", url, method });
    const p = Reflect.apply(origFetch, this, args) as Promise<Response>;
    p.then(
      (r) => emit({ kind: "fetchEnd", url, status: r.status, ms: Math.round(performance.now() - t0), contentType: r.headers.get("content-type") || "" }),
      (e) => emit({ kind: "fetchError", url, error: String(e) })
    );
    return p;
  };

  // --- XMLHttpRequest.open/send (metadata only) ---
  const origOpen = XMLHttpRequest.prototype.open;
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, ...a: any[]) {
    (this as any).__diag = { method: a[0], url: a[1] };
    return Reflect.apply(origOpen, this, a as any);
  };
  XMLHttpRequest.prototype.send = function (this: XMLHttpRequest, ...a: any[]) {
    const d = (this as any).__diag || {};
    emit({ kind: "xhrSend", url: d.url, method: d.method, respType: this.responseType });
    this.addEventListener("loadend", () => {
      emit({ kind: "xhrEnd", url: d.url, status: this.status, respType: this.responseType });
    });
    return Reflect.apply(origSend, this, a as any);
  };

  // --- HTMLImageElement.src setter (which element got a blob: URL) ---
  const desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, "src");
  if (desc && desc.set && desc.get) {
    const origSet = desc.set;
    Object.defineProperty(HTMLImageElement.prototype, "src", {
      configurable: true,
      enumerable: desc.enumerable,
      get: desc.get,
      set(this: HTMLImageElement, value: string) {
        if (typeof value === "string" && value.startsWith("blob:")) {
          emit({ kind: "imgSrc", blobUrl: value, id: this.id || null, className: this.className || null });
        }
        return Reflect.apply(origSet, this, [value]);
      },
    });
  }

  emit({ kind: "instrumented" });
}

export async function installInstrumentation(page: Page, saveBlobs: boolean): Promise<void> {
  await page.addInitScript(initScript, saveBlobs);
}
