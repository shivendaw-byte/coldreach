"""Run: python tests/test_network.py  (no network, no real data needed)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coldreach import network as n  # noqa: E402


def person(**kw):
    base = {"id": "x", "name": "Ana Lee", "first": "Ana", "role": "Analyst", "org": "Deloitte", "firm": "Deloitte",
            "email": "", "linkedin": "https://linkedin.com/in/ana", "kind": "work", "connected": "", "stage": "new",
            "last": "", "target": True, "thread": [], "events": [], "debrief": None}
    base.update(kw)
    return base


def test_firm_aliases():
    assert n.firm_of("Deloitte Consulting") == "Deloitte"
    assert n.firm_of("Boston Consulting Group (BCG)") == "BCG"
    assert n.firm_of("L.E.K. Consulting") == "L.E.K. Consulting"


def test_hook_grammar_and_team_split():
    assert "an Analyst" in n._hook(person(role="Analyst"))
    assert n._hook(person(role="Senior Consultant, Strategy & Analytics")) == "your work in Strategy & Analytics at Deloitte"
    assert "landed the" in n._hook(person(role="Business Strategy Intern"))


def test_cold_message_follows_his_shape():
    t = n.draft_message(person(), "cold")["text"]
    assert t.startswith("Hi Ana, I'm Shiven") and "I'm super interested in" in t and "Fun facts about me:" in t


def test_nudge_names_the_referrer():
    p = person(stage="messaged", thread=[{"from_me": True, "date": "2026-07-27", "text": "Renato recommended I reach out!"}])
    assert "Renato suggested" in n.draft_message(p, "nudge")["text"]


def test_search_tolerates_typos():
    ppl = [person(), person(id="y", name="Bo Chen", org="McKinsey & Company", firm="McKinsey", role="Business Analyst")]
    assert [p["name"] for p in n.search(ppl, "mckinsy analyst")] == ["Bo Chen"]


def test_followups_only_nudge_once():
    old = "2026-01-01T10:00"
    once = person(stage="messaged", last=old, thread=[{"from_me": True, "date": old, "text": "hi"}])
    twice = person(id="z", stage="messaged", last=old,
                   thread=[{"from_me": True, "date": old, "text": "hi"}, {"from_me": True, "date": old, "text": "bump"}])
    assert [p["id"] for p in n.followups([once, twice])] == ["x"]


def test_debrief_airtime(tmp=None):
    n.EVENTS = Path(__file__).resolve().parent / "_events_test.jsonl"
    try:
        ev = n.debrief("x", "Shiven: How did you pick Deloitte?\nPeter: " + "word " * 60 + "\nShiven: Why GPS?")
        m = ev["metrics"]
        assert m["questions"] == 2 and m["open_questions"] == 2 and m["airtime_pct"] < 20
    finally:
        n.EVENTS.unlink(missing_ok=True)


if __name__ == "__main__":
    bad = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            try:
                f(); print("ok  ", k)
            except Exception as e:  # noqa: BLE001
                bad += 1; print("FAIL", k, repr(e))
    sys.exit(bad)
