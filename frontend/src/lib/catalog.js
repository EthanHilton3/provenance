/**
 * Catalog linking and shared releases (S12), without a screen: which categories search a catalog, what to search
 * for, and what a shared release is made of.
 *
 * Films and shows search TMDB, books Open Library (by ISBN first). Video games have no catalog yet (no IGDB) but can
 * still be shared. Every other category skips all of it: those things stay private and unique.
 *
 * What is shared is only catalog facts: the release's title, format, edition and barcode, and the work's title, year
 * and kind. `releaseBody` builds exactly that, and the backend accepts nothing else. Notes, photos, occasion, price,
 * who gave it and where it is never leave the item.
 */

export const SHARED_TEXT = 'its title, format, edition and barcode, and the title, year and kind of the film, show, book or game'
export const PRIVATE_TEXT = 'Your notes, photos, occasion, price, condition, who gave it and where it is stay private.'

/** The catalog kind of a category: movie, tv or screen (film or show, not known which), book, game, or null. */
export function catalogKind(categoryId, byId = {}, card = null) {
  const c = byId[categoryId]
  if (!c) return null
  const top = c.parent_id ? byId[c.parent_id] : c
  if (c.owner_id || top?.owner_id) return null
  switch (top?.name) {
    case 'Movies & TV':
      return card?.catalog === 'tmdb_movie' || card?.catalog === 'tmdb_collection' ? 'movie'
        : card?.catalog === 'tmdb_tv' ? 'tv' : 'screen'
    case 'Books': return 'book'
    case 'Video Games': return c.name === 'Games' ? 'game' : null
    default: return null
  }
}

export const searchable = (kind) => ['movie', 'tv', 'screen', 'book'].includes(kind)
export const shareable = (kind) => searchable(kind) || kind === 'game'

const YEAR = /\(\s*((?:1[89]|20)\d\d)\s*\)/

/** 'Princess Mononoke (1997)' -> {title: 'Princess Mononoke', year: 1997}. */
export function splitYear(text) {
  const t = String(text ?? '').trim()
  const m = t.match(YEAR)
  if (!m) return { title: t, year: null }
  return { title: (t.slice(0, m.index) + t.slice(m.index + m[0].length)).replace(/^[\s:-]+|[\s:-]+$/g, ''), year: Number(m[1]) }
}

export function isbnOf(...values) {
  for (const v of values) {
    const d = String(v ?? '').replace(/[\s-]/g, '')
    if (/^97[89]\d{10}$/.test(d)) return d
  }
  return null
}

/**
 * What to search for. The AI's card has a clean search title (`catalog_query`, sometimes with the year in brackets,
 * which is split off as a hint); without one, the item's name. An ISBN comes from the item's ISBN field or a barcode.
 */
export function catalogQuery({ card = null, draft = {}, kind = null, barcode = null, title = null } = {}) {
  const raw = title ?? (card?.catalog_query && card?.catalog !== 'none' ? card.catalog_query : draft.name)
  const { title: clean, year } = splitYear(raw)
  return { title: clean, kind, year, isbn: kind === 'book' ? isbnOf(draft.attributes?.isbn, barcode) : null }
}

/** The kind a new work gets: a film-or-show the owner didn't narrow down is filed as a film. */
export function workKind(kind) {
  return kind === 'screen' ? 'movie' : ['movie', 'tv', 'book', 'game'].includes(kind) ? kind : 'other'
}

const blank = (v) => v === undefined || v === null || String(v).trim() === ''

/**
 * POST /api/releases: the release from the approved draft, and its work: the catalog entry the owner picked, or
 * (for "none of these", or a game) a new work from the search title and year.
 */
export function releaseBody(draft, { choice = null, query = {}, kind = null, barcode = null, declined = [] } = {}) {
  const a = draft.attributes || {}
  const format = !blank(a.format) ? a.format : !blank(a.platform) ? a.platform : null
  // Discs keep packaging apart from the edition, but a steelbook is a different release from the plain case, so it
  // is part of the shared edition (the duplicate check must tell them apart). A standard case adds nothing.
  const packaging = !blank(a.packaging) && !/^standard/i.test(String(a.packaging)) ? String(a.packaging) : null
  const edition = [blank(a.edition) ? null : String(a.edition).trim(), packaging]
    .filter((v, i, all) => v && all.findIndex((w) => w?.toLowerCase() === v.toLowerCase()) === i).join(', ') || null
  const work = choice && choice !== 'none'
    ? { ref: choice }
    : { new: { title: (query.title || draft.name || '').trim(), year: query.year || null, kind: workKind(kind) } }
  return {
    title: draft.name.trim(),
    format: format === null ? null : String(format),
    edition,
    barcode: barcode || null,
    work,
    declined,
  }
}

/** The owner must say which work it is before sharing: a candidate, or "none of these". Games have no search. */
export function needsChoice({ share, kind, choice, result }) {
  if (!share || !searchable(kind) || choice) return false
  return result?.status === 'ok' && (result.candidates?.length ?? 0) > 0
}

/**
 * Makes or finds the shared release. {releaseId} to save the item with; {similar} to ask "use it?" (nothing was
 * made); {message} when the duplicate check couldn't run (save without a shared release).
 */
export async function resolveRelease(api, body) {
  const r = await api.createRelease(body)
  if (r.status === 'similar') return { similar: r.similar }
  if (r.status === 'unavailable') return { message: r.message || "Couldn't check the shared catalog right now." }
  return { releaseId: r.release.id, existing: r.status === 'existing' }
}

export const SOURCE_LABEL = { tmdb: 'TMDB', open_library: 'Open Library' }

export function candidateLine(c) {
  return `${c.title}${c.year ? ` (${c.year})` : ''}`
}

export function releaseLine(r) {
  return [r.title, r.format, r.edition || 'Standard edition', r.work_year ? String(r.work_year) : null].filter(Boolean).join(' · ')
}
