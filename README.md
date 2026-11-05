# Tasmania Welcome Platform (hellotas)

A student-built guide to events, stories and community life for ICT students in Tasmania.

**Live site:** https://weiluoyan.github.io/hellotas/events/

---

## Why this exists

When I arrived in Tasmania as a new international student, finding out what was happening was harder than it should have been. Events were shared in many different places, MyLO was full of notices, and it was easy to miss things, or to find out about them after they had finished. Teachers had to post the same reminders again and again.

This project puts it all in one place, so that:

- **New students** can see what ICT students before them did, and how they found their place and their first job in Tasmania.
- **Teachers** can share one link instead of posting reminders again.
- **UTAS colleagues overseas** can follow what is happening in Tasmania.

## What's here now

- **ICT Events page** for 2025 and 2026, with photos and details for each event.
- **Happening**: upcoming events, found automatically every morning by the [event collector](collector/README.md)
  from GDG Hobart, ACS, AISA, SecTalks Hobart, TasICT and Careerify, plus events people suggest.
- **Calendar subscription**: `happening/index.ics` (all events, or one feed per topic), so new events appear in
  students' own calendars, and `happening/index.json` for other tools.
- **New and pinned events** on the homepage.
- **Community features**, switched on once the [community API](server/README.md) is running: sign in with a UTAS
  email, mark events Interested or Going, find someone to go with, the Noticeboard (Wish Wall, achievements,
  opportunities with who-can-apply labels), a saved arrival checklist and a weekly email digest.

This is an early version. Some events are examples, and the full list is still being checked, so details may change.

## How it fits together

| Part | Folder | Guide |
|---|---|---|
| The site (Hugo, GitHub Pages) | `content/`, `layouts/`, `data/` | this file |
| Event collector (GitHub Actions) | `collector/` | [collector/README.md](collector/README.md) |
| Community API (a small server) | `server/` | [server/README.md](server/README.md) |
| Deploying all of it | | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| What is left to do | | [docs/NEXT-STEPS.md](docs/NEXT-STEPS.md) |
| Why these features, and not a social network | | [docs/research/platform-v2.md](docs/research/platform-v2.md) |

## Coming next

- Upcoming events page
- Student stories: how people found their first job and settled in
- Local community volunteering and career-relevant volunteering
- Local sports and wellbeing activities
- More languages

## Built with

- [Hugo](https://gohugo.io/) static site generator
- [PaperMod](https://github.com/adityatelange/hugo-PaperMod) theme
- GitHub Pages, deployed with GitHub Actions

## Run it locally

1. [Install Hugo](https://gohugo.io/installation/) (extended version).
2. Clone the repository:
   ```
   git clone https://github.com/weiluoyan/hellotas.git
   cd hellotas
   ```
3. Start the local server:
   ```
   hugo server
   ```
4. Open the address Hugo prints in your terminal, usually http://localhost:1313/.

## Adding or changing an event

Most upcoming events now arrive by themselves: the collector opens a pull request with new events each morning.
To add one it missed, use the **Suggest an event** issue form (or the site's Suggest page): it reads the link and
proposes the entry for you.

To write one by hand, add a YAML file to `data/happening/` (upcoming) or `data/events/<year>/` (past), using an
existing one as your template; the fields are explained at the top of `layouts/happening/list.html` and
`layouts/partials/events-adapter.html`. Photos go in `static/images/`. When you push to `main`, the site is rebuilt
and deployed automatically.

## Photos and content

Event photos and details belong to the people and organisations who took part in them. If you appear in a photo or are named on the site and would like it changed or removed, please open an issue or contact me and I'll sort it out.

## About

Built by Luoyan Wei (Laura), UTAS Master of Information Technology and Systems graduate (2026), as a volunteer project to help new students feel at home in Tasmania.

Suggestions and event tips are welcome. Please open an issue.
