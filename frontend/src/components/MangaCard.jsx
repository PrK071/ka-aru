import { memo, useEffect, useMemo, useState } from "react"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

function resolveImageUrl(url) {
  if (!url) return ""
  return url.startsWith("/") ? `${API_BASE_URL}${url}` : url
}

function relativeTime(iso) {
  if (!iso) return ""
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ""
  const diff = Math.max(0, Date.now() - then)
  const min = Math.floor(diff / 60000)
  if (min < 60) return `há ${min || 1}min`
  const h = Math.floor(min / 60)
  if (h < 24) return `há ${h}h`
  const d = Math.floor(h / 24)
  if (d < 30) return `há ${d}d`
  const mo = Math.floor(d / 30)
  if (mo < 12) return `há ${mo}mês`
  return `há ${Math.floor(mo / 12)}a`
}

function Badge({ children }) {
  return (
    <span className="rounded-full border border-line bg-soft/80 px-2 py-0.5 text-[11px] text-muted backdrop-blur">
      {children}
    </span>
  )
}

export function MangaCardSkeleton() {
  return (
    <article className="h-[430px] overflow-hidden rounded-lg border border-line bg-panel">
      <div className="h-[300px] animate-pulse bg-soft" />
      <div className="p-3">
        <div className="h-4 w-4/5 animate-pulse rounded bg-soft" />
        <div className="mt-2 h-3 w-full animate-pulse rounded bg-soft" />
        <div className="mt-2 h-3 w-5/6 animate-pulse rounded bg-soft" />
        <div className="mt-3 flex gap-2">
          <div className="h-5 w-14 animate-pulse rounded-full bg-soft" />
          <div className="h-5 w-16 animate-pulse rounded-full bg-soft" />
        </div>
      </div>
    </article>
  )
}

function MangaCard({ manga, priority = false, onSelect }) {
  const [loaded, setLoaded] = useState(false)
  const [coverIndex, setCoverIndex] = useState(0)
  const coverUrls = useMemo(
    () => [manga.cover_url, ...(manga.cover_fallbacks ?? [])].filter(Boolean),
    [manga.cover_url, manga.cover_fallbacks],
  )
  const currentCover = coverIndex >= 0 ? resolveImageUrl(coverUrls[coverIndex]) : ""
  const hasCover = Boolean(currentCover)
  const chapterText = Number.isFinite(Number(manga.chapter_count))
    ? `${manga.chapter_count} caps`
    : manga.source
  const ratingValue = Number(manga.rating)
  const ratingText = Number.isFinite(ratingValue) && ratingValue > 0
    ? ratingValue.toFixed(1)
    : null
  const authors = Array.isArray(manga.authors) ? manga.authors.filter(Boolean) : []

  useEffect(() => {
    setLoaded(false)
    setCoverIndex(0)
  }, [manga.id, manga.cover_url])

  return (
    <button
      type="button"
      onClick={() => onSelect?.(manga)}
      className="group relative flex h-[430px] w-full flex-col overflow-hidden rounded-lg border border-line bg-panel text-left shadow-card transition-all duration-200 hover:-translate-y-1 hover:border-zinc-600 hover:shadow-glow focus:outline-none focus:ring-1 focus:ring-accent/60"
    >
      <div className="relative h-[300px] overflow-hidden">
        {hasCover ? (
          <>
            {!loaded && <div className="absolute inset-0 animate-pulse bg-zinc-800" />}
            <img
              src={currentCover}
              alt={`Capa de ${manga.title}`}
              loading={priority ? "eager" : "lazy"}
              decoding="async"
              fetchPriority={priority ? "high" : "low"}
              draggable="false"
              onLoad={() => setLoaded(true)}
              onError={() => {
                setLoaded(false)
                setCoverIndex((index) => (
                  index + 1 < coverUrls.length ? index + 1 : -1
                ))
              }}
              className={`h-full w-full object-cover transition duration-300 group-hover:scale-105 ${
                loaded ? "opacity-100" : "opacity-0"
              }`}
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-5xl font-black text-zinc-700">
            {manga.title?.slice(0, 1) || "M"}
          </div>
        )}

        {/* gradiente pra fundir a capa no card */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-2/3 bg-fade-app" />

        {/* rating chip (accent neutro) */}
        {ratingText && (
          <span className="absolute right-2 top-2 rounded-md bg-app/80 px-2 py-0.5 text-[11px] font-bold text-accent ring-1 ring-line backdrop-blur">
            ★ {ratingText}
          </span>
        )}

        {/* titulo sobre a capa */}
        <div className="absolute inset-x-0 bottom-0 p-3">
          <h3 className="line-clamp-2 text-sm font-bold leading-5 text-zinc-50 drop-shadow">
            {manga.title}
          </h3>
          <p className="mt-0.5 text-[11px] text-accent-dim">{chapterText}</p>
        </div>
      </div>

      <div className="flex flex-1 flex-col p-3">
        {(manga.latest_chapter || manga.updated_at) && (
          <p className="text-[11px] font-semibold text-accent-dim">
            {manga.latest_chapter ? `Cap ${manga.latest_chapter}` : "Novo cap"}
            {manga.updated_at ? ` · ${relativeTime(manga.updated_at)}` : ""}
          </p>
        )}
        {authors.length > 0 && (
          <p className="truncate text-xs text-zinc-500">{authors.slice(0, 2).join(", ")}</p>
        )}
        {manga.description && (
          <p className="mt-1 line-clamp-2 text-xs leading-4 text-muted">{manga.description}</p>
        )}
        <div className="mt-auto flex gap-1.5 overflow-hidden pt-2">
          {manga.genres?.slice(0, 2).map((genre) => (
            <Badge key={genre}>{genre}</Badge>
          ))}
        </div>
      </div>
    </button>
  )
}

export default memo(MangaCard)
