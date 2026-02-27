import html
import json
import os
import sys

from flask import Flask, Response, request, stream_with_context
from flask_cors import CORS

# Ensure backend module imports work from Vercel function runtime.
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from index import (
    chat_streaming,
    create_thread,
    delete_thread,
    get_threads,
    get_chat_logs,
    get_email_health,
    send_test_email,
    summarize_thread,
    create_share_link,
    import_shared_thread,
    render_shared_link_page,
)

app = Flask(__name__)
CORS(app)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "echoo")


@app.route("/api/get_threads", methods=["POST"])
def route_get_threads():
    args = request.json or {}
    result = get_threads(**args)
    return json.dumps(result)


@app.route("/api/create_thread", methods=["POST"])
def route_create_thread():
    args = request.json or {}
    result = create_thread(**args)
    return json.dumps(result)


@app.route("/api/delete_thread", methods=["POST"])
def route_delete_thread():
    args = request.json or {}
    result = delete_thread(**args)
    return json.dumps(result)


@app.route("/api/summarize_thread", methods=["POST"])
def route_summarize_thread():
    args = request.json or {}
    result = summarize_thread(**args)
    return json.dumps(result)


@app.route("/api/create_share_link", methods=["POST"])
def route_create_share_link():
    args = request.json or {}
    result = create_share_link(**args)
    return json.dumps(result)


@app.route("/api/import_shared_thread", methods=["POST"])
def route_import_shared_thread():
    args = request.json or {}
    result = import_shared_thread(**args)
    return json.dumps(result)


@app.route("/api/chat_streaming", methods=["POST"])
def route_chat_streaming():
    args = request.json or {}
    forwarded = request.headers.get("x-forwarded-for", "")
    args["client_ip"] = (forwarded.split(",")[0].strip() if forwarded else request.remote_addr or "").strip()

    def generate():
        for chunk in chat_streaming(**args):
            yield f"data: {json.dumps(chunk)}\n\n"

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def _admin_authorized() -> bool:
    return request.args.get("key", "") == ADMIN_KEY


@app.route("/api/admin_logs", methods=["GET"])
def route_admin_logs():
    if not _admin_authorized():
        return Response("Unauthorized", status=401)
    try:
        limit = int(request.args.get("limit", "1200"))
    except Exception:
        limit = 1200
    return json.dumps(get_chat_logs(limit=max(50, min(limit, 3000))))


@app.route("/api/admin_email_health", methods=["GET"])
def route_admin_email_health():
    if not _admin_authorized():
        return Response("Unauthorized", status=401)
    return json.dumps(get_email_health(), ensure_ascii=False)


@app.route("/api/admin_send_test_email", methods=["POST"])
def route_admin_send_test_email():
    if not _admin_authorized():
        return Response("Unauthorized", status=401)
    args = request.json or {}
    result = send_test_email(**args)
    code = 200 if result.get("success") else 400
    return Response(json.dumps(result, ensure_ascii=False), status=code, mimetype="application/json")


@app.route("/api/admin", methods=["GET"])
@app.route("/admin", methods=["GET"])
def route_admin():
    if not _admin_authorized():
        return Response("Unauthorized. Use ?key=echoo", status=401)

    rows = get_chat_logs(limit=1200)
    rows_payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    key = html.escape(request.args.get("key", ""))

    page = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Echo Admin Logs</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #0b1020; color: #e5e7eb; }}
    h1 {{ margin: 0 0 16px; }}
    .hint {{ color: #9ca3af; margin-bottom: 16px; }}
    .toolbar {{ display: grid; gap: 8px; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); margin-bottom: 12px; }}
    .toolbar input, .toolbar select, .toolbar button {{
      border: 1px solid #374151; background: #111827; color: #e5e7eb; border-radius: 6px; padding: 8px 10px; font-size: 13px;
    }}
    .toolbar button {{ background: #2563eb; border-color: #1d4ed8; cursor: pointer; }}
    .toolbar button.alt {{ background: #0f172a; border-color: #374151; }}
    .cards {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); margin-bottom: 14px; }}
    .card {{ border: 1px solid #374151; background: #111827; border-radius: 8px; padding: 10px; }}
    .card .k {{ font-size: 11px; color: #9ca3af; text-transform: uppercase; letter-spacing: .04em; }}
    .card .v {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
    .panel {{ border: 1px solid #374151; background: #111827; border-radius: 8px; padding: 12px; margin-bottom: 14px; }}
    .panel h2 {{ margin: 0 0 10px; font-size: 14px; }}
    .insights-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit,minmax(220px,1fr)); }}
    .mini-list {{ border: 1px solid #374151; border-radius: 8px; padding: 10px; background: #0f172a; }}
    .mini-list h3 {{ margin: 0 0 8px; font-size: 12px; color: #93c5fd; text-transform: uppercase; letter-spacing: .04em; }}
    .mini-list ul {{ margin: 0; padding-left: 16px; font-size: 12px; color: #d1d5db; }}
    .mini-list li {{ margin: 4px 0; }}
    .email-status {{ display: grid; gap: 10px; grid-template-columns: repeat(auto-fit,minmax(170px,1fr)); margin-top: 10px; }}
    .pill {{ display: inline-block; border-radius: 999px; padding: 2px 8px; font-size: 11px; border: 1px solid #374151; }}
    .ok {{ color: #86efac; border-color: #15803d; background: rgba(34,197,94,.12); }}
    .bad {{ color: #fca5a5; border-color: #b91c1c; background: rgba(239,68,68,.12); }}
    .timeline-row {{ display: grid; grid-template-columns: 92px 1fr 70px; gap: 8px; align-items: center; margin: 6px 0; font-size: 12px; }}
    .timeline-bar-wrap {{ background: #0f172a; border: 1px solid #374151; border-radius: 999px; height: 10px; position: relative; overflow: hidden; }}
    .timeline-bar {{ position: absolute; top: 0; left: 50%; height: 100%; }}
    .timeline-mid {{ position: absolute; top: 0; left: 50%; width: 1px; height: 100%; background: #4b5563; }}
    .calendar-grid {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; }}
    .day {{ border: 1px solid #374151; border-radius: 6px; min-height: 58px; padding: 6px; background: #0f172a; font-size: 11px; }}
    .day-num {{ color: #9ca3af; }}
    .day-metric {{ margin-top: 6px; font-weight: 700; font-size: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #111827; }}
    th, td {{ border: 1px solid #374151; padding: 10px; text-align: left; vertical-align: top; }}
    th {{ background: #1f2937; position: sticky; top: 0; }}
    tr:nth-child(even) {{ background: #0f172a; }}
    .wrap {{ max-width: 100%; overflow-x: auto; }}
    .btn {{ display: inline-block; padding: 8px 12px; background: #2563eb; color: #fff; text-decoration: none; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Echo Admin Logs</h1>
  <div class="hint">Route: /admin?key=echoo (or configured ADMIN_KEY). Server logs from all available clients + browser backup cache.</div>
  <div class="hint" id="cache-info">Cache status: loading...</div>
  <div class="toolbar">
    <input id="search-box" type="text" placeholder="Search user or bot text..." />
    <select id="sentiment-filter">
      <option value="all">All sentiments</option>
      <option value="positive">Positive</option>
      <option value="neutral">Neutral</option>
      <option value="negative">Negative</option>
      <option value="crisis">Crisis</option>
    </select>
    <select id="client-filter">
      <option value="all">All clients</option>
    </select>
    <button id="export-csv-btn" class="alt">Export CSV</button>
    <button id="refresh-btn">Refresh Data</button>
  </div>
  <div class="cards" id="kpis"></div>
  <div class="panel">
    <h2>Live Insights</h2>
    <div class="insights-grid">
      <div class="mini-list">
        <h3>Top Keywords</h3>
        <ul id="top-keywords"></ul>
      </div>
      <div class="mini-list">
        <h3>Most Active Clients</h3>
        <ul id="top-clients"></ul>
      </div>
      <div class="mini-list">
        <h3>Fast Signals</h3>
        <ul id="fast-signals"></ul>
      </div>
    </div>
  </div>
  <div class="panel">
    <h2>Email Operations</h2>
    <div id="email-health-note" class="hint">Loading email status...</div>
    <div class="email-status" id="email-health-cards"></div>
    <div class="toolbar" style="margin-top:10px;">
      <input id="email-test-note" type="text" placeholder="Optional test note..." />
      <button id="send-test-email-btn">Send Test Email</button>
    </div>
    <div class="mini-list">
      <h3>Recent Email Events</h3>
      <ul id="recent-email-events"></ul>
    </div>
  </div>
  <div class="panel">
    <h2>Mood Timeline (Daily Trend Bars)</h2>
    <div id="timeline"></div>
  </div>
  <div class="panel">
    <h2>Mood Timeline Calendar</h2>
    <div class="hint">Calendar cells are colored by daily average sentiment score.</div>
    <div class="calendar-grid" id="calendar"></div>
  </div>
  <div class="wrap">
    <table>
      <thead><tr><th>Timestamp</th><th>IP</th><th>Client</th><th>Sentiment</th><th>User Message</th><th>Bot Reply</th></tr></thead>
      <tbody id="logs-body"><tr><td colspan="6">Loading...</td></tr></tbody>
    </table>
  </div>
  <script>
    const CACHE_KEY = "echo_admin_logs_cache_v1";
    const MAX_ROWS = 2500;
    const serverRows = {rows_payload};
    const keyParam = "{key}";

    function esc(v) {{
      return String(v ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}

    function mergeRows(primaryRows, cachedRows) {{
      const map = new Map();
      const add = (r) => {{
        const k = `${{r.timestamp_iso || r.timestamp || ""}}|${{r.client_id || ""}}|${{r.user_message || ""}}|${{r.bot_reply || ""}}`;
        if (!map.has(k)) map.set(k, r);
      }};
      (primaryRows || []).forEach(add);
      (cachedRows || []).forEach(add);
      return Array.from(map.values()).slice(0, MAX_ROWS);
    }}

    function scoreForRow(r) {{
      if (typeof r.sentiment_score === "number") return r.sentiment_score;
      const s = String(r.sentiment || "").toLowerCase();
      if (s === "crisis") return -3;
      if (s === "negative") return -1;
      if (s === "positive") return 1;
      return 0;
    }}

    function toDateKey(r) {{
      const raw = String(r.timestamp_iso || r.timestamp || "");
      if (raw.includes("T")) return raw.slice(0, 10);
      return raw.slice(0, 10);
    }}

    function aggregateDaily(rows) {{
      const dayMap = new Map();
      for (const r of rows) {{
        const dk = toDateKey(r);
        if (!dk) continue;
        if (!dayMap.has(dk)) dayMap.set(dk, {{ scoreSum: 0, count: 0, pos: 0, neg: 0 }});
        const cur = dayMap.get(dk);
        const sc = scoreForRow(r);
        cur.scoreSum += sc;
        cur.count += 1;
        if (sc > 0) cur.pos += 1;
        if (sc < 0) cur.neg += 1;
      }}
      const out = Array.from(dayMap.entries()).map(([date, v]) => ({{
        date,
        avg: v.count ? v.scoreSum / v.count : 0,
        count: v.count,
        pos: v.pos,
        neg: v.neg,
      }}));
      out.sort((a, b) => a.date.localeCompare(b.date));
      return out;
    }}

    function barColor(avg) {{
      if (avg >= 1.2) return "#16a34a";
      if (avg >= 0.3) return "#22c55e";
      if (avg <= -1.2) return "#dc2626";
      if (avg <= -0.3) return "#f97316";
      return "#94a3b8";
    }}

    function dayColor(avg) {{
      if (avg >= 1.2) return "rgba(22,163,74,.40)";
      if (avg >= 0.3) return "rgba(34,197,94,.30)";
      if (avg <= -1.2) return "rgba(220,38,38,.40)";
      if (avg <= -0.3) return "rgba(249,115,22,.30)";
      return "rgba(148,163,184,.18)";
    }}

    function renderKpis(rows, daily) {{
      const kpis = document.getElementById("kpis");
      if (!kpis) return;
      const scoreAvg = rows.length ? rows.reduce((a, r) => a + scoreForRow(r), 0) / rows.length : 0;
      const pos = rows.filter(r => scoreForRow(r) > 0).length;
      const neg = rows.filter(r => scoreForRow(r) < 0).length;
      const tone = scoreAvg >= 0.6 ? "Positive" : scoreAvg <= -0.6 ? "Low" : "Steady";
      const today = daily.length ? daily[daily.length - 1] : null;
      kpis.innerHTML = `
        <div class="card"><div class="k">Total Events</div><div class="v">${{rows.length}}</div></div>
        <div class="card"><div class="k">Overall Tone</div><div class="v">${{tone}}</div></div>
        <div class="card"><div class="k">Positive / Negative</div><div class="v">${{pos}} / ${{neg}}</div></div>
        <div class="card"><div class="k">Today Avg</div><div class="v">${{today ? today.avg.toFixed(2) : "n/a"}}</div></div>
      `;
    }}

    function renderTimeline(daily) {{
      const root = document.getElementById("timeline");
      if (!root) return;
      const last = daily.slice(-14).reverse();
      if (!last.length) {{
        root.innerHTML = "<div class='hint'>No timeline data yet.</div>";
        return;
      }}
      root.innerHTML = last.map(d => {{
        const widthPct = Math.min(50, Math.abs(d.avg) / 3 * 50);
        const left = d.avg >= 0 ? 50 : 50 - widthPct;
        return `
          <div class="timeline-row">
            <div>${{esc(d.date)}}</div>
            <div class="timeline-bar-wrap">
              <div class="timeline-mid"></div>
              <div class="timeline-bar" style="left:${{left}}%;width:${{widthPct}}%;background:${{barColor(d.avg)}}"></div>
            </div>
            <div>${{d.avg.toFixed(2)}} (${{d.count}})</div>
          </div>
        `;
      }}).join("");
    }}

    function renderCalendar(daily) {{
      const root = document.getElementById("calendar");
      if (!root) return;
      const map = new Map(daily.map(d => [d.date, d]));
      const now = new Date();
      const start = new Date(now);
      start.setDate(now.getDate() - 41);
      const cells = [];
      for (let i = 0; i < 42; i++) {{
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        const dayKey = d.toISOString().slice(0, 10);
        const item = map.get(dayKey);
        const avg = item ? item.avg : 0;
        const count = item ? item.count : 0;
        cells.push(`
          <div class="day" style="background:${{dayColor(avg)}}">
            <div class="day-num">${{d.getDate()}}</div>
            <div class="day-metric">${{count ? avg.toFixed(2) : "-"}}</div>
          </div>
        `);
      }}
      root.innerHTML = cells.join("");
    }}

    function renderRows(rows) {{
      const tbody = document.getElementById("logs-body");
      if (!tbody) return;
      if (!rows.length) {{
        tbody.innerHTML = "<tr><td colspan='6'>No chat logs yet</td></tr>";
        return;
      }}
      tbody.innerHTML = rows.map((r) => `
        <tr>
          <td>${{esc(r.timestamp)}}</td>
          <td>${{esc(r.ip)}}</td>
          <td>${{esc(r.client_id || "unknown")}}</td>
          <td>${{esc(r.sentiment)}} (${{scoreForRow(r)}})</td>
          <td>${{esc(r.user_message)}}</td>
          <td>${{esc(r.bot_reply)}}</td>
        </tr>
      `).join("");
    }}

    function wordsFromRows(rows) {{
      const stop = new Set(["the","and","you","that","with","this","from","have","what","your","about","just","they","them","will","would","could","there","their","then","were","when","where","which","into","also","been","being","i","me","my","we","our","is","are","to","of","in","it","for","on","a","an"]);
      const map = new Map();
      for (const r of rows) {{
        const text = `${{r.user_message || ""}} ${{r.bot_reply || ""}}`.toLowerCase();
        const tokens = text.match(/[a-z][a-z0-9']{{2,}}/g) || [];
        for (const tok of tokens) {{
          if (stop.has(tok)) continue;
          map.set(tok, (map.get(tok) || 0) + 1);
        }}
      }}
      return Array.from(map.entries()).sort((a,b) => b[1]-a[1]).slice(0, 8);
    }}

    function topClients(rows) {{
      const map = new Map();
      for (const r of rows) {{
        const id = String(r.client_id || "unknown");
        map.set(id, (map.get(id) || 0) + 1);
      }}
      return Array.from(map.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 8);
    }}

    function renderInsights(rows, daily) {{
      const keywordsEl = document.getElementById("top-keywords");
      const clientsEl = document.getElementById("top-clients");
      const signalsEl = document.getElementById("fast-signals");
      if (keywordsEl) {{
        const kws = wordsFromRows(rows);
        keywordsEl.innerHTML = kws.length ? kws.map(([k,v]) => `<li>${{esc(k)}} <span class="pill">${{v}}</span></li>`).join("") : "<li>No keyword data yet.</li>";
      }}
      if (clientsEl) {{
        const clients = topClients(rows);
        clientsEl.innerHTML = clients.length ? clients.map(([k,v]) => `<li>${{esc(k)}} <span class="pill">${{v}}</span></li>`).join("") : "<li>No client data yet.</li>";
      }}
      if (signalsEl) {{
        const last7 = daily.slice(-7);
        const avg7 = last7.length ? last7.reduce((a,d)=>a+d.avg,0)/last7.length : 0;
        const today = daily.length ? daily[daily.length - 1] : null;
        const total = rows.length;
        const crisisCount = rows.filter(r => String(r.sentiment||"").toLowerCase() === "crisis").length;
        signalsEl.innerHTML = `
          <li>7-day mood average: <span class="pill">${{avg7.toFixed(2)}}</span></li>
          <li>Today score: <span class="pill">${{today ? today.avg.toFixed(2) : "n/a"}}</span></li>
          <li>Total logged events: <span class="pill">${{total}}</span></li>
          <li>Crisis-flag messages: <span class="pill">${{crisisCount}}</span></li>
        `;
      }}
    }}

    function applyFilters(rows) {{
      const q = String(document.getElementById("search-box")?.value || "").toLowerCase().trim();
      const sentiment = String(document.getElementById("sentiment-filter")?.value || "all").toLowerCase();
      const client = String(document.getElementById("client-filter")?.value || "all");
      return rows.filter((r) => {{
        if (sentiment !== "all" && String(r.sentiment || "").toLowerCase() !== sentiment) return false;
        if (client !== "all" && String(r.client_id || "unknown") !== client) return false;
        if (!q) return true;
        const blob = `${{r.user_message || ""}} ${{r.bot_reply || ""}} ${{r.ip || ""}} ${{r.client_id || ""}}`.toLowerCase();
        return blob.includes(q);
      }});
    }}

    function populateClientFilter(rows) {{
      const sel = document.getElementById("client-filter");
      if (!sel) return;
      const current = String(sel.value || "all");
      const clients = Array.from(new Set(rows.map(r => String(r.client_id || "unknown")))).sort();
      sel.innerHTML = `<option value="all">All clients</option>` + clients.map(c => `<option value="${{esc(c)}}">${{esc(c)}}</option>`).join("");
      sel.value = clients.includes(current) ? current : "all";
    }}

    function exportCsv(rows) {{
      const headers = ["timestamp","ip","client_id","sentiment","sentiment_score","user_message","bot_reply"];
      const escapeCsv = (v) => `"${{String(v ?? "").replaceAll('"','""')}}"`;
      const lines = [headers.join(",")];
      for (const r of rows) {{
        lines.push([
          r.timestamp, r.ip, r.client_id, r.sentiment, scoreForRow(r), r.user_message, r.bot_reply
        ].map(escapeCsv).join(","));
      }}
      const blob = new Blob([lines.join("\\n")], {{ type: "text/csv;charset=utf-8;" }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `echo-admin-logs-${{new Date().toISOString().slice(0,10)}}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    }}

    async function fetchEmailHealth() {{
      try {{
        const res = await fetch(`/api/admin_email_health?key=${{encodeURIComponent(keyParam)}}`, {{ credentials: "same-origin" }});
        if (!res.ok) return null;
        return await res.json();
      }} catch {{
        return null;
      }}
    }}

    function renderEmailHealth(data) {{
      const note = document.getElementById("email-health-note");
      const cards = document.getElementById("email-health-cards");
      const events = document.getElementById("recent-email-events");
      if (!cards || !events || !note) return;
      if (!data) {{
        note.textContent = "Email status unavailable.";
        cards.innerHTML = "";
        events.innerHTML = "<li>No email event data.</li>";
        return;
      }}
      note.innerHTML = `Email delivery: <span class="pill ${{data.enabled ? "ok" : "bad"}}">${{data.enabled ? "enabled" : "disabled"}}</span>`;
      const byKind = Object.entries(data.by_kind || {{}}).slice(0, 6)
        .map(([k,v]) => `<span class="pill">${{esc(k)}}: ${{v}}</span>`).join(" ");
      cards.innerHTML = `
        <div class="card"><div class="k">SMTP User</div><div class="v">${{data.smtp_user_set ? "set" : "missing"}}</div></div>
        <div class="card"><div class="k">SMTP Password</div><div class="v">${{data.smtp_password_set ? "set" : "missing"}}</div></div>
        <div class="card"><div class="k">To</div><div class="v" style="font-size:14px">${{esc(data.email_to_masked || "n/a")}}</div></div>
        <div class="card"><div class="k">Last Sent</div><div class="v" style="font-size:14px">${{esc(data.last_sent_at || "n/a")}}</div></div>
        <div class="card"><div class="k">Event Types</div><div style="margin-top:6px">${{byKind || "<span class='pill'>none</span>"}}</div></div>
      `;
      const recent = Array.isArray(data.recent) ? data.recent : [];
      events.innerHTML = recent.length
        ? recent.slice(0, 8).map((e) => `<li>${{esc(e.sent_at_iso)}} - <b>${{esc(e.kind)}}</b></li>`).join("")
        : "<li>No email events yet.</li>";
    }}

    async function fetchServerRows() {{
      try {{
        const res = await fetch(`/api/admin_logs?key=${{encodeURIComponent(keyParam)}}&limit=2500`, {{ credentials: "same-origin" }});
        if (!res.ok) return [];
        return await res.json();
      }} catch (e) {{
        return [];
      }}
    }}

    let cached = [];
    let lastRows = [];
    try {{
      cached = JSON.parse(localStorage.getItem(CACHE_KEY) || "[]");
    }} catch (e) {{
      cached = [];
    }}

    async function updateAll() {{
      const latestServer = await fetchServerRows();
      const seed = latestServer.length ? latestServer : serverRows;
      const merged = mergeRows(seed, cached);
      localStorage.setItem(CACHE_KEY, JSON.stringify(merged));
      cached = merged;
      lastRows = merged;
      populateClientFilter(merged);
      const filtered = applyFilters(merged);
      renderRows(filtered);
      const daily = aggregateDaily(filtered);
      renderKpis(filtered, daily);
      renderTimeline(daily);
      renderCalendar(daily);
      renderInsights(filtered, daily);
      renderEmailHealth(await fetchEmailHealth());
      const cacheInfo = document.getElementById("cache-info");
      if (cacheInfo) {{
        cacheInfo.textContent = `Cache status: ${{
          seed.length ? "server+cache merged" : (merged.length ? "served from browser cache" : "empty")
        }} (${{merged.length}} rows, ${{filtered.length}} visible)`;
      }}
    }}

    function bindControls() {{
      const rerender = () => {{
        const filtered = applyFilters(lastRows);
        const daily = aggregateDaily(filtered);
        renderRows(filtered);
        renderKpis(filtered, daily);
        renderTimeline(daily);
        renderCalendar(daily);
        renderInsights(filtered, daily);
      }};
      document.getElementById("search-box")?.addEventListener("input", rerender);
      document.getElementById("sentiment-filter")?.addEventListener("change", rerender);
      document.getElementById("client-filter")?.addEventListener("change", rerender);
      document.getElementById("export-csv-btn")?.addEventListener("click", () => exportCsv(applyFilters(lastRows)));
      document.getElementById("refresh-btn")?.addEventListener("click", () => updateAll());
      document.getElementById("send-test-email-btn")?.addEventListener("click", async () => {{
        const note = String(document.getElementById("email-test-note")?.value || "").trim();
        try {{
          const res = await fetch(`/api/admin_send_test_email?key=${{encodeURIComponent(keyParam)}}`, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            credentials: "same-origin",
            body: JSON.stringify({{ note }})
          }});
          const data = await res.json();
          alert(data.message || (res.ok ? "Test email sent." : "Failed to send test email."));
        }} catch {{
          alert("Failed to send test email.");
        }}
        renderEmailHealth(await fetchEmailHealth());
      }});
    }}

    bindControls();
    updateAll();
    setInterval(updateAll, 15000);
  </script>
</body>
</html>"""
    return Response(page, mimetype="text/html")


@app.route("/shared/<share_id>", methods=["GET"])
def route_shared_page(share_id: str):
    page = render_shared_link_page(share_id=share_id)
    return Response(page, mimetype="text/html")


if __name__ == "__main__":
    app.run(port=5328)
