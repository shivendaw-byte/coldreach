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

### Your LinkedIn export

LinkedIn → Me → **Settings & Privacy** → **Data privacy** → **Get a copy of your
data** → **Request archive**. They email you a zip in about ten minutes. Unzip it
anywhere on your machine; the app finds it by itself.

Press **Import my LinkedIn export** and it does two things:

1. **Fills in "Who you are"** from your real profile, positions, and resume — your
   school, year, major, and a first-draft background built from what you've
   actually done. Edit it; it's a draft, not gospel.
2. **Loads your connections as targets**, with company, job title, and profile URL.

**Expect almost none of them to have an email.** In a real 6,600-connection
export, 41 did — about 0.6%. That's LinkedIn hiding it, not a bug. So the export
is a *targeting* list, not an email list.

### Turning connections into emails

Filter to who you actually want (`McKinsey`, `Consultant`, `Google`), then press
**Look up work emails**. Apollo matches on the LinkedIn profile URL, which is the
most reliable key it accepts. Roughly **1 credit per person**, and the app shows
you the names and the exact credit count before spending anything.

This is the pipeline worth knowing: **your connections → filter → Apollo lookup →
personalized draft.** It beats a cold Apollo search because these people already
accepted your connection request.

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

## Putting it on GitHub

Double-click **Push to GitHub.bat**. It asks for the URL of an empty repo you
made at [github.com/new](https://github.com/new), then pushes. Git opens a
browser to sign you in the first time.

**What gets uploaded:** the code, the example config, the docs.
**What never does:** `data/` (your contacts, drafts, and log), `config.yaml`
(your details), your LinkedIn export, `credentials.json`, `token.json`, and your
Apollo key. All of it is in `.gitignore`, and a fresh clone starts from
`config.example.yaml` with placeholders.

That last part matters beyond your own privacy: `contacts.csv` holds real names,
employers, and profile URLs of thousands of people who never agreed to be in a
public repo.

## The draft checker (on Vercel)

`site/index.html` is the linter, ported to run entirely in your browser. It's
deployed at
**[coldreach-shivendaw-6428s-projects.vercel.app](https://coldreach-shivendaw-6428s-projects.vercel.app)**,
behind Vercel Authentication — only your Vercel account can open it.

Paste any email, from any device, and it runs the same checks the desktop app
runs: spam phrases, length, links, tracking markers, subject rules, and
similarity against drafts you've saved. Saved drafts live in that browser's
local storage and never touch a server.

Use it for emails you write by hand, on your phone, outside the app.

### Why the app itself isn't hosted



The desktop app can't run on Vercel, and the reason is mechanical rather than
philosophical: Vercel is serverless, so the filesystem is read-only apart from a
scratch directory that's wiped between requests. coldreach continuously reads and
writes `contacts.csv`, `drafts.jsonl`, `settings.json`, and a Gmail token. Hosted
there it would lose your contacts on every request.

The privacy side matters too — it holds your Gmail OAuth, your Apollo key, and
thousands of other people's contact details — but the filesystem is the part that
makes it a non-starter regardless.

Running locally is the feature. It's why the Gmail scope can stay draft-only and
why your data never leaves the machine.

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
