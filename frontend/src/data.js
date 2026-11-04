// Mock data — replace with backend API responses later.
export const SCHOOLS = [
  { id:1, name:'Woodstock Middle School', city:'Woodstock, GA', grades:'6–8', type:'Public', rating:9, students:1120, ratio:'17:1', distance:'1.8 mi', hue:152,
    tags:[{l:'After-school care',s:'confirmed',e:'Program runs until 6 PM (2025 listing)'},{l:'STEM program',s:'confirmed',e:'Robotics + coding electives'}] },
  { id:2, name:'Cherokee Charter Academy', city:'Canton, GA', grades:'6–8', type:'Charter', rating:8, students:640, ratio:'15:1', distance:'4.2 mi', hue:205,
    tags:[{l:'After-school care',s:'partial',e:'Ends at 5 PM — may not fit your schedule'},{l:'STEM program',s:'confirmed',e:'STEM-focused curriculum'}] },
  { id:3, name:'Etowah Prep', city:'Woodstock, GA', grades:'6–12', type:'Private', rating:7, students:410, ratio:'11:1', distance:'3.1 mi', hue:28,
    tags:[{l:'After-school care',s:'attention',e:'Listing is from 2023 — please verify'},{l:'STEM program',s:'partial',e:'Mentioned in 2 reviews, no official program'}] },
  { id:4, name:'Sixes Magnet Middle', city:'Canton, GA', grades:'6–8', type:'Magnet', rating:8, students:870, ratio:'118:1', distance:'6.5 mi', hue:280,
    tags:[{l:'After-school care',s:'confirmed',e:'District-run care until 6 PM'},{l:'STEM program',s:'attention',e:'Student-teacher ratio (118:1) looks like a data error'}] },
]
// Questions the AI asks one at a time (backend later). If `options` exists, they show as tappable choices under the chat;
// otherwise the parent types a free-text answer.
export const QUESTIONS = [
  { id:'care', q:'Until what time do you need after-school care?', options:['Before 5 PM','5–7 PM','After 7 PM','No care needed'] },
  { id:'stem', q:'What would you want your child to get out of a STEM program?' },
  { id:'dist', q:'How far can you realistically travel to school each day?', options:['Under 3 miles','3–5 miles','5–10 miles','Distance doesn’t matter'] },
]
export const STATUS = { confirmed:'Confirmed', partial:'Partially meets', attention:'Needs attention' }
