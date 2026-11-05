import { useState, useRef, useEffect, useLayoutEffect, useId, forwardRef } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence, MotionConfig } from 'motion/react'
import logo from './assets/greatschools-logo.png'
import { turn, saveSchool, unsaveSchool, rateReply, getSchool, getPartners, requestVisit, listVisits } from './api.js'

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

const PAGE = 4  // cards shown at first; "View more schools" adds this many (decision 041)
// A school's distinctive words ("Tamarind Cove" from "Tamarind Cove STEM Academy"), to spot it in a reply
const core = name => (name || '').replace(/\b(Elementary|Middle|High|Senior|Junior|Charter|Preparatory|Prep|STEM|Academy|School|Center|K-8)\b/g, '').replace(/\s+/g, ' ').trim()

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

const BUCKETS = [['require', 'Must have'], ['prefer', 'Nice to have'], ['avoid', 'Avoid']]  // in this order on the chip line
const pop = { initial: { opacity: 0, scale: 0.7 }, animate: { opacity: 1, scale: 1 }, exit: { opacity: 0, scale: 0.7 }, transition: spring }

// A chip's own menu: move it to the other bucket, or turn it off. Words, not icons, so a parent
// knows what each choice does; Escape or a click elsewhere closes it.
function ChipMenu({ c, anchor, onMove, onOff, onClose }) {
  const box = useRef(null)
  const [at, setAt] = useState(null)
  useLayoutEffect(() => {  // placed on the page, so a chip row that scrolls sideways can't clip it
    const r = anchor.getBoundingClientRect()
    setAt({ top: r.bottom + 6, left: Math.max(8, Math.min(r.left, window.innerWidth - 228)) })
  }, [])
  useEffect(() => {
    box.current?.querySelector('button')?.focus()
    const key = e => { if (e.key === 'Escape') { onClose(); anchor.querySelector('.clabel')?.focus() } }
    const away = e => { if (!box.current?.contains(e.target) && !anchor.contains(e.target)) onClose() }
    const moved = e => { if (!box.current?.contains(e.target)) onClose() }
    window.addEventListener('keydown', key); window.addEventListener('pointerdown', away)
    window.addEventListener('scroll', moved, true); window.addEventListener('resize', onClose)
    return () => {
      window.removeEventListener('keydown', key); window.removeEventListener('pointerdown', away)
      window.removeEventListener('scroll', moved, true); window.removeEventListener('resize', onClose)
    }
  }, [onClose, anchor])
  const to = c.mode === 'require' ? ['prefer', 'Move to Nice to have'] : ['require', 'Move to Must have']
  return (
    <motion.div ref={box} className="chipmenu" role="menu" aria-label={`${c.label} options`} style={{ transformOrigin: 'top left', ...(at || { visibility: 'hidden' }) }}
      initial={{ opacity: 0, scale: 0.94, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }} exit={{ opacity: 0, scale: 0.96 }} transition={spring}>
      {c.mode !== 'avoid' && <button role="menuitem" onClick={() => { onClose(); onMove(c, to[0]) }}>{to[1]}</button>}
      <button role="menuitem" onClick={() => { onClose(); onOff(c) }}>Turn off</button>
    </motion.div>
  )
}

// What the parent asked for, on one line: "Must have" chips, then "Nice to have" chips, each
// group named by a small label. Grade and place are fixed (search again to change them). Any
// other chip opens a menu to move it to the other group or turn it off; × turns it off at once.
// Turned-off chips stay at the end, faded, and one tap turns them back on. Chips slide to their
// new place when they change group.
function Filters({ block, off, onMove, onOff, onOn, onAdd, busy }) {
  const [menu, setMenu] = useState(null)
  if (!block) return null
  const { chips = [], unmapped = [], suggested = [], profile } = block
  const next = profile?.topics.find(t => !t.done)
  const offList = [...off.values()].filter(o => !chips.some(c => c.need === o.need))
  const menuChip = chips.find(c => c.need === menu?.need)
  const flow = []
  for (const [mode, title] of BUCKETS) {
    const these = chips.filter(c => c.mode === mode)
    if (!these.length) continue
    flow.push(<motion.span key={'t-' + mode} layout="position" className="btitle">{title}</motion.span>)
    for (const c of these) {
      const fixed = FIXED_NEEDS.has(c.need)
      flow.push(
        <motion.span key={c.need} layout="position" {...pop}
          className={'chip ' + c.mode + (c.source === 'inferred' ? ' inferred' : '') + (fixed ? ' fixed' : '')}
          title={fixed ? 'Search again to change this' : c.source === 'inferred' ? 'I assumed this. Change it if it’s wrong.' : undefined}>
          {fixed ? <span className="clabel">{c.label}</span> : (
            <button className="clabel" disabled={busy} aria-haspopup="menu" aria-expanded={menu?.need === c.need}
              onClick={e => { const el = e.currentTarget.parentElement; setMenu(m => m?.need === c.need ? null : { need: c.need, el }) }}>
              {c.label}<svg viewBox="0 0 12 12" width="10" height="10" aria-hidden="true"><path d="M3 4.5l3 3 3-3" /></svg>
            </button>
          )}
          {!fixed && <button className="chipx" disabled={busy} onClick={() => onOff(c)} aria-label={`Turn off ${c.label}`} title="Turn off">×</button>}
        </motion.span>)
    }
  }
  for (const u of unmapped) {
    flow.push(<motion.span key={'u-' + u} layout="position" {...pop} className="chip unmapped" title="We can’t check this in our data yet">{u}: can’t check yet</motion.span>)
  }
  for (const o of offList) {
    flow.push(
      <motion.button key={o.need} layout="position" {...pop} whileTap={{ scale: 0.94 }} className="chip off" disabled={busy}
        onClick={() => onOn(o)} title="Turned off. Tap to turn it back on" aria-label={`Turn ${o.label} back on`}>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M3.5 6.5h6a3 3 0 010 6H7M3.5 6.5L6 4M3.5 6.5L6 9" /></svg>{o.label}
      </motion.button>)
  }
  return (
    <div className="buckets">
      {/* The family profile the agent's questions fill in, one topic at a time (decision 042) */}
      {profile && (
        <div className="profile" aria-label={`Your family profile: ${profile.done} of ${profile.total} topics known`}>
          <span className="lbl">Your family profile</span>
          <span className="segs" aria-hidden="true">
            {profile.topics.map(t => <motion.i key={t.id} title={t.label} className={t.done ? 'on' : ''} initial={false}
              animate={{ scaleY: t.done ? 1 : 0.6 }} transition={spring} />)}
          </span>
          <span className="hint">{profile.done === profile.total ? 'Complete' : `${profile.done} of ${profile.total}`}
            {next && <> · next: {next.label.toLowerCase()}</>}</span>
        </div>
      )}
      {/* The menu goes on the page body: the sticky header's blur would offset a fixed position */}
      {createPortal(<AnimatePresence>{menuChip && !busy && <ChipMenu key={menuChip.need} c={menuChip} anchor={menu.el}
        onMove={onMove} onOff={onOff} onClose={() => setMenu(null)} />}</AnimatePresence>, document.body)}
      <div className="chips" aria-label="What you asked for">
        <AnimatePresence initial={false} mode="popLayout">{flow}</AnimatePresence>
      </div>
      {suggested.length > 0 && (
        <div className="chips sugg">
          <span className="btitle">Also worth checking?</span>
          <AnimatePresence initial={false} mode="popLayout">
            {suggested.map(s => (
              <motion.button key={s.need} layout="position" {...pop} whileTap={{ scale: 0.94 }} className="chip suggested" disabled={busy} title={s.why}
                onClick={() => onAdd(s)}>+ {s.label}</motion.button>
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

// One "Best for ..." per school, chosen in code (decision 032); `why` says what it's based on.
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
    // The whole card opens the details panel, except its own buttons and the Compare box (PR #20)
    <motion.article ref={ref} className={'card school school-card' + (checked ? ' sel' : '')} style={{ '--d': `${0.5 + step(i)}s` }}
      onClick={e => { if (!e.target.closest('button, a, input, label')) onDetails(r) }}
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
        <button className="link" onClick={() => onDetails(r)}>See fit, programs and reviews</button>
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

function SchoolFit({ profile, labels }) {
  const criteria = profile.criteria || []
  const confirmed = criteria.filter(c => c.status === 'confirmed')
  const gaps = criteria.filter(c => c.status !== 'confirmed')
  return (
    <section className="school-fit" aria-label="How it fits">
      <h4>How it fits</h4>
      {!criteria.length ? <p className="meta">Tell us what matters to your family in the search to see this school’s fit and nearby programs.</p> : <>
        <p className="meta">{confirmed.length} of {criteria.length} needs confirmed for this school.</p>
        {confirmed.length > 0 && <Checks criteria={confirmed} labels={labels} />}
        {gaps.length > 0 && <>
          <h4>Where you may need extra support</h4>
          <p className="meta">Nearby programs may help with some gaps. Missing or older school information still needs checking with the school.</p>
          {gaps.map(c => {
            const matches = (profile.programs || []).filter(p => p.fills_need === c.need)
            return <div className="fit-gap" key={c.need}>
              <Checks criteria={[c]} labels={labels} />
              {matches.length > 0 ? <>
                <p className="program-label">A nearby option that could help</p>
                {matches.map(p => <ProgramCard key={p.program_id} p={p} />)}
              </> : <p className="meta gap-empty">{profile.programs_status !== 'ready'
                ? 'We couldn’t check nearby programs. Try opening this school again.'
                : 'No suitable program to suggest for this need yet. Ask the school about your options.'}</p>}
            </div>
          })}
          {(profile.programs || []).length > 0 && <p className="meta">Check availability, eligibility and travel between the school and program before making plans.</p>}
        </>}
      </>}
    </section>
  )
}

// P3: the verified profile for one school, built by the backend's code for this parent's needs.
function Details({ school, sessionId, labels, saved, onSave, onClose }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    let active = true
    setData(null); setError(null)
    getSchool(sessionId, school.school_id)
      .then(result => { if (active) setData(result) })
      .catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [sessionId, school.school_id])
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
          <motion.div variants={rise}><SchoolFit profile={p} labels={labels} /></motion.div>
          <motion.h4 variants={rise}>School details</motion.h4>
          {facts.length > 0 && <motion.dl className="facts" variants={rise}>{facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</motion.dl>}
          {p.cost && <motion.p className="meta" variants={rise}><Cost cost={p.cost} /></motion.p>}
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

// Splits a reply into its first sentence and the rest, for the short view (decision 033).
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

// The step after saving: see the schools in person with a local partner (decision 042)
function VisitOffer({ offer, onPlan }) {
  const names = offer.partners.map(p => p.name)
  return (
    <motion.div className="visit-offer" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={soft}>
      <b>Next step: see them in person</b>
      <span>{offer.text}</span>
      <small>{names.slice(0, 2).join(' or ')}{names.length > 2 ? ` and ${names.length - 2} more` : ''} · free</small>
      <motion.button whileTap={{ scale: 0.95 }} onClick={() => onPlan(offer)}>Plan a visit</motion.button>
    </motion.div>
  )
}

const WHEN = { 'Weekday mornings': 'on a weekday morning', 'Weekday afternoons': 'on a weekday afternoon', Evenings: 'in the evening', Saturdays: 'on a Saturday' }
const pick = (list, value, set, label = x => x) => (
  <div className="pills">{list.map(x => (
    <button key={x} type="button" className={value === x ? 'on' : ''} aria-pressed={value === x} onClick={() => set(x)}>{label(x)}</button>
  ))}</div>
)

function VisitPlanner({ seed, sessionId, onClose, onSent }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [partnerId, setPartnerId] = useState(null)
  const [schoolIds, setSchoolIds] = useState([])
  const [way, setWay] = useState('visit')
  const [when, setWhen] = useState(null)
  const [language, setLanguage] = useState(null)
  const [note, setNote] = useState('')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(null)
  useEffect(() => {
    let active = true
    getPartners(sessionId, (seed?.schools || []).map(s => s.school_id))
      .then(d => { if (!active) return; setData(d); if (d.partners[0]) choose(d.partners[0]) })
      .catch(e => { if (active) setError(e.message) })
    return () => { active = false }
  }, [sessionId, seed])
  useEffect(() => { const f = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f) }, [onClose])
  const choose = p => { setPartnerId(p.partner_id); setSchoolIds(p.schools.map(s => s.school_id)); setLanguage(p.languages[0]) }
  const partner = data?.partners.find(p => p.partner_id === partnerId)
  const toggle = id => setSchoolIds(ids => ids.includes(id) ? ids.filter(x => x !== id) : [...ids, id])
  const ready = partner && schoolIds.length && when && language && !sending
  const submit = async e => {
    e.preventDefault()
    if (!ready) return
    setSending(true); setError(null)
    try {
      const res = await requestVisit({ session_id: sessionId, partner_id: partnerId, school_ids: schoolIds, way, when, language, note })
      setSent(res.request); onSent(res.requests, res.request)
    } catch (err) { setError(err.message) } finally { setSending(false) }
  }
  return (
    <motion.div className="overlay" onClick={onClose} {...fade}>
      <motion.div className="modal visit" onClick={e => e.stopPropagation()} role="dialog" aria-label="Plan a school visit"
        initial={{ opacity: 0, y: 28, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 16, scale: 0.98 }} transition={spring}>
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <h2>See schools in person</h2>
        {sent ? (
          <motion.div className="sent" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={spring}>
            <p className="big">✓ Request sent to {sent.partner_name}</p>
            <p>{sent.way_label} for {sent.schools.map(s => s.name).join(', ')}, {WHEN[sent.when] || sent.when}, in {sent.language}.
              They’ll contact you through your GreatSchools account, usually by {day(sent.reply_by)}.</p>
            <p className="meta">You’ll find this request in My list.</p>
            <button className="cta" onClick={onClose}>Done</button>
          </motion.div>
        ) : <>
          <p className="summary">GreatSchools works with local nonprofits and parent guides who know these schools first-hand. They can visit with you, or talk your list through first. It’s free.</p>
          {error && <p className="watch">{error}</p>}
          {!data && !error && <div className="skel-lines" aria-label="Loading"><i /><i /><i /></div>}
          {data && !data.partners.length && <p className="meta">We don’t have a local partner for {data.schools.length ? 'these schools' : 'your list'} yet. Save a school first, or ask the school for a tour.</p>}
          {data?.partners.length > 0 && <form onSubmit={submit}>
            <h4>Who can help</h4>
            <div className="partners">{data.partners.map(p => (
              <label key={p.partner_id} className={'partner' + (p.partner_id === partnerId ? ' on' : '')}>
                <input type="radio" name="partner" checked={p.partner_id === partnerId} onChange={() => choose(p)} />
                <b>{p.name}</b><small>{p.kind}</small>
                <span>{p.what}</span>
                <small>Knows {p.schools.map(s => s.name).join(', ')} · {p.languages.join(', ')} · replies in about {p.reply_days} days</small>
              </label>
            ))}</div>
            {partner && <>
              <h4>Which schools?</h4>
              <div className="pills">{partner.schools.map(s => (
                <button key={s.school_id} type="button" className={schoolIds.includes(s.school_id) ? 'on' : ''}
                  aria-pressed={schoolIds.includes(s.school_id)} onClick={() => toggle(s.school_id)}>{s.name}</button>
              ))}</div>
              <h4>How?</h4>
              {pick(partner.ways, way, setWay, w => data.ways[w])}
              <h4>When are you free?</h4>
              {pick(data.times, when, setWhen)}
              <h4>Language</h4>
              {pick(partner.languages, language, setLanguage)}
              <h4>Anything they should know? <small>(optional)</small></h4>
              <textarea value={note} maxLength={300} rows={2} onChange={e => setNote(e.target.value)}
                placeholder="For example: we need to see the after-school program" />
            </>}
            <div className="send">
              <motion.button className="cta" whileTap={{ scale: 0.96 }} disabled={!ready}>{sending ? 'Sending…' : 'Send request'}</motion.button>
              <small>Sample partners for this demo: no request reaches anyone.</small>
            </div>
          </form>}
        </>}
      </motion.div>
    </motion.div>
  )
}

function Message({ m, live, canUndo, onUndo, onOption, onVote, onOpenComparison, onPlanVisit, busy }) {
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
        {m.visit && <VisitOffer offer={m.visit} onPlan={onPlanVisit} />}
      </div>
      {/* Turning a need off is undone in one tap, right where the parent reads the result */}
      <AnimatePresence>
        {m.undo && canUndo && (
          <motion.div className="choices" {...pop}>
            <motion.button className="undo" whileTap={{ scale: 0.95 }} disabled={busy} onClick={() => onUndo(m.undo)}>
              <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M3.5 6.5h6a3 3 0 010 6H7M3.5 6.5L6 4M3.5 6.5L6 9" /></svg>
              Turn “{m.undo.label}” back on
            </motion.button>
          </motion.div>
        )}
      </AnimatePresence>
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

function Chat({ msgs, progress, busy, question, send, off, onUndo, onOption, onVote, onOpenComparison, onPlanVisit }) {
  const [text, setText] = useState('')
  const box = useRef(null)
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight }, [msgs, progress])
  return (
    <aside className="chat">
      <div className="msgs" ref={box}>
        {msgs.map((m, i) => <Message key={i} m={m} live={!!m.question && m.question === question} busy={busy}
          canUndo={!!m.undo && off.has(m.undo.need)} onUndo={onUndo}
          onOption={onOption} onVote={onVote} onOpenComparison={onOpenComparison} onPlanVisit={onPlanVisit} />)}
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
  const [planning, setPlanning] = useState(null)  // the visit offer the planner opened from, or {} from My list
  const [visits, setVisits] = useState([])  // visit and call requests to local partners
  const [split, setSplit] = useState(58)
  const [pane, setPane] = useState('schools')  // phones show one pane at a time
  const [unread, setUnread] = useState(false)
  const [off, setOff] = useState(new Map())  // need -> chip the parent turned off, to turn back on in one tap
  const [shown, setShown] = useState(PAGE)  // how many school cards are on screen
  const paneNow = useRef('schools')  // the pane on screen when a reply lands (replies are async)
  useEffect(() => { paneNow.current = pane; if (pane === 'chat') setUnread(false) }, [pane])
  const wrap = useRef(null)
  const session = useRef(null)  // the latest session_id, for calls made between renders

  const labels = Object.fromEntries((chips?.chips || []).map(c => [c.need, c.label]))
  const nameOf = id => schools.find(s => s.school_id === id)?.name || id
  const addMsg = m => setMsgs(ms => [...ms, m])

  // Apply one /api/turn response: each block updates its part of the page, and the
  // turn's text, notes and question become one chat reply with its trace underneath.
  const apply = (res, kind, extra) => {
    session.current = res.session_id
    setSessionId(res.session_id)
    writeSid(res.session_id)
    const reply = { r: 'ai', t: '', trace: res.trace, turn: res.turn, ...(extra?.undo ? { undo: extra.undo } : {}) }
    let nextQuestion = null
    const calloutIds = []
    const results = (res.blocks || []).find(b => b.type === 'school_results')?.results
    for (const b of res.blocks || []) {
      if (b.type === 'criteria_chips') {
        setChips(b)
        setOff(prev => { const n = new Map(prev); (b.chips || []).forEach(c => n.delete(c.need)); return n })
      }
      else if (b.type === 'text') { reply.t = reply.t ? `${reply.t}\n\n${b.markdown}` : b.markdown; if (b.sources) reply.sources = b.sources }
      else if (b.type === 'clarifying_question') nextQuestion = b
      else if (b.type === 'evidence_callout') {
        const name = (results || schools).find(r => r.school_id === b.school_id)?.name || 'One school'
        ;(reply.callouts ||= []).push({ name, text: b.text })
        calloutIds.push(b.school_id)
      } else if (b.type === 'school_results') {
        setSchools(b.results)
        setSaved(prev => { const n = new Map(prev); b.results.filter(r => r.saved).forEach(r => n.set(r.school_id, r)); return n })
        setPicked(p => p.filter(id => b.results.some(r => r.school_id === id)))
      } else if (b.type === 'program_results') setPrograms(b)
      else if (b.type === 'comparison') { setComparison(b); reply.comparison = b; if (b.summary) reply.t = b.summary }
      else if (b.type === 'visit_offer') reply.visit = b
    }
    // A chip edit keeps the open question: leave it live where it was instead of asking it twice
    const same = nextQuestion && question && nextQuestion.question_id === question.question_id
    if (nextQuestion && !same) reply.question = nextQuestion
    if (kind === 'chip_edit' && !reply.t) reply.t = extra?.note || 'I updated the results for your new list.'
    else if (!reply.t && !reply.question && !reply.callouts) reply.t = extra?.note || 'Here’s what I found.'
    if (results) {
      // A new search starts at the first 4 cards (a chip edit keeps what the parent opened), and
      // every card the reply talks about is shown, so no school it names is hidden
      const said = [reply.t, nextQuestion?.text, ...(reply.callouts || []).map(c => c.text)].join(' ')
      let last = -1
      results.forEach((r, i) => { const w = core(r.name); if (calloutIds.includes(r.school_id) || (w.length > 3 && said.includes(w))) last = i })
      setShown(n => Math.max(kind === 'chip_edit' ? n : PAGE, Math.ceil((last + 1) / PAGE) * PAGE))
    }
    setQuestion(same ? question : nextQuestion)
    addMsg(reply)
    // On a phone, a question needs the chat; otherwise flag the new reply on the Chat tab.
    if (nextQuestion && !results) setPane('chat')
    else if (paneNow.current !== 'chat') setUnread(true)
  }

  const run = async (event, mine, extra) => {
    if (busy) return
    if (mine) addMsg({ r: 'me', t: mine })
    setBusy(true); setProgress('')
    try {
      apply(await turn(session.current, event, setProgress), event.type, extra)
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
  // Chip edits run in code on the server, no model call (decision 006)
  const turnOff = c => {
    if (busy) return
    setOff(prev => new Map(prev).set(c.need, { need: c.need, label: c.label, mode: c.mode, value: c.value }))
    run({ type: 'chip_edit', need: c.need, removed: true }, `Turn off “${c.label}”`,
      { undo: { need: c.need, label: c.label }, note: `I turned off “${c.label}” and updated the schools.` })
  }
  const turnOn = ({ need }) => {
    const c = off.get(need)
    if (!c || busy) return
    run({ type: 'chip_edit', need, mode: c.mode, ...(c.value != null ? { value: c.value } : {}) }, `Turn “${c.label}” back on`,
      { note: `“${c.label}” is back on, and the schools are updated.` })
  }
  const moveChip = (c, mode) => {
    const where = mode === 'require' ? 'a must-have' : 'nice to have'
    run({ type: 'chip_edit', need: c.need, mode }, `Make “${c.label}” ${where}`, { note: `“${c.label}” is now ${where}, and the schools are updated.` })
  }
  const addChip = s => run({ type: 'chip_edit', need: s.need, mode: 'prefer' }, `Add “${s.label}”`,
    { note: `I added “${s.label}” as nice to have and updated the schools.` })
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
        // The agent keeps going after a save (decision 042): the next profile question, or a visit offer
        const q = res.follow_up?.find(b => b.type === 'clarifying_question')
        const visit = res.follow_up?.find(b => b.type === 'visit_offer')
        if (q || visit) {
          const lead = res.programs?.length ? '' : `Saved ${r.name}. `
          addMsg({ r: 'ai', t: lead + (q ? 'One more question while you look, so I can keep narrowing your list.' : ''), question: q, visit })
          if (q) setQuestion(q)
          if (paneNow.current !== 'chat') setUnread(true)
        }
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
    try { setVisits((await listVisits(sid)).requests || []) } catch { /* shown next time */ }
  }

  const newSearch = () => {
    setChips(null); setSchools([]); setPrograms(null); setMsgs([]); setQuestion(null)
    setPicked([]); setShowSaved(false); setQuery(''); setStage('home')
    setPane('schools'); setUnread(false); setOff(new Map()); setShown(PAGE)
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
                  {/* The end of the journey: from a saved list to seeing the schools with someone local */}
                  {visits.map(v => (
                    <p key={v.request_id} className="visitreq">
                      <b>✓ {v.way === 'call' ? 'Call' : 'Visit'} requested</b> with {v.partner_name} for {v.schools.map(s => s.name).join(', ')}.
                      <small>They’ll reply by {day(v.reply_by)}.</small>
                    </p>
                  ))}
                  {saved.size > 0 && (
                    <button className="cta small" onClick={() => { setPlanning({ schools: [...saved.values()] }); setShowSaved(false) }}>
                      Plan a visit with a local guide
                    </button>
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
            {/* The filters stay put while the cards scroll under them */}
            <div className="filters">
              <Filters block={chips} off={off} onMove={moveChip} onOff={turnOff} onOn={turnOn} onAdd={addChip} busy={busy} />
              <AnimatePresence>
                {busy && schools.length > 0 && <motion.div key="bar" className="refresh" aria-hidden="true" {...fade} />}
              </AnimatePresence>
            </div>
            {schools.length > 0
              ? <p className="count"><b>{schools.length} schools</b> match your search<span>. Tap one to see how it fits.</span></p>
              : <p className="count">{busy ? 'Looking for schools…' : sessionId ? 'Answer in the chat and I’ll find schools that fit.' : ''}</p>}
            {busy && !schools.length && <Placeholders />}
            <div className={'cards schools' + (busy && schools.length ? ' stale' : '')}>
              <AnimatePresence mode="popLayout">
                {schools.slice(0, shown).map((r, i) => (
                  <SchoolCard key={r.school_id} r={r} i={i % PAGE} deps={schools} checked={picked.includes(r.school_id)} onToggle={toggle}
                    saved={saved.has(r.school_id)} onSave={toggleSave} onDetails={setDetails} />
                ))}
              </AnimatePresence>
            </div>
            {schools.length > shown && (
              <div className="moreschools">
                <motion.button whileTap={{ scale: 0.97 }} onClick={() => setShown(n => n + PAGE)}>View more schools</motion.button>
                <span>{shown} of {schools.length} shown</span>
              </div>
            )}
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
              off={off} onUndo={turnOn}
              onVote={vote} onOpenComparison={setComparison} onPlanVisit={setPlanning} />
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
      <AnimatePresence>
        {planning && <VisitPlanner key="visit" seed={planning} sessionId={sessionId} onClose={() => setPlanning(null)}
          onSent={(all, req) => {
            setVisits(all)
            addMsg({ r: 'ai', t: `I sent your ${req.way === 'call' ? 'call' : 'visit'} request to ${req.partner_name}. They usually reply by ${day(req.reply_by)}. After your visits, tell me which school felt right and I’ll help with the next steps.` })
          }} />}
      </AnimatePresence>
    </div>
    </MotionConfig>
  )
}
