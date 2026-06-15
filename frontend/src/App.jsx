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
        <div className="min-w-36">
          <h1 className="text-lg font-black tracking-wide text-zinc-50">MangaTemp</h1>
          <p className="text-xs text-muted">{total} obras no catalogo</p>
        </div>
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Buscar manga, manhwa ou novel"
          className="h-10 flex-1 rounded-md border border-line bg-panel px-3 text-sm text-zinc-100 outline-none transition focus:border-zinc-500"
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
        <div>
          <h2 className="text-xl font-black text-zinc-50">{title}</h2>
          <p className="text-xs text-muted">{items.length} obras</p>
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
  if (!visibleSections.length) {
    return (
      <main className="px-5 py-8 text-sm text-muted">
        Nenhuma obra encontrada.
      </main>
    )
  }

  return (
    <main className="pb-8">
      {visibleSections.map((section, index) => (
        <MangaSection
          key={section.title}
          title={section.title}
          items={section.items}
          sectionIndex={index}
          onSelect={onSelect}
        />
      ))}
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

    const load = async () => {
      try {
        const params = new URLSearchParams({
          source_url: manga.source_url,
          title: manga.title ?? "",
          lang: "pt-br",
        })
        const response = await fetch(`${API_BASE_URL}/api/chapters?${params}`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json()
        setChapters(payload.chapters ?? [])
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
  }, [manga])

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
        lang: "pt-br",
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
            {manga.cover_url ? (
              <img
                src={resolveApiUrl(manga.cover_url)}
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
                {manga.genres?.slice(0, 6).map((genre) => (
                  <span key={genre} className="rounded border border-line bg-soft px-2 py-1 text-xs text-muted">
                    {genre}
                  </span>
                ))}
              </div>
              <p className="text-muted">
                {manga.description || "Sem sinopse disponivel nessa fonte."}
              </p>
              {manga.authors?.length > 0 && (
                <p className="text-xs text-zinc-500">
                  Autores: {manga.authors.slice(0, 4).join(", ")}
                </p>
              )}
            </div>
          </div>

          <div className="mt-6">
            <h3 className="text-base font-bold text-zinc-100">Capitulos</h3>
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

  useEffect(() => {
    const controller = new AbortController()
    const timeout = setTimeout(async () => {
      setLoading(true)
      setError("")
      try {
        const params = new URLSearchParams({ limit: "200" })
        if (query.trim()) params.set("q", query.trim())
        const response = await fetch(`${API_BASE_URL}/api/mangas?${params}`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json()
        setMangas(payload.items ?? [])
        setSections(payload.sections ?? [])
        setTotal(payload.total ?? payload.items?.length ?? 0)
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
      controller.abort()
    }
  }, [query])

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
        <SectionedCatalog sections={sections} items={mangas} onSelect={setSelectedManga} />
      )}
      <MangaDetailPanel manga={selectedManga} onClose={() => setSelectedManga(null)} />
    </div>
  )
}
