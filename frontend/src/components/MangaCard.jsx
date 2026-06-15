import { memo, useEffect, useMemo, useState } from "react"

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

function resolveImageUrl(url) {
  if (!url) return ""
  return url.startsWith("/") ? `${API_BASE_URL}${url}` : url
}

function Badge({ children }) {
  return (
    <span className="rounded border border-line bg-soft px-2 py-0.5 text-[11px] text-muted">
      {children}
    </span>
  )
}

export function MangaCardSkeleton() {
  return (
    <article className="h-[430px] overflow-hidden rounded-md border border-line bg-panel p-3">
      <div className="h-[228px] animate-pulse rounded bg-soft" />
      <div className="mt-3 h-4 w-4/5 animate-pulse rounded bg-soft" />
      <div className="mt-2 h-3 w-3/5 animate-pulse rounded bg-soft" />
      <div className="mt-2 h-3 w-full animate-pulse rounded bg-soft" />
      <div className="mt-2 h-3 w-5/6 animate-pulse rounded bg-soft" />
      <div className="mt-4 flex gap-2">
        <div className="h-5 w-14 animate-pulse rounded bg-soft" />
        <div className="h-5 w-16 animate-pulse rounded bg-soft" />
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
  const ratingText = Number.isFinite(Number(manga.rating))
    ? Number(manga.rating).toFixed(1)
    : manga.provider
  const authors = Array.isArray(manga.authors) ? manga.authors.filter(Boolean) : []

  useEffect(() => {
    setLoaded(false)
    setCoverIndex(0)
  }, [manga.id, manga.cover_url])

  return (
    <button
      type="button"
      onClick={() => onSelect?.(manga)}
      className="group h-[430px] w-full overflow-hidden rounded-md border border-line bg-panel p-3 text-left transition-colors duration-150 hover:border-zinc-500 focus:border-zinc-400 focus:outline-none"
    >
      <div className="relative h-[228px] overflow-hidden rounded bg-soft">
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
              className={`h-full w-full object-cover transition duration-150 ${
                loaded ? "opacity-100" : "opacity-0"
              }`}
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center px-4 text-center text-4xl font-black text-zinc-700">
            {manga.title?.slice(0, 1) || "M"}
          </div>
        )}
      </div>

      <h3 className="mt-3 line-clamp-2 min-h-10 text-sm font-bold leading-5 text-zinc-100">
        {manga.title}
      </h3>

      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted">
        <span>{chapterText}</span>
        <span>{ratingText}</span>
      </div>

      {authors.length > 0 && (
        <p className="mt-1 truncate text-xs text-zinc-500">
          {authors.slice(0, 2).join(", ")}
        </p>
      )}

      {manga.description && (
        <p className="mt-2 line-clamp-3 min-h-12 text-xs leading-4 text-muted">
          {manga.description}
        </p>
      )}

      <div className="mt-3 flex gap-1.5 overflow-hidden">
        {manga.genres?.slice(0, 2).map((genre) => (
          <Badge key={genre}>{genre}</Badge>
        ))}
      </div>
    </button>
  )
}

export default memo(MangaCard)
