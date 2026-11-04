// Client for the agent API (docs/contract.md, section 3).
// In production CloudFront serves the app and /api/* from one URL, so paths are relative.
// In development Vite proxies /api to the agent (see vite.config.js).
const BASE = import.meta.env?.VITE_API_BASE || ''

async function json(path, options = {}) {
  const r = await fetch(BASE + path, { headers: { 'content-type': 'application/json' }, ...options })
  const raw = await r.text()
  let data
  try { data = JSON.parse(raw) } catch { throw new Error(`The server returned ${r.status}. Please try again.`) }
  if (!r.ok) throw new Error(data.detail || `The server returned ${r.status}.`)
  return data
}

// One agent turn over /api/turn/stream: calls onProgress(text) for each progress event and
// resolves with the same body /api/turn returns ({session_id, blocks, trace, ...}).
export async function turn(sessionId, event, onProgress = () => {}) {
  const r = await fetch(BASE + '/api/turn/stream', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId || undefined, event }),
  })
  if (!r.ok || !r.body) {
    let detail = `The server returned ${r.status}.`
    try { detail = JSON.parse(await r.text()).detail || detail } catch { /* not JSON */ }
    throw new Error(detail)
  }
  const reader = r.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let cut
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const line = buffer.slice(0, cut).split('\n').find(l => l.startsWith('data: '))
      buffer = buffer.slice(cut + 2)
      if (!line) continue
      const msg = JSON.parse(line.slice(6))
      if (msg.type === 'progress') onProgress(msg.text)
      else if (msg.type === 'error') throw new Error(msg.detail || 'Something went wrong. Please try again.')
      else if (msg.type === 'result') return msg.response
    }
  }
  throw new Error('The connection closed before the answer arrived. Please try again.')
}

export const saveSchool = (sessionId, schoolId) =>
  json('/api/saved', { method: 'POST', body: JSON.stringify({ session_id: sessionId, school_id: schoolId }) })

export const unsaveSchool = (sessionId, schoolId) =>
  json(`/api/saved/${encodeURIComponent(schoolId)}?session_id=${encodeURIComponent(sessionId)}`, { method: 'DELETE' })

export const sendFeedback = (sessionId, schoolId, vote) =>
  json('/api/feedback', { method: 'POST', body: JSON.stringify({ session_id: sessionId, school_id: schoolId, vote }) })
