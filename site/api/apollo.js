// Stateless proxy. Apollo blocks browser calls (CORS), so this forwards one
// lookup and returns the email. Nothing is logged, cached, or stored here —
// the key arrives with each request and is discarded when the function returns.
export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });

  const { key, person } = req.body || {};
  if (!key) return res.status(400).json({ error: "No Apollo API key supplied." });
  if (!person) return res.status(400).json({ error: "No person supplied." });

  const payload = {};
  for (const f of ["first_name", "last_name", "organization_name", "domain", "linkedin_url", "id"]) {
    if (person[f]) payload[f] = person[f];
  }
  if (!Object.keys(payload).length) return res.status(400).json({ error: "Nothing to match on." });

  let r;
  try {
    r = await fetch("https://api.apollo.io/api/v1/people/match", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Cache-Control": "no-cache", "x-api-key": key },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    return res.status(502).json({ error: "Could not reach Apollo." });
  }

  if (r.status === 401) return res.status(401).json({ error: "Apollo rejected the API key." });
  if (r.status === 403) return res.status(403).json({ error: "Apollo says your plan can't use this endpoint." });
  if (r.status === 429) return res.status(429).json({ error: "Apollo rate limit hit. Wait a minute." });
  if (!r.ok) return res.status(502).json({ error: `Apollo error ${r.status}.` });

  const data = await r.json();
  const p = data.person || {};
  const email = (p.email || "").trim().toLowerCase();
  const masked = !email || ["email_not_unlocked", "not_unlocked", "domain.com"].some(m => email.includes(m));

  return res.status(200).json({
    email: masked ? "" : email,
    title: p.title || "",
    organization: (p.organization && p.organization.name) || "",
  });
}
