// Client for the agent API (docs/contract.md, section 3).
// In production CloudFront serves the app and /api/* from one URL, so paths are relative.
// In development Vite proxies /api to the agent (see vite.config.js).
const BASE = import.meta.env?.VITE_API_BASE || ''

const OFFLINE = "We couldn't reach GreatSchools. Please check your internet connection and try again."

// fetch() rejects (Chrome: "Failed to fetch") when the connection drops before any reply, for
// example on flaky Wi-Fi. Try once more after a short pause, then explain in plain words.
async function send(url, options) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fetch(url, options)
    } catch (e) {
      if (attempt >= 1 || e?.name === 'AbortError') throw new Error(OFFLINE)
      await new Promise(resolve => setTimeout(resolve, 800))
    }
  }
}

async function json(path, options = {}) {
  const r = await send(BASE + path, { headers: { 'content-type': 'application/json' }, ...options })
  const raw = await r.text()
  let data
  try { data = JSON.parse(raw) } catch { throw new Error(`The server returned ${r.status}. Please try again.`) }
  if (!r.ok) throw new Error(data.detail || `The server returned ${r.status}.`)
  return data
}

// One agent turn over /api/turn/stream: calls onProgress(text) for each progress event and
// resolves with the same body /api/turn returns ({session_id, blocks, trace, ...}).
export async function turn(sessionId, event, onProgress = () => {}) {
  const r = await send(BASE + '/api/turn/stream', {
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
    let value, done
    try {
      ({ value, done } = await reader.read())
    } catch {
      throw new Error('The connection dropped before the answer arrived. Please try again.')
    }
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

// Thumbs on one agent reply: `turn` is the number the /api/turn response carried.
export const rateReply = (sessionId, turn, vote) =>
  json('/api/feedback', { method: 'POST', body: JSON.stringify({ session_id: sessionId, turn, vote }) })

// The school record plus a verified `profile` for this session's needs (P3; no model call).
export const getSchool = (sessionId, schoolId) =>
  json(`/api/schools/${encodeURIComponent(schoolId)}${sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''}`)

// Local partners who visit schools with parents (decision 042; code only, no model call).
// With no school ids, the server uses the parent's saved list.
export const getPartners = (sessionId, schoolIds = []) =>
  json(`/api/partners?session_id=${encodeURIComponent(sessionId)}${schoolIds.length ? `&school_ids=${schoolIds.map(encodeURIComponent).join(',')}` : ''}`)

export const requestVisit = body => json('/api/visits', { method: 'POST', body: JSON.stringify(body) })

export const listVisits = sessionId => json(`/api/visits?session_id=${encodeURIComponent(sessionId)}`)
