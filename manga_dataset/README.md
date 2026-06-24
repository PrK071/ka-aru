# manga_dataset

Subprojeto do [Kari](https://github.com/PrK071/Kari).

Raspador modular de mangás/webtoons que **re-hospeda as imagens no Hugging Face**
(Git LFS) e cataloga tudo num **SQLite** (`mangas.db`) — pronto pra publicar e a
comunidade consumir via código.

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
    ├── __init__.py        # registry + auto-descoberta de scrapers
    ├── base.py            # BaseScraper + MangaRef/ChapterRef/PageRef + download (HTTP)
    ├── browser_base.py    # PlaywrightScraper (base opcional p/ navegador)
    └── example_source.py  # template (copie para criar a sua fonte)
```

> Os scrapers de fontes específicas são **plugáveis**: qualquer `scrapers/*.py`
> que registre uma classe com `@register` é carregado automaticamente. Eles
> podem ficar **fora do versionamento** (ver `.gitignore`) — o núcleo público
> não depende de nenhuma fonte em particular.

## Tabela `pages`

| coluna | tipo | nota |
|---|---|---|
| id | INTEGER PK AUTOINCREMENT | |
| manga_name | TEXT | nome como na fonte |
| manga_slug | TEXT | padronizado (unifica fontes) |
| chapter | TEXT | normalizado: `"01"`→`"1"`, mantém `"10.5"` |
| page_number | INTEGER | |
| url_image | TEXT | URL pública no Hugging Face |
| source | TEXT | rótulo da fonte |
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
o `iter_mangas` (funciona em qualquer fonte). `python crawler.py` (sem args)
lista as fontes registradas localmente.

```bash
# 1) Demo 100% offline (sem rede, sem HF)
python crawler.py --mock

# 2) DRY-RUN por URL: baixa de verdade, grava no SQLite, NÃO sobe no HF
python crawler.py --source <Fonte> --dry-run --manga-url "<url-da-obra>" --max-chapters 1 --max-pages 5

# 3) REAL: sobe as imagens no Hugging Face (precisa HF_TOKEN)
python crawler.py --source <Fonte> --manga-url "<url-da-obra>"
```

Flags: `--source`, `--manga-url`, `--mock`, `--dry-run`, `--max-mangas`,
`--max-chapters`, `--max-pages`.

## Arquiteturas suportadas

O `BaseScraper` cobre fontes via **HTTP puro** (requests/curl_cffi — rápido).
Fontes que exigem **navegador** (JS pesado / proteção anti-bot) herdam de
`PlaywrightScraper` (`browser_base.py`), isolado — o núcleo HTTP não depende dele.

Padrões já exercitados pela interface: API JSON, HTML estático, HTML + array JS,
sites WordPress com listagem via AJAX, sites atrás de Cloudflare (HTTP com
impersonate ou navegador headless) e leitores verticais (webtoon).

## Adicionar uma fonte

Copie `scrapers/example_source.py` para `scrapers/<sua_fonte>.py`, implemente
`iter_mangas` / `iter_chapters` / `iter_pages`, decore com `@register`. Se
precisar de navegador, herde de `PlaywrightScraper`. Nada no motor muda.

## Aviso

Respeite `robots.txt`, Termos de Uso e rate-limit de cada fonte. Algumas servem
URLs com token que expiram — por isso o re-host no Hugging Face.
