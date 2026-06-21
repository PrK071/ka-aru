import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { FixedSizeGrid as Grid } from "react-window"
import MangaCard, { MangaCardSkeleton } from "./components/MangaCard.jsx"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
const CARD_WIDTH = 184
const CARD_HEIGHT = 454
const GRID_GAP = 14
const OVERSCAN_ROWS = 2

function resolveApiUrl(url) {
  if (!url) return ""
  return url.startsWith("/") ? `${API_BASE_URL}${url}` : url
}

const LANG_LABEL = {
  "pt-br": "PT", pt: "PT", en: "EN", es: "ES", "es-la": "ES", ja: "JP",
  ko: "KR", zh: "ZH", "zh-hk": "ZH", fr: "FR", de: "DE", it: "IT", ru: "RU",
  id: "ID", th: "TH", vi: "VI", pl: "PL", tr: "TR", ar: "AR", uk: "UK",
}
function langLabel(lang) {
  return LANG_LABEL[lang] ?? String(lang || "").toUpperCase().slice(0, 2)
}

function useElementSize() {
  const ref = useRef(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    if (!ref.current) return undefined
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width, height })
    })
    observer.observe(ref.current)
    return () => observer.disconnect()
  }, [])

  return [ref, size]
}

function Header({ query, onQueryChange, total }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-app/95 px-5 py-4 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-4">
        <div className="flex min-w-36 items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-md bg-accent text-base font-black text-app">
            M
          </span>
          <div>
            <h1 className="text-lg font-black tracking-wide text-zinc-50">MangaTemp</h1>
            <p className="text-xs text-muted">{total} obras no catalogo</p>
          </div>
        </div>
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Buscar manga, manhwa ou novel"
          className="h-10 flex-1 rounded-md border border-line bg-panel px-3 text-sm text-zinc-100 outline-none transition focus:border-accent/70 focus:ring-1 focus:ring-accent/30"
        />
      </div>
    </header>
  )
}

function VirtualMangaGrid({ mangas, onSelect }) {
  const [containerRef, size] = useElementSize()
  const columnCount = Math.max(1, Math.floor((size.width + GRID_GAP) / (CARD_WIDTH + GRID_GAP)))
  const rowCount = Math.ceil(mangas.length / columnCount)
  const gridHeight = Math.max(420, size.height)

  const itemData = useMemo(
    () => ({ mangas, columnCount }),
    [mangas, columnCount],
  )

  const Cell = useCallback(({ columnIndex, rowIndex, style, data }) => {
    const index = rowIndex * data.columnCount + columnIndex
    const manga = data.mangas[index]
    if (!manga) return null

    return (
      <div
        style={{
          ...style,
          left: Number(style.left) + GRID_GAP / 2,
          top: Number(style.top) + GRID_GAP / 2,
          width: Number(style.width) - GRID_GAP,
          height: Number(style.height) - GRID_GAP,
        }}
      >
        <MangaCard manga={manga} priority={index < 16} onSelect={onSelect} />
      </div>
    )
  }, [])

  return (
    <main ref={containerRef} className="h-[calc(100vh-73px)] px-5 py-5">
      {size.width > 0 && (
        <Grid
          columnCount={columnCount}
          columnWidth={Math.floor(size.width / columnCount)}
          height={gridHeight}
          rowCount={rowCount}
          rowHeight={CARD_HEIGHT}
          width={size.width}
          itemData={itemData}
          overscanRowCount={OVERSCAN_ROWS}
          className="scrollbar-thin scrollbar-thumb-zinc-700 scrollbar-track-app"
        >
          {Cell}
        </Grid>
      )}
    </main>
  )
}

function MangaSection({ title, items, sectionIndex, onSelect }) {
  if (!items?.length) return null

  return (
    <section className="px-5 py-5">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="h-6 w-1 rounded-full bg-accent" />
          <div>
            <h2 className="text-xl font-black text-zinc-50">{title}</h2>
            <p className="text-xs text-muted">{items.length} obras</p>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 2xl:grid-cols-7">
        {items.map((manga, index) => (
          <MangaCard
            key={`${title}-${manga.source_url ?? manga.id ?? manga.title}-${index}`}
            manga={manga}
            priority={sectionIndex === 0 && index < 14}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  )
}

function HeroCarousel({ items, onSelect }) {
  const list = (items ?? []).slice(0, 8)
  const [idx, setIdx] = useState(0)
  useEffect(() => {
    setIdx(0)
  }, [items])
  useEffect(() => {
    if (list.length <= 1) return undefined
    const t = setInterval(() => setIdx((i) => (i + 1) % list.length), 6000)
    return () => clearInterval(t)
  }, [list.length])
  if (!list.length) return null
  const manga = list[idx]
  const cover = resolveApiUrl(manga.cover_path || manga.cover_url)
  const go = (d) => setIdx((i) => (i + d + list.length) % list.length)
  return (
    <section className="relative mx-5 mt-5 overflow-hidden rounded-xl border border-line bg-panel">
      {cover && (
        <img
          src={cover}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 h-full w-full scale-110 object-cover opacity-30 blur-2xl"
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-r from-app via-app/90 to-app/40" />
      <div className="relative flex items-center gap-6 p-6 md:p-8">
        {cover && (
          <img
            src={cover}
            alt={`Capa de ${manga.title}`}
            className="hidden h-56 w-40 shrink-0 rounded-lg object-cover shadow-glow sm:block"
            loading="eager"
            decoding="async"
          />
        )}
        <div className="min-w-0">
          <span className="text-xs font-semibold uppercase tracking-widest text-accent-dim">
            Em alta
          </span>
          <h2 className="mt-1 line-clamp-2 text-2xl font-black text-zinc-50 md:text-3xl">
            {manga.title}
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {manga.genres?.slice(0, 4).map((genre) => (
              <span
                key={genre}
                className="rounded-full border border-line bg-soft/70 px-2.5 py-0.5 text-xs text-muted"
              >
                {genre}
              </span>
            ))}
          </div>
          {manga.description && (
            <p className="mt-3 line-clamp-3 max-w-2xl text-sm text-muted">{manga.description}</p>
          )}
          <button
            type="button"
            onClick={() => onSelect?.(manga)}
            className="mt-4 rounded-md bg-accent px-5 py-2 text-sm font-bold text-app transition hover:bg-white"
          >
            Abrir
          </button>
        </div>
      </div>
      {list.length > 1 && (
        <>
          <button
            type="button"
            onClick={() => go(-1)}
            aria-label="Anterior"
            className="absolute left-3 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full border border-line bg-app/70 text-zinc-100 backdrop-blur transition hover:border-accent hover:text-accent"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => go(1)}
            aria-label="Proximo"
            className="absolute right-3 top-1/2 grid h-9 w-9 -translate-y-1/2 place-items-center rounded-full border border-line bg-app/70 text-zinc-100 backdrop-blur transition hover:border-accent hover:text-accent"
          >
            ›
          </button>
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1.5">
            {list.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setIdx(i)}
                aria-label={`Slide ${i + 1}`}
                className={`h-1.5 rounded-full transition-all ${
                  i === idx ? "w-5 bg-accent" : "w-1.5 bg-line hover:bg-zinc-500"
                }`}
              />
            ))}
          </div>
        </>
      )}
    </section>
  )
}

function MangaCarousel({ title, items, onSelect }) {
  const scrollRef = useRef(null)
  if (!items?.length) return null
  const scrollBy = (dir) => {
    const el = scrollRef.current
    if (el) el.scrollBy({ left: dir * el.clientWidth * 0.85, behavior: "smooth" })
  }
  return (
    <section className="py-5 pl-5">
      <div className="mb-3 flex items-center justify-between gap-3 pr-5">
        <div className="flex items-center gap-3">
          <span className="h-6 w-1 rounded-full bg-accent" />
          <div>
            <h2 className="text-xl font-black text-zinc-50">{title}</h2>
            <p className="text-xs text-muted">{items.length} obras em destaque</p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => scrollBy(-1)}
            aria-label="Anterior"
            className="grid h-8 w-8 place-items-center rounded-full border border-line bg-soft text-zinc-200 transition hover:border-accent hover:text-accent"
          >
            ‹
          </button>
          <button
            type="button"
            onClick={() => scrollBy(1)}
            aria-label="Proximo"
            className="grid h-8 w-8 place-items-center rounded-full border border-line bg-soft text-zinc-200 transition hover:border-accent hover:text-accent"
          >
            ›
          </button>
        </div>
      </div>
      <div
        ref={scrollRef}
        className="no-scrollbar flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-smooth pb-1 pr-5"
      >
        {items.map((manga, index) => (
          <div
            key={`hot-${manga.source_url ?? manga.id ?? manga.title}-${index}`}
            className="w-[184px] shrink-0 snap-start"
          >
            <MangaCard manga={manga} priority={index < 6} onSelect={onSelect} />
          </div>
        ))}
      </div>
    </section>
  )
}

function SectionedCatalog({ sections, items, onSelect }) {
  // If sections is empty but items exist, group items by their section field
  const visibleSections = useMemo(() => {
    const fromSections = (sections ?? []).filter((s) => s.items?.length)
    if (fromSections.length > 0) return fromSections

    // Fallback: group flat items by section field
    if (!items?.length) return []
    const grouped = new Map()
    for (const item of items) {
      const sec = item.section || "Destaques"
      if (!grouped.has(sec)) grouped.set(sec, [])
      grouped.get(sec).push(item)
    }
    return Array.from(grouped.entries()).map(([title, secItems]) => ({ title, items: secItems }))
  }, [sections, items])

  // lazy home: renderiza poucas secoes, carrega mais conforme rola
  const [shown, setShown] = useState(3)
  const sentinelRef = useRef(null)
  useEffect(() => {
    setShown(3)
  }, [visibleSections])
  useEffect(() => {
    if (shown >= visibleSections.length) return undefined
    const el = sentinelRef.current
    if (!el) return undefined
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting) {
          setShown((value) => Math.min(value + 2, visibleSections.length))
        }
      },
      { rootMargin: "800px" },
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [shown, visibleSections])

  if (!visibleSections.length) {
    return (
      <main className="px-5 py-8 text-sm text-muted">
        Nenhuma obra encontrada.
      </main>
    )
  }

  return (
    <main className="pb-8">
      {visibleSections.slice(0, shown).map((section, index) =>
        section.layout === "carousel" ? (
          <MangaCarousel
            key={section.title}
            title={section.title}
            items={section.items}
            onSelect={onSelect}
          />
        ) : (
          <MangaSection
            key={section.title}
            title={section.title}
            items={section.items}
            sectionIndex={index}
            onSelect={onSelect}
          />
        ),
      )}
      {shown < visibleSections.length && (
        <div ref={sentinelRef} className="flex justify-center py-8 text-xs text-muted">
          Carregando mais...
        </div>
      )}
    </main>
  )
}

function SkeletonGrid() {
  return (
    <main className="grid grid-cols-2 gap-3 px-5 py-5 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6">
      {Array.from({ length: 18 }).map((_, index) => (
        <MangaCardSkeleton key={index} />
      ))}
    </main>
  )
}

function MangaDetailPanel({ manga, onClose }) {
  const [chapters, setChapters] = useState([])
  const [loadingChapters, setLoadingChapters] = useState(false)
  const [chapterError, setChapterError] = useState("")
  const [resolvedSource, setResolvedSource] = useState("")
  const [sourceChanged, setSourceChanged] = useState(false)
  const [openedChapter, setOpenedChapter] = useState(null)
  const [loadingChapter, setLoadingChapter] = useState(false)
  const [openChapterError, setOpenChapterError] = useState("")
  const [meta, setMeta] = useState(null)

  // Lista da home e enxuta; os metadados ricos (sinopse multi-idioma, generos,
  // autores, idiomas) vem do /api/chapters (payload.manga) e sao mesclados aqui.
  const detail = useMemo(() => ({ ...manga, ...(meta || {}) }), [manga, meta])

  const descriptions = Array.isArray(detail?.descriptions) && detail.descriptions.length
    ? detail.descriptions
    : (detail?.description ? [{ lang: "pt-br", text: detail.description }] : [])
  const [descLang, setDescLang] = useState(descriptions[0]?.lang ?? "pt-br")
  useEffect(() => {
    setDescLang(descriptions[0]?.lang ?? "pt-br")
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manga?.id, meta])
  const activeDesc = descriptions.find((d) => d.lang === descLang) ?? descriptions[0]

  const chapterLangs = useMemo(() => {
    const raw = (detail?.chapter_languages ?? []).map((l) => String(l).toLowerCase())
    const uniq = [...new Set(raw)]
    const pt = uniq.filter((l) => l === "pt-br" || l === "pt")
    const en = uniq.filter((l) => l === "en")
    const rest = uniq.filter((l) => !["pt-br", "pt", "en"].includes(l)).sort()
    const ordered = [...pt, ...en, ...rest]
    return ordered.length ? ordered : ["pt-br"]
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manga?.id, meta])
  const [chapterLang, setChapterLang] = useState(chapterLangs[0])
  useEffect(() => {
    setChapterLang(chapterLangs[0])
  }, [chapterLangs])

  useEffect(() => {
    if (!manga?.source_url) return undefined
    const controller = new AbortController()
    setLoadingChapters(true)
    setChapterError("")
    setChapters([])
    setResolvedSource("")
    setSourceChanged(false)
    setOpenedChapter(null)
    setLoadingChapter(false)
    setOpenChapterError("")
    setMeta(null)

    const load = async () => {
      try {
        const params = new URLSearchParams({
          source_url: manga.source_url,
          title: manga.title ?? "",
          lang: chapterLang,
        })
        const response = await fetch(`${API_BASE_URL}/api/chapters?${params}`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json()
        setChapters(payload.chapters ?? [])
        setMeta(payload.manga ?? null)
        setResolvedSource(payload.resolved_source || payload.provider || "")
        setSourceChanged(
          Boolean(payload.resolved_source_url)
          && payload.resolved_source_url !== payload.requested_source_url,
        )
      } catch (err) {
        if (err.name !== "AbortError") {
          setChapterError("Nao consegui carregar os capitulos dessa fonte.")
        }
      } finally {
        if (!controller.signal.aborted) setLoadingChapters(false)
      }
    }

    load()
    return () => controller.abort()
  }, [manga, chapterLang])

  if (!manga) return null
  const sourceLabel = resolvedSource || manga.source
  const orderedChapters = [...chapters].sort((a, b) => {
    const numberA = Number(a.number ?? a.number_text)
    const numberB = Number(b.number ?? b.number_text)
    if (Number.isFinite(numberA) && Number.isFinite(numberB)) {
      return numberA - numberB
    }
    return String(a.label ?? "").localeCompare(String(b.label ?? ""), "pt-BR", { numeric: true })
  })

  const openChapter = async (chapter) => {
    if (!chapter?.url) return
    setLoadingChapter(true)
    setOpenChapterError("")
    setOpenedChapter(null)
    try {
      const params = new URLSearchParams({
        source_url: chapter.url,
        lang: chapterLang,
      })
      const response = await fetch(`${API_BASE_URL}/api/chapter?${params}`, {
        headers: { Accept: "application/json" },
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      const payload = await response.json()
      setOpenedChapter(payload)
    } catch (_err) {
      setOpenChapterError("Nao consegui abrir esse capitulo.")
    } finally {
      setLoadingChapter(false)
    }
  }

  return (
    <>
      <aside className="fixed inset-y-0 right-0 z-20 flex w-full max-w-xl flex-col border-l border-line bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div>
            <h2 className="line-clamp-1 text-lg font-black text-zinc-50">{manga.title}</h2>
            <p className="text-xs text-muted">
              {sourceLabel}
              {sourceChanged ? " - fonte completa escolhida" : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-line bg-soft px-3 py-1.5 text-sm text-zinc-100 hover:border-zinc-500"
          >
            Fechar
          </button>
        </div>

        <div className="overflow-y-auto px-5 py-5">
          <div className="grid grid-cols-[132px_1fr] gap-4">
            {manga.cover_path || manga.cover_url ? (
              <img
                src={resolveApiUrl(manga.cover_path || manga.cover_url)}
                alt={`Capa de ${manga.title}`}
                className="h-48 w-32 rounded object-cover"
                loading="eager"
                decoding="async"
              />
            ) : (
              <div className="flex h-48 w-32 items-center justify-center rounded bg-soft text-4xl font-black text-zinc-700">
                {manga.title?.slice(0, 1)}
              </div>
            )}

            <div className="space-y-3 text-sm">
              <div className="flex flex-wrap gap-2">
                {detail.genres?.slice(0, 6).map((genre) => (
                  <span key={genre} className="rounded border border-line bg-soft px-2 py-1 text-xs text-muted">
                    {genre}
                  </span>
                ))}
              </div>
              <div>
                {descriptions.length > 1 && (
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {descriptions.map((d) => (
                      <button
                        key={d.lang}
                        type="button"
                        onClick={() => setDescLang(d.lang)}
                        title={d.auto ? "Traduzido automaticamente" : ""}
                        className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
                          d.lang === descLang
                            ? "bg-accent text-app"
                            : "border border-line bg-soft text-muted hover:border-zinc-500"
                        }`}
                      >
                        {langLabel(d.lang)}{d.auto ? "*" : ""}
                      </button>
                    ))}
                  </div>
                )}
                <p className="text-muted">
                  {activeDesc?.text || "Sem sinopse disponivel nessa fonte."}
                </p>
              </div>
              {detail.authors?.length > 0 && (
                <p className="text-xs text-zinc-500">
                  Autores: {detail.authors.slice(0, 4).join(", ")}
                </p>
              )}
            </div>
          </div>

          <div className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-base font-bold text-zinc-100">Capitulos</h3>
              {chapterLangs.length > 1 && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs text-muted">Idioma:</span>
                  {chapterLangs.map((l) => (
                    <button
                      key={l}
                      type="button"
                      onClick={() => setChapterLang(l)}
                      className={`rounded px-2 py-0.5 text-[11px] font-semibold transition ${
                        l === chapterLang
                          ? "bg-accent text-app"
                          : "border border-line bg-soft text-muted hover:border-zinc-500"
                      }`}
                    >
                      {langLabel(l)}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {loadingChapters && <p className="mt-3 text-sm text-muted">Carregando capitulos...</p>}
            {chapterError && <p className="mt-3 text-sm text-red-300">{chapterError}</p>}
            {openChapterError && <p className="mt-3 text-sm text-red-300">{openChapterError}</p>}
            {!loadingChapters && !chapterError && (
              <div className="mt-3 grid gap-2">
                {orderedChapters.map((chapter) => (
                  <button
                    key={chapter.url}
                    type="button"
                    onClick={() => openChapter(chapter)}
                    disabled={loadingChapter}
                    className="rounded border border-line bg-app px-3 py-2 text-left text-sm text-zinc-200 transition hover:border-zinc-500 disabled:cursor-wait disabled:opacity-60"
                  >
                    {chapter.label}
                    {chapter.title ? <span className="text-muted"> - {chapter.title}</span> : null}
                  </button>
                ))}
                {orderedChapters.length === 0 && <p className="text-sm text-muted">Nenhum capitulo encontrado.</p>}
              </div>
            )}
          </div>
        </div>
      </aside>

      {(loadingChapter || openedChapter) && (
        <div className="fixed inset-0 z-30 flex flex-col bg-app">
          <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-app/95 px-5 py-3 backdrop-blur">
            <div>
              <h2 className="line-clamp-1 text-base font-black text-zinc-50">
                {openedChapter?.chapter?.label || "Carregando capitulo"}
              </h2>
              <p className="text-xs text-muted">
                {openedChapter?.provider || sourceLabel}
                {openedChapter?.count ? ` - ${openedChapter.count} paginas` : ""}
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setOpenedChapter(null)
                setLoadingChapter(false)
              }}
              className="rounded border border-line bg-soft px-3 py-1.5 text-sm text-zinc-100 hover:border-zinc-500"
            >
              Voltar
            </button>
          </header>

          <main className="flex-1 overflow-y-auto px-2 py-4">
            {loadingChapter && (
              <p className="mx-auto max-w-3xl rounded border border-line bg-panel px-4 py-3 text-sm text-muted">
                Carregando imagens...
              </p>
            )}
            {openedChapter?.images?.length > 0 && (
              <div className="mx-auto flex max-w-5xl flex-col items-center">
                {openedChapter.images.map((image, index) => (
                  <img
                    key={`${image.index}-${image.src}`}
                    src={resolveApiUrl(image.src)}
                    alt={`Pagina ${image.index}`}
                    loading={index < 3 ? "eager" : "lazy"}
                    decoding="async"
                    draggable="false"
                    className="w-full max-w-4xl bg-zinc-950 object-contain"
                  />
                ))}
              </div>
            )}
          </main>
        </div>
      )}
    </>
  )
}

export default function App() {
  const [query, setQuery] = useState("")
  const [mangas, setMangas] = useState([])
  const [sections, setSections] = useState([])
  const [selectedManga, setSelectedManga] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [refreshTick, setRefreshTick] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    let retryId = null
    const timeout = setTimeout(async () => {
      setLoading(true)
      setError("")
      try {
        const trimmedQuery = query.trim()
        const params = new URLSearchParams({ limit: trimmedQuery ? "40" : "32" })
        if (trimmedQuery) params.set("q", trimmedQuery)
        const response = await fetch(`${API_BASE_URL}/api/mangas?${params}`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json()
        setMangas(payload.items ?? [])
        setSections(payload.sections ?? [])
        setTotal(payload.total ?? payload.items?.length ?? 0)
        if (!trimmedQuery && payload.refreshing) {
          retryId = window.setTimeout(() => {
            setRefreshTick((value) => value + 1)
          }, 2500)
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          setError("Nao consegui carregar o catalogo.")
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }, 180)

    return () => {
      clearTimeout(timeout)
      if (retryId) clearTimeout(retryId)
      controller.abort()
    }
  }, [query, refreshTick])

  const heroSection = (sections ?? []).find(
    (s) => s.layout === "carousel" && s.title === "Em alta",
  )
  const heroItems = heroSection?.items?.length ? heroSection.items : mangas.slice(0, 8)
  const catalogSections = (sections ?? []).filter(
    (s) => !(s.layout === "carousel" && s.title === "Em alta"),
  )

  return (
    <div className="min-h-screen bg-app text-zinc-100">
      <Header query={query} onQueryChange={setQuery} total={total} />
      {error && (
        <div className="mx-5 mt-4 rounded-md border border-red-900 bg-red-950/30 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}
      {loading ? (
        <SkeletonGrid />
      ) : query.trim() ? (
        <VirtualMangaGrid mangas={mangas} onSelect={setSelectedManga} />
      ) : (
        <>
          <HeroCarousel items={heroItems} onSelect={setSelectedManga} />
          <SectionedCatalog sections={catalogSections} items={mangas} onSelect={setSelectedManga} />
        </>
      )}
      <MangaDetailPanel manga={selectedManga} onClose={() => setSelectedManga(null)} />
    </div>
  )
}
