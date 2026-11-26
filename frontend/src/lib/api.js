/**
 * The one way the app talks to the FastAPI backend. Every request carries the signed-in user's Supabase access
 * token as a Bearer token; the backend works out who you are from that token alone.
 *
 * `createApi` takes its token source and transport as arguments so it can be tested without a browser or Supabase
 * (see api.test.js). The app's instance is in backend.js.
 */

export class ApiError extends Error {
  constructor(status, message, body = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.fields = fieldErrorsOf(body)
  }
}

/** A PATCH with a stale `version`: someone saved the item after you loaded it. `current` is the row as it is now. */
export class ConflictError extends ApiError {
  constructor(message, current, body) {
    super(409, message, body)
    this.name = 'ConflictError'
    this.current = current
  }
}

/**
 * The readable message in a FastAPI error body. The backend sends three shapes:
 * `{detail: "No such item"}`, `{detail: {message: "..."}}` and, for validation, `{detail: [{msg: "..."}]}`.
 */
export function messageOf(body, fallback) {
  const d = body && body.detail
  if (typeof d === 'string') return d
  if (d && typeof d === 'object' && !Array.isArray(d) && typeof d.message === 'string') return d.message
  if (Array.isArray(d) && d[0] && typeof d[0].msg === 'string') {
    const where = Array.isArray(d[0].loc) ? d[0].loc.filter((p) => p !== 'body').join('.') : ''
    const msg = d[0].msg.replace(/^Value error, /, '')
    return where ? `${where}: ${msg}` : msg
  }
  return fallback || 'Something went wrong. Try again.'
}

/**
 * Validation errors by field, for showing each next to its input: `{name: "...", "attributes.piece_count": "..."}`.
 * A category field's key comes after `attributes`; the first error for a field wins. Empty for any other error.
 */
export function fieldErrorsOf(body) {
  const out = {}
  const d = body && body.detail
  if (!Array.isArray(d)) return out
  for (const e of d) {
    if (!e || !Array.isArray(e.loc) || typeof e.msg !== 'string') continue
    const [, field, key] = e.loc
    if (typeof field !== 'string') continue
    const name = field === 'attributes' && typeof key === 'string' ? `attributes.${key}` : field
    // A category field's value is text, a number or yes/no, so a type error from any one branch of that union is
    // reworded; a length error says how long text may be.
    const wrongType = field === 'attributes' && key !== undefined && e.type !== 'string_too_long'
    out[name] ??= wrongType ? 'Use text, a number or yes/no here.' : e.msg.replace(/^Value error, /, '')
  }
  return out
}

function errorFor(status, body, statusText) {
  // With a message next to each field, the notice only points at them.
  const hasFields = status === 422 && Object.keys(fieldErrorsOf(body)).length > 0
  const message = hasFields ? 'Some details need fixing. See the messages next to the fields.' : messageOf(body, statusText)
  // Only the stale-version 409 carries `current`; a unique-constraint 409 from the database does not.
  if (status === 409 && body && body.detail && typeof body.detail === 'object' && body.detail.current) {
    return new ConflictError(message, body.detail.current, body)
  }
  return new ApiError(status, message, body)
}

const enc = encodeURIComponent

/**
 * @param {object} opts
 * @param {() => Promise<string|null>} opts.getToken  the current access token, or null when signed out
 * @param {typeof fetch} [opts.fetch]
 * @param {() => XMLHttpRequest} [opts.createXhr]     for uploads: fetch cannot report upload progress
 * @param {(err: ApiError) => void} [opts.onUnauthorized]  called on a 401 (expired or revoked session)
 */
export function createApi({ getToken, fetch: fetchFn = (...a) => globalThis.fetch(...a), createXhr, onUnauthorized } = {}) {
  async function authHeaders() {
    const token = await getToken()
    return token ? { Authorization: `Bearer ${token}` } : {}
  }

  function fail(err) {
    if (err.status === 401 && onUnauthorized) onUnauthorized(err)
    throw err
  }

  async function request(method, path, body) {
    const headers = await authHeaders()
    const init = { method, headers }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
    let resp
    try {
      resp = await fetchFn(`/api${path}`, init)
    } catch {
      throw new ApiError(0, 'Could not reach the server. Check your connection and try again.')
    }
    if (!resp.ok) {
      const errBody = await resp.json().catch(() => null)
      fail(errorFor(resp.status, errBody, resp.statusText))
    }
    return resp.status === 204 ? null : resp.json()
  }

  /** Multipart upload with progress. `onProgress(fraction)` gets 0..1 as the bytes go up. */
  async function upload(path, file, onProgress) {
    const headers = await authHeaders()
    const xhr = (createXhr || (() => new XMLHttpRequest()))()
    const form = new FormData()
    form.append('file', file, file.name)
    return new Promise((resolve, reject) => {
      xhr.open('POST', `/api${path}`)
      for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v)
      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
      }
      xhr.onerror = () => reject(new ApiError(0, 'Upload failed: could not reach the server.'))
      xhr.onload = () => {
        let body = null
        try { body = xhr.responseText ? JSON.parse(xhr.responseText) : null } catch { /* not JSON */ }
        if (xhr.status >= 200 && xhr.status < 300) return resolve(body)
        try { fail(errorFor(xhr.status, body, xhr.statusText)) } catch (e) { reject(e) }
      }
      xhr.send(form)
    })
  }

  return {
    request,
    listCategories: () => request('GET', '/categories'),
    categoryFields: (id) => request('GET', `/categories/${enc(id)}/fields`),

    /** One page, newest first. Pass the previous page's `next` as `cursor` for the page after it. */
    async listItems({ limit = 50, cursor = null, categoryId = null } = {}) {
      const q = new URLSearchParams({ limit: String(limit) })
      if (categoryId) q.set('category_id', categoryId)
      if (cursor) {
        q.set('before_created_at', cursor.created_at)
        q.set('before_id', cursor.id)
      }
      const items = await request('GET', `/items?${q}`)
      const last = items[items.length - 1]
      // A full page may or may not have more after it; a short page certainly doesn't.
      const next = items.length === limit && last ? { created_at: last.created_at, id: last.id } : null
      return { items, next }
    },
    getItem: (id) => request('GET', `/items/${enc(id)}`),
    createItem: (item) => request('POST', '/items', item),
    /** `changes` must include the `version` you loaded. A stale one throws ConflictError with the current row. */
    updateItem: (id, changes) => request('PATCH', `/items/${enc(id)}`, changes),
    deleteItem: (id) => request('DELETE', `/items/${enc(id)}`),

    listPhotos: (itemId) => request('GET', `/items/${enc(itemId)}/photos`),
    uploadPhoto: (itemId, file, onProgress) => upload(`/items/${enc(itemId)}/photos`, file, onProgress),
    deletePhoto: (photoId) => request('DELETE', `/photos/${enc(photoId)}`),
    /** A photo with no item yet, for intake. */
    uploadIntakePhoto: (file, onProgress) => upload('/photos', file, onProgress),

    listOccasions: () => request('GET', '/occasions'),
    createOccasion: (occasion) => request('POST', '/occasions', occasion),

    /** `open: true` lists only jobs still waiting on the AI or on you. */
    listIntakeJobs: ({ open = false, limit = 50 } = {}) => request('GET', `/intake/jobs?${new URLSearchParams({ open: String(open), limit: String(limit) })}`),
    getIntakeJob: (id) => request('GET', `/intake/jobs/${enc(id)}`),
    /** `barcode`: one photo of one item whose barcode the catalog didn't know; the job keeps the code. */
    createIntakeJobs: (photoIds, mode, occasionId = null, barcode = null) =>
      request('POST', '/intake/jobs', {
        photo_ids: photoIds, mode, ...(occasionId ? { occasion_id: occasionId } : {}), ...(barcode ? { barcode } : {}),
      }),

    /** {status: found | not_found | unavailable, barcode, release, hints, message}. 422 for a code that isn't valid. */
    lookupBarcode: (code) => request('POST', '/barcodes/lookup', { code }),
    /** {status: ok | skipped | unavailable, step, strength: strong | weak, candidates, sources, message}. */
    searchCatalog: ({ title, kind, year = null, isbn = null }) =>
      request('POST', '/catalog/search', { title, kind, ...(year ? { year } : {}), ...(isbn ? { isbn } : {}) }),
    /** A shared release from approved catalog facts. {status: created | existing | similar | unavailable, release, similar}. */
    createRelease: (body) => request('POST', '/releases', body),
    /** Links a release that has no work yet. {linked, work}: a release that has one keeps it. */
    linkReleaseWork: (releaseId, ref) => request('POST', `/releases/${enc(releaseId)}/work`, { ref }),
    /** 409 if already saved (another tab, a double tap): the error body's detail.job lists what was saved. */
    confirmIntakeJob: (id, items) => request('POST', `/intake/jobs/${enc(id)}/confirm`, { items }),
    discardIntakeJob: (id) => request('POST', `/intake/jobs/${enc(id)}/discard`),
    retryIntakeJob: (id) => request('POST', `/intake/jobs/${enc(id)}/retry`),
  }
}
