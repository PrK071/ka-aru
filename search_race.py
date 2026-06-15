"""search_race.py — busca um manga em todas as fontes ao mesmo tempo e
retorna a que responder mais rapido com resultado relevante.

Modo padrao (sem --all):
  Retorna assim que a PRIMEIRA fonte bater o limiar de qualidade (>=0.86).
  Se nenhuma bater esse limiar no tempo limite, retorna a melhor das que
  responderam dentro de SEARCH_TOTAL_TIMEOUT.

Uso:
    python search_race.py "Soul Eater"
    python search_race.py "Chainsaw Man" --all
    python search_race.py "Berserk" --json
    python search_race.py "One Piece" --timeout 12
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urljoin, urlparse

import requests

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Score considerado "bom o suficiente" para retorno imediato
GOOD_SCORE: float = 0.86
# Relevância mínima para qualquer hit ser válido
MIN_RELEVANCE: float = 0.48
# Relevância mínima do piecePROJECT
PIECEPROJECT_MIN_RELEVANCE: float = 0.55
# Score mínimo para piecePROJECT entrar na corrida
PIECEPROJECT_RACE_SCORE: float = 0.55
# Timeout total da corrida (segundos) quando nenhum bate GOOD_SCORE
SEARCH_TOTAL_TIMEOUT: float = 8.0
# Workers máximos em paralelo
MAX_WORKERS: int = 8

# Fontes excluídas da corrida automática
EXCLUDED_KINDS: frozenset[str] = frozenset({"mangakatana"})
# Fontes legadas (ocultas do carregamento de sites)
LEGACY_KINDS: frozenset[str] = frozenset({"noveltoon"})

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

SITES_FILE = Path(__file__).resolve().parent / "reader_sites.json"

DEFAULT_SITES: dict = {
    "sites": [
        {
            "name": "MangaDex",
            "kind": "mangadex",
            "base_url": "https://mangadex.org",
            "manga_url_template": "https://mangadex.org/title/{slug}",
            "default_lang": "pt-br",
        },
        {
            "name": "One Piece Project",
            "kind": "pieceproject",
            "base_url": "https://scan.onepieceproject.com.br/",
            "manga_url_template": "pieceproject://one-piece",
            "default_lang": "pt-br",
        },
        {
            "name": "ReadFull",
            "kind": "readfull",
            "base_url": "https://readfullapi.herokuapp.com",
            "manga_url_template": "readfull://novel/{slug}",
            "default_lang": "en",
        },
        {
            "name": "DragonTea",
            "kind": "dragontea",
            "base_url": "https://dragontea.ink",
            "manga_url_template": "https://dragontea.ink/{slug}",
            "default_lang": "pt-br",
        },
    ]
}


# ---------------------------------------------------------------------------
# Dataclass de resultado
# ---------------------------------------------------------------------------

@dataclass
class RaceHit:
    site: dict
    elapsed: float
    title: str
    url: str
    relevance: float

    def display(self, rank: int | None = None) -> str:
        prefix = f"#{rank}" if rank is not None else "→"
        lines = [
            f"{prefix}  [{self.site['name']}]  {self.title}",
            f"    URL       : {self.url}",
            f"    Relevancia: {self.relevance:.0%}",
            f"    Tempo     : {self.elapsed:.2f}s",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "site": self.site["name"],
            "site_kind": self.site.get("kind"),
            "title": self.title,
            "url": self.url,
            "relevance": round(self.relevance, 4),
            "elapsed_seconds": round(self.elapsed, 3),
        }


# ---------------------------------------------------------------------------
# Carregamento de sites
# ---------------------------------------------------------------------------

def load_sites(sites_file: Path | None = None) -> list[dict]:
    path = sites_file or SITES_FILE
    data = DEFAULT_SITES
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    sites = [
        s for s in (data.get("sites") or DEFAULT_SITES["sites"])
        if s.get("name") and s.get("kind") not in LEGACY_KINDS
    ]

    # Garante que os padrões estejam sempre presentes
    names = {s["name"] for s in sites}
    for default in DEFAULT_SITES["sites"]:
        if default["name"] not in names:
            sites.append(default)

    return sites


def eligible_sites(sites: list[dict], query: str) -> list[dict]:
    """Filtra fontes que participam da corrida para esta query."""
    from reader_server import fuzzy_match_score

    filtered = [s for s in sites if s.get("kind") not in EXCLUDED_KINDS]

    # piecePROJECT só entra se a query for relevante para One Piece
    one_piece_score = fuzzy_match_score(query, "One Piece", "OnePiece", "Luffy", "Ruffy")
    if one_piece_score < PIECEPROJECT_RACE_SCORE:
        filtered = [s for s in filtered if s.get("kind") != "pieceproject"]

    return filtered


# ---------------------------------------------------------------------------
# Busca no DragonTea (WP-Manga/WordPress)
# ---------------------------------------------------------------------------

def _dragontea_clean_title(raw: str) -> str:
    """Remove ruído comum de títulos extraídos do HTML do DragonTea."""
    text = unescape(raw)
    text = re.sub(r"<[^>]+>", "", text)           # strip HTML tags se houver
    text = re.sub(r"\s+", " ", text).strip()
    # Remove sufixos desnecessários
    text = re.sub(r"\s*[-|]\s*Dragon\s*Tea.*$", "", text, flags=re.IGNORECASE).strip()
    return text


def _dragontea_extract_results(html: str, base_url: str, limit: int) -> list[dict]:
    """
    Extrai resultados de busca do HTML do dragontea.ink.

    O site usa WP-Manga. A página de busca lista os títulos tipicamente em:
      - <div class="tab-thumb"><a href="..."><img ...></a></div>
        <div class="tab-summary"><div class="post-title h5"><a href="...">Titulo</a></div></div>
      - ou <h3 class="h4"><a href="URL">Titulo</a></h3>
      - ou qualquer <a> cujo href aponte para um slug de manga

    A estratégia é pegar todos os <a> cujo href contenha o domínio/slug de manga e
    que tenham texto de título, evitando links de nav/footer.
    """
    results: list[dict] = []
    seen: set[str] = set()

    # Padrão 1: post-title links (WP-Manga típico)
    for match in re.finditer(
        r'<(?:h\d|div)[^>]+class=["\'][^"\']*(?:post-title|tab-thumb|c-image-hover)[^"\']*["\'][^>]*>'
        r'.*?<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html, re.IGNORECASE | re.DOTALL
    ):
        url = match.group(1).strip()
        title = _dragontea_clean_title(match.group(2))
        if not url or not title or len(title) < 2:
            continue
        full_url = urljoin(base_url, url)
        if full_url in seen:
            continue
        seen.add(full_url)
        results.append({"title": title, "url": full_url})
        if len(results) >= limit:
            return results

    # Padrão 2: qualquer <a href="/slug/"> com texto, excluindo nav/categorias
    if not results:
        parsed_base = urlparse(base_url)
        domain = parsed_base.netloc

        for match in re.finditer(
            r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            html, re.IGNORECASE | re.DOTALL
        ):
            raw_url = match.group(1).strip()
            title = _dragontea_clean_title(match.group(2))
            if not raw_url or not title or len(title) < 2:
                continue

            # URL deve apontar para o mesmo domínio e parecer um slug de manga
            if raw_url.startswith("http"):
                parsed = urlparse(raw_url)
                if parsed.netloc and domain and domain not in parsed.netloc:
                    continue
                full_url = raw_url
            else:
                full_url = urljoin(base_url, raw_url)

            # Filtra links de navegação (categorias, tags, /?..., /page/, etc.)
            path = urlparse(full_url).path.strip("/")
            if not path:
                continue
            if re.search(r"^(?:page|tag|category|genre|manga-genre|author|artist|wp-content|wp-admin|\?)", path, re.IGNORECASE):
                continue
            if "?" in full_url or "#" in urlparse(full_url).fragment:
                continue

            if full_url in seen:
                continue
            seen.add(full_url)
            results.append({"title": title, "url": full_url})
            if len(results) >= limit:
                break

    return results[:limit]


def search_dragontea(query: str, site: dict, limit: int = 15, timeout: int = 8) -> dict:
    """
    Busca mangas no dragontea.ink via endpoint de busca WP-Manga.

    Tenta em ordem:
      1. /?s=QUERY&post_type=wp-manga   (busca nativa WP-Manga)
      2. /wp-json/wp/v2/posts?search=QUERY&per_page=N&post_type=wp-manga  (REST API)
      3. /manga/?s=QUERY  (fallback)
    """
    base_url = (site.get("base_url") or "https://dragontea.ink").rstrip("/")
    results: list[dict] = []
    last_error: Exception | None = None

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    session.headers.update({"Referer": base_url + "/"})

    scan_limit = max(limit * 3, 20)

    # Tentativa 1: busca WP-Manga nativa (HTML)
    candidates = [
        f"{base_url}/?s={quote(query)}&post_type=wp-manga",
        f"{base_url}/manga/?s={quote(query)}",
        f"{base_url}/?s={quote(query)}",
    ]

    for search_url in candidates:
        try:
            response = session.get(search_url, timeout=timeout, allow_redirects=True)
            response.raise_for_status()
            found = _dragontea_extract_results(response.text, base_url, scan_limit)
            for item in found:
                if item["url"] not in {r["url"] for r in results}:
                    results.append(item)
            if results:
                break
        except Exception as exc:
            last_error = exc
            continue

    # Tentativa 2: REST API do WordPress como fallback
    if not results:
        try:
            rest_url = f"{base_url}/wp-json/wp/v2/posts"
            response = session.get(
                rest_url,
                params={"search": query, "per_page": scan_limit, "post_type": "wp-manga"},
                timeout=timeout,
            )
            response.raise_for_status()
            items = response.json()
            if isinstance(items, list):
                for item in items:
                    title = item.get("title", {}).get("rendered") or item.get("slug") or ""
                    title = _dragontea_clean_title(title)
                    link = item.get("link") or ""
                    if title and link:
                        results.append({"title": title, "url": link})
        except Exception as exc:
            last_error = exc

    if not results and last_error:
        raise RuntimeError(f"DragonTea indisponivel: {last_error}")

    return {
        "ok": True,
        "provider": "dragontea",
        "api_url": base_url,
        "keyword": query,
        "count": len(results),
        "results": results[:limit],
    }


# ---------------------------------------------------------------------------
# Dispatcher de busca por fonte
# ---------------------------------------------------------------------------

def _search_on_site(reader, site: dict, query: str, limit: int) -> dict:
    kind = site.get("kind")
    if kind == "dragontea":
        # Usa o método do reader se disponível (reader_server atualizado),
        # caso contrário cai no standalone local
        if hasattr(reader, "search_dragontea"):
            return reader.search_dragontea(query, limit=limit)
        return search_dragontea(query, site, limit=limit)
    if kind == "mangadex":
        return reader.search_mangadex(query, limit=limit)
    if kind == "pieceproject":
        return reader.search_pieceproject(query, limit=limit)
    if kind == "readfull":
        return reader.search_readfull(query, limit=limit)
    # Qualquer outra fonte configurada usa a busca agregada do reader.
    return reader.search_manga(query, limit=limit)


def _best_hit(reader, site: dict, query: str, limit: int) -> RaceHit | None:
    """Executa a busca em uma fonte e retorna o melhor hit (ou None)."""
    from reader_server import fuzzy_match_score

    def relevance(result: dict) -> float:
        return fuzzy_match_score(
            query,
            result.get("title"),
            result.get("description"),
            result.get("alternative_title"),
            result.get("alt_title"),
        )

    min_rel = (
        PIECEPROJECT_MIN_RELEVANCE
        if site.get("kind") == "pieceproject"
        else MIN_RELEVANCE
    )

    started = time.perf_counter()
    try:
        payload = _search_on_site(reader, site, query, limit)
        results: list[dict] = payload.get("results") or []
        if not results:
            return None

        best = max(results, key=relevance)
        score = relevance(best)
        if score < min_rel:
            return None

        url = str(best.get("url") or "").strip()
        if not url:
            return None

        return RaceHit(
            site=site,
            elapsed=time.perf_counter() - started,
            title=str(best.get("title") or "").strip(),
            url=url,
            relevance=score,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Race com retorno antecipado real
# ---------------------------------------------------------------------------

def race(
    reader,
    sites: list[dict],
    query: str,
    *,
    limit: int = 15,
    good_score: float = GOOD_SCORE,
    total_timeout: float = SEARCH_TOTAL_TIMEOUT,
    collect_all: bool = False,
) -> list[RaceHit]:
    """
    Busca em todos os sites em paralelo com retorno antecipado.

    - Se collect_all=False: retorna assim que a primeira fonte atingir
      good_score. Se nenhuma bater, espera total_timeout e retorna a melhor.
    - Se collect_all=True: espera todas as threads (respeita total_timeout)
      e retorna todas ordenadas por (-relevância, elapsed).
    """
    result_queue: queue.Queue[RaceHit | None] = queue.Queue()
    found_good = threading.Event()
    n_sites = len(sites)

    def worker(site: dict) -> None:
        hit = _best_hit(reader, site, query, limit)
        result_queue.put(hit)
        if hit is not None and hit.relevance >= good_score:
            found_good.set()

    # Inicia todas as threads de uma vez — paralelo de verdade
    threads = [
        threading.Thread(target=worker, args=(site,), daemon=True)
        for site in sites[:MAX_WORKERS]
    ]
    race_start = time.perf_counter()
    for t in threads:
        t.start()

    hits: list[RaceHit] = []
    received = 0

    while received < n_sites:
        elapsed = time.perf_counter() - race_start
        remaining = total_timeout - elapsed
        if remaining <= 0:
            break

        try:
            hit = result_queue.get(timeout=min(remaining, 0.05))
            received += 1
            if hit is not None:
                hits.append(hit)

            # Retorno antecipado: primeiro a bater good_score vence
            if not collect_all and found_good.is_set():
                break
        except queue.Empty:
            if time.perf_counter() - race_start >= total_timeout:
                break

    hits.sort(key=lambda h: (-h.relevance, h.elapsed))
    return hits


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Busca um manga em todas as fontes configuradas ao mesmo tempo. "
            "Retorna assim que a primeira fonte responder com boa relevancia."
        )
    )
    parser.add_argument("query", help="Nome do manga. Ex.: 'Soul Eater'")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Coleta todas as fontes (ate o timeout) e exibe ordenadas por relevancia.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Saida em JSON.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        metavar="N",
        help="Resultados pedidos por fonte. Padrao: 15",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=SEARCH_TOTAL_TIMEOUT,
        metavar="SEG",
        help=f"Timeout total da corrida em segundos. Padrao: {SEARCH_TOTAL_TIMEOUT}",
    )
    parser.add_argument(
        "--good-score",
        type=float,
        default=GOOD_SCORE,
        metavar="0-1",
        help=f"Score minimo para retorno imediato. Padrao: {GOOD_SCORE}",
    )
    parser.add_argument(
        "--readfull-api-url",
        default="https://readfullapi.herokuapp.com",
        metavar="URL",
        help="URL da API ReadFull.",
    )
    parser.add_argument(
        "--sites-file",
        default=None,
        metavar="PATH",
        help="Caminho alternativo para reader_sites.json.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        from reader_server import MangaReader
    except ImportError as exc:
        print(
            f"Erro: nao consegui importar reader_server.py.\n"
            f"Verifique que ele esta na mesma pasta.\nDetalhe: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)

    sites_path = Path(args.sites_file) if args.sites_file else None
    sites = load_sites(sites_path)
    candidates = eligible_sites(sites, args.query)

    if not candidates:
        msg = "Nenhuma fonte elegivel para esta busca."
        if args.output_json:
            print(json.dumps({"ok": False, "error": msg, "query": args.query}))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    reader_args = SimpleNamespace(
        librewolf_path=None,
        show_browser=False,
        timeout=int(args.timeout) + 2,
        readfull_api_url=args.readfull_api_url,
        noveltoon_base_url="https://noveltoon.mobi",
    )
    reader = MangaReader(reader_args)

    if not args.output_json:
        names = ", ".join(s["name"] for s in candidates)
        mode = "coletando todas" if args.all else f"retorno ao atingir {args.good_score:.0%}"
        print(f'Buscando "{args.query}"  |  {names}  |  {mode}')
        print()

    race_start = time.perf_counter()
    hits = race(
        reader,
        candidates,
        args.query,
        limit=args.limit,
        good_score=args.good_score,
        total_timeout=args.timeout,
        collect_all=args.all,
    )
    total_elapsed = time.perf_counter() - race_start

    # ---------- JSON ----------
    if args.output_json:
        print(json.dumps(
            {
                "ok": bool(hits),
                "query": args.query,
                "total_elapsed_seconds": round(total_elapsed, 3),
                "sources_searched": len(candidates),
                "winner": hits[0].to_dict() if hits else None,
                "all_hits": [h.to_dict() for h in hits] if args.all else None,
            },
            ensure_ascii=False,
            indent=2,
        ))
        sys.exit(0 if hits else 2)

    # ---------- Texto ----------
    if not hits:
        print(
            f'Nenhuma fonte retornou resultado relevante para: {args.query}\n'
            f'Tempo: {total_elapsed:.2f}s',
            file=sys.stderr,
        )
        sys.exit(2)

    if args.all:
        print(f"{len(hits)} fonte(s) com resultado  |  tempo: {total_elapsed:.2f}s\n")
        for rank, hit in enumerate(hits, start=1):
            print(hit.display(rank=rank))
            print()
    else:
        winner = hits[0]
        print(winner.display())
        print()
        if len(hits) > 1:
            others = ", ".join(h.site["name"] for h in hits[1:])
            print(f"  (outras fontes com resultado: {others})")
        print(f"  Tempo total: {total_elapsed:.2f}s")


if __name__ == "__main__":
    main()
