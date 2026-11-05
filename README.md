# GreatSchools Guided Agent

**We investigate. You decide.**

A school search that works like talking to a helpful advisor. A parent describes what their child
needs in their own words. The app asks a few simple questions, checks every school against what
matters to that family, and shows the best matches, with the reasons and an honest note when
information is missing or out of date.

Built by Team 18 (SchoolFish) at AWS Breaking Barriers 2026 in Seattle, for GreatSchools.

## The problem

Choosing a school has become a maze. Today's search asks parents to pick filters and assumes they
know what to look for. Families with money and time get help from friends and advisors; everyone
else is left guessing.

We focused on the two problems that matter most:

1. **Parents don't know what to ask.** They miss needs like after-school care or counseling until
   it's too late.
2. **Parents don't know about help with cost.** They rule out schools without knowing a scholarship
   could cover about half.

Along the way, we also tackled jargon, lack of time, and not knowing which information to trust.
More in [The problems we're solving](docs/pain-points.md).

## What a parent can do

- **Type one sentence**, like "Middle school near Miami for my son who loves robotics. I work
  until 6pm."
- **Answer a few simple questions** about their child, one at a time, with tap-to-answer buttons.
- **See the best schools first**, each with what it's best for and how well it fits.
- **See the real cost**, including what a typical scholarship would cover.
- **Find local programs** that fill a school's gaps, like a library club that runs until 6.
- **Compare two schools** side by side.
- **Save schools to a list** and **plan a visit** with a local partner who knows the schools.

The full list is in [What parents can do](docs/features.md).

## Try it

The demo runs on made-up Miami-area schools. Try a search like:

> Middle school near Miami for my son who loves robotics. I work until 6pm.

To run it yourself, see the [technical guide](docs/technical.md).

## Good to know

- **Made-up data only.** Every school, program and partner is fictional. No real GreatSchools data
  and no student data.
- **Fair by design.** The app never sorts or steers families by race, religion, disability or
  income.
- **No login.** The demo assumes the parent is signed in.

## More reading

| Document | What's in it |
|---|---|
| [The problems we're solving](docs/pain-points.md) | The parent problems we chose, and how the app answers each |
| [What parents can do](docs/features.md) | Every feature, in the order a parent meets it |
| [Technical guide](docs/technical.md) | How it's built on AWS, how to deploy, load data, run and test it |
| [API contract](docs/contract.md) | The API and what the app shows for each response |
| [Decisions](docs/decisions.md) | Why things are the way they are |
| [Next steps](docs/next-steps.md) | What's left to build |
| [Parent app](frontend/README.md) | How the web app is built |
