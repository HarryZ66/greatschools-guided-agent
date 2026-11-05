// Quick dictionary for school terms (pain point: parents don't know the jargon, decision 044).
// A known term gets a dashed underline; hover, keyboard focus or a tap shows a one-line meaning.
// Definitions are short versions of the parent guide (data/content/guide.json).
import { useState, useRef, useLayoutEffect, useEffect, useId } from 'react'
import { createPortal } from 'react-dom'
import { motion } from 'motion/react'

// `acronyms` match only in capitals ("AP", not "ap"; "ESA", not Spanish "esa"); `words` in any case.
// Plurals ("IEPs", "charter schools") match too.
const ENTRIES = [
  { id: 'stem', title: 'STEM', acronyms: ['STEM', 'STEAM'], def: 'Science, technology, engineering and math. A STEM school puts extra focus on these, often with labs, robotics or coding.' },
  { id: 'iep', title: 'IEP', acronyms: ['IEP'], words: ['individualized education program'], def: 'A written plan for a student with a disability. It lists the child’s goals and the extra help the school will give.' },
  { id: '504', title: '504 plan', acronyms: ['504'], words: ['504 plan', 'section 504'], def: 'A plan that gives a student with a disability changes like extra test time or a seat near the teacher, in a regular class.' },
  { id: 'special-ed', title: 'Special education', words: ['special education', 'special ed'], def: 'Extra teaching and services for students with disabilities. Public schools provide it for free.' },
  { id: 'ell', title: 'English learner support', acronyms: ['ELL', 'ESL', 'ESOL'], def: 'Help for students who are still learning English, like extra English classes or help inside regular classes.' },
  { id: 'ap', title: 'AP classes', acronyms: ['AP'], words: ['advanced placement'], def: 'College-level classes taught in high school. A good score on the final exam can earn college credit.' },
  { id: 'ib', title: 'IB', acronyms: ['IB'], words: ['international baccalaureate'], def: 'A demanding international high school program with its own classes and exams. It can earn college credit.' },
  { id: 'cte', title: 'Career classes (CTE)', acronyms: ['CTE'], words: ['career and technical education'], def: 'Classes that teach job skills for careers like health care, tech, building trades or cooking.' },
  { id: 'dual', title: 'Dual enrollment', words: ['dual enrollment'], def: 'High school students taking real college courses, often for free, that count for high school and college.' },
  { id: 'charter', title: 'Charter school', words: ['charter school', 'charter'], def: 'A free public school run by its own organization instead of the school district. Many pick students by lottery.' },
  { id: 'magnet', title: 'Magnet school', words: ['magnet school', 'magnet program', 'magnet'], def: 'A free public school built around a focus like science, the arts or languages. Students can come from across the district.' },
  { id: 'montessori', title: 'Montessori', words: ['montessori'], def: 'A way of teaching with mixed-age classes and hands-on materials, where children choose much of their own work.' },
  { id: 'microschool', title: 'Microschool', words: ['microschool', 'micro-school'], def: 'A very small school, often a few dozen students or fewer, sometimes meeting in homes or community spaces.' },
  { id: 'k8', title: 'K-8 school', words: ['K-8'], def: 'One school from kindergarten through 8th grade, so children don’t switch schools for middle school.' },
  { id: 'gifted', title: 'Gifted program', words: ['gifted and talented', 'gifted'], def: 'Extra challenge for students who learn quickly, through separate classes, small groups or harder work in class.' },
  { id: 'zoned', title: 'Zoned school', words: ['zoned school', 'attendance zone', 'attendance boundary'], def: 'The public school assigned to your home address. Your child is guaranteed a seat there.' },
  { id: 'open-enrollment', title: 'Open enrollment', words: ['open enrollment'], def: 'A way to enroll in a public school other than your zoned school, if it has room.' },
  { id: 'lottery', title: 'Lottery', words: ['lottery'], def: 'When a school has more applicants than seats, it picks students at random.' },
  { id: 'ratio', title: 'Student-teacher ratio', words: ['student-teacher ratio', 'students per teacher'], def: 'How many students there are for each teacher. A rough guide to class size, not an exact count.' },
  { id: 'absence', title: 'Chronic absence', words: ['chronic absence', 'chronically absent', 'chronic absenteeism'], def: 'Missing 10% or more of the school year, about 18 days.' },
  { id: 'esa', title: 'Education Savings Account', acronyms: ['ESA'], words: ['education savings account'], def: 'A state program that puts money in an account parents control, for costs like private school tuition or tutoring.' },
  { id: 'voucher', title: 'School voucher', words: ['voucher'], def: 'A state program that uses public money to pay some or all of a child’s private school tuition.' },
  { id: 'tax-credit', title: 'Tax-credit scholarship', words: ['tax-credit scholarship', 'tax credit scholarship'], def: 'A scholarship for private school, paid by a nonprofit from donations that earn the donors a tax credit.' },
  { id: 'fl-scholarship', title: 'Florida scholarship', acronyms: ['FES-EO', 'FES-UA', 'FES', 'FTC'], def: 'A Florida state scholarship that helps families pay for private school.' },
]

const ACRONYMS = new Map()
const WORDS = new Map()
for (const e of ENTRIES) {
  for (const a of e.acronyms || []) ACRONYMS.set(a, e)
  for (const w of e.words || []) WORDS.set(w.toLowerCase(), e)
}
const escape = s => s.replace(/[.*+?^${}()|[\]\\-]/g, '\\$&')
const ALTS = [...ACRONYMS.keys(), ...WORDS.keys()].sort((a, b) => b.length - a.length).map(escape)
// No letters, digits or "$" right before (so "$16,504" isn't the 504 plan), no letters right after
const RE = new RegExp(`(?<![\\w$,.\\-])(?:${ALTS.join('|')})s?(?![\\w\\-])`, 'gi')

function lookup(word) {
  const bare = word.endsWith('s') || word.endsWith('S') ? word.slice(0, -1) : null
  return ACRONYMS.get(word) || (bare && ACRONYMS.get(bare)) || WORDS.get(word.toLowerCase()) || (bare && WORDS.get(bare.toLowerCase())) || null
}

// Text with each known term underlined, the first time it appears. `inert` is for text inside a
// button or chip: the underline and hover still work, and a tap does what the button does.
export function Terms({ text, inert }) {
  if (typeof text !== 'string' || !text) return text ?? null
  const parts = []
  const seen = new Set()
  let last = 0
  for (const m of text.matchAll(RE)) {
    const entry = lookup(m[0])
    if (!entry || seen.has(entry.id)) continue
    seen.add(entry.id)
    parts.push(text.slice(last, m.index), <Term key={m.index} word={m[0]} entry={entry} inert={inert} />)
    last = m.index + m[0].length
  }
  if (!parts.length) return text
  parts.push(text.slice(last))
  return parts
}

function Term({ word, entry, inert }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const id = useId()
  useEffect(() => {
    if (!open) return
    const close = e => { if (e.type !== 'keydown' || e.key === 'Escape') setOpen(false) }
    const outside = e => { if (!ref.current?.contains(e.target)) setOpen(false) }
    window.addEventListener('keydown', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('pointerdown', outside)
    return () => {
      window.removeEventListener('keydown', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('pointerdown', outside)
    }
  }, [open])
  return (
    <span ref={ref} className="gloss" tabIndex={inert ? undefined : 0} aria-describedby={open ? id : undefined}
      onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onClick={inert ? undefined : e => { e.stopPropagation(); setOpen(true) }}>
      {word}
      {open && createPortal(<Tip id={id} anchor={ref} entry={entry} />, document.body)}
    </span>
  )
}

// Above the term, or below it near the top of the screen; always inside the window.
function Tip({ id, anchor, entry }) {
  const box = useRef(null)
  const [at, setAt] = useState(null)
  useLayoutEffect(() => {
    const r = anchor.current?.getBoundingClientRect()
    const t = box.current?.getBoundingClientRect()
    if (!r || !t) return
    const above = r.top - t.height - 8
    const below = above < 8
    setAt({
      top: below ? r.bottom + 8 : above,
      left: Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8),
      origin: below ? 'top center' : 'bottom center',
    })
  }, [anchor])
  return (
    <motion.div ref={box} id={id} role="tooltip" className="gloss-tip"
      style={at ? { top: at.top, left: at.left, transformOrigin: at.origin } : { top: 0, left: 0, visibility: 'hidden' }}
      initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.15 }}>
      <b>{entry.title}</b>{entry.def}
    </motion.div>
  )
}
