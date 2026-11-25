/**
 * Category search for the picker: no screen, no network, so it is tested in Node.
 *
 * A category's description says what it holds, then what it is not for ("Mugs, cups, glasses… Not popcorn buckets
 * (Popcorn & snack ware)"). Only the first part is searched, so typing "popcorn" finds Popcorn & snack ware and not
 * every category that points away from it.
 */

/** Lower case, accents off ("Pokémon" → "pokemon"), "&" as "and", punctuation as spaces. */
export function normalize(s) {
  return String(s ?? '')
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
}

/** The part of a description that says what belongs: everything before the first "Not …" sentence or clause. */
export function holds(description) {
  const text = String(description ?? '')
  const m = text.match(/(^|[.:;!?]\s+)not\s/i)
  return (m ? text.slice(0, m.index + m[1].length) : text).trim()
}

/**
 * One entry per category, in tree order (each top-level category, then its children by name):
 * `{ id, name, path, parentPath, general, holds, depth }`. `general` marks a parent that has children: choosing it
 * means "fits no child", and the picker labels it "(general)".
 */
export function buildEntries(rows) {
  const byId = Object.fromEntries(rows.map((c) => [c.id, c]))
  const kids = new Map()
  for (const c of rows) {
    const p = c.parent_id && byId[c.parent_id] ? c.parent_id : null
    if (!kids.has(p)) kids.set(p, [])
    kids.get(p).push(c)
  }
  for (const list of kids.values()) list.sort((a, b) => a.name.localeCompare(b.name))
  // Other goes last among the top-level categories: it is the escape hatch, not a place to browse.
  kids.get(null)?.sort((a, b) => (a.name === 'Other') - (b.name === 'Other') || a.name.localeCompare(b.name))

  const out = []
  const walk = (parent, trail) => {
    for (const c of kids.get(parent) || []) {
      const names = [...trail, c.name]
      out.push({
        id: c.id,
        name: c.name,
        path: names.join(' › '),
        parentPath: trail.join(' › '),
        general: kids.has(c.id),
        holds: holds(c.description),
        description: c.description || '',
        depth: trail.length,
        _name: normalize(c.name),
        _parent: normalize(trail.join(' ')),
        _holds: normalize(holds(c.description)),
      })
      if (trail.length < 5) walk(c.id, names) // a user's tree can't loop, but never trust that blindly
    }
  }
  walk(null, [])
  return out
}

const words = (s) => (s ? s.split(' ') : [])
const startsWord = (text, token) => words(text).some((w) => w.startsWith(token))
// "mugs" should find "mug", "dishes" "dish", "boxes" "box": try the token without a plural ending as well.
const stems = (token) => {
  const out = [token]
  if (token.length > 3 && token.endsWith('es')) out.push(token.slice(0, -2))
  if (token.length > 2 && token.endsWith('s')) out.push(token.slice(0, -1))
  return out
}

/** How well one query word matches an entry; 0 = not at all. */
function tokenScore(e, token) {
  let best = 0
  for (const t of stems(token)) {
    if (startsWord(e._name, t)) best = Math.max(best, 10)
    else if (e._name.includes(t)) best = Math.max(best, 6)
    else if (startsWord(e._parent, t)) best = Math.max(best, 4)
    else if (startsWord(e._holds, t)) best = Math.max(best, 3)
    else if (t.length >= 4 && e._holds.includes(t)) best = Math.max(best, 1)
  }
  return best
}

/**
 * Entries matching every word of the query, best first. A name match beats a parent match, which beats a match in
 * the description; ties keep tree order. An empty query returns every entry, in tree order.
 */
export function searchCategories(entries, query, limit = Infinity) {
  const q = normalize(query)
  if (!q) return entries.slice(0, limit)
  const tokens = words(q)
  const scored = []
  entries.forEach((e, i) => {
    let score = 0
    for (const t of tokens) {
      const s = tokenScore(e, t)
      if (!s) return
      score += s
    }
    if (e._name === q) score += 20 // the exact name
    else if (e._name.startsWith(q)) score += 8
    if (e.general && score < 10 * tokens.length) score -= 1 // a child that matches as well as its parent comes first
    scored.push({ e, score, i })
  })
  scored.sort((a, b) => b.score - a.score || a.i - b.i)
  return scored.slice(0, limit).map((s) => s.e)
}
