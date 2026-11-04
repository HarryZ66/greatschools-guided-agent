import { useState, useRef, useEffect } from 'react'
import logo from './assets/greatschools-logo.png'
import { SCHOOLS, QUESTIONS, STATUS } from './data.js'

const Logo = () => <img className="logo" src={logo} alt="GreatSchools.org" />

function SearchBox({ query, setQuery, zip, setZip, onSearch, busy, compact }) {
  return (
    <form className={'sbox' + (compact ? ' compact' : '')} onSubmit={e => { e.preventDefault(); onSearch() }}>
      <input className="q" value={query} onChange={e => setQuery(e.target.value)}
        placeholder="Describe the school you’re looking for…" aria-label="Search" />
      <input className="zip" value={zip} onChange={e => setZip(e.target.value.replace(/\D/g, '').slice(0, 5))}
        placeholder="ZIP (optional)" inputMode="numeric" aria-label="ZIP code" />
      <button className={'go' + (busy ? ' busy' : '')} aria-label="Search">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      </button>
    </form>
  )
}

function SchoolCard({ s, checked, onToggle }) {
  return (
    <article className={'card' + (checked ? ' sel' : '')}>
      <div className="thumb" style={{ background: `linear-gradient(135deg,hsl(${s.hue} 55% 38%),hsl(${s.hue + 30} 60% 62%))` }}>
        <span>{s.name[0]}</span>
      </div>
      <div className="info">
        <div className="top">
          <h3>{s.name}</h3>
          <label className="cmp"><input type="checkbox" checked={checked} onChange={() => onToggle(s.id)} /> Compare</label>
        </div>
        <p className="meta">{s.city} · {s.type} · Grades {s.grades} · {s.distance}</p>
        <div className="stats"><b className={'rate ' + (s.rating >= 8 ? 'hi' : s.rating >= 5 ? 'mid' : 'lo')} title="Summary rating (1–10)">{s.rating}</b><span>Summary rating</span><span>{s.students} students</span><span>Ratio {s.ratio}</span></div>
        <ul className="tags">
          {s.tags.map(t => (
            <li key={t.l} className={'tag ' + t.s} title={t.e}>
              <i />{t.l}<small>{STATUS[t.s]} — {t.e}</small>
            </li>
          ))}
        </ul>
      </div>
    </article>
  )
}

function CompareModal({ items, onClose }) {
  useEffect(() => { const f = e => e.key === 'Escape' && onClose(); window.addEventListener('keydown', f); return () => window.removeEventListener('keydown', f) }, [onClose])
  const rows = [['Rating', s => s.rating + '/10'], ['Type', s => s.type], ['Grades', s => s.grades], ['Distance', s => s.distance],
    ['Students', s => s.students], ['Student–teacher ratio', s => s.ratio],
    ['After-school care', s => s.tags[0]], ['STEM program', s => s.tags[1]]]
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()} role="dialog" aria-label="Compare schools">
        <button className="x" onClick={onClose} aria-label="Close">×</button>
        <h2>Compare schools</h2>
        <div className="tw"><table>
          <thead><tr><th />{items.map(s => <th key={s.id}>{s.name}</th>)}</tr></thead>
          <tbody>{rows.map(([label, f]) => (
            <tr key={label}><th>{label}</th>{items.map(s => {
              const v = f(s)
              return <td key={s.id}>{typeof v === 'object' ? <span className={'tag ' + v.s}><i />{STATUS[v.s]}<small>{v.e}</small></span> : v}</td>
            })}</tr>))}</tbody>
        </table></div>
      </div>
    </div>
  )
}

function Chat({ msgs, options, send, free }) {
  const [text, setText] = useState('')
  const box = useRef(null)
  useEffect(() => { const b = box.current; if (b) b.scrollTop = b.scrollHeight }, [msgs, options])
  return (
    <aside className="chat">
      <div className="msgs" ref={box}>
        {msgs.map((m, i) => <div key={i} className={'m ' + m.r}>{m.t}</div>)}
      </div>
      {options && (
        <div className="choices">
          {options.map(o => <button key={o} onClick={() => send(o)}>{o}</button>)}
        </div>
      )}
      <form className="in" onSubmit={e => { e.preventDefault(); if (text.trim()) { send(text.trim()); setText('') } }}>
        <input value={text} onChange={e => setText(e.target.value)} placeholder={options ? 'Or type your own answer…' : free ? 'Type your answer…' : 'Tell us anything about your needs…'} />
        <button>Send</button>
      </form>
    </aside>
  )
}

export default function App() {
  const [query, setQuery] = useState('')
  const [zip, setZip] = useState('')
  const [stage, setStage] = useState('home')
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState([])
  const [showCmp, setShowCmp] = useState(false)
  const [split, setSplit] = useState(58)
  const [msgs, setMsgs] = useState([])
  const [cur, setCur] = useState(null)
  const wrap = useRef(null)

  const say = (t, delay = 500) => setTimeout(() => setMsgs(m => [...m, { r: 'ai', t }]), delay)
  const askNext = (i, delay) => {
    if (i >= QUESTIONS.length) { setCur(null); say('Thanks! I’ll use your answers to re-rank these schools. (Mock reply: backend not connected yet.)', delay); return }
    setTimeout(() => { setMsgs(m => [...m, { r: 'ai', t: QUESTIONS[i].q }]); setCur(i) }, delay)
  }
  const search = () => {
    if (busy) return
    setBusy(true)
    setTimeout(() => {
      setMsgs([{ r: 'ai', t: `I found ${SCHOOLS.length} schools for “${query || 'your search'}”. I checked each one against your criteria. I have a question to help me narrow these down.` }])
      setCur(null); askNext(0, 900)
      setStage('results'); setBusy(false)
    }, 650)
  }
  const send = t => {
    setMsgs(m => [...m, { r: 'me', t }])
    const next = cur === null ? null : cur + 1
    setCur(null)
    if (next === null) say('Thanks, I’ve noted that. (Mock reply: backend not connected yet.)')
    else { say('Got it.', 400); askNext(next, 1100) }
  }
  const toggle = id => setPicked(p => p.includes(id) ? p.filter(x => x !== id) : [...p, id])
  const drag = e => {
    e.preventDefault()
    const mv = ev => { const r = wrap.current.getBoundingClientRect(); setSplit(Math.min(75, Math.max(30, ((ev.clientX - r.left) / r.width) * 100))) }
    const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up)
  }
  const chosen = SCHOOLS.filter(s => picked.includes(s.id))

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
          <button className="back" onClick={() => setStage('home')}>New search</button>
        </header>
        <div className="split" ref={wrap}>
          <div className="list" style={{ width: split + '%' }}>
            <p className="count">{SCHOOLS.length} schools matched</p>
            {SCHOOLS.map(s => <SchoolCard key={s.id} s={s} checked={picked.includes(s.id)} onToggle={toggle} />)}
            <div className="pad" />
          </div>
          <div className="bar" onPointerDown={drag} role="separator" aria-label="Resize panels" />
          <div className="chatw" style={{ width: 100 - split + '%' }}><Chat msgs={msgs} send={send} options={cur !== null ? QUESTIONS[cur].options : null} free={cur !== null} /></div>
        </div>
        <div className={'cmpbar' + (picked.length ? ' show' : '')} style={{ width: split + '%' }}>
          <span>{picked.length} selected</span>
          <button disabled={picked.length < 2} onClick={() => setShowCmp(true)}>Compare schools</button>
        </div>
      </section>
      {showCmp && <CompareModal items={chosen} onClose={() => setShowCmp(false)} />}
    </div>
  )
}
