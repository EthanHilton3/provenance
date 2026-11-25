import assert from 'node:assert/strict'
import { test } from 'node:test'
import { cleanForSave, isVisible, visibleFields } from './fields.js'

// Music › Albums, as category_fields() returns it.
const vinylOnly = { key: 'format', equals: 'Vinyl' }
const albums = [
  { key: 'artist', label: 'Artist', type: 'text' },
  { key: 'format', label: 'Format', type: 'choice', options: ['Vinyl', 'CD', 'Cassette', 'Other'], scope: 'product' },
  { key: 'record_size', label: 'Record size', type: 'choice', options: ['12"', '10"', '7"'], show_if: vinylOnly },
  { key: 'speed', label: 'Speed (RPM)', type: 'choice', options: ['33', '45', '78'], show_if: vinylOnly },
  { key: 'pressing', label: 'Pressing', type: 'text', scope: 'product', show_if: vinylOnly },
]
const keys = (fields) => fields.map((f) => f.key)

test('a conditional field shows only while its condition holds', () => {
  assert.deepEqual(keys(visibleFields(albums, { format: 'Vinyl' })), ['artist', 'format', 'record_size', 'speed', 'pressing'])
  assert.deepEqual(keys(visibleFields(albums, { format: 'CD' })), ['artist', 'format'])
  assert.deepEqual(keys(visibleFields(albums, {})), ['artist', 'format'])
  assert.deepEqual(keys(visibleFields(albums, { format: '' })), ['artist', 'format'])
})

test('fields without show_if are always visible, whatever scope says', () => {
  assert.equal(isVisible(albums[1], {}), true)
})

test('the condition compares values as text, so a number matches its string', () => {
  const f = { key: 'x', label: 'X', type: 'text', show_if: { key: 'n', equals: '2' } }
  assert.equal(isVisible(f, { n: 2 }), true)
  assert.equal(isVisible(f, { n: ' 2 ' }), true)
  assert.equal(isVisible(f, { n: 3 }), false)
})

test('cleanForSave wipes a hidden known field, keeps visible fields and unknown keys', () => {
  const attrs = { artist: 'Queen', format: 'CD', record_size: '12"', speed: '33', numbered: '3/100', brand: 'EMI' }
  assert.deepEqual(cleanForSave(albums, attrs), { artist: 'Queen', format: 'CD', numbered: '3/100', brand: 'EMI' })
})

test('cleanForSave keeps conditional values while their condition holds', () => {
  const attrs = { format: 'Vinyl', record_size: '12"', pressing: 'First UK' }
  assert.deepEqual(cleanForSave(albums, attrs), attrs)
})

test('cleanForSave does not change its input', () => {
  const attrs = { format: 'CD', speed: '45' }
  cleanForSave(albums, attrs)
  assert.deepEqual(attrs, { format: 'CD', speed: '45' })
})

test('Vinyl → CD → Vinyl while editing loses nothing: hidden values are only dropped by cleanForSave', () => {
  let attrs = { format: 'Vinyl', speed: '45' }
  attrs = { ...attrs, format: 'CD' }
  assert.equal(attrs.speed, '45')
  attrs = { ...attrs, format: 'Vinyl' }
  assert.deepEqual(cleanForSave(albums, attrs), { format: 'Vinyl', speed: '45' })
})

test('a field that depends on a hidden field is hidden too', () => {
  const fields = [
    { key: 'a', label: 'A', type: 'choice', options: ['yes', 'no'] },
    { key: 'b', label: 'B', type: 'choice', options: ['yes', 'no'], show_if: { key: 'a', equals: 'yes' } },
    { key: 'c', label: 'C', type: 'text', show_if: { key: 'b', equals: 'yes' } },
  ]
  assert.deepEqual(keys(visibleFields(fields, { a: 'yes', b: 'yes' })), ['a', 'b', 'c'])
  assert.deepEqual(keys(visibleFields(fields, { a: 'no', b: 'yes' })), ['a'])
  assert.deepEqual(cleanForSave(fields, { a: 'no', b: 'yes', c: 'x' }), { a: 'no' })
})

test('a loop in show_if is treated as hidden, not an endless recursion', () => {
  const fields = [
    { key: 'a', label: 'A', type: 'text', show_if: { key: 'b', equals: 'x' } },
    { key: 'b', label: 'B', type: 'text', show_if: { key: 'a', equals: 'x' } },
  ]
  assert.deepEqual(visibleFields(fields, { a: 'x', b: 'x' }), [])
})

test('Board games: expansion_for only for an expansion', () => {
  const board = [
    { key: 'base_or_expansion', label: 'Base game or expansion', type: 'choice', options: ['Base game', 'Expansion'] },
    { key: 'expansion_for', label: 'Expansion for', type: 'text', show_if: { key: 'base_or_expansion', equals: 'Expansion' } },
  ]
  assert.deepEqual(cleanForSave(board, { base_or_expansion: 'Base game', expansion_for: 'Catan' }), { base_or_expansion: 'Base game' })
  assert.deepEqual(cleanForSave(board, { base_or_expansion: 'Expansion', expansion_for: 'Catan' }),
    { base_or_expansion: 'Expansion', expansion_for: 'Catan' })
})
