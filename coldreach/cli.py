"""Command line, for when you'd rather type than click. The app is the main way in."""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from . import compose, find, harvest, server, settings, store

ROOT = Path(__file__).resolve().parent.parent
cfg = settings.load


def cmd_app(args) -> None:
    server.main()


def cmd_find(args) -> None:
    c = cfg()
    rows: list[dict] = []
    if args.url:
        rows = find.run_url(args.url, args.org or "", args.team or "", c,
                            args.limit, args.audience)
    else:
        names = args.source or [s["name"] for s in c.get("sources", [])
                                if s.get("enabled")]
        for src in c.get("sources", []):
            if src["name"] not in names:
                continue
            print(f"\n== {src['name']} ==")
            out = find.run_source(src, c, args.limit, print, args.spend_credits)
            rows += out["rows"]
            if out.get("needs") == "confirm_credits":
                print(f"\n{len(out.get('candidates', []))} candidates found. Apollo hides "
                      f"emails until revealed (~1 credit each).")
                print(f"Re-run with --spend-credits to reveal up to {out.get('cap')}.")
    if rows:
        find.save(rows)


def cmd_compose(args) -> None:
    c = cfg()
    campaigns = c["campaigns"]
    if args.campaign not in campaigns:
        raise SystemExit(f"Unknown campaign. Options: {list(campaigns)}")
    campaign = campaigns[args.campaign]

    cap = c.get("limits", {}).get("drafts_per_day", 8)
    limit = min(args.limit, cap)
    if args.limit > cap:
        print(f"Capping at {cap}/day (limits.drafts_per_day).")

    seen = set() if args.all else store.already_contacted()
    pool = [x for x in store.load_contacts()
            if x.get("email") and x["email"].lower() not in seen]
    if args.filter:
        f = args.filter.lower()
        pool = [x for x in pool if f in " ".join(
            [x.get("org", ""), x.get("team", ""), x.get("role", ""), x.get("name", "")]).lower()]
    pool.sort(key=lambda x: (0 if x.get("signals") else 1, 0 if x.get("focus") else 1))
    targets = pool[:limit]
    if not targets:
        print("No eligible contacts. Run `find` first.")
        return

    prior = [d["body"] for d in store.load_drafts()]
    sim = c.get("limits", {}).get("similarity_threshold", 0.60)
    made = blocked = 0
    for t in targets:
        d = compose.compose_one(t, c["me"], campaign, args.campaign, prior,
                                use_llm=args.llm, sim_threshold=sim)
        print(f"\n--- {d['name']} <{d['email']}> [{d['engine']}]")
        print(f"Subject: {d['subject']}\n{d['body']}")
        for issue in d["issues"]:
            print(f"  ! {issue}")
        if d["blocked"] and not args.force:
            print("  BLOCKED (use --force to queue anyway)")
            blocked += 1
            continue
        store.append_draft(d)
        prior.append(d["body"])
        made += 1
    print(f"\n{made} queued, {blocked} blocked -> {store.DRAFTS}")


def cmd_harvest(args) -> None:
    folder = Path(args.folder).expanduser()
    if not folder.is_dir():
        raise SystemExit(f"Not a folder: {folder}")
    if args.mode == "notes":
        written = harvest.harvest_notes(folder, clip=args.clip)
        print(f"\n{len(written)} file(s) -> {store.DATA / 'notes'}")
    else:
        rows = harvest.harvest_contacts(folder, args.org or "", args.team or "")
        find.save(rows)


def cmd_push(args) -> None:
    from . import gmail_api
    c = cfg()
    sender = c["me"]["email"]
    all_drafts = store.load_drafts()
    queue = [d for d in all_drafts if not d.get("pushed")]
    if args.campaign:
        queue = [d for d in queue if d["campaign"] == args.campaign]
    queue = queue[:c.get("limits", {}).get("drafts_per_day", 8)]
    if not queue:
        print("Nothing queued.")
        return

    print(f"About to create {len(queue)} Gmail DRAFT(s) from {sender}:")
    for d in queue:
        print(f"  {d['name']} <{d['email']}>  |  {d['subject']}")
    print("\nDrafts only. Nothing sends until you press send in Gmail.")
    if input("Create them? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return

    svc = gmail_api.service()
    pushed = 0
    for d in queue:
        try:
            did = gmail_api.create_draft(svc, sender, d["email"], d["subject"], d["body"])
        except Exception as exc:
            print(f"  FAILED {d['name']}: {exc}")
            continue
        d["pushed"] = True
        pushed += 1
        store.append_log({
            "email": d["email"], "name": d["name"], "org": d.get("org", ""),
            "campaign": d["campaign"], "subject": d["subject"],
            "drafted_at": store.now(), "draft_id": did,
            "followup_due": (date.today() + timedelta(
                days=c.get("limits", {}).get("followup_days", 9))).isoformat(),
            "status": "drafted"})
        print(f"  drafted: {d['name']}")
    store.write_drafts(all_drafts)
    print(f"\n{pushed} created. Open Gmail -> Drafts. Send Tue-Thu, 8-10am.")


def cmd_status(args) -> None:
    contacts = store.load_contacts()
    seen = store.already_contacted()
    with_email = [c for c in contacts if c.get("email")]
    print(f"Contacts:        {len(contacts)} ({len(with_email)} with an email)")
    print(f"Already drafted: {len(seen)}")
    print(f"Queued drafts:   {sum(1 for d in store.load_drafts() if not d.get('pushed'))}")
    print(f"Untouched pool:  {sum(1 for c in with_email if c['email'].lower() not in seen)}")
    today = date.today().isoformat()
    due = [r for r in store.load_log()
           if r.get("status") == "drafted" and r.get("followup_due", "9999") <= today]
    if due:
        print(f"\nFollow-up due ({len(due)}) — same thread, 2-3 lines, once:")
        for r in due[:10]:
            print(f"  {r['name']} <{r['email']}> (drafted {r['drafted_at'][:10]})")


def main(argv=None) -> None:
    p = argparse.ArgumentParser("coldreach", description="Personalized cold outreach drafts.")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("app", help="open the point-and-click app (default)").set_defaults(func=cmd_app)

    f = sub.add_parser("find", help="find people from configured sources")
    f.add_argument("--source", nargs="*")
    f.add_argument("--url"); f.add_argument("--org"); f.add_argument("--team")
    f.add_argument("--audience", default="academic",
                   choices=["academic", "work", "warm"])
    f.add_argument("--limit", type=int, default=0)
    f.add_argument("--spend-credits", action="store_true",
                   help="allow Apollo enrichment to use credits")
    f.set_defaults(func=cmd_find)

    c = sub.add_parser("compose", help="generate and lint drafts")
    c.add_argument("--campaign", default="research_assistant")
    c.add_argument("--limit", type=int, default=5)
    c.add_argument("--filter"); c.add_argument("--llm", action="store_true")
    c.add_argument("--force", action="store_true"); c.add_argument("--all", action="store_true")
    c.set_defaults(func=cmd_compose)

    h = sub.add_parser("harvest", help="pull contacts or text out of local documents")
    h.add_argument("folder")
    h.add_argument("--mode", choices=["contacts", "notes"], default="contacts")
    h.add_argument("--clip", action="store_true")
    h.add_argument("--org"); h.add_argument("--team")
    h.set_defaults(func=cmd_harvest)

    u = sub.add_parser("push", help="create Gmail drafts from the queue")
    u.add_argument("--campaign"); u.set_defaults(func=cmd_push)

    sub.add_parser("status", help="pipeline overview").set_defaults(func=cmd_status)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        return cmd_app(args)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
