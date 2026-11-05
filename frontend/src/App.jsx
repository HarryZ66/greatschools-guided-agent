import { useState, useRef, useEffect, useId, forwardRef } from 'react'
import { motion, AnimatePresence, MotionConfig } from 'motion/react'
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
// "2026-11-03" -> "Tue, Nov 3" (UTC, so US time zones don't shift it a day) and "15:30" -> "3:30 PM"
const day = d => new Date(d + 'T00:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })
const clock = t => { const [h, m] = String(t).split(':').map(Number); return Number.isNaN(h) ? t : `${(h + 11) % 12 + 1}:${String(m || 0).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}` }

// The session id stands in for the signed-in parent (login is out of scope), so My list
// survives a refresh and a New search (docs/contract.md, section 3). Storage can be blocked.
const SID_KEY = 'gs_session_id'
const readSid = () => { try { return localStorage.getItem(SID_KEY) } catch { return null } }
const writeSid = sid => { try { if (sid) localStorage.setItem(SID_KEY, sid) } catch { /* private mode */ } }

const Logo = () => <img className="logo" src={logo} alt="GreatSchools.org" />

// Motion: things move to show what changed after a parent acts (MotionConfig below turns
// movement off for people who ask their device for reduced motion).
const spring = { type: 'spring', stiffness: 380, damping: 32 }
const soft = { type: 'spring', stiffness: 240, damping: 28 }
const rise = { hidden: { opacity: 0, y: 14 }, show: { opacity: 1, y: 0, transition: soft } }
const stagger = (each = 0.07, after = 0) => ({ hidden: {}, show: { transition: { staggerChildren: each, delayChildren: after } } })
const step = i => Math.min(i, 8) * 0.06  // cards come in one after another, capped so long lists don't wait

function SearchBox({ query, setQuery, onSearch, busy, compact, variants }) {
  return (
    <motion.form variants={variants} className={'sbox' + (compact ? ' compact' : '')} onSubmit={e => { e.preventDefault(); onSearch() }}>
      <input className="q" value={query} onChange={e => setQuery(e.target.value)}
        placeholder="Tell us about your child and what you need…" aria-label="Search" />
      <button className={'go' + (busy ? ' busy' : '')} aria-label="Search" disabled={busy}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      </button>
    </motion.form>
  )
}

const BURST = [0, 60, 120, 180, 240, 300].map(a => (a * Math.PI) / 180)

// Saving pops the heart and throws a small burst, so the parent sees it took.
function Heart({ on, onClick, name }) {
  const [pops, setPops] = useState(0)
  return (
    <motion.button className={'heart' + (on ? ' on' : '')} whileTap={{ scale: 0.82 }} aria-pressed={on}
      onClick={() => { if (!on) setPops(n => n + 1); onClick() }}
      aria-label={on ? `Remove ${name} from your list` : `Save ${name} to your list`} title={on ? 'Saved to your list' : 'Save to your list'}>
      <motion.svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true" initial={false}
        animate={on ? { scale: [1, 1.35, 1] } : { scale: 1 }} transition={{ duration: 0.35 }}>
        <path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 4.5 6.7 4.5c2.1 0 3.6 1.2 5.3 3.1 1.7-1.9 3.2-3.1 5.3-3.1 3.7 0 5.8 3.9 4.3 7.3C19.5 16.4 12 21 12 21z" />
      </motion.svg>
      {pops > 0 && (
        <span className="burst" key={pops} aria-hidden="true">
          {BURST.map(a => <motion.i key={a} initial={{ x: 0, y: 0, opacity: 1, scale: 1 }}
            animate={{ x: Math.cos(a) * 17, y: Math.sin(a) * 17, opacity: 0, scale: 0.4 }} transition={{ duration: 0.5, ease: 'easeOut' }} />)}
        </span>
      )}
    </motion.button>
  )
}

const Pin = () => (
  <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" className="pin">
    <path d="M12 22s7-6.2 7-12a7 7 0 10-14 0c0 5.8 7 12 7 12z" /><circle cx="12" cy="10" r="2.6" />
  </svg>
)

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
    <motion.ul className="checks" variants={stagger(0.05)}>
      {(criteria || []).map(c => {
        const st = status(c.status)
        return (
          <motion.li key={c.need} className={st.cls} variants={rise}>
            <span className="ic" aria-hidden="true">{st.icon}</span>
            <span><b>{labels[c.need] || humanize(c.need)}</b> <em>{st.word}</em>{c.note && <small>{c.note}</small>}</span>
          </motion.li>
        )
      })}
    </motion.ul>
  )
}

function Chips({ block, onRemove, onAdd, busy }) {
  if (!block) return null
  const { chips = [], unmapped = [], suggested = [] } = block
  return (
    <div className="chipbar">
      {/* Added chips grow in and removed ones shrink away; the rest slide over to make room */}
      <div className="chips" aria-label="What you asked for">
        <AnimatePresence initial={false} mode="popLayout">
          {chips.map(c => (
            <motion.span key={c.need} layout transition={spring} initial={{ opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.7 }} className={'chip ' + c.mode + (c.source === 'inferred' ? ' inferred' : '')}
              title={c.source === 'inferred' ? 'I assumed this. Remove it if it’s wrong.' : c.mode === 'require' ? 'Must have' : 'Nice to have'}>
              {c.mode === 'require' && <i className="must">Must</i>}{c.mode === 'avoid' && <i className="must">Avoid</i>}{c.label}
              {!FIXED_NEEDS.has(c.need) && <button className="chipx" disabled={busy} onClick={() => onRemove(c.need)} aria-label={`Remove ${c.label}`}>×</button>}
            </motion.span>
          ))}
          {unmapped.map(u => <motion.span key={'u-' + u} layout exit={{ opacity: 0 }} className="chip unmapped" title="We can’t check this in our data yet">{u}: can’t check yet</motion.span>)}
        </AnimatePresence>
      </div>
      {suggested.length > 0 && (
        <div className="chips sugg">
          <span className="hint">Also worth checking?</span>
          <AnimatePresence initial={false} mode="popLayout">
            {suggested.map(s => (
              <motion.button key={s.need} layout transition={spring} initial={{ opacity: 0, scale: 0.7 }} animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.7 }} whileTap={{ scale: 0.94 }} className="chip suggested" disabled={busy} title={s.why}
                onClick={() => onAdd(s.need)}>+ {s.label}</motion.button>
            ))}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}

const TypeTag = ({ type }) => <span className={'type t-' + type}>{TYPE[type] || humanize(type)}</span>

const Rosette = () => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true" className="rosette">
    <path d="M8 14.5L5.5 22l3.3-1.6L11 23l1-7.2M16 14.5l2.5 7.5-3.3-1.6L13 23l-1-7.2" className="tails" />
    <circle cx="12" cy="9" r="7" /><path d="M12 5.4l1.1 2.3 2.5.3-1.8 1.8.4 2.5L12 11.1l-2.2 1.2.4-2.5-1.8-1.8 2.5-.3z" className="star" />
  </svg>
)

// One "Best for ..." per school, chosen in code (decision 031); `why` says what it's based on.
// On a card it's a ribbon tied around the card's edge, with one shine when the results land.
function Badge({ badge, full }) {
  if (!badge) return null
  return (
    <p className={'badge' + (full ? ' full' : '')} title={full ? undefined : badge.why}>
      <span className="ribbon">
        <Rosette />
        <span><b>{badge.label}</b>{full && <small>{badge.why}</small>}</span>
        {!full && <i className="shine" aria-hidden="true" />}
      </span>
    </p>
  )
}

// The card stays short: who the school is, its one standout, and what to watch. The full
// checklist for every need lives in the details panel. Cards come in one after another;
// when a search changes, the ones that stay slide to their new place.
const SchoolCard = forwardRef(function SchoolCard({ r, i, deps, checked, onToggle, saved, onSave, onDetails }, ref) {
  return (
    <motion.article ref={ref} className={'card school' + (checked ? ' sel' : '')} style={{ '--d': `${0.5 + step(i)}s` }}
      layout="position" layoutDependency={deps} transition={spring}
      initial={{ opacity: 0, y: 18, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1, transition: { ...soft, delay: step(i) } }}
      exit={{ opacity: 0, scale: 0.94, transition: { duration: 0.18 } }}>
      <header className="card-head">
        <TypeTag type={r.entity_type} />
        <Heart on={saved} onClick={() => onSave(r)} name={r.name} />
      </header>
      <h3><button className="name" onClick={() => onDetails(r)}>{r.name}</button></h3>
      <p className="place"><Pin />{r.city}</p>
      {r.cost && <p className="meta cost"><Cost cost={r.cost} /></p>}
      <Badge badge={r.badge} />
      {r.watch_out && <p className="watch" title={r.watch_out}><b>Good to know:</b> {r.watch_out}</p>}
      <footer className="card-foot">
        <button className="link" onClick={() => onDetails(r)}>See details and reviews</button>
        <label className={'cmp' + (checked ? ' on' : '')}>
          <input type="checkbox" checked={checked} onChange={() => onToggle(r.school_id)} />
          <span>{checked ? 'Comparing' : 'Compare'}</span>
        </label>
      </footer>
    </motion.article>
  )
})

// Grey stand-in cards while the first search runs, shaped like the real ones
function Placeholders() {
  return (
    <div className="cards" aria-hidden="true">
      {[0, 1, 2, 3, 4, 5].map(i => (
        <div key={i} className="card skel" style={{ '--i': i }}><i className="s-tag" /><i className="s-name" /><i className="s-line" /><i className="s-badge" /></div>
      ))}
    </div>
  )
}

function ProgramCard({ p, i = 0 }) {
  const next = (p.next_sessions || [])[0]
  const mi = miles(p)
  return (
    <motion.article className="card prog" initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0, transition: { ...soft, delay: step(i) } }}>
      <h3>{p.url ? <a href={p.url} target="_blank" rel="noreferrer">{p.name}</a> : p.name}</h3>
      <p className="meta">{p.organization} · {p.city}{mi != null && p.near ? ` · ${mi} miles from ${p.near}` : ''}</p>
      <p className="meta">{[p.ages, p.cost, p.meets_on?.length ? `Meets ${p.meets_on.join(', ')}` : null,
        next ? `Next: ${day(next.date)} · ${clock(next.start)}–${clock(next.end)}` : null, p.registration_open ? 'Sign-up open' : null].filter(Boolean).join(' · ')}</p>
      {p.why && <p className="why">{p.why}</p>}
      {p.time_fit && <p className={'fit ' + status(p.time_fit.status).cls}>{status(p.time_fit.status).icon} {p.time_fit.note}</p>}
      {p.quality_flags?.length > 0 && <p className="watch"><b>Good to know:</b> {p.quality_flags.map(f => f.note).join(' ')}</p>}
    </motion.article>
  )
}

const fade = { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 }, transition: { duration: 0.2 } }

function CompareModal({ data, labels, onClose }) {
  useEffect(() => { const f = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f) }, [onClose])
  return (
    <motion.div className="overlay" onClick={onClose} {...fade}>
      <motion.div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-label="Compare schools"
        initial={{ opacity: 0, y: 28, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }} transition={spring}>
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <h2>Compare schools</h2>
        {data.summary && <p className="summary">{data.summary}</p>}
        <div className="tw"><table>
          <thead><tr><th />{(data.names || data.school_ids).map(n => <th key={n}>{n}</th>)}</tr></thead>
          <motion.tbody initial="hidden" animate="show" variants={stagger(0.04, 0.12)}>{data.rows.map(row => (
            <motion.tr key={row.need} variants={rise}><th>{labels[row.need] || row.label || humanize(row.need)}</th>{row.cells.map((c, i) => {
              const st = status(c.status)
              // "No problems found" needs no badge; everything else shows the check's status.
              return <td key={i} className={st.cls}>{row.need === 'data_quality' && c.status === 'confirmed'
                ? <span className="none">{c.text}</span>
                : <><span className="ic">{st.icon}</span> <em>{st.word}</em><small>{c.text}</small></>}</td>
            })}</motion.tr>))}</motion.tbody>
        </table></div>
      </motion.div>
    </motion.div>
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
    <motion.div className="overlay side" onClick={onClose} {...fade}>
      <motion.aside className="drawer" onClick={e => e.stopPropagation()} role="dialog" aria-label={`${school.name} details`}
        initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }} transition={{ type: 'spring', stiffness: 320, damping: 36 }}>
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <div className="drawer-head">
          <h2>{school.name}</h2>
          <Heart on={saved} onClick={() => onSave(school)} name={school.name} />
        </div>
        <p className="meta drawer-meta"><TypeTag type={school.entity_type} />{data ? [data.street, data.city, data.zipcode].filter(Boolean).join(', ') : school.city}</p>
        <Badge badge={school.badge} full />
        {error && <p className="watch">I couldn’t load this school: {error}</p>}
        {!data && !error && <div className="skel-lines" aria-label="Loading"><i /><i /><i /><i /></div>}
        {p && <motion.div initial="hidden" animate="show" variants={stagger(0.06)}>
          {facts.length > 0 && <motion.dl className="facts" variants={rise}>{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</motion.dl>}
          {p.cost && <motion.p className="meta" variants={rise}><Cost cost={p.cost} /></motion.p>}
          {p.criteria?.length > 0 && <motion.section variants={rise}><h4>How it fits what you asked for</h4><Checks criteria={p.criteria} labels={labels} /></motion.section>}
          <motion.section variants={rise}>
            <h4>What parents say</h4>
            {p.reviews?.total ? <>
              <p className="meta">{p.reviews.total} review{p.reviews.total === 1 ? '' : 's'}</p>
              {(p.reviews.excerpts || []).map((x, i) => (
                <blockquote key={i}>“{x.text}”<small>{x.date}{x.older ? ', an older review that may not reflect today' : ''}</small></blockquote>
              ))}
            </> : <p className="meta">No reviews yet.</p>}
          </motion.section>
          {p.quality_flags?.length > 0 && <motion.section variants={rise}><h4>Problems in our data</h4><ul className="flags">{p.quality_flags.map(f => <li key={f.field}>{f.note}</li>)}</ul></motion.section>}
          {p.terms?.length > 0 && <motion.section variants={rise}><h4>Words on this page</h4>{p.terms.map(t => <details key={t.id} className="term"><summary>{t.title}</summary><p>{t.body}</p></details>)}</motion.section>}
        </motion.div>}
      </motion.aside>
    </motion.div>
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

// Splits a reply into its first sentence and the rest, for the short view (decision 032).
// Code only, so the prompt and evals don't change. A boundary is ., ! or ? followed by a
// space and a word that doesn't start lowercase (so "St. Johns" and "4.5 miles" don't split),
// or a line break. A first sentence under 25 characters ("Good question.") takes the next one too.
const ABBR = /\b(?:St|Dr|Mr|Mrs|Ms|Ave|Blvd|Rd|Mt|Ft|Jr|Sr|No|vs|etc|approx|e\.g|i\.e|U\.S)\.$/i
export function firstSentence(text) {
  const t = (text || '').trim()
  const end = /[.!?…]+["”’)\]*_]*(?=\s+[^\sa-z])|\n/g
  for (let m; (m = end.exec(t));) {
    const cut = m.index + m[0].length
    const head = t.slice(0, cut).trim()
    if (m[0] !== '\n' && ABBR.test(head)) continue
    if (head.length < 25) continue
    return [head, t.slice(cut).trim()]
  }
  return [t, '']
}

function Message({ m, live, onOption, onVote, onOpenComparison, busy }) {
  const [open, setOpen] = useState(false)
  const ai = m.r === 'ai' && !m.error
  const [summary, rest] = ai ? firstSentence(m.t) : [m.t, '']
  const notes = m.callouts?.length || 0
  const hasMore = ai && !!(rest || notes || m.sources?.length || m.question?.why)
  const full = open || !hasMore
  const id = useId()
  return (
    <motion.div className={'turn ' + m.r} style={{ transformOrigin: m.r === 'me' ? 'bottom right' : 'top left' }}
      initial={{ opacity: 0, y: 12, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={soft}>
      <div className={'m ' + m.r + (m.error ? ' err' : '')}>
        {summary}
        {hasMore && (
          <span className="more">
            <button className="link" aria-expanded={open} aria-controls={id} onClick={() => setOpen(o => !o)}>
              {open ? 'View less' : 'View more'}
            </button>
            {/* Data notes stay signposted while collapsed: flagging old or missing data is the point */}
            {!open && notes > 0 && (
              <button className="notes" onClick={() => setOpen(true)} aria-label={`Show ${notes} data ${notes === 1 ? 'note' : 'notes'}`}>
                ⚠️ {notes} data {notes === 1 ? 'note' : 'notes'}
              </button>
            )}
          </span>
        )}
        <AnimatePresence initial={false}>
          {full && (rest || notes > 0 || m.sources?.length > 0) && (
            <motion.div id={id} className="rest" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.2 }}>
              {rest && <div className="t">{rest}</div>}
              {m.sources?.length > 0 && <small className="src">From the GreatSchools guide: {m.sources.map(s => s.document ? `${s.title} (${s.document})` : s.title).join(' · ')}</small>}
              {m.callouts?.map((c, i) => <p key={i} className="callout"><b>{c.name}:</b> {c.text}</p>)}
            </motion.div>
          )}
        </AnimatePresence>
        {m.question && <p className="ask"><b>{m.question.text}</b>{full && m.question.why && <small>{m.question.why}</small>}</p>}
        {m.comparison && <button className="link" onClick={() => onOpenComparison(m.comparison)}>Open the comparison table</button>}
        {m.programs?.length > 0 && <div className="progs">{m.programs.map((p, i) => <ProgramCard key={p.program_id} p={p} i={i} />)}</div>}
      </div>
      <AnimatePresence>
        {m.question && live && (
          <motion.div className="choices" initial="hidden" animate="show" exit={{ opacity: 0, transition: { duration: 0.15 } }} variants={stagger(0.05, 0.15)}>
            {m.question.options.map(o => <motion.button key={o.id} variants={rise} whileTap={{ scale: 0.95 }} disabled={busy}
              onClick={() => onOption(m.question, o)}>{o.label}</motion.button>)}
          </motion.div>
        )}
      </AnimatePresence>
      {m.r === 'ai' && (m.trace || m.turn) && (
        <div className="under">
          <HowIChecked trace={m.trace} />
          {m.turn != null && <Rate vote={m.vote} onVote={v => onVote(m, v)} />}
        </div>
      )}
    </motion.div>
  )
}

// Three bouncing dots plus the backend's progress line, which swaps in place as it changes
function Typing({ progress }) {
  return (
    <motion.div className="m ai typing" aria-live="polite" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={soft}>
      <span className="dots" aria-hidden="true"><i /><i /><i /></span>
      <AnimatePresence mode="wait" initial={false}>
        <motion.span key={progress || 'thinking'} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -5 }} transition={{ duration: 0.18 }}>
          {progress || 'Thinking…'}
        </motion.span>
      </AnimatePresence>
    </motion.div>
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
        <AnimatePresence>{busy && <Typing key="typing" progress={progress} />}</AnimatePresence>
      </div>
      <form className="in" onSubmit={e => { e.preventDefault(); if (text.trim() && !busy) { send(text.trim()); setText('') } }}>
        <input value={text} onChange={e => setText(e.target.value)} disabled={busy}
          placeholder={question ? 'Or type your own answer…' : 'Ask anything, like “what is a charter school?”'} />
        <motion.button whileTap={{ scale: 0.94 }} disabled={busy}>Send</motion.button>
      </form>
    </aside>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
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
    writeSid(res.session_id)
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
    run({ type: 'query', text }, text)
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

  // Start over with the same parent: the server forgets the conversation and returns the kept list
  const restart = async sid => {
    if (!sid) return
    try {
      const res = await turn(sid, { type: 'new_search' })
      session.current = res.session_id
      setSessionId(res.session_id)
      writeSid(res.session_id)
      setSaved(new Map((res.saved || []).map(s => [s.school_id, s])))
    } catch { /* the list just stays as it is */ }
  }

  const newSearch = () => {
    setChips(null); setSchools([]); setPrograms(null); setMsgs([]); setQuestion(null)
    setPicked([]); setShowSaved(false); setQuery(''); setStage('home')
    setPane('schools'); setUnread(false)
    restart(session.current)
  }

  useEffect(() => {  // a returning parent: fresh conversation, same saved list
    const sid = readSid()
    if (sid) { session.current = sid; setSessionId(sid); restart(sid) }
  }, [])

  const drag = e => {
    e.preventDefault()
    const mv = ev => { const r = wrap.current.getBoundingClientRect(); setSplit(Math.min(75, Math.max(30, ((ev.clientX - r.left) / r.width) * 100))) }
    const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up)
  }

  return (
    <MotionConfig reducedMotion="user">
    <div className={'app s-' + stage}>
      <section className="page pg-home">
        <header>
          <Logo />
          {saved.size > 0 && (  // a returning parent sees the list they saved last time
            <button className="savedn on home-saved" onClick={() => { setStage('results'); setShowSaved(true) }}>
              ♥ My list ({saved.size})
            </button>
          )}
        </header>
        {/* The one entrance on page load: headline, line, search box, then the examples */}
        <motion.main initial="hidden" animate="show" variants={stagger(0.09, 0.1)}>
          <motion.h1 variants={rise}>Find the right school, together.</motion.h1>
          <motion.p variants={rise}>Tell us about your child and what matters to your family. We investigate. You decide.</motion.p>
          <SearchBox variants={rise} {...{ query, setQuery, busy }} onSearch={() => search()} />
          <motion.div className="examples" variants={stagger(0.06)}>
            <motion.span variants={rise}>Not sure what to ask? Try:</motion.span>
            {EXAMPLES.map(x => <motion.button key={x} variants={rise} whileTap={{ scale: 0.96 }} onClick={() => search(x)} disabled={busy}>{x}</motion.button>)}
          </motion.div>
        </motion.main>
      </section>

      <section className="page pg-results">
        <header>
          <Logo />
          <SearchBox compact {...{ query, setQuery, busy }} onSearch={() => search()} />
          <div className="savedw">
            <button className={'savedn' + (saved.size ? ' on' : '')} onClick={() => setShowSaved(v => !v)} aria-expanded={showSaved}>
              ♥ My list{saved.size > 0 && <> (<motion.span className="n" key={saved.size} initial={{ scale: 1.6 }} animate={{ scale: 1 }} transition={spring}>{saved.size}</motion.span>)</>}
            </button>
            <AnimatePresence>
              {showSaved && (
                <motion.div className="savedlist" role="dialog" aria-label="My list" style={{ transformOrigin: 'top right' }}
                  initial={{ opacity: 0, scale: 0.94, y: -6 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96, y: -4 }} transition={spring}>
                  {saved.size === 0 ? <p className="meta">Tap the heart on a school to save it here.</p> : (
                    <AnimatePresence initial={false}>
                      {[...saved.values()].map(s => (
                        <motion.div key={s.school_id} className="saveditem" layout exit={{ opacity: 0, height: 0, paddingTop: 0, paddingBottom: 0 }}>
                          <button className="link" onClick={() => { setDetails(s); setShowSaved(false) }}>{s.name}</button>
                          <Heart on onClick={() => toggleSave(s)} name={s.name} />
                        </motion.div>
                      ))}
                    </AnimatePresence>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <button className="back" onClick={newSearch}>New search</button>
        </header>
        <div className="tabs" role="tablist" aria-label="Show">
          {[['schools', <>Schools{schools.length ? ` (${schools.length})` : ''}</>], ['chat', <>Chat{unread && <i className="dot" aria-label="new reply" />}</>]].map(([id, label]) => (
            <button key={id} role="tab" aria-selected={pane === id} onClick={() => setPane(id)}>
              {pane === id && <motion.span className="pill" layoutId="tab-pill" transition={spring} />}
              <span className="lbl">{label}</span>
            </button>
          ))}
        </div>
        <div className={'split pane-' + pane} ref={wrap}>
          <motion.div className="list" style={{ width: split + '%' }} layoutScroll>
            <AnimatePresence>
              {busy && schools.length > 0 && <motion.div key="bar" className="refresh" aria-hidden="true" {...fade} />}
            </AnimatePresence>
            <Chips block={chips} onRemove={removeChip} onAdd={addChip} busy={busy} />
            {schools.length > 0
              ? <p className="count"><b>{schools.length} schools</b> match your search. Tap one to see how it fits each of your needs.</p>
              : <p className="count">{busy ? 'Looking for schools…' : sessionId ? 'Answer in the chat and I’ll find schools that fit.' : ''}</p>}
            {busy && !schools.length && <Placeholders />}
            <div className={'cards schools' + (busy && schools.length ? ' stale' : '')}>
              <AnimatePresence mode="popLayout">
                {schools.map((r, i) => (
                  <SchoolCard key={r.school_id} r={r} i={i} deps={schools} checked={picked.includes(r.school_id)} onToggle={toggle}
                    saved={saved.has(r.school_id)} onSave={toggleSave} onDetails={setDetails} />
                ))}
              </AnimatePresence>
            </div>
            {programs?.programs?.length > 0 && (
              <>
                <h4 className="sub">Programs nearby, run by libraries and community centers</h4>
                <div className="cards">{programs.programs.map((p, i) => <ProgramCard key={p.program_id} p={p} i={i} />)}</div>
                {programs.excluded_past?.length > 0 && (
                  <p className="count">Not shown because they already ended: {programs.excluded_past.map(x => x.name).join(', ')}</p>
                )}
              </>
            )}
            <div className="pad" />
          </motion.div>
          <div className="bar" onPointerDown={drag} role="separator" aria-label="Resize panels" />
          <div className="chatw" style={{ width: 100 - split + '%' }}>
            <Chat msgs={msgs} progress={progress} busy={busy} question={question} send={send} onOption={answer}
              onVote={vote} onOpenComparison={setComparison} />
          </div>
        </div>
        <motion.div className="cmpbar" style={{ width: split + '%' }} initial={false} animate={{ y: picked.length ? 0 : '110%' }} transition={spring}>
          <span className="picks" aria-live="polite">
            {[0, 1].map(k => <i key={k} className={k < picked.length ? 'on' : ''} />)}
            {picked.length < 2 ? `Pick ${2 - picked.length} more to compare` : `${picked.map(nameOf).join(' and ')}`}
          </span>
          <motion.button whileTap={{ scale: 0.95 }} disabled={picked.length < 2 || busy} onClick={compare}>Compare schools</motion.button>
        </motion.div>
      </section>
      <AnimatePresence>
        {comparison && <CompareModal key="compare" data={comparison} labels={labels} onClose={() => setComparison(null)} />}
      </AnimatePresence>
      <AnimatePresence>
        {details && <Details key={details.school_id} school={details} sessionId={sessionId} labels={labels} saved={saved.has(details.school_id)}
          onSave={toggleSave} onClose={() => setDetails(null)} />}
      </AnimatePresence>
    </div>
    </MotionConfig>
  )
}
