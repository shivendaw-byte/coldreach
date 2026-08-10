# coldreach

Find people, write a real email to each one, put it in your Gmail drafts.
**Nothing ever sends by itself.**

## Start it

Double-click **coldreach** on your Desktop.

A black window opens (leave it), then your browser opens the app. Work top to
bottom: who you are → find people → write drafts → review → send to Gmail.

When you're done, close the black window.

First run installs a few things and takes about a minute. You need Python
installed — if the window tells you it's missing, get it from
[python.org/downloads](https://www.python.org/downloads/) and tick
**"Add python.exe to PATH"** during setup.

## Where it finds people

| Source | Cost | What you need |
|---|---|---|
| **Web directories** — university faculty pages, company team pages | Free | Nothing. Some are set up already; paste any other URL into the app. |
| **Apollo** — find people by job title and company | Search free, **~1 credit per email revealed** | An Apollo API key (Settings → Integrations → API). The app asks before spending anything. |
| **Your LinkedIn connections** | Free | Your own export — see below. |
| **Local documents** | Free | A folder of PDFs, Word docs, or text files. |

### Getting your LinkedIn connections

LinkedIn → Me → **Settings & Privacy** → **Data privacy** → **Get a copy of your
data** → tick **Connections** → Request archive. They email you a zip in about
ten minutes. Unzip it anywhere; the app finds `Connections.csv` on its own.

Most connections don't expose an email in the export — those still import as warm
contacts so you can message them on LinkedIn instead. **I can't read your
LinkedIn directly**; this export is the only legitimate way in, and it's yours.

## Campaigns

`research_assistant` · `coffee_chat` · `advice` — professors
`startup_intro` — founders, YC
`consulting_chat` — consulting
`pm_chat` — product and tech
`linkedin_reconnect` — people you're already connected to

Each is a few lines in `config.yaml`: a subject, an opener, and one ask. Copy a
block, change the words, restart the app — that's how you add your own.

## The checks that run on every draft

**Errors block the draft. Warnings just print.**

Blocked for: more than 60% similarity to a draft you already made · tracking
pixels or redirect links · more than one link · any HTML · spam-trigger phrases ·
mentioning an attachment · a subject over 65 characters, with `!`, with emoji, or
a fake `Re:` · a body over 210 words · **nothing specific to that person in it**.

That last one is the important one. It's what stops this being a mail merge.

## Two things it deliberately won't do

**It won't guess an email address.** People without a published one are kept and
marked, not guessed at. A guessed address bounces, and bounces hurt your sender
reputation more than a missed contact costs you.

**It won't send.** It creates Gmail *drafts* using a permission scope that
literally cannot send, read, or delete your mail. You read each one and press
send. That's also where you'll catch the draft that was subtly wrong about
someone's work.

Read [DELIVERABILITY.md](DELIVERABILITY.md) once — it's the reasoning behind
every rule above, with sources.

## If you'd rather type

```bash
python -m coldreach find --source wharton-bepp --limit 20
python -m coldreach compose --campaign research_assistant --limit 5 --llm
python -m coldreach push
python -m coldreach status
```

`find` on an Apollo source searches for free and stops; add `--spend-credits`
to actually reveal emails.

## Files

```
config.yaml            you, your limits, your campaigns, your sources — edit freely
Start coldreach.bat    the launcher
coldreach/
  server.py + ui.html  the app
  find.py              one entry point for every source
  scrape.py            web directory crawling
  apollo.py            Apollo search + reveal
  linkedin.py          Connections.csv import
  harvest.py           PDFs, Word docs, text
  compose.py           draft writing + the linter
  store.py             contacts, drafts, log, similarity
  settings.py          app settings overlay (keeps config.yaml's comments safe)
  gmail_api.py         Gmail drafts (compose scope only)
data/                  everything generated. Never commit this.
```
