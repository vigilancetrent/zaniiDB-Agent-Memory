"""Memory observability dashboard — a single self-contained HTML page served
by the gateway at /dashboard. Vanilla JS, no external assets; fetches
/api/overview (passing ?token= through when the gateway requires auth).
Light + dark, responsive, matches the ZaniiDB brand palette."""

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZaniiDB Agent Memory</title>
<style>
  :root {
    color-scheme: light dark;
    --bg:#f6f7f9; --surface:#ffffff; --surface2:#eef0f4; --line:#e3e6ec;
    --text:#16181d; --muted:#5b6170; --faint:#8a90a0;
    --accent:#2a78d6; --aqua:#1baf7a; --violet:#4a3aa7; --orange:#eb6834; --red:#e34948;
    --shadow:0 1px 3px rgba(16,18,24,.06), 0 4px 16px rgba(16,18,24,.05);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg:#101218; --surface:#171a21; --surface2:#1e222b; --line:#272b36;
      --text:#e8eaf0; --muted:#9aa0ae; --faint:#6b7180;
      --accent:#3987e5; --aqua:#199e70; --violet:#9085e9; --orange:#d95926; --red:#e66767;
      --shadow:0 1px 2px rgba(0,0,0,.4);
    }
  }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--text);
         font:14px/1.6 "Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif; }
  a { color:var(--accent); text-decoration:none; }

  header { position:sticky; top:0; z-index:5; background:var(--surface);
           border-bottom:1px solid var(--line); padding:14px 28px;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  .logo { width:12px; height:12px; border-radius:3px; background:var(--accent);
          box-shadow:0 0 0 4px color-mix(in srgb, var(--accent) 18%, transparent); }
  h1 { font-size:16px; font-weight:650; letter-spacing:.01em; }
  .ver { color:var(--faint); font-size:12px; font-variant-numeric:tabular-nums; }
  .pills { margin-left:auto; display:flex; gap:8px; flex-wrap:wrap; }
  .pill { font-size:11.5px; padding:3px 10px; border-radius:99px; border:1px solid var(--line);
          color:var(--muted); background:var(--surface2); display:flex; gap:6px; align-items:center; }
  .dot { width:7px; height:7px; border-radius:50%; background:var(--faint); }
  .pill.on .dot { background:var(--aqua); }
  .pill.on { color:var(--text); }

  main { max-width:1180px; margin:0 auto; padding:26px 28px 60px; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-bottom:26px; }
  .tile { background:var(--surface); border:1px solid var(--line); border-radius:12px;
          padding:16px 18px; box-shadow:var(--shadow); }
  .tile .n { font-size:26px; font-weight:650; font-variant-numeric:tabular-nums; letter-spacing:-.01em; }
  .tile .l { color:var(--muted); font-size:12px; margin-top:2px; }

  .grid { display:grid; grid-template-columns:1.6fr 1fr; gap:22px; align-items:start; }
  @media (max-width: 900px) { .grid { grid-template-columns:1fr; } }
  section { background:var(--surface); border:1px solid var(--line); border-radius:12px;
            box-shadow:var(--shadow); margin-bottom:22px; overflow:hidden; }
  section > h2 { font-size:12px; font-weight:600; letter-spacing:.06em; text-transform:uppercase;
                 color:var(--muted); padding:14px 20px 0; }
  .body { padding:12px 20px 18px; }

  input[type=search] { width:100%; background:var(--surface2); border:1px solid var(--line);
    color:var(--text); border-radius:9px; padding:10px 14px; font:inherit; outline:none;
    transition:border-color .15s; }
  input[type=search]:focus { border-color:var(--accent); }

  .mem { display:flex; gap:10px; padding:10px 0; border-bottom:1px solid var(--line);
         align-items:baseline; }
  .mem:last-child { border-bottom:none; }
  .chip { flex:none; font-size:10.5px; font-weight:600; letter-spacing:.04em; text-transform:uppercase;
          padding:2px 8px; border-radius:6px; color:#fff; }
  .chip.persona { background:var(--accent); } .chip.episodic { background:var(--orange); }
  .chip.instruction { background:var(--violet); }
  .chip.team { background:transparent; color:var(--aqua); border:1px solid var(--aqua); }
  .mem .score { margin-left:auto; color:var(--faint); font-size:11.5px; font-variant-numeric:tabular-nums; }
  .empty { color:var(--faint); padding:8px 0; }

  pre { white-space:pre-wrap; font:12.5px/1.55 ui-monospace,Consolas,monospace; color:var(--text);
        max-height:340px; overflow:auto; }
  .files span { display:inline-block; background:var(--surface2); border:1px solid var(--line);
    border-radius:7px; padding:2px 10px; margin:0 6px 6px 0; font-size:12px; color:var(--muted); }
  .audit-row { display:flex; gap:10px; padding:7px 0; border-bottom:1px solid var(--line);
               font-size:12.5px; }
  .audit-row:last-child { border-bottom:none; }
  .audit-row .op { flex:none; color:var(--accent); font-weight:600; min-width:110px; }
  .audit-row time { margin-left:auto; color:var(--faint); white-space:nowrap; }
  footer { text-align:center; color:var(--faint); font-size:12px; padding:10px 0 30px; }
  .err { color:var(--red); padding:20px 28px; }
</style>
</head>
<body>
<header>
  <div class="logo"></div><h1>ZaniiDB Agent Memory</h1><span class="ver" id="ver"></span>
  <div class="pills" id="pills"></div>
</header>
<main>
  <div class="tiles" id="tiles"></div>
  <div class="grid">
    <div>
      <section><h2>Search memories</h2><div class="body">
        <input id="q" type="search" placeholder="Search long-term memories&hellip;" autocomplete="off">
        <div id="results"><div class="empty">Type to search.</div></div>
      </div></section>
      <section><h2>Recent memories</h2><div class="body" id="recent"></div></section>
      <section id="qsec" style="display:none"><h2>Firewall quarantine — pending review</h2>
        <div class="body" id="quarantine"></div></section>
      <section><h2>Audit trail</h2><div class="body" id="audit"></div></section>
    </div>
    <div>
      <section><h2>Persona</h2><div class="body"><pre id="persona">(none yet)</pre></div></section>
      <section><h2>Scenes</h2><div class="body files" id="scenes"></div></section>
      <section><h2>Skills</h2><div class="body files" id="skills"></div></section>
    </div>
  </div>
  <footer id="foot"></footer>
</main>
<script>
const token = new URLSearchParams(location.search).get("token");
const auth = token ? {headers: {Authorization: "Bearer " + token}} : {};
const qs = token ? "?token=" + encodeURIComponent(token) : "";
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const memHtml = m => `<div class="mem"><span class="chip ${esc(m.type)}">${esc(m.type)}</span>` +
  (m.scope === "team" ? `<span class="chip team">team</span>` : "") +
  `<span>${esc(m.content)}</span>` +
  (m.score != null ? `<span class="score">${Number(m.score).toFixed(2)}</span>` : "") + `</div>`;

async function load() {
  let r;
  try { r = await fetch("/api/overview" + qs, auth); } catch { r = null; }
  if (!r || !r.ok) {
    document.querySelector("main").innerHTML =
      `<div class="err">Cannot load overview${r ? " (HTTP " + r.status + ")" : ""} — if the gateway has an API key, open /dashboard?token=&lt;key&gt;</div>`;
    return;
  }
  const d = await r.json();
  document.getElementById("ver").textContent = "v" + d.version + " · " + d.backend;
  const caps = [["LLM", d.llm], ["Embeddings", d.embeddings], ["Vectors", d.vectors],
                ["Ledger", d.ledger && d.ledger.enabled]];
  document.getElementById("pills").innerHTML = caps.map(([n, on]) =>
    `<span class="pill ${on ? "on" : ""}"><span class="dot"></span>${n}</span>`).join("");
  const tiles = [
    [d.l1_memories, "active memories"],
    [d.superseded ?? 0, "superseded (history)"],
    [d.quarantined ?? 0, "quarantined (firewall)"],
    [d.l0_messages, "captured messages"],
    [d.sessions, "sessions"],
    [d.ledger && d.ledger.enabled ? d.ledger.entries : "—", "ledger receipts"],
  ];
  document.getElementById("tiles").innerHTML = tiles.map(([n, l]) =>
    `<div class="tile"><div class="n">${esc(n)}</div><div class="l">${esc(l)}</div></div>`).join("");
  document.getElementById("recent").innerHTML =
    (d.recent_memories || []).map(memHtml).join("") || `<div class="empty">No memories yet — capture a conversation or seed facts.</div>`;
  const q = d.quarantine_entries || [];
  document.getElementById("qsec").style.display = q.length ? "" : "none";
  document.getElementById("quarantine").innerHTML = q.map(r =>
    `<div class="mem"><span class="chip" style="background:var(--red)">${esc(r.reason.split(":")[0])}</span>` +
    `<span>${esc(r.content)}</span><span class="score">${esc(r.id.slice(0,8))}</span></div>`).join("");
  document.getElementById("persona").textContent = d.persona || "(no persona generated yet)";
  document.getElementById("scenes").innerHTML =
    (d.scenes || []).map(s => `<span>${esc(s)}</span>`).join("") || `<div class="empty">none</div>`;
  document.getElementById("skills").innerHTML =
    (d.skills || []).map(s => `<span>${esc(s)}</span>`).join("") || `<div class="empty">none</div>`;
  document.getElementById("audit").innerHTML =
    (d.audit || []).length ? d.audit.map(a =>
      `<div class="audit-row"><span class="op">${esc(a.op)}</span><span>${esc(a.detail)}</span>` +
      `<time>${new Date(a.ts).toLocaleTimeString()}</time></div>`).join("")
    : `<div class="empty">Audit log is empty — enable with ZANII_AUDIT_ENABLED=true.</div>`;
  document.getElementById("foot").textContent =
    "data: " + d.data_dir + " · refreshed " + new Date().toLocaleTimeString();
}
let t;
document.getElementById("q").addEventListener("input", e => {
  clearTimeout(t);
  t = setTimeout(async () => {
    const q = e.target.value.trim();
    const box = document.getElementById("results");
    if (!q) { box.innerHTML = `<div class="empty">Type to search.</div>`; return; }
    const r = await fetch("/search/memories" + qs, {method: "POST", ...auth,
      headers: {...(auth.headers || {}), "Content-Type": "application/json"},
      body: JSON.stringify({query: q, limit: 10})});
    const d = await r.json();
    box.innerHTML = (d.results || []).map(memHtml).join("") || `<div class="empty">No matches.</div>`;
  }, 250);
});
load();
setInterval(load, 30000);
</script>
</body>
</html>"""
