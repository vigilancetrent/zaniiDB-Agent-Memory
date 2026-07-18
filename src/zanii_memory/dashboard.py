"""Memory observability dashboard — a single self-contained HTML page served
by the gateway at /dashboard. Vanilla JS, no external assets; fetches
/api/overview (passing ?token= through when the gateway requires auth)."""

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZaniiDB Agent Memory</title>
<style>
  :root { --bg:#0f1115; --card:#181b22; --text:#e6e8ee; --muted:#8b91a0; --accent:#5aa9e6; --line:#262a33; }
  @media (prefers-color-scheme: light) {
    :root { --bg:#f5f6f8; --card:#ffffff; --text:#1c1e24; --muted:#5c6270; --accent:#1f6fb2; --line:#e3e5ea; }
  }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text); font:15px/1.55 system-ui, "Segoe UI", sans-serif; padding:32px 24px; }
  .wrap { max-width:1080px; margin:0 auto; }
  h1 { font-size:20px; font-weight:650; margin-bottom:4px; }
  .sub { color:var(--muted); margin-bottom:24px; font-size:13px; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:24px; }
  .tile { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .tile .n { font-size:24px; font-weight:650; }
  .tile .l { color:var(--muted); font-size:12px; }
  h2 { font-size:14px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; margin:24px 0 10px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 18px; overflow-x:auto; }
  .mem { padding:7px 0; border-bottom:1px solid var(--line); font-size:14px; }
  .mem:last-child { border-bottom:none; }
  .tag { display:inline-block; font-size:11px; padding:1px 8px; border-radius:99px; border:1px solid var(--line); color:var(--accent); margin-right:8px; }
  pre { white-space:pre-wrap; font:13px/1.5 ui-monospace, Consolas, monospace; }
  input { background:var(--bg); border:1px solid var(--line); color:var(--text); border-radius:8px; padding:8px 12px; width:100%; margin-bottom:12px; font:inherit; }
  .err { color:#e66a6a; }
</style>
</head>
<body>
<div class="wrap">
  <h1>ZaniiDB Agent Memory</h1>
  <div class="sub" id="sub">loading&hellip;</div>
  <div class="tiles" id="tiles"></div>
  <h2>Search memories</h2>
  <input id="q" placeholder="Type to search L1 memories&hellip;">
  <div class="card" id="results">No query yet.</div>
  <h2>Recent memories</h2>
  <div class="card" id="recent"></div>
  <h2>Persona</h2>
  <div class="card"><pre id="persona">(none)</pre></div>
  <h2>Scenes &amp; skills</h2>
  <div class="card" id="files"></div>
  <h2>Audit (latest)</h2>
  <div class="card" id="audit">(audit disabled)</div>
</div>
<script>
const token = new URLSearchParams(location.search).get("token");
const auth = token ? {headers: {Authorization: "Bearer " + token}} : {};
const qs = token ? "?token=" + encodeURIComponent(token) : "";
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const memHtml = m => `<div class="mem"><span class="tag">${esc(m.type)}${m.scope==="team"?" · team":""}</span>${esc(m.content)}</div>`;

async function load() {
  const r = await fetch("/api/overview" + qs, auth);
  if (!r.ok) { document.getElementById("sub").innerHTML = `<span class="err">Error ${r.status} — pass ?token=&lt;gateway api key&gt; in the URL</span>`; return; }
  const d = await r.json();
  document.getElementById("sub").textContent = `v${d.version} · ${d.backend} backend · llm ${d.llm?"on":"off"} · embeddings ${d.embeddings?"on":"off"}`;
  document.getElementById("tiles").innerHTML = [
    [d.l1_memories,"memories (L1)"],[d.l0_messages,"messages (L0)"],[d.sessions,"sessions"],
    [d.scenes.length,"scenes"],[d.skills.length,"skills"],[d.vectors?"on":"off","vector search"]
  ].map(([n,l])=>`<div class="tile"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");
  document.getElementById("recent").innerHTML = d.recent_memories.map(memHtml).join("") || "No memories yet.";
  document.getElementById("persona").textContent = d.persona || "(no persona generated yet)";
  document.getElementById("files").innerHTML =
    "<b>scenes:</b> " + (d.scenes.map(esc).join(", ") || "none") +
    "<br><b>skills:</b> " + (d.skills.map(esc).join(", ") || "none");
  document.getElementById("audit").innerHTML =
    d.audit.length ? d.audit.map(a=>`<div class="mem"><span class="tag">${esc(a.op)}</span>${esc(a.detail)} <span style="color:var(--muted)">· ${new Date(a.ts).toLocaleString()}</span></div>`).join("") : "(audit disabled or empty)";
}
let t;
document.getElementById("q").addEventListener("input", e => {
  clearTimeout(t);
  t = setTimeout(async () => {
    const q = e.target.value.trim();
    if (!q) { document.getElementById("results").textContent = "No query yet."; return; }
    const r = await fetch("/search/memories" + qs, {method:"POST", ...auth,
      headers:{...(auth.headers||{}), "Content-Type":"application/json"}, body: JSON.stringify({query:q, limit:10})});
    const d = await r.json();
    document.getElementById("results").innerHTML = d.results.map(memHtml).join("") || "No matches.";
  }, 250);
});
load();
</script>
</body>
</html>"""
