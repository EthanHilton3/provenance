// Run with `npm test` (Node's built-in test runner; no extra dependencies).
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError, ConflictError, createApi, fieldErrorsOf, messageOf } from './api.js'

function fakeFetch(status, body) {
  const calls = []
  const fn = async (url, init) => {
    calls.push({ url, init })
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: 'Status text',
      json: async () => {
        if (body === undefined) throw new Error('no body')
        return body
      },
    }
  }
  fn.calls = calls
  return fn
}

test('sends the access token as a Bearer token, and JSON bodies with a content type', async () => {
  const fetch = fakeFetch(201, { id: 'i1' })
  const api = createApi({ getToken: async () => 'tok123', fetch })
  await api.createItem({ name: 'Lamp' })
  const { url, init } = fetch.calls[0]
  assert.equal(url, '/api/items')
  assert.equal(init.method, 'POST')
  assert.equal(init.headers.Authorization, 'Bearer tok123')
  assert.equal(init.headers['Content-Type'], 'application/json')
  assert.deepEqual(JSON.parse(init.body), { name: 'Lamp' })
})

test('sends no Authorization header when signed out', async () => {
  const fetch = fakeFetch(200, [])
  await createApi({ getToken: async () => null, fetch }).listCategories()
  assert.equal(fetch.calls[0].init.headers.Authorization, undefined)
})

test('a 204 resolves to null', async () => {
  const api = createApi({ getToken: async () => 't', fetch: fakeFetch(204) })
  assert.equal(await api.deleteItem('i1'), null)
})

test('keyset paging: a full page returns a cursor from its last row, which the next call sends', async () => {
  const rows = [{ id: 'a', created_at: '2026-11-24T10:00:00+00:00' }, { id: 'b', created_at: '2026-11-24T09:00:00+00:00' }]
  const fetch = fakeFetch(200, rows)
  const api = createApi({ getToken: async () => 't', fetch })
  const page = await api.listItems({ limit: 2 })
  assert.deepEqual(page.next, { created_at: rows[1].created_at, id: 'b' })

  await api.listItems({ limit: 2, cursor: page.next })
  const q = new URL(fetch.calls[1].url, 'http://x').searchParams
  assert.equal(q.get('before_created_at'), rows[1].created_at) // the "+" in the offset survives encoding
  assert.equal(q.get('before_id'), 'b')
  assert.equal(q.get('limit'), '2')
})

test('keyset paging: a short page has no next cursor', async () => {
  const api = createApi({ getToken: async () => 't', fetch: fakeFetch(200, [{ id: 'a', created_at: 'x' }]) })
  assert.equal((await api.listItems({ limit: 50 })).next, null)
})

test('a stale-version 409 throws ConflictError carrying the current row', async () => {
  const current = { id: 'i1', version: 5, name: 'Theirs' }
  const fetch = fakeFetch(409, { detail: { message: 'Changed since you loaded it', current } })
  const api = createApi({ getToken: async () => 't', fetch })
  const err = await api.updateItem('i1', { version: 4, name: 'Mine' }).catch((e) => e)
  assert.ok(err instanceof ConflictError)
  assert.equal(err.status, 409)
  assert.equal(err.message, 'Changed since you loaded it')
  assert.deepEqual(err.current, current)
  assert.equal(fetch.calls[0].init.method, 'PATCH')
})

test('a 409 without a current row (a database constraint) is a plain ApiError', async () => {
  const fetch = fakeFetch(409, { detail: { message: 'duplicate key' }, code: '23505' })
  const err = await createApi({ getToken: async () => 't', fetch }).createItem({}).catch((e) => e)
  assert.ok(err instanceof ApiError && !(err instanceof ConflictError))
  assert.equal(err.message, 'duplicate key')
})

test('a 401 calls onUnauthorized and still throws', async () => {
  let called = 0
  const api = createApi({
    getToken: async () => 't',
    fetch: fakeFetch(401, { detail: 'Invalid or expired token' }),
    onUnauthorized: () => called++,
  })
  const err = await api.getItem('i1').catch((e) => e)
  assert.equal(err.status, 401)
  assert.equal(called, 1)
})

test('a network failure becomes a readable ApiError with status 0', async () => {
  const api = createApi({ getToken: async () => 't', fetch: async () => { throw new TypeError('Failed to fetch') } })
  const err = await api.listCategories().catch((e) => e)
  assert.equal(err.status, 0)
  assert.match(err.message, /reach the server/)
})

test('messageOf reads all three FastAPI error shapes', () => {
  assert.equal(messageOf({ detail: 'No such item' }), 'No such item')
  assert.equal(messageOf({ detail: { message: 'Photo is over the 15 MB limit' } }), 'Photo is over the 15 MB limit')
  assert.equal(messageOf({ detail: [{ loc: ['body', 'name'], msg: 'String should have at least 1 character' }] }),
    'name: String should have at least 1 character')
  assert.equal(messageOf({ detail: [{ loc: ['body'], msg: 'Value error, nothing to update' }] }), 'nothing to update')
  assert.equal(messageOf(null, 'Bad Gateway'), 'Bad Gateway')
})

test('upload sends multipart with the token and reports progress', async () => {
  const sent = {}
  const xhr = {
    upload: {},
    open: (m, u) => Object.assign(sent, { m, u }),
    setRequestHeader: (k, v) => { sent[k] = v },
    send(form) {
      sent.file = form.get('file')
      this.upload.onprogress({ lengthComputable: true, loaded: 50, total: 100 })
      this.status = 201
      this.responseText = JSON.stringify({ id: 'p1' })
      this.onload()
    },
  }
  const progress = []
  const api = createApi({ getToken: async () => 'tok', createXhr: () => xhr })
  const file = new File([new Uint8Array([1, 2, 3])], 'a.jpg', { type: 'image/jpeg' })
  const photo = await api.uploadPhoto('i1', file, (f) => progress.push(f))
  assert.deepEqual(photo, { id: 'p1' })
  assert.equal(sent.m, 'POST')
  assert.equal(sent.u, '/api/items/i1/photos')
  assert.equal(sent.Authorization, 'Bearer tok')
  assert.equal(sent.file.name, 'a.jpg')
  assert.deepEqual(progress, [0.5])
})

test('a refused upload rejects with the server message', async () => {
  const xhr = {
    open() {},
    setRequestHeader() {},
    send() {
      this.status = 415
      this.responseText = JSON.stringify({ detail: { message: 'Not a supported image' } })
      this.onload()
    },
  }
  const api = createApi({ getToken: async () => 't', createXhr: () => xhr })
  const err = await api.uploadPhoto('i1', new File([], 'x.gif'), () => {}).catch((e) => e)
  assert.equal(err.status, 415)
  assert.equal(err.message, 'Not a supported image')
})

test('fieldErrorsOf maps validation errors to the field they name', () => {
  const body = { detail: [
    { loc: ['body', 'name'], type: 'string_too_short', msg: 'String should have at least 1 character' },
    { loc: ['body', 'attributes', 'piece_count', 'constrained-str'], type: 'string_type', msg: 'Input should be a valid string' },
    { loc: ['body', 'attributes', 'piece_count', 'int'], msg: 'Input should be a valid integer' },
    { loc: ['body'], msg: 'Value error, nothing to update' },
  ] }
  assert.deepEqual(fieldErrorsOf(body), {
    name: 'String should have at least 1 character',
    'attributes.piece_count': 'Use text, a number or yes/no here.',
  })
  assert.deepEqual(fieldErrorsOf({ detail: 'No such item' }), {})
  assert.deepEqual(fieldErrorsOf(null), {})
  assert.equal(new ApiError(422, 'x', body).fields.name, 'String should have at least 1 character')
})

test('a 422 with field errors says so in one line; other errors keep their own message', async () => {
  const body = { detail: [{ loc: ['body', 'name'], type: 'string_too_short', msg: 'String should have at least 1 character' }] }
  const api = createApi({ getToken: async () => 't', fetch: fakeFetch(422, body) })
  await assert.rejects(api.createItem({}), (e) => e.status === 422 && /next to the fields/.test(e.message) && !!e.fields.name)
  const api2 = createApi({ getToken: async () => 't', fetch: fakeFetch(422, { detail: 'bad cursor' }) })
  await assert.rejects(api2.createItem({}), (e) => e.message === 'bad cursor')
})
