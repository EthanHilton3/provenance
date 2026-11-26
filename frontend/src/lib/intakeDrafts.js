/**
 * Unsaved edits to a confirmation card or grid, kept on this device so leaving the page (or a phone reloading the
 * tab after you switch apps) doesn't lose them. A convenience only: the job itself is on the server either way.
 * Every access is guarded, because storage can be missing or full (private windows).
 */
const KEY = (jobId) => `provenance.intake.${jobId}`

export function loadDraft(jobId) {
  try {
    const raw = localStorage.getItem(KEY(jobId))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveDraft(jobId, value) {
  try {
    localStorage.setItem(KEY(jobId), JSON.stringify(value))
  } catch { /* full or blocked: the edits just aren't kept */ }
}

export function forgetDraft(jobId) {
  try {
    localStorage.removeItem(KEY(jobId))
  } catch { /* nothing to do */ }
}
