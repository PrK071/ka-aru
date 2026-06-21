# manga_dataset

Raspador modular de mangás/webtoons que **re-hospeda as imagens no Hugging Face**
(Git LFS) e cataloga tudo num **SQLite** (`mangas.db`) — pronto pra publicar no
GitHub e a comunidade consumir via código.

Fluxo por página (nunca acumula no HD): **download temp → upload HF → URL pública
→ grava no SQLite → apaga o temp**. Idempotente (re-rodar não duplica).

## Estrutura

```
manga_dataset/
├── config.py          # env (HF_TOKEN, repo, paths) + autoload .env
├── database.py        # SQLite + slugify + normalize_chapter
├── uploader.py        # HuggingFaceUploader (Git LFS, retries)
├── crawler.py         # motor: CLI, --mock, --dry-run, idempotência
├── requirements.txt
├── .env.example
└── scrapers/
    ├── __init__.py        # registry (@register / get_scraper)
    ├── base.py            # BaseScraper + MangaRef/ChapterRef/PageRef + download (HTTP)
    ├── browser_base.py    # PlaywrightScraper (base opcional p/ navegador)
    ├── mangadex.py        # API JSON
    ├── mangakatana.py     # HTML + array JS (thzq)
    ├── mangasbrasuka.py   # WordPress/Madara + AJAX/CDN
    ├── mangalivre.py      # WordPress + Cloudflare (curl_cffi)
    ├── toomics.py         # Webtoon vertical (POST episódios)
    └── dragontea.py       # Madara + Cloudflare (Playwright headful + perfil)
```

## Tabela `pages`

| coluna | tipo | nota |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| manga_name | TEXT | nome como na fonte |
| manga_slug | TEXT | padronizado (unifica fontes) |
| chapter | TEXT | normalizado: `"01"`→`"1"`, mantém `"10.5"` |
| page_number | INTEGER | |
| url_image | TEXT | URL pública no Hugging Face |
| source | TEXT | nome da fonte |
| scraped_at | TIMESTAMP | UTC |

`UNIQUE(manga_slug, source, chapter, page_number)` → idempotência.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # edite HF_TOKEN e HF_DATASET_REPO
python database.py          # cria mangas.db e testa o slugify
```

## Uso

`--manga-url` é a forma mais prática no dia a dia: aponta direto pra obra e pula
o `iter_mangas` (funciona em todas as fontes).

```bash
# 1) Demo 100% offline (sem rede, sem HF)
python crawler.py --mock

# 2) DRY-RUN por URL direta: baixa de verdade, grava no SQLite, NÃO sobe no HF
python crawler.py --source MangaKatana --dry-run --manga-url "<url-da-obra>" --max-chapters 1 --max-pages 5

# 3) Sem URL: usa o iter_mangas (diretório da fonte)
python crawler.py --source MangaKatana --dry-run --max-mangas 2 --max-chapters 1

# 4) REAL: sobe as imagens no Hugging Face (precisa HF_TOKEN)
python crawler.py --source MangaKatana --manga-url "<url-da-obra>"
```

Flags: `--source`, `--manga-url`, `--mock`, `--dry-run`, `--max-mangas`,
`--max-chapters`, `--max-pages`.

## Fontes

| Fonte | Arquitetura | Transporte |
|---|---|---|
| MangaDex | API JSON (/at-home) | HTTP |
| MangaKatana | HTML + array JS `thzq` | HTTP |
| MangasBrasuka | WordPress/Madara + AJAX, 1 img/capítulo | HTTP |
| MangaLivre | WordPress + Cloudflare (curl_cffi impersonate) | HTTP |
| Toomics | Webtoon vertical, POST episódios, ignora VIP | HTTP |
| DragonTea | WordPress/Madara + Cloudflare agressivo + lazy JS | **Navegador (Playwright)** |

Filosofia: **HTTP puro por padrão** (requests/curl_cffi, rápido). Navegador
headless só como exceção, isolado em `scrapers/browser_base.py` — os outros 5
não dependem de Playwright.

### DragonTea (navegador)

```bash
pip install playwright && playwright install chromium
```

Usa janela visível + perfil persistente (`.dragontea-profile/`). Na **1ª
execução**, resolva o "Just a moment" do Cloudflare na janela; o `cf_clearance`
fica salvo e as próximas execuções passam direto.

## Adicionar uma fonte

HTTP: crie `scrapers/<site>.py` com subclasse de `BaseScraper`. Se precisar de
navegador, herde de `PlaywrightScraper` (`browser_base.py`). Decore com
`@register` e inclua o nome do módulo no loop em `scrapers/__init__.py`.
Nada no motor muda.

## Aviso

Respeite `robots.txt`, Termos de Uso e rate-limit de cada site. Use rate-limit/
delays no scrape em massa. Algumas fontes servem URLs com token que expiram —
por isso o re-host no Hugging Face.
