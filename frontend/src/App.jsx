import { useState, useRef, useEffect } from 'react'
import logo from './assets/greatschools-logo.png'
import { turn, saveSchool, unsaveSchool, sendFeedback } from './api.js'

// Card statuses are decided by the backend's code (docs/contract.md, section 2); we only label them.
const STATUS = { confirmed: 'Confirmed', partial: 'Partially meets', needs_attention: 'Needs attention', missing: 'We don’t know: ask the school' }
const STATUS_CLASS = { confirmed: 'confirmed', partial: 'partial', needs_attention: 'attention', missing: 'missing' }
const TYPE = { public: 'Public', charter: 'Charter', private: 'Private' }
const FIXED_NEEDS = new Set(['grade_level', 'location'])  // always required; edit by searching again

const humanize = id => (id || '').replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
const money = n => '$' + Number(n).toLocaleString('en-US')

const Logo = () => <img className="logo" src={logo} alt="GreatSchools.org" />

function SearchBox({ query, setQuery, zip, setZip, onSearch, busy, compact }) {
  return (
    <form className={'sbox' + (compact ? ' compact' : '')} onSubmit={e => { e.preventDefault(); onSearch() }}>
      <input className="q" value={query} onChange={e => setQuery(e.target.value)}
        placeholder="Describe the school you’re looking for…" aria-label="Search" />
      <input className="zip" value={zip} onChange={e => setZip(e.target.value.replace(/\D/g, '').slice(0, 5))}
        placeholder="ZIP (optional)" inputMode="numeric" aria-label="ZIP code" />
      <button className={'go' + (busy ? ' busy' : '')} aria-label="Search" disabled={busy}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      </button>
    </form>
  )
}

function evidenceText(c) {
  return (c.evidence || []).map(e => `${e.field}: ${Array.isArray(e.value) ? e.value.join(', ') : e.value}${e.as_of ? ` (as of ${e.as_of})` : ''}`).join('\n')
}

function Cost({ cost }) {
  if (!cost) return null
  if (cost.tuition === 0) return <span>Tuition-free</span>
  if (cost.tuition == null) return <span>Tuition not listed</span>
  return (
    <span title={cost.after_aid_estimate != null ? `Subtracts the average state scholarship award${cost.aid_as_of ? ` (${cost.aid_as_of})` : ''}. Your amount may differ.` : undefined}>
      {money(cost.tuition)}/yr
      {cost.after_aid_estimate != null && <> · about {money(cost.after_aid_estimate)} after typical aid (estimate)</>}
    </span>
  )
}

function Chips({ block, onRemove, onAdd, busy }) {
  if (!block) return null
  const { chips = [], unmapped = [], suggested = [] } = block
  return (
    <div className="chips" aria-label="Your criteria">
      {chips.map(c => (
        <span key={c.need} className={'chip ' + c.mode + (c.source === 'inferred' ? ' inferred' : '')}
          title={c.source === 'inferred' ? 'I assumed this. Remove it if it’s wrong.' : undefined}>
          {c.mode === 'require' ? 'Must: ' : c.mode === 'avoid' ? 'Avoid: ' : ''}{c.label}
          {!FIXED_NEEDS.has(c.need) && <button className="chipx" disabled={busy} onClick={() => onRemove(c.need)} aria-label={`Remove ${c.label}`}>×</button>}
        </span>
      ))}
      {unmapped.map(u => <span key={u} className="chip unmapped" title="We can’t check this in our data yet">{u} · can’t check yet</span>)}
      {suggested.map(s => (
        <button key={s.need} className="chip suggested" disabled={busy} title={s.why} onClick={() => onAdd(s.need)}>+ {s.label}</button>
      ))}
    </div>
  )
}

function SchoolCard({ r, labels, checked, onToggle, saved, onSave, vote, onVote }) {
  return (
    <article className={'card' + (checked ? ' sel' : '')}>
      <div className="thumb" style={{ background: `linear-gradient(135deg,hsl(${(r.rank * 53) % 360} 55% 38%),hsl(${(r.rank * 53 + 30) % 360} 60% 62%))` }}>
        <span>{r.rank}</span>
      </div>
      <div className="info">
        <div className="top">
          <h3>{r.name}</h3>
          <label className="cmp"><input type="checkbox" checked={checked} onChange={() => onToggle(r.school_id)} /> Compare</label>
        </div>
        <p className="meta">{TYPE[r.entity_type] || r.entity_type} · {r.city}{r.cost && <> · <Cost cost={r.cost} /></>}</p>
        <div className="stats">
          <b className={'rate ' + (r.score >= 0.75 ? 'hi' : r.score >= 0.5 ? 'mid' : 'lo')} title="How well this school matches your criteria">{Math.round(r.score * 100)}</b>
          <span>% match with your criteria</span>
        </div>
        <ul className="tags">
          {(r.criteria || []).map(c => (
            <li key={c.need} className={'tag ' + (STATUS_CLASS[c.status] || 'missing')} title={evidenceText(c) || undefined}>
              <i />{labels[c.need] || humanize(c.need)}<small>{STATUS[c.status] || c.status}{c.note ? ` — ${c.note}` : ''}</small>
            </li>
          ))}
        </ul>
        {r.watch_out && <p className="watch">Watch out: {r.watch_out}</p>}
        <div className="acts">
          <button className={'save' + (saved ? ' on' : '')} onClick={() => onSave(r)} aria-pressed={saved}>{saved ? '★ Saved' : '☆ Save'}</button>
          <span className="vote" aria-label="Is this a good match?">
            <button className={vote === 'up' ? 'on' : ''} onClick={() => onVote(r.school_id, 'up')} aria-label="Good match" aria-pressed={vote === 'up'}>👍</button>
            <button className={vote === 'down' ? 'on' : ''} onClick={() => onVote(r.school_id, 'down')} aria-label="Not a good match" aria-pressed={vote === 'down'}>👎</button>
          </span>
        </div>
      </div>
    </article>
  )
}

function ProgramCard({ p }) {
  const next = (p.next_sessions || [])[0]
  return (
    <article className="card prog">
      <div className="info">
        <h3>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.name}</a> : p.name}</h3>
        <p className="meta">{p.organization} · {p.city}{p.distance_km != null && p.near ? ` · ${p.distance_km} km from ${p.near}` : ''}</p>
        <p className="meta">{[p.ages, p.cost, p.meets_on?.length ? `Meets ${p.meets_on.join(', ')}` : null,
          next ? `Next: ${next.day} ${next.date} ${next.start}–${next.end}` : null, p.registration_open ? 'Registration open' : null].filter(Boolean).join(' · ')}</p>
        {p.why && <p className="why">{p.why}</p>}
        {p.time_fit && <span className={'tag ' + (STATUS_CLASS[p.time_fit.status] || 'missing')}><i />{p.time_fit.note}</span>}
        {p.quality_flags?.length > 0 && <p className="watch">Watch out: {p.quality_flags.map(f => f.note).join(' ')}</p>}
      </div>
    </article>
  )
}

function CompareModal({ data, onClose }) {
  useEffect(() => { const f = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f) }, [onClose])
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-label="Compare schools">
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <h2>Compare schools</h2>
        {data.summary && <p className="summary">{data.summary}</p>}
        <div className="tw"><table>
          <thead><tr><th />{(data.names || data.school_ids).map(n => <th key={n}>{n}</th>)}</tr></thead>
          <tbody>{data.rows.map(row => (
            <tr key={row.need}><th>{row.label || humanize(row.need)}</th>{row.cells.map((c, i) => (
              <td key={i}><span className={'tag ' + (STATUS_CLASS[c.status] || 'missing')}><i />{STATUS[c.status] || c.status}<small>{c.text}</small></span></td>
            ))}</tr>))}</tbody>
        </table></div>
      </div>
    </div>
  )
}

// "How I checked this": the response's top-level `trace` (docs/contract.md, section 4).
// Code records each step as it runs, so we show `service` and `text` exactly as given.
// New `tool` values may appear, so nothing here depends on them.
export function HowIChecked({ trace }) {
  const steps = trace?.steps || []
  if (!steps.length) return null
  const secs = trace.elapsed_ms != null ? ` · ${(trace.elapsed_ms / 1000).toFixed(1)}s` : ''
  return (
    <details className="trace">
      <summary>How I checked this <span>({steps.length} {steps.length === 1 ? 'step' : 'steps'}{secs})</span></summary>
      <ol>
        {steps.map((s, i) => (
          <li key={i}>
            <b>{s.service}</b>
            <span>{s.text}</span>
            {s.ms != null && <small>{s.ms} ms</small>}
          </li>
        ))}
      </ol>
    </details>
  )
}

function Message({ m, onOption, busy }) {
  const bubble = (
    <div className={'m ' + m.r + (m.error ? ' err' : '')}>
      {m.t}
      {m.sources?.length > 0 && <small className="src">From the GreatSchools guide: {m.sources.map(s => s.title).join(' · ')}</small>}
      {m.callouts?.map((c, i) => <p key={i} className="callout"><b>{c.name}:</b> {c.text}</p>)}
      {m.question && <p className="ask"><b>{m.question.text}</b>{m.question.why && <small>{m.question.why}</small>}</p>}
      {m.programs?.length > 0 && <div className="progs">{m.programs.map(p => <ProgramCard key={p.program_id} p={p} />)}</div>}
    </div>
  )
  return (
    <div className={'turn ' + m.r}>
      {bubble}
      {m.question && m.live && (
        <div className="choices">
          {m.question.options.map(o => <button key={o.id} disabled={busy} onClick={() => onOption(m.question, o)}>{o.label}</button>)}
        </div>
      )}
      <HowIChecked trace={m.trace} />
    </div>
  )
}

function Chat({ msgs, progress, busy, question, send, onOption }) {
  const [text, setText] = useState('')
  const box = useRef(null)
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight }, [msgs, progress])
  return (
    <aside className="chat">
      <div className="msgs" ref={box}>
        {msgs.map((m, i) => <Message key={i} m={{ ...m, live: m.question && m.question === question }} onOption={onOption} busy={busy} />)}
        {busy && <div className="m ai typing" aria-live="polite">{progress || 'Thinking…'}</div>}
      </div>
      <form className="in" onSubmit={e => { e.preventDefault(); if (text.trim() && !busy) { send(text.trim()); setText('') } }}>
        <input value={text} onChange={e => setText(e.target.value)} disabled={busy}
          placeholder={question ? 'Or type your own answer…' : 'Ask anything, or tell me more about your needs…'} />
        <button disabled={busy}>Send</button>
      </form>
    </aside>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
  const [zip, setZip] = useState('')
  const [stage, setStage] = useState('home')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState('')
  const [sessionId, setSessionId] = useState(null)
  const [chips, setChips] = useState(null)
  const [schools, setSchools] = useState([])
  const [programs, setPrograms] = useState(null)
  const [msgs, setMsgs] = useState([])
  const [question, setQuestion] = useState(null)
  const [picked, setPicked] = useState([])
  const [comparison, setComparison] = useState(null)
  const [saved, setSaved] = useState(new Set())
  const [votes, setVotes] = useState({})
  const [split, setSplit] = useState(58)
  const wrap = useRef(null)
  const session = useRef(null)  // the latest session_id, for calls made between renders

  const labels = Object.fromEntries((chips?.chips || []).map(c => [c.need, c.label]))
  const nameOf = id => schools.find(s => s.school_id === id)?.name || id
  const addMsg = m => setMsgs(ms => [...ms, m])

  // Apply one /api/turn response: each block updates its part of the page, and the
  // turn's text, notes and question become one chat reply with its trace underneath.
  const apply = (res, kind) => {
    session.current = res.session_id
    setSessionId(res.session_id)
    const reply = { r: 'ai', t: '', trace: res.trace }
    let nextQuestion = null
    for (const b of res.blocks || []) {
      if (b.type === 'criteria_chips') setChips(b)
      else if (b.type === 'text') { reply.t = reply.t ? `${reply.t}\n\n${b.markdown}` : b.markdown; if (b.sources) reply.sources = b.sources }
      else if (b.type === 'clarifying_question') nextQuestion = b
      else if (b.type === 'evidence_callout') (reply.callouts ||= []).push({ name: b.school_id, school_id: b.school_id, text: b.text })
      else if (b.type === 'school_results') {
        setSchools(b.results)
        setSaved(prev => new Set([...prev, ...b.results.filter(r => r.saved).map(r => r.school_id)]))
        setPicked(p => p.filter(id => b.results.some(r => r.school_id === id)))
      } else if (b.type === 'program_results') setPrograms(b)
      else if (b.type === 'comparison') setComparison(b)
    }
    // Show school names, not ids, in callouts (this turn's results, else the current list).
    const results = (res.blocks || []).find(b => b.type === 'school_results')?.results || schools
    reply.callouts?.forEach(c => { c.name = results.find(r => r.school_id === c.school_id)?.name || c.name })
    if (nextQuestion) reply.question = nextQuestion
    if (!reply.t && !reply.question && !reply.callouts) {
      reply.t = kind === 'chip_edit' ? 'I updated the results for your new criteria.'
        : kind === 'compare' ? 'Here’s the side-by-side comparison.' : 'Here’s what I found.'
    }
    setQuestion(nextQuestion)
    addMsg(reply)
  }

  const run = async (event, mine) => {
    if (busy) return
    if (mine) addMsg({ r: 'me', t: mine })
    setBusy(true); setProgress('')
    try {
      apply(await turn(session.current, event, setProgress), event.type)
    } catch (e) {
      addMsg({ r: 'ai', t: e.message || 'Something went wrong. Please try again.', error: true })
    } finally {
      setBusy(false); setProgress('')
    }
  }

  const search = () => {
    const text = query.trim()
    if (!text || busy) return
    setStage('results')
    run({ type: 'query', text: zip ? `${text} (near ZIP ${zip})` : text }, zip ? `${text} · ZIP ${zip}` : text)
  }

  const send = text => question
    ? run({ type: 'answer', question_id: question.question_id, text }, text)
    : run({ type: 'query', text }, text)
  const answer = (q, o) => run({ type: 'answer', question_id: q.question_id, option_id: o.id }, o.label)
  const removeChip = need => run({ type: 'chip_edit', need, removed: true }, `Remove “${labels[need] || humanize(need)}”`)
  const addChip = need => {
    const s = chips?.suggested?.find(x => x.need === need)
    run({ type: 'chip_edit', need, mode: 'prefer' }, `Add “${s?.label || humanize(need)}”`)
  }
  const compare = () => run({ type: 'compare', school_ids: picked.slice(0, 2) }, `Compare ${picked.slice(0, 2).map(nameOf).join(' and ')}`)

  const toggleSave = async r => {
    const sid = session.current
    if (!sid) return
    const on = saved.has(r.school_id)
    try {
      if (on) {
        await unsaveSchool(sid, r.school_id)
        setSaved(s => { const n = new Set(s); n.delete(r.school_id); return n })
      } else {
        const res = await saveSchool(sid, r.school_id)
        setSaved(s => new Set(s).add(r.school_id))
        if (res.programs?.length) addMsg({ r: 'ai', t: `Saved ${r.name}. These nearby programs could help with what it doesn’t fully cover:`, programs: res.programs })
      }
    } catch (e) {
      addMsg({ r: 'ai', t: `I couldn’t ${on ? 'remove' : 'save'} ${r.name}: ${e.message}`, error: true })
    }
  }

  const vote = async (schoolId, v) => {
    const sid = session.current
    if (!sid) return
    setVotes(x => ({ ...x, [schoolId]: v }))
    try { await sendFeedback(sid, schoolId, v) } catch { setVotes(x => ({ ...x, [schoolId]: undefined })) }
  }

  const toggle = id => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : p.length >= 2 ? [p[1], id] : [...p, id])

  const newSearch = () => {
    session.current = null
    setSessionId(null); setChips(null); setSchools([]); setPrograms(null); setMsgs([]); setQuestion(null)
    setPicked([]); setSaved(new Set()); setVotes({}); setQuery(''); setZip(''); setStage('home')
  }

  const drag = e => {
    e.preventDefault()
    const mv = ev => { const r = wrap.current.getBoundingClientRect(); setSplit(Math.min(75, Math.max(30, ((ev.clientX - r.left) / r.width) * 100))) }
    const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up)
  }

  return (
    <div className={'app s-' + stage}>
      <section className="page pg-home">
        <header><Logo /></header>
        <main>
          <h1>Find the right school, together.</h1>
          <p>Tell us what matters to your family. We investigate. You decide.</p>
          <SearchBox {...{ query, setQuery, zip, setZip, busy }} onSearch={search} />
        </main>
      </section>

      <section className="page pg-results">
        <header>
          <Logo />
          <SearchBox compact {...{ query, setQuery, zip, setZip, busy }} onSearch={search} />
          {saved.size > 0 && <span className="savedn">★ {saved.size} saved</span>}
          <button className="back" onClick={newSearch}>New search</button>
        </header>
        <div className="split" ref={wrap}>
          <div className="list" style={{ width: split + '%' }}>
            <Chips block={chips} onRemove={removeChip} onAdd={addChip} busy={busy} />
            {schools.length > 0
              ? <p className="count">{schools.length} schools, best match first</p>
              : <p className="count">{busy ? 'Looking for schools…' : sessionId ? 'Answer in the chat and I’ll find schools that fit.' : ''}</p>}
            {schools.map(r => (
              <SchoolCard key={r.school_id} r={r} labels={labels} checked={picked.includes(r.school_id)} onToggle={toggle}
                saved={saved.has(r.school_id)} onSave={toggleSave} vote={votes[r.school_id]} onVote={vote} />
            ))}
            {programs?.programs?.length > 0 && (
              <>
                <h4 className="sub">Programs nearby (libraries and community centers)</h4>
                {programs.programs.map(p => <ProgramCard key={p.program_id} p={p} />)}
                {programs.excluded_past?.length > 0 && (
                  <p className="count">Not shown, only past sessions: {programs.excluded_past.map(x => x.name).join(', ')}</p>
                )}
              </>
            )}
            <div className="pad" />
          </div>
          <div className="bar" onPointerDown={drag} role="separator" aria-label="Resize panels" />
          <div className="chatw" style={{ width: 100 - split + '%' }}>
            <Chat msgs={msgs} progress={progress} busy={busy} question={question} send={send} onOption={answer} />
          </div>
        </div>
        <div className={'cmpbar' + (picked.length ? ' show' : '')} style={{ width: split + '%' }}>
          <span>{picked.length} of 2 selected</span>
          <button disabled={picked.length < 2 || busy} onClick={compare}>Compare schools</button>
        </div>
      </section>
      {comparison && <CompareModal data={comparison} onClose={() => setComparison(null)} />}
    </div>
  )
}
