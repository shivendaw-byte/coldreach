# Staying on the happy list

The thing to internalize: **you are not fighting a spam filter, you are avoiding
looking like bulk mail.** Gmail-to-Gmail, 1:1, from an authenticated `.edu`
address, with unique bodies and low volume, is about as safe as email gets. Every
rule below exists because it's one of the few ways that setup still breaks.

## Why your setup starts strong

`sdawda@sas.upenn.edu` runs on Penn's Google Workspace. Sending through the Gmail
API means SPF, DKIM, and DMARC are already aligned by Penn — the authentication
layer that Google made mandatory for bulk senders in February 2024 is handled for
you, and you're nowhere near the 5,000-messages-a-day threshold those rules
target anyway. What still applies to you is the principle behind them:
**user-reported spam rate under 0.3%** is the number Google enforces, and at your
volume that means roughly *one* spam report is a meaningful fraction of your
reputation. ([Gmail sender guidelines FAQ](https://support.google.com/mail/answer/14229414?hl=en),
[Email sender guidelines](https://support.google.com/mail/answer/81126?hl=en))

A `.edu` sender writing to a `.edu` recipient about their published research is
also contextually normal. The risk isn't the filter — it's a professor hitting
"Report spam" because your email read like a mail merge.

## The rules this tool enforces in code

| Rule | Why |
|---|---|
| **No tracking pixels, ever** | The single most damaging thing you could add. Emails with tracking pixels see roughly 8–12% lower inbox placement in cold outreach, SpamAssassin scores tracking identifiers positively toward spam, and open-tracking has been measured cutting *reply* rates substantially. Do not install Mailtrack, Streak, Yesware, or HubSpot Sales. ([Instantly](https://instantly.ai/blog/email-tracking-and-deliverability-why-tracking-pixels-can-hurt-your-inbox-placement/), [Mailforge](https://www.mailforge.ai/blog/how-open-rate-tracking-can-hurt-your-email-deliverability), [Suped](https://www.suped.com/learn/email-deliverability/do-tracking-pixels-directly-cause-emails-to-be-marked-as-spam)) |
| **Unique body per recipient** | Identical bodies sent to many recipients in a window is the fingerprint of bulk mail. The linter blocks anything ≥60% shingle-identical to a draft you already made. |
| **Plain text, no HTML** | `gmail_api.py` sends `text/plain`. HTML-heavy 1:1 mail reads as marketing. |
| **0–1 links, no shorteners** | Shortened and shared-tracking domains inherit the reputation of everyone else using them. |
| **No attachments on first contact** | Attachments from unknown senders raise spam scores. Offer the CV; attach it when they reply. |
| **No unsubscribe footer** | Counterintuitive: a one-click unsubscribe is *required for marketing mail* and marks 1:1 mail as bulk. Use a human out instead — "no worries if you're not taking students." |
| **≤8 drafts/day** | Volume is the loudest bulk signal. Free Gmail caps at 500 recipients/day and Workspace at 2,000, but reputation-wise you should be an order of magnitude under that. |
| **Subject under 65 chars, no caps, no `!`, no emoji, no fake `Re:`** | Classic filter triggers, and a fake `Re:` is the fastest way to get reported. |
| **Spam-phrase blocklist** | "guarantee", "act now", "limited time", "click here" and friends. |
| **One follow-up, in the same thread, 9 days later** | Two touches maximum. A third unanswered email is where outreach becomes harassment. |

## Rules the tool can't enforce for you

- **Reply rate is the strongest positive signal there is.** A professor replying
  to you teaches Gmail your address is wanted. Ten good emails that get three
  replies beat a hundred that get none — and a hundred that get none is how a
  personal address actually degrades.
- **Send Tuesday–Thursday, 8–10am recipient time.** Monday is triage, Friday is
  abandoned.
- **Send in small batches, spread across the day.** Forty sends in ninety seconds
  looks automated because it is.
- **Never BCC multiple professors.** One recipient per message, always.
- **Never guess an email address.** The scraper only collects published addresses
  and marks the rest `no_published_email` on purpose. Bounces hurt sender
  reputation directly, and a `firstname.lastname@` guess bounces often.
- **If someone asks you to stop, stop, and delete them from the CSV.**

## What actually gets replies

The relevant study is Milkman, Akinola & Chugh's audit of **6,548 professors
across 259 institutions and 89 disciplines**, who received emails from fictional
prospective doctoral students asking to discuss research. Two findings matter for
you:

1. **67% of the emails got a response.** Professors do answer well-formed
   cold emails from students. The base rate is high.
2. **The meeting-timing manipulation mattered.** Requests to meet *that day*
   versus *in one week* produced measurably different behavior. This tool defaults
   to asking for a slot roughly a week out (`meeting_days_out: 8`).

Sources: [Temporal Distance and Discrimination (Psych Science, 2012)](https://journals.sagepub.com/doi/10.1177/0956797611434539) ·
[What Happens Before? (JAP, 2015)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2063742) ·
[Knowledge at Wharton summary](https://knowledge.wharton.upenn.edu/article/e-mails-ignored-meetings-denied-bias-at-the-search-stage-limits-diversity/)
(Katherine Milkman is at Wharton — worth knowing if you email her department.)

University research offices converge on the same advice, and the tool's templates
follow it: **2–3 short paragraphs**, a specific subject line rather than "Hi" or
"Research", identify your year and major in the first line, say *why this
professor specifically*, and name the relevant coursework or skills. The most
repeated instruction across every guide is the one this tool automates a check
for: **do not copy-paste the same email to multiple professors.**

Sources: [UNC Office for Undergraduate Research](https://our.unc.edu/find/emails-to-faculty/) ·
[Ohio State Undergraduate Research (PDF)](https://ugresearch.osu.edu/sites/default/files/documents/Emailing%20Professors%20for%20Research%20Opportunities.pdf) ·
[Penn State — Kimberly Del Bright](https://sites.psu.edu/gileswriter/2016/08/26/research-opportunity-please-how-to-email-a-professor/) ·
[Purdue Chemistry 499 email guide (PDF)](https://www.chem.purdue.edu/academic_programs/docs/499emailguidesp24.pdf)

## The honest summary

The way you keep your address on the happy list and the way you actually get
replies are **the same set of behaviors**: low volume, real personalization, no
tracking, one ask, one follow-up. There is no version of this where you send 200
identical emails safely. That tool would be a spam bot, it would work for about a
week, and then `sdawda@sas.upenn.edu` would be the thing you burned — which is a
much worse trade than never sending them.
