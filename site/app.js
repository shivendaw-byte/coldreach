/* coldreach web — all contact data lives in this browser's IndexedDB.
   Serverless functions proxy outbound calls only; they never store anything. */

// ── storage ──────────────────────────────────────────────────────────────────
const DB = "coldreach", STORE = "contacts", DSTORE = "drafts", MSTORE = "meta";
let db;

function open() {
  return new Promise((res, rej) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => {
      const d = r.result;
      if (!d.objectStoreNames.contains(STORE)) d.createObjectStore(STORE, { keyPath: "id" });
      if (!d.objectStoreNames.contains(DSTORE)) d.createObjectStore(DSTORE, { keyPath: "id", autoIncrement: true });
      if (!d.objectStoreNames.contains(MSTORE)) d.createObjectStore(MSTORE);
    };
    r.onsuccess = () => { db = r.result; res(db); };
    r.onerror = () => rej(r.error);
  });
}
const tx = (store, mode = "readonly") => db.transaction(store, mode).objectStore(store);
const all = store => new Promise((res, rej) => {
  const r = tx(store).getAll(); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const put = (store, val, key) => new Promise((res, rej) => {
  const r = key === undefined ? tx(store, "readwrite").put(val) : tx(store, "readwrite").put(val, key);
  r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
});
const clearStore = store => new Promise(res => { tx(store, "readwrite").clear().onsuccess = () => res(); });
const getMeta = key => new Promise(res => { const r = tx(MSTORE).get(key); r.onsuccess = () => res(r.result); });

async function putMany(rows) {
  const t = db.transaction(STORE, "readwrite"), s = t.objectStore(STORE);
  let added = 0;
  for (const row of rows) { s.put(row); added++; }
  return new Promise(res => { t.oncomplete = () => res(added); });
}

// ── profile + campaigns ──────────────────────────────────────────────────────
const DEFAULT_ME = {
  name: "", first: "", email: "", year: "sophomore", institution: "",
  major: "", background: "", signature_line: ""
};

const CAMPAIGNS = {
  research_assistant: { audience: "academic", days: 8,
    subject: ["undergrad question: {anchor_short}", "question on {anchor_short}"],
    fit: ["I'm a {year} at {institution} studying {major}. {background}",
          "For context: {year} at {institution}, {major}. {background}"],
    ask: ["If you're taking on undergraduate research help this term, I'd like to be considered, including for the unglamorous parts: cleaning data, replication, literature pulls. Would you have 15 minutes the week of {meeting_date}? No worries at all if you're not taking students.",
          "Are you taking undergraduate RAs this term? I'd be glad to start on whatever is least interesting to you and most useful to the project. Could we talk for 15 minutes the week of {meeting_date}? Totally understand if the answer is no."] },
  coffee_chat: { audience: "academic", days: 8,
    subject: ["question about {anchor_short}", "quick question on {anchor_short}"],
    fit: ["I'm a {year} at {institution} studying {major}, trying to work out which questions in this area are worth spending years on."],
    ask: ["Would you be open to 15 minutes the week of {meeting_date}? I'd mostly want to hear how you picked this line of work. Completely understand if your calendar doesn't allow it."] },
  advice: { audience: "academic", days: 8,
    subject: ["one question on {anchor_short}"],
    fit: ["I'm a {year} at {institution} studying {major}. {background}"],
    ask: ["I'm not asking for a position, just whether you'd tell me what you'd read or learn first if you were starting on this today. A two-line reply would genuinely help. Thank you either way."] },
  startup_intro: { audience: "work", days: 7, salutation: ["Hi {first_name},"], signoff: ["Best", "Thanks"],
    subject: ["{institution} student — question about {org}", "question about the hard part of {org}"],
    fit: ["I'm a {year} at {institution} studying {major}. {background}",
          "Quick context: {year} at {institution}, {major}, and I spend most of my free time building things rather than reading about them. {background}"],
    ask: ["Would you be up for 15 minutes in the week of {meeting_date}? I want to understand what the actual hard part of the problem is, not the pitch version. Happy to work around whatever time is least disruptive.",
          "Could I ask you two or three specific questions, either over email or in 15 minutes the week of {meeting_date}? Either works, and no hard feelings if you're heads-down."] },
  consulting_chat: { audience: "work", days: 8, salutation: ["Hi {first_name},"],
    subject: ["{institution} student — 15 min about {org}?", "question about your work at {org}"],
    fit: ["I'm a {year} at {institution} studying {major} and starting to look seriously at consulting. {background}",
          "I'm a {year} in {major} at {institution}. I'd rather hear what the work is actually like from someone doing it than from a recruiting deck. {background}"],
    ask: ["Would you have 15 minutes the week of {meeting_date}? I'm trying to work out which parts of the job people actually find worth doing. No problem at all if your schedule is full.",
          "Could I take 15 minutes the week of {meeting_date}? I'd want to ask what surprised you most in your first year. Completely understand if not."] },
  pm_chat: { audience: "work", days: 8, salutation: ["Hi {first_name},"],
    subject: ["question about {anchor_short} at {org}", "{institution} student — question on how {org} builds"],
    fit: ["I'm a {year} at {institution} studying {major}, and I build things on the side rather than only reading about them. {background}"],
    ask: ["Would you be open to 15 minutes the week of {meeting_date}? I mostly want to understand how decisions actually get made on your team. No worries if the timing is bad.",
          "Could I ask you a couple of specific questions about how that shipped, either by email or in 15 minutes the week of {meeting_date}?"] },
  linkedin_reconnect: { audience: "warm", days: 7,
    salutation: ["Hi {first_name},", "Hey {first_name},"], signoff: ["Best", "Thanks", "Cheers"],
    subject: ["long overdue hello", "we're connected but have never talked", "quick hello from {institution}"],
    fit: ["I'm a {year} at {institution} studying {major}, and I'm trying to be deliberate about actually talking to people instead of collecting connections. {background}",
          "Quick context in case it's been a while: {year} at {institution}, {major}. {background}"],
    ask: ["Would you be up for 15 minutes the week of {meeting_date}? No agenda beyond hearing what you're working on now. Totally fine if not.",
          "If you're open to it, I'd love 15 minutes the week of {meeting_date}. And if email is easier than a call, that works just as well."] }
};

// Only usable when the person has a real focus area — "work on associate" is nonsense.
const FOCUS_HOOKS = [
  "I've been following what {org} is doing, and you're the person there whose work on {focus} lines up with what I'm trying to learn.",
  "I've been reading about {org} for a while, and the {focus} side of it is where I have the most questions."];
const ROLE_HOOKS = [
  "You came up when I was digging into {org}, and what you do as {role_article} is close to the problem I've been trying to understand properly.",
  "I've been reading about {org} for a while, and your side of it — the {role_lower} side — is the part I have the most questions about."];
const ORG_HOOKS = [
  "I've been following {org} for a while and wanted to write to someone actually doing the work rather than send a form into the void.",
  "{org} keeps coming up in what I read, and you're on the side of it I'm most curious about."];
const WARM_HOOKS = [
  "We're connected on LinkedIn but have never actually talked, and that seems like a waste given you're at {org}.",
  "We connected on LinkedIn a while back — I've been watching what you're doing at {org} since, and wanted to actually reach out."];
const PAPER_HOOKS = [
  'I read "{paper}" last week and it is the closest thing I have found to the question I keep circling back to.',
  'Your paper "{paper}" is what prompted this email — I read it twice and I am still turning over the identification strategy.',
  'I came to your work through "{paper}", and it reframed something I had been thinking about badly.'];

// ── compose ──────────────────────────────────────────────────────────────────
function hash(s) { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0; return h; }
const pick = (list, seed) => Array.isArray(list) ? list[hash(seed) % list.length] : (list || "");
const fmt = (tpl, slots) => (tpl || "").replace(/\{(\w+)\}/g, (m, k) => (k in slots ? slots[k] : m));

function meetingDate(days) {
  const d = new Date(); d.setDate(d.getDate() + days);
  while (d.getDay() === 5 || d.getDay() === 6 || d.getDay() === 0) d.setDate(d.getDate() + 1);
  return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
}
function shorten(t, max = 42) {
  t = (t || "").trim().replace(/[\s,.;:]+$/, "").replace(/^(the|a|an|on)\s+/i, "");
  if (t.length <= max) return t;
  const out = []; for (const w of t.split(/\s+/)) { if ([...out, w].join(" ").length > max) break; out.push(w); }
  return out.join(" ") || t.slice(0, max);
}
function fitSubject(s, cap = 62) {
  s = (s || "").replace(/\s+/g, " ").replace(/[\s,.;:-]+$/, "");
  if (s.length <= cap) return s;
  const out = []; for (const w of s.split(" ")) { if ([...out, w].join(" ").length > cap) break; out.push(w); }
  return (out.join(" ") || s.slice(0, cap)).replace(/[\s,.;:-]+$/, "");
}

function buildDraft(c, me, campName) {
  const camp = CAMPAIGNS[campName];
  const seed = (c.email || c.linkedin || c.name || "x").toLowerCase();
  const aud = camp.audience;
  const role = c.role || "", org = c.org || "", focus = c.focus || "", signal = c.signals || "";
  // Lowercase the whole role for mid-sentence use, but leave acronyms (VP, PM) alone.
  const roleLower = role.split(/\s+/)
    .map(w => (w.length > 1 && w === w.toUpperCase()) ? w : w.toLowerCase()).join(" ");
  const ctx = { paper: signal, org: org || "your team", role, focus,
    role_lower: roleLower || "your work",
    role_article: roleLower ? (/^[aeiou]/i.test(roleLower) ? "an " : "a ") + roleLower : "your work" };

  let hook, anchor;
  if (signal) { hook = fmt(pick(PAPER_HOOKS, seed), ctx); anchor = signal; }
  else if (aud === "warm" && org) { hook = fmt(pick(WARM_HOOKS, seed + "w"), ctx); anchor = org; }
  else if (focus && org) { hook = fmt(pick(FOCUS_HOOKS, seed + "x"), ctx); anchor = focus; }
  else if (role && org) { hook = fmt(pick(ROLE_HOOKS, seed + "r"), ctx); anchor = role + " at " + org; }
  else if (org) { hook = fmt(pick(ORG_HOOKS, seed + "o"), ctx); anchor = org; }
  else { hook = "I came across your work and wanted to write to you directly rather than send something generic."; anchor = ""; }

  const parts = (c.name || "").split(/\s+/);
  const slots = { ...me,
    first_name: c.first_name || parts[0] || "there",
    last_name: c.last_name || parts[parts.length - 1] || "there",
    name: me.name, org, role, anchor,
    anchor_short: shorten(signal || focus || role || org) || "your work",
    meeting_date: meetingDate(camp.days), hook };
  slots.fit = fmt(pick(camp.fit, seed + "f"), slots);
  slots.ask = fmt(pick(camp.ask, seed + "a"), slots);
  const sal = camp.salutation || (aud === "academic" ? ["Dear Professor {last_name},"] : ["Hi {first_name},"]);
  slots.salutation = fmt(pick(sal, seed + "g"), slots);
  slots.signoff = pick(camp.signoff || ["Best"], seed + "z");

  const subject = fitSubject(fmt(pick(camp.subject, seed + "s"), slots));
  const body = [slots.salutation, "", slots.hook, "", slots.fit, "", slots.ask, "",
    slots.signoff + ",", me.name, me.signature_line].join("\n").replace(/\n{3,}/g, "\n\n").trim();
  return { email: c.email, name: c.name, org, role, campaign: campName, subject, body, anchor,
    signal: signal, focus: focus };
}

// ── linter (same rules as the desktop app) ───────────────────────────────────
const SPAM = ["act now","limited time","risk free","risk-free","100% free","click here","guarantee",
  "guaranteed","no obligation","special promotion","dear friend","opportunity of a lifetime","urgent",
  "congratulations","winner","cash bonus","make money","unsubscribe","this is not spam","call now","order now"];
const TRACKERS = ["<img","track.","click.","bit.ly","tinyurl","utm_source","mailtrack","1x1.gif","open.php","pixel"];
const URL_RE = /https?:\/\/\S+|www\.\S+/g;
const EMOJI = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;

function shingles(text, n = 5) {
  const w = (text.toLowerCase().match(/[a-z0-9']+/g) || []);
  if (w.length < n) return new Set(w.length ? [w.join(" ")] : []);
  const s = new Set(); for (let i = 0; i <= w.length - n; i++) s.add(w.slice(i, i + n).join(" "));
  return s;
}
function similarity(a, b) {
  const A = shingles(a), B = shingles(b); if (!A.size || !B.size) return 0;
  let n = 0; for (const x of A) if (B.has(x)) n++;
  return n / (A.size + B.size - n);
}

function lint(subject, body, d, priorBodies) {
  const out = [], low = body.toLowerCase();
  const words = body.trim() ? body.trim().split(/\s+/).length : 0;
  const links = body.match(URL_RE) || [];
  const err = m => out.push({ lvl: "error", msg: m }), warn = m => out.push({ lvl: "warn", msg: m });

  if (subject.length > 65) err(`subject is ${subject.length} chars (keep under 65)`);
  if (subject.includes("!")) err("exclamation mark in subject");
  if (EMOJI.test(subject) || EMOJI.test(body)) err("emoji present");
  if (/^\s*(re|fwd)\s*:/i.test(subject)) err("fake Re:/Fwd: prefix");
  for (const w of subject.split(/\s+/)) {
    const a = w.replace(/[^A-Za-z]/g, "");
    if (a.length > 3 && a === a.toUpperCase()) { warn(`ALL-CAPS word in subject: ${w}`); break; }
  }
  if (words && words < 85) warn(`body is ${words} words (thin; aim 110-170)`);
  if (words > 210) err(`body is ${words} words (too long)`);
  if (links.length > 1) err(`${links.length} links — first contact should have 0 or 1`);
  for (const t of TRACKERS) if (low.includes(t)) { err(`tracking marker "${t}"`); break; }
  for (const t of SPAM) if (low.includes(t)) { err(`spam trigger phrase: "${t}"`); break; }
  if (/\battach(ed|ment)\b/.test(low)) err("mentions an attachment");
  if (low.includes("i hope this email finds you well")) warn("opens with the most templated sentence in email");
  if (/<[a-z\/][^>]*>/i.test(body)) err("HTML markup detected — send plain text");

  const anchor = (d.anchor || "").toLowerCase();
  if (anchor) {
    const toks = (anchor.match(/[a-z]{4,}/g) || []).slice(0, 5);
    if (toks.length && !toks.some(t => low.includes(t)))
      err("nothing specific to this person in the body — reads as a blast");
  }
  if (!d.signal && !d.focus)
    warn("anchored only on job title/company — add a real detail before sending");

  let top = 0;
  for (const p of priorBodies) { const s = similarity(body, p); if (s > top) top = s; }
  if (top >= 0.60) err(`${Math.round(top * 100)}% similar to another draft — rewrite the angle`);
  else if (top >= 0.45) warn(`${Math.round(top * 100)}% similar to another draft`);

  return out;
}

// ── CSV parsing ──────────────────────────────────────────────────────────────
function parseCSV(text) {
  const rows = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (q) {
      if (ch === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (ch !== "\r") cell += ch;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter(r => r.some(c => c.trim()));
}

const HEADER_HINTS = ["first name", "last name", "url", "company", "position", "email"];
function toContacts(text, source) {
  const rows = parseCSV(text);
  let start = 0;
  for (let i = 0; i < Math.min(rows.length, 12); i++) {
    const low = rows[i].map(c => c.trim().toLowerCase());
    if (HEADER_HINTS.filter(h => low.includes(h) || low.some(c => c.includes(h))).length >= 2) { start = i; break; }
  }
  const head = rows[start].map(c => c.trim().toLowerCase());
  const idx = names => { for (const n of names) { const i = head.indexOf(n); if (i >= 0) return i; } return -1; };
  const iF = idx(["first name", "firstname", "first"]), iL = idx(["last name", "lastname", "last"]);
  const iE = idx(["email address", "email", "e-mail"]), iC = idx(["company", "organization", "org"]);
  const iP = idx(["position", "title", "role", "job title"]), iU = idx(["url", "profile url", "linkedin"]);
  const iN = idx(["name", "full name"]);

  const out = [];
  for (let r = start + 1; r < rows.length; r++) {
    const g = i => (i >= 0 && rows[r][i] ? rows[r][i].trim() : "");
    let first = g(iF), last = g(iL), name = g(iN);
    if (!first && !last && name) { const p = name.split(/\s+/); first = p[0]; last = p.slice(1).join(" "); }
    if (!name) name = [first, last].filter(Boolean).join(" ");
    if (!name) continue;
    const email = g(iE).toLowerCase();
    out.push({ id: (email || g(iU) || name).toLowerCase(), name, first_name: first, last_name: last,
      email, org: g(iC), role: g(iP), linkedin: g(iU), focus: "", signals: "",
      audience: source === "linkedin" ? "warm" : "work", source,
      status: email ? "new" : "no_email", added: Date.now() });
  }
  return out;
}

// ── UI ───────────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const esc = s => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let ME = { ...DEFAULT_ME }, CONTACTS = [], DRAFTS = [];

async function boot() {
  await open();
  ME = { ...DEFAULT_ME, ...((await getMeta("me")) || {}) };
  CONTACTS = await all(STORE);
  DRAFTS = await all(DSTORE);
  renderProfile(); render();
}

function renderProfile() {
  const f = [["name", "Your name"], ["email", "Your email"], ["year", "Year"],
    ["institution", "School"], ["major", "What you study"],
    ["background", "Your background — what makes you worth replying to"],
    ["signature_line", "Signature line"]];
  $("profile").innerHTML = f.map(([k, l]) =>
    `<label>${l}</label>${k === "background" ? `<textarea id="me_${k}"></textarea>` : `<input id="me_${k}">`}`).join("");
  for (const [k] of f) $("me_" + k).value = ME[k] || "";
}

async function saveProfile() {
  for (const k of ["name", "email", "year", "institution", "major", "background", "signature_line"])
    ME[k] = $("me_" + k).value;
  ME.first = (ME.name || "").split(" ")[0];
  await put(MSTORE, ME, "me");
  $("saved").textContent = "Saved."; setTimeout(() => $("saved").textContent = "", 2200);
}

function filtered() {
  const c = $("fCompany").value.trim().toLowerCase(), t = $("fTitle").value.trim().toLowerCase();
  const only = $("fEmail").checked;
  return CONTACTS.filter(x => (!only || x.email)
    && (!c || (x.org || "").toLowerCase().includes(c))
    && (!t || (x.role || "").toLowerCase().includes(t)));
}

function render() {
  const withEmail = CONTACTS.filter(c => c.email).length;
  $("stats").innerHTML = [["People", CONTACTS.length], ["With an email", withEmail],
    ["No email yet", CONTACTS.length - withEmail], ["Drafts", DRAFTS.length]]
    .map(([k, v]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join("");

  const f = filtered();
  $("matchCount").textContent = f.length;
  const top = {};
  for (const c of f) if (c.org) top[c.org] = (top[c.org] || 0) + 1;
  const list = Object.entries(top).sort((a, b) => b[1] - a[1]).slice(0, 8);
  $("orgs").innerHTML = list.length
    ? list.map(([o, n]) => `<button class="pill" onclick="setCompany(${JSON.stringify(o)})">${esc(o)} <b>${n}</b></button>`).join("")
    : "";

  $("drafts").innerHTML = DRAFTS.length ? DRAFTS.map((d, i) => `
    <div class="draft">
      <h3>${esc(d.name)} ${d.org ? `<span class="tag">${esc(d.org)}</span>` : ""}</h3>
      <div class="subj">${esc(d.email || "no email")} · <b>${esc(d.subject)}</b></div>
      <pre>${esc(d.body)}</pre>
      ${(d.issues || []).map(x => `<div class="issue ${x.lvl}">${x.lvl === "error" ? "FIX" : "NOTE"} — ${esc(x.msg)}</div>`).join("")}
      <div class="row">
        ${d.email ? `<button class="primary" onclick="openGmail(${i})">Open in Gmail</button>` : ""}
        <button onclick="copyDraft(${i})">Copy</button>
        <button class="ghost" onclick="dropDraft(${i})">Discard</button>
      </div>
    </div>`).join("") : `<p class="muted">No drafts yet.</p>`;
  $("dlBar").classList.toggle("hidden", !DRAFTS.length);
}

function setCompany(o) { $("fCompany").value = o; render(); }

async function upload(ev) {
  const file = ev.target.files[0]; if (!file) return;
  $("upStatus").textContent = "Reading…";
  const text = await file.text();
  const kind = /connections/i.test(file.name) ? "linkedin" : "csv";
  const rows = toContacts(text, kind);
  if (!rows.length) { $("upStatus").textContent = "No rows found. Needs a header row with names."; return; }
  await putMany(rows);
  CONTACTS = await all(STORE);
  const withE = rows.filter(r => r.email).length;
  $("upStatus").innerHTML = `Loaded <b>${rows.length}</b> people. <b>${withE}</b> came with an email`
    + (withE < rows.length ? ` — LinkedIn hides the rest, which is normal. Use the lookup below for the ones you want.` : ".");
  render();
  ev.target.value = "";
}

async function makeDrafts() {
  if (!ME.name || !ME.email) { alert("Fill in your name and email in step 1 first."); return; }
  const camp = $("campaign").value, limit = Math.min(+$("limit").value || 5, 8);
  const seen = new Set(DRAFTS.map(d => d.email));
  const pool = filtered().filter(c => c.email && !seen.has(c.email))
    .sort((a, b) => (a.signals ? 0 : 1) - (b.signals ? 0 : 1));
  if (!pool.length) { alert("Nobody eligible. Loosen the filter, or look up some emails first."); return; }

  const prior = DRAFTS.map(d => d.body);
  let made = 0, blocked = 0;
  for (const c of pool.slice(0, limit)) {
    const d = buildDraft(c, ME, camp);
    d.issues = lint(d.subject, d.body, d, prior);
    if (d.issues.some(i => i.lvl === "error") && !$("force").checked) { blocked++; continue; }
    await put(DSTORE, d); prior.push(d.body); made++;
  }
  DRAFTS = await all(DSTORE); render();
  $("composeStatus").textContent = `${made} draft${made === 1 ? "" : "s"} written`
    + (blocked ? `, ${blocked} blocked by the checks (tick "show blocked" to see why).` : ".");
}

function openGmail(i) {
  const d = DRAFTS[i];
  const u = "https://mail.google.com/mail/?view=cm&fs=1&to=" + encodeURIComponent(d.email)
    + "&su=" + encodeURIComponent(d.subject) + "&body=" + encodeURIComponent(d.body);
  window.open(u, "_blank", "noopener");
}
async function copyDraft(i) {
  const d = DRAFTS[i];
  await navigator.clipboard.writeText(`To: ${d.email}\nSubject: ${d.subject}\n\n${d.body}`);
  $("composeStatus").textContent = "Copied.";
}
async function dropDraft(i) {
  const d = DRAFTS[i];
  await new Promise(res => { tx(DSTORE, "readwrite").delete(d.id).onsuccess = res; });
  DRAFTS = await all(DSTORE); render();
}
function downloadAll() {
  const blob = new Blob([DRAFTS.map(d =>
    `To: ${d.email}\nSubject: ${d.subject}\n\n${d.body}\n\n${"=".repeat(70)}\n`).join("\n")],
    { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "coldreach-drafts.txt"; a.click();
}

async function lookupEmails() {
  const key = ($("apolloKey").value || "").trim() || (await getMeta("apolloKey")) || "";
  if (!key) { alert("Paste your Apollo API key first (Apollo → Settings → Integrations → API)."); return; }
  await put(MSTORE, key, "apolloKey");
  const targets = filtered().filter(c => !c.email && c.linkedin).slice(0, Math.min(+$("enLimit").value || 10, 50));
  if (!targets.length) { alert("Nobody in the current filter is missing an email."); return; }
  if (!confirm(`Look up ${targets.length} email${targets.length === 1 ? "" : "s"}?\n\n`
    + `This uses about ${targets.length} Apollo credit${targets.length === 1 ? "" : "s"} from your account.`)) return;

  $("enStatus").textContent = "Looking up…";
  let found = 0;
  for (let i = 0; i < targets.length; i++) {
    const t = targets[i];
    $("enStatus").textContent = `Looking up ${i + 1} of ${targets.length}…`;
    try {
      const r = await fetch("/api/apollo", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, person: { first_name: t.first_name, last_name: t.last_name,
          organization_name: t.org, linkedin_url: t.linkedin } }) });
      const j = await r.json();
      if (!r.ok) { $("enStatus").textContent = "Stopped: " + (j.error || r.status); break; }
      if (j.email) { t.email = j.email; t.status = "new"; if (j.title) t.role = j.title || t.role; await put(STORE, t); found++; }
    } catch (e) { $("enStatus").textContent = "Network error: " + e.message; break; }
  }
  CONTACTS = await all(STORE); render();
  $("enStatus").textContent = `Found ${found} of ${targets.length}. About ${targets.length} credits used.`;
}

async function wipe() {
  if (!confirm("Delete every contact and draft stored in this browser?")) return;
  await clearStore(STORE); await clearStore(DSTORE);
  CONTACTS = []; DRAFTS = []; render();
}

window.saveProfile = saveProfile; window.upload = upload; window.makeDrafts = makeDrafts;
window.openGmail = openGmail; window.copyDraft = copyDraft; window.dropDraft = dropDraft;
window.downloadAll = downloadAll; window.lookupEmails = lookupEmails; window.wipe = wipe;
window.render = render; window.setCompany = setCompany;
boot();
