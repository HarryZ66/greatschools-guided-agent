# What parents can do

A walk through the app from a parent's side, in the order they meet each feature. The problem
each one answers is in [`pain-points.md`](pain-points.md). How each one is built is in
[`decisions.md`](decisions.md) (decision numbers in brackets).

## 1. Search in their own words

- **One search box.** Parents type what they need the way they'd say it: "Middle school near Miami
  for my son who loves robotics. I work until 6pm." No filters to learn.
- **The app turns it into a short list of needs**, shown as chips: *Middle school · Near Miami ·
  Care until 6pm · Robotics / STEM*. "Care until 6pm" comes from "I work until 6"; the parent never
  had to know the term. [016]
- **Chips in two groups:** "Must have" and "Nice to have". Tap a chip to move it to the other group
  or turn it off. A turned-off chip stays at the end, faded, and one tap brings it back. [041]
- **A ZIP code works too.** If the area isn't covered yet, the app says so and lists the areas it
  does cover, instead of guessing. [030]
- **Spanish works**, along with English.

## 2. Get guided with questions

- **One question at a time.** The agent asks what parents don't think to ask: how the child
  learns, getting there and pickup, feeling safe and supported, classes, what the child enjoys,
  and budget. Each question comes with 2 to 4 answer buttons. [023, 042]
- **It never asks the same thing twice**, and it keeps going after a save or a comparison. [042]
- **Trade-offs, explained.** When the best match falls short, it says how and offers a way out: "Tamarind
  Cove's care ends at 5pm. A free robotics club at the library runs 5 to 6:30pm. Would that work?"
  [009]
- **"Also worth checking?"** suggests needs the parent didn't mention, such as counseling support,
  with a short reason. [016, 017]

## 3. See results they can trust

- **Ranked school cards**, 4 at first, with "View more schools" for more. [041]
- **One "Best for …" badge per school**, such as "Best for late pickup", given only when the data
  clearly backs it. [032]
- **"How it fits"** when a parent opens a school: which needs are confirmed, which are partly met,
  and which need a closer look, each with the evidence. [019, 031]
- **Honest about bad data.** Old or missing information is flagged ("Good to know", "Watch out")
  instead of hidden. [030, 033]
- **"How I checked this"** under every reply shows the steps the agent really took. [022]
- **Plain words.** No "IEP", "504" or "CTE" unless the parent uses them; distances in miles;
  ratings as "4 out of 10". [024]
- **Quick dictionary.** School terms that still appear, like "Charter", "STEM" or "AP", have a
  dashed underline. Hover or tap to see what they mean in one line. [044]
- **Short replies.** Each reply shows one sentence, with "View more" for the rest. [033]

## 4. Understand the cost

- **Cost after typical scholarship help.** A private school shows its tuition and what it may cost
  after a typical Florida scholarship: "$16,500 a year · about $8,300 with a typical scholarship".
  It's labeled an estimate, not a promise. [018]

## 5. Fill the gaps with local programs

- **Programs that fill a school's gaps.** If a school's care ends too early, the app finds a
  nearby library or community program that covers the rest of the afternoon. [010, 020]
- Programs show up in results, when a school is opened, and right after it's saved. [020, 031]

## 6. Compare two schools

- **Side-by-side table.** Tick Compare on two schools to see them need by need, with cost and data
  warnings. The agent then asks the one question that would settle the choice. [042]

## 7. Ask about schools and terms

- **Questions about education.** "What is a charter school?" or "What does the rating mean?" get a
  short answer from the GreatSchools-style parent guide, with its source. [008, 028]

## 8. Save, give feedback, and visit

- **My list.** Save schools with the heart. The list stays after a refresh or a new search. [029]
- **"Helpful?"** thumbs up or down on results and replies. [024]
- **Plan a visit with a local partner.** After saving or comparing, the app offers a visit with a
  local nonprofit or parent guide who knows the schools. The parent picks the partner, schools, a
  visit or a call, a time and a language. [042]

## Fairness, built in

The agent never filters, ranks or steers by race, ethnicity, national origin, religion, disability
or income. Needs tied to a child's disability or language only appear when the parent asks for
them. [007, 032]

## What it doesn't do (yet)

- Log in: the demo assumes the parent is signed in.
- Use real GreatSchools data: every school, program and partner is made up.
- Send visit requests to anyone: partners are samples, and the app says so.
- Reach parents who haven't searched yet (Level 3, texts and emails).
