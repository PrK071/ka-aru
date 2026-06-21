# blob-diagnostic

Ferramenta de diagnóstico **autorizada**. Observa como respostas HTTP binárias viram
`Blob` Object URLs num leitor de imagens. **Somente localhost / 127.0.0.1 / ALLOWED_HOSTS.**

## O que NÃO faz (por design)

- Sem bypass de Cloudflare/WAF/CAPTCHA.
- Sem evasão de automação / spoof de `navigator.webdriver`.
- Sem replay/forja de token, sem quebra de cripto, sem brute force.
- Sem reutilização de cookie de terceiro, sem downloader em massa, sem scraping de capítulo.
- **Valores** de credenciais (`Cookie`, `Authorization`, `Set-Cookie`, CSRF, assinaturas)
  nunca são gravados — só os **nomes**, com valor `[REDACTED]`.

Roda **só** em host da allowlist. Fora dela → recusa antes de navegar.

## Instalação

```bash
cd blob-diagnostic
npm install          # baixa Playwright + chromium (postinstall)
cp .env.example .env # ajuste TARGET_URL / ALLOWED_HOSTS / OUTPUT_DIR
```

## Build & Run

```bash
npm run build
npm start -- --report
```

Ou dev sem build:

```bash
npm run dev -- --report
```

## Exemplo (somente localhost)

`.env`:

```
TARGET_URL=http://localhost:3000
ALLOWED_HOSTS=
OUTPUT_DIR=./out
TIMEOUT_MS=30000
SAVE_BLOBS=true
```

```bash
npm start -- --report
```

Saída em `./out/`:
- `session.har` — HAR sanitizado (valores sensíveis `[REDACTED]`)
- `events.ndjson` — logs estruturados JSON (uma linha por evento)
- `blobs/` — bytes dos Blobs decodificados (`blob#1.webp`, ...)
- `report.md` — relatório Markdown (com `--report`)

Apontar pra host fora da allowlist:

```
FATAL: Refused: host "sakuramangas.org" not in allowlist. Allowed: localhost, 127.0.0.1, ::1, [::1]
```

## Arquitetura

| Arquivo | Papel |
|---------|-------|
| `config.ts` | Carrega `.env` + flags (`--report`) |
| `allowlist.ts` | Gate rígido de hostname (refuse off-list) |
| `sanitizer.ts` | Redige query params + valores de header sensíveis |
| `logger.ts` | Log NDJSON estruturado + stdout |
| `browser-instrumentation.ts` | `addInitScript` envolve `fetch`/XHR/`createObjectURL`/`revokeObjectURL`/`Response.blob`/`img.src`. Originais preservados via `Reflect.apply`. Só metadata + SHA-256 |
| `network-monitor.ts` | `page.on` para fetch/xhr/image/media/websocket → registros sanitizados + HAR |
| `har-writer.ts` | HAR 1.2 sanitizado |
| `report.ts` | Relatório Markdown (timeline, endpoints, MIME, ciclo de Blob, headers, erros) |
| `index.ts` | Orquestra: gate → launch chromium (headless:false) → bindings → navega → coleta → artefatos → shutdown |

Bindings `__blobDiag` (metadata) e `__blobBytes` (bytes opcionais) passam dados da
página pro Node. `clone()`/leitura assíncrona evita consumir a resposta da aplicação.

## Testes

```bash
npm test
```

Cobre: allowlist, sanitização de URL, redação de header, geração de relatório.
