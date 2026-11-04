import { useState, useRef, useEffect } from 'react'
import logo from './assets/greatschools-logo.png'
import { turn, saveSchool, unsaveSchool, rateReply, getSchool } from './api.js'

// Statuses are decided by the backend's code (docs/contract.md, section 2); we only word them.
const STATUS = {
  confirmed: { icon: '✓', word: 'Yes', cls: 'confirmed' },
  partial: { icon: '◐', word: 'Partly', cls: 'partial' },
  needs_attention: { icon: '!', word: 'Watch out', cls: 'attention' },
  missing: { icon: '?', word: 'Not known', cls: 'missing' },
}
const status = s => STATUS[s] || STATUS.missing
const TYPE = { public: 'Public', charter: 'Charter', private: 'Private' }
const FIXED_NEEDS = new Set(['grade_level', 'location'])  // always required; change them by searching again
const EXAMPLES = [
  'Middle school near Miami with STEM. I work until 6pm',
  'Free elementary school in Hialeah with help learning English',
  'My son has ADHD and needs extra help in class. High school near Doral',
]

const humanize = id => (id || '').replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
const money = n => '$' + Number(n).toLocaleString('en-US')
const miles = p => p.distance_miles ?? (p.distance_km != null ? Math.round(p.distance_km * 6.21371) / 10 : null)

const Logo = () => <img className="logo" src={logo} alt="GreatSchools.org" />

function SearchBox({ query, setQuery, zip, setZip, onSearch, busy, compact }) {
  return (
    <form className={'sbox' + (compact ? ' compact' : '')} onSubmit={e => { e.preventDefault(); onSearch() }}>
      <input className="q" value={query} onChange={e => setQuery(e.target.value)}
        placeholder="Tell us about your child and what you need…" aria-label="Search" />
      <input className="zip" value={zip} onChange={e => setZip(e.target.value.replace(/\D/g, '').slice(0, 5))}
        placeholder="ZIP (optional)" inputMode="numeric" aria-label="ZIP code" />
      <button className={'go' + (busy ? ' busy' : '')} aria-label="Search" disabled={busy}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      </button>
    </form>
  )
}

function Heart({ on, onClick, name }) {
  return (
    <button className={'heart' + (on ? ' on' : '')} onClick={onClick} aria-pressed={on}
      aria-label={on ? `Remove ${name} from your list` : `Save ${name} to your list`} title={on ? 'Saved to your list' : 'Save to your list'}>
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
        <path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.7 4.5c2.1 0 3.6 1.2 5.3 3.1 1.7-1.9 3.2-3.1 5.3-3.1 3.7 0 5.8 3.9 4.3 7.3C19.5 16.4 12 21 12 21z" />
      </svg>
    </button>
  )
}

function Cost({ cost }) {
  if (!cost) return null
  if (cost.tuition === 0) return <span>Free (no tuition)</span>
  if (cost.tuition == null) return <span>Tuition not listed</span>
  return (
    <span title={cost.after_aid_estimate != null ? `Subtracts the average Florida scholarship${cost.aid_as_of ? ` (${cost.aid_as_of})` : ''}. Your amount may differ.` : undefined}>
      {money(cost.tuition)} a year{cost.after_aid_estimate != null && <> · about {money(cost.after_aid_estimate)} with a typical scholarship (estimate)</>}
    </span>
  )
}

function Checks({ criteria, labels }) {
  return (
    <ul className="checks">
      {(criteria || []).map(c => {
        const st = status(c.status)
        return (
          <li key={c.need} className={st.cls}>
            <span className="ic" aria-hidden="true">{st.icon}</span>
            <span><b>{labels[c.need] || humanize(c.need)}</b> <em>{st.word}</em>{c.note && <small>{c.note}</small>}</span>
          </li>
        )
      })}
    </ul>
  )
}

function Chips({ block, onRemove, onAdd, busy }) {
  if (!block) return null
  const { chips = [], unmapped = [], suggested = [] } = block
  return (
    <div className="chipbar">
      <div className="chips" aria-label="What you asked for">
        {chips.map(c => (
          <span key={c.need} className={'chip ' + c.mode + (c.source === 'inferred' ? ' inferred' : '')}
            title={c.source === 'inferred' ? 'I assumed this. Remove it if it’s wrong.' : c.mode === 'require' ? 'Must have' : 'Nice to have'}>
            {c.mode === 'require' && <i className="must">Must</i>}{c.mode === 'avoid' && <i className="must">Avoid</i>}{c.label}
            {!FIXED_NEEDS.has(c.need) && <button className="chipx" disabled={busy} onClick={() => onRemove(c.need)} aria-label={`Remove ${c.label}`}>×</button>}
          </span>
        ))}
        {unmapped.map(u => <span key={u} className="chip unmapped" title="We can’t check this in our data yet">{u} · can’t check yet</span>)}
      </div>
      {suggested.length > 0 && (
        <div className="chips sugg">
          <span className="hint">Also worth checking?</span>
          {suggested.map(s => (
            <button key={s.need} className="chip suggested" disabled={busy} title={s.why} onClick={() => onAdd(s.need)}>+ {s.label}</button>
          ))}
        </div>
      )}
    </div>
  )
}

const TypeTag = ({ type }) => <span className={'type t-' + type}>{TYPE[type] || humanize(type)}</span>

// One "Best for ..." per school, chosen in code (decision 029); `why` says what it's based on.
function Badge({ badge, full }) {
  if (!badge) return null
  return (
    <p className={'badge' + (full ? ' full' : '')} title={full ? undefined : badge.why}>
      <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M12 2.5l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.3l-5.8 3.1 1.1-6.5-4.7-4.6 6.5-.9z" /></svg>
      <span><b>{badge.label}</b>{full && <small>{badge.why}</small>}</span>
    </p>
  )
}

// The card stays short: who the school is, its one standout, and what to watch. The full
// checklist for every need lives in the details panel.
function SchoolCard({ r, checked, onToggle, saved, onSave, onDetails }) {
  return (
    <article className={'card school' + (checked ? ' sel' : '')}>
      <header className="card-head">
        <TypeTag type={r.entity_type} />
        <Heart on={saved} onClick={() => onSave(r)} name={r.name} />
      </header>
      <h3><button className="name" onClick={() => onDetails(r)}>{r.name}</button></h3>
      <p className="meta">{r.city}{r.cost && <> · <Cost cost={r.cost} /></>}</p>
      <Badge badge={r.badge} />
      {r.watch_out && <p className="watch" title={r.watch_out}><b>Good to know:</b> {r.watch_out}</p>}
      <footer className="card-foot">
        <button className="link" onClick={() => onDetails(r)}>See details and reviews</button>
        <label className="cmp"><input type="checkbox" checked={checked} onChange={() => onToggle(r.school_id)} /> Compare</label>
      </footer>
    </article>
  )
}

function ProgramCard({ p }) {
  const next = (p.next_sessions || [])[0]
  const mi = miles(p)
  return (
    <article className="card prog">
      <h3>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.name}</a> : p.name}</h3>
      <p className="meta">{p.organization} · {p.city}{mi != null && p.near ? ` · ${mi} miles from ${p.near}` : ''}</p>
      <p className="meta">{[p.ages, p.cost, p.meets_on?.length ? `Meets ${p.meets_on.join(', ')}` : null,
        next ? `Next: ${next.day} ${next.date} ${next.start}–${next.end}` : null, p.registration_open ? 'Sign-up open' : null].filter(Boolean).join(' · ')}</p>
      {p.why && <p className="why">{p.why}</p>}
      {p.time_fit && <p className={'fit ' + status(p.time_fit.status).cls}>{status(p.time_fit.status).icon} {p.time_fit.note}</p>}
      {p.quality_flags?.length > 0 && <p className="watch"><b>Good to know:</b> {p.quality_flags.map(f => f.note).join(' ')}</p>}
    </article>
  )
}

function CompareModal({ data, labels, onClose }) {
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
            <tr key={row.need}><th>{labels[row.need] || row.label || humanize(row.need)}</th>{row.cells.map((c, i) => {
              const st = status(c.status)
              // "No problems found" needs no badge; everything else shows the check's status.
              return <td key={i} className={st.cls}>{row.need === 'data_quality' && c.status === 'confirmed'
                ? <span className="none">{c.text}</span>
                : <><span className="ic">{st.icon}</span> <em>{st.word}</em><small>{c.text}</small></>}</td>
            })}</tr>))}</tbody>
        </table></div>
      </div>
    </div>
  )
}

// P3: the verified profile for one school, built by the backend's code for this parent's needs.
function Details({ school, sessionId, labels, saved, onSave, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => { getSchool(sessionId, school.school_id).then(setData).catch(e => setError(e.message)) }, [sessionId, school.school_id])
  useEffect(() => { const f = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f) }, [onClose])
  const p = data?.profile
  const flagged = new Set((p?.quality_flags || []).map(f => f.field))
  const facts = data ? [
    data.summary_rating != null && ['GreatSchools rating', `${data.summary_rating} out of 10`],
    data.avg_review_rating != null && ['Parent rating', `${data.avg_review_rating} out of 5`],
    data.enrollment != null && !flagged.has('enrollment') && ['Students', data.enrollment],
    data.student_teacher_ratio != null && !flagged.has('student_teacher_ratio') && ['Students per teacher', data.student_teacher_ratio],
  ].filter(Boolean) : []
  return (
    <div className="overlay side" onClick={onClose}>
      <aside className="drawer" onClick={e => e.stopPropagation()} role="dialog" aria-label={`${school.name} details`}>
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <div className="drawer-head">
          <h2>{school.name}</h2>
          <Heart on={saved} onClick={() => onSave(school)} name={school.name} />
        </div>
        <p className="meta drawer-meta"><TypeTag type={school.entity_type} />{data ? [data.street, data.city, data.zipcode].filter(Boolean).join(', ') : school.city}</p>
        <Badge badge={school.badge} full />
        {error && <p className="watch">I couldn’t load this school: {error}</p>}
        {!data && !error && <p className="meta">Loading…</p>}
        {p && <>
          {facts.length > 0 && <dl className="facts">{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>}
          {p.cost && <p className="meta"><Cost cost={p.cost} /></p>}
          {p.criteria?.length > 0 && <><h4>How it fits what you asked for</h4><Checks criteria={p.criteria} labels={labels} /></>}
          <h4>What parents say</h4>
          {p.reviews?.total ? <>
            <p className="meta">{p.reviews.total} review{p.reviews.total === 1 ? '' : 's'}</p>
            {(p.reviews.excerpts || []).map((x, i) => (
              <blockquote key={i}>“{x.text}”<small>{x.date}{x.older ? ' · older review, may not reflect today' : ''}</small></blockquote>
            ))}
          </> : <p className="meta">No reviews yet.</p>}
          {p.quality_flags?.length > 0 && <><h4>Problems in our data</h4><ul className="flags">{p.quality_flags.map(f => <li key={f.field}>{f.note}</li>)}</ul></>}
          {p.terms?.length > 0 && <><h4>Words on this page</h4>{p.terms.map(t => <details key={t.id} className="term"><summary>{t.title}</summary><p>{t.body}</p></details>)}</>}
        </>}
      </aside>
    </div>
  )
}

// "How I checked this": the response's top-level `trace` (docs/contract.md, section 4).
// Code records each step as it runs, so we show `service` and `text` exactly as given.
export function HowIChecked({ trace }) {
  const steps = trace?.steps || []
  if (!steps.length) return null
  const secs = trace.elapsed_ms != null ? ` · ${(trace.elapsed_ms / 1000).toFixed(1)}s` : ''
  return (
    <details className="trace">
      <summary>How I checked this <span>({steps.length} {steps.length === 1 ? 'step' : 'steps'}{secs})</span></summary>
      <ol>
        {steps.map((s, i) => (
          <li key={i}><b>{s.service}</b><span>{s.text}</span>{s.ms != null && <small>{s.ms} ms</small>}</li>
        ))}
      </ol>
    </details>
  )
}

function Rate({ vote, onVote }) {
  return (
    <span className="rate" aria-label="Was this helpful?">
      <span>{vote ? 'Thanks for the feedback' : 'Helpful?'}</span>
      <button className={vote === 'up' ? 'on' : ''} onClick={() => onVote('up')} aria-label="Helpful" aria-pressed={vote === 'up'}>👍</button>
      <button className={vote === 'down' ? 'on' : ''} onClick={() => onVote('down')} aria-label="Not helpful" aria-pressed={vote === 'down'}>👎</button>
    </span>
  )
}

function Message({ m, live, onOption, onVote, onOpenComparison, busy }) {
  return (
    <div className={'turn ' + m.r}>
      <div className={'m ' + m.r + (m.error ? ' err' : '')}>
        {m.t}
        {m.sources?.length > 0 && <small className="src">From the GreatSchools guide: {m.sources.map(s => s.document ? `${s.title} (${s.document})` : s.title).join(' · ')}</small>}
        {m.callouts?.map((c, i) => <p key={i} className="callout"><b>{c.name}:</b> {c.text}</p>)}
        {m.question && <p className="ask"><b>{m.question.text}</b>{m.question.why && <small>{m.question.why}</small>}</p>}
        {m.comparison && <button className="link" onClick={() => onOpenComparison(m.comparison)}>Open the comparison table</button>}
        {m.programs?.length > 0 && <div className="progs">{m.programs.map(p => <ProgramCard key={p.program_id} p={p} />)}</div>}
      </div>
      {m.question && live && (
        <div className="choices">
          {m.question.options.map(o => <button key={o.id} disabled={busy} onClick={() => onOption(m.question, o)}>{o.label}</button>)}
        </div>
      )}
      {m.r === 'ai' && (m.trace || m.turn) && (
        <div className="under">
          <HowIChecked trace={m.trace} />
          {m.turn != null && <Rate vote={m.vote} onVote={v => onVote(m, v)} />}
        </div>
      )}
    </div>
  )
}

function Chat({ msgs, progress, busy, question, send, onOption, onVote, onOpenComparison }) {
  const [text, setText] = useState('')
  const box = useRef(null)
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight }, [msgs, progress])
  return (
    <aside className="chat">
      <div className="msgs" ref={box}>
        {msgs.map((m, i) => <Message key={i} m={m} live={!!m.question && m.question === question} busy={busy}
          onOption={onOption} onVote={onVote} onOpenComparison={onOpenComparison} />)}
        {busy && <div className="m ai typing" aria-live="polite">{progress || 'Thinking…'}</div>}
      </div>
      <form className="in" onSubmit={e => { e.preventDefault(); if (text.trim() && !busy) { send(text.trim()); setText('') } }}>
        <input value={text} onChange={e => setText(e.target.value)} disabled={busy}
          placeholder={question ? 'Or type your own answer…' : 'Ask anything, like “what is a charter school?”'} />
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
  const [saved, setSaved] = useState(new Map())  // school_id -> school (for the saved list)
  const [showSaved, setShowSaved] = useState(false)
  const [details, setDetails] = useState(null)
  const [split, setSplit] = useState(58)
  const [pane, setPane] = useState('schools')  // phones show one pane at a time
  const [unread, setUnread] = useState(false)
  const paneNow = useRef('schools')  // the pane on screen when a reply lands (replies are async)
  useEffect(() => { paneNow.current = pane; if (pane === 'chat') setUnread(false) }, [pane])
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
    const reply = { r: 'ai', t: '', trace: res.trace, turn: res.turn }
    let nextQuestion = null
    const results = (res.blocks || []).find(b => b.type === 'school_results')?.results
    for (const b of res.blocks || []) {
      if (b.type === 'criteria_chips') setChips(b)
      else if (b.type === 'text') { reply.t = reply.t ? `${reply.t}\n\n${b.markdown}` : b.markdown; if (b.sources) reply.sources = b.sources }
      else if (b.type === 'clarifying_question') nextQuestion = b
      else if (b.type === 'evidence_callout') {
        const name = (results || schools).find(r => r.school_id === b.school_id)?.name || 'One school'
        ;(reply.callouts ||= []).push({ name, text: b.text })
      } else if (b.type === 'school_results') {
        setSchools(b.results)
        setSaved(prev => { const n = new Map(prev); b.results.filter(r => r.saved).forEach(r => n.set(r.school_id, r)); return n })
        setPicked(p => p.filter(id => b.results.some(r => r.school_id === id)))
      } else if (b.type === 'program_results') setPrograms(b)
      else if (b.type === 'comparison') { setComparison(b); reply.comparison = b; if (b.summary) reply.t = b.summary }
    }
    if (nextQuestion) reply.question = nextQuestion
    if (!reply.t && !reply.question && !reply.callouts) {
      reply.t = kind === 'chip_edit' ? 'I updated the results for your new list.' : 'Here’s what I found.'
    }
    setQuestion(nextQuestion)
    addMsg(reply)
    // On a phone, a question needs the chat; otherwise flag the new reply on the Chat tab.
    if (nextQuestion && !results) setPane('chat')
    else if (paneNow.current !== 'chat') setUnread(true)
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

  const search = (text = query.trim()) => {
    if (!text || busy) return
    setQuery(text)
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
    // Update at once; undo if the server says no
    setSaved(s => { const n = new Map(s); on ? n.delete(r.school_id) : n.set(r.school_id, r); return n })
    try {
      if (on) await unsaveSchool(sid, r.school_id)
      else {
        const res = await saveSchool(sid, r.school_id)
        if (res.programs?.length) addMsg({ r: 'ai', t: `Saved ${r.name}. These nearby programs could help with what it doesn’t fully cover:`, programs: res.programs })
      }
    } catch (e) {
      setSaved(s => { const n = new Map(s); on ? n.set(r.school_id, r) : n.delete(r.school_id); return n })
      addMsg({ r: 'ai', t: `I couldn’t ${on ? 'remove' : 'save'} ${r.name}: ${e.message}`, error: true })
    }
  }

  const vote = async (m, v) => {
    const sid = session.current
    if (!sid || m.turn == null) return
    setMsgs(ms => ms.map(x => x === m ? { ...x, vote: v } : x))
    try { await rateReply(sid, m.turn, v) } catch { setMsgs(ms => ms.map(x => x.turn === m.turn && x.r === 'ai' ? { ...x, vote: undefined } : x)) }
  }

  const toggle = id => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : p.length >= 2 ? [p[1], id] : [...p, id])

  const newSearch = () => {
    session.current = null
    setSessionId(null); setChips(null); setSchools([]); setPrograms(null); setMsgs([]); setQuestion(null)
    setPicked([]); setSaved(new Map()); setShowSaved(false); setQuery(''); setZip(''); setStage('home')
    setPane('schools'); setUnread(false)
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
          <p>Tell us about your child and what matters to your family. We investigate. You decide.</p>
          <SearchBox {...{ query, setQuery, zip, setZip, busy }} onSearch={() => search()} />
          <div className="examples">
            <span>Not sure what to ask? Try:</span>
            {EXAMPLES.map(x => <button key={x} onClick={() => search(x)} disabled={busy}>{x}</button>)}
          </div>
        </main>
      </section>

      <section className="page pg-results">
        <header>
          <Logo />
          <SearchBox compact {...{ query, setQuery, zip, setZip, busy }} onSearch={() => search()} />
          <div className="savedw">
            <button className={'savedn' + (saved.size ? ' on' : '')} onClick={() => setShowSaved(v => !v)} aria-expanded={showSaved}>
              ♥ My list{saved.size ? ` (${saved.size})` : ''}
            </button>
            {showSaved && (
              <div className="savedlist" role="dialog" aria-label="My list">
                {saved.size === 0 ? <p className="meta">Tap the heart on a school to save it here.</p> : [...saved.values()].map(s => (
                  <div key={s.school_id} className="saveditem">
                    <button className="link" onClick={() => { setDetails(s); setShowSaved(false) }}>{s.name}</button>
                    <Heart on onClick={() => toggleSave(s)} name={s.name} />
                  </div>
                ))}
              </div>
            )}
          </div>
          <button className="back" onClick={newSearch}>New search</button>
        </header>
        <div className="tabs" role="tablist" aria-label="Show">
          <button role="tab" aria-selected={pane === 'schools'} onClick={() => setPane('schools')}>
            Schools{schools.length ? ` (${schools.length})` : ''}
          </button>
          <button role="tab" aria-selected={pane === 'chat'} onClick={() => setPane('chat')}>
            Chat{unread && <i className="dot" aria-label="new reply" />}
          </button>
        </div>
        <div className={'split pane-' + pane} ref={wrap}>
          <div className="list" style={{ width: split + '%' }}>
            <Chips block={chips} onRemove={removeChip} onAdd={addChip} busy={busy} />
            {schools.length > 0
              ? <p className="count">{schools.length} schools that match your search. Tap a school for how it fits each of your needs.</p>
              : <p className="count">{busy ? 'Looking for schools…' : sessionId ? 'Answer in the chat and I’ll find schools that fit.' : ''}</p>}
            <div className="cards">
              {schools.map(r => (
                <SchoolCard key={r.school_id} r={r} checked={picked.includes(r.school_id)} onToggle={toggle}
                  saved={saved.has(r.school_id)} onSave={toggleSave} onDetails={setDetails} />
              ))}
            </div>
            {programs?.programs?.length > 0 && (
              <>
                <h4 className="sub">Programs nearby, run by libraries and community centers</h4>
                <div className="cards">{programs.programs.map(p => <ProgramCard key={p.program_id} p={p} />)}</div>
                {programs.excluded_past?.length > 0 && (
                  <p className="count">Not shown because they already ended: {programs.excluded_past.map(x => x.name).join(', ')}</p>
                )}
              </>
            )}
            <div className="pad" />
          </div>
          <div className="bar" onPointerDown={drag} role="separator" aria-label="Resize panels" />
          <div className="chatw" style={{ width: 100 - split + '%' }}>
            <Chat msgs={msgs} progress={progress} busy={busy} question={question} send={send} onOption={answer}
              onVote={vote} onOpenComparison={setComparison} />
          </div>
        </div>
        <div className={'cmpbar' + (picked.length ? ' show' : '')} style={{ width: split + '%' }}>
          <span>{picked.length} of 2 picked to compare</span>
          <button disabled={picked.length < 2 || busy} onClick={compare}>Compare schools</button>
        </div>
      </section>
      {comparison && <CompareModal data={comparison} labels={labels} onClose={() => setComparison(null)} />}
      {details && <Details school={details} sessionId={sessionId} labels={labels} saved={saved.has(details.school_id)}
        onSave={toggleSave} onClose={() => setDetails(null)} />}
    </div>
  )
}
