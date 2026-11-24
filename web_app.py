from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from dummy_gh import (
    _load_state,
    force_dirty_state,
    get_dashboard_payload,
    get_gh_report,
    mark_cleaning_completed,
)

app = FastAPI(title="Greenhouse Smart Monitor — Bento Liquid Glass")

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="id" data-theme="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Greenhouse Smart Monitor — Bento Liquid Glass</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8/hammer.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
  <style>
    :root {
      --glass-bg: rgba(255, 255, 255, 0.07);
      --glass-bg-strong: rgba(255, 255, 255, 0.12);
      --glass-border: rgba(255, 255, 255, 0.18);
      --glass-highlight: rgba(255, 255, 255, 0.28);
      --inner-bg: rgba(15, 23, 42, 0.36);
      --inner-border: rgba(255, 255, 255, 0.12);
      --text-main: #f8fafc;
      --text-muted: #cbd5e1;
      --text-dim: #94a3b8;
      --grid-line: rgba(255, 255, 255, 0.08);
      --shadow: rgba(0, 0, 0, 0.35);
      --good: #4ade80;
      --warn: #fbbf24;
      --bad: #f87171;
      --blue: #38bdf8;
      --orange: #f97316;
      --option-bg: #0f172a;
      --body-bg:
        radial-gradient(circle at 12% 15%, rgba(56, 189, 248, 0.26), transparent 42%),
        radial-gradient(circle at 88% 18%, rgba(74, 222, 128, 0.22), transparent 40%),
        radial-gradient(circle at 50% 88%, rgba(249, 115, 22, 0.20), transparent 45%),
        linear-gradient(145deg, #070d19 0%, #0d172a 55%, #091120 100%);
    }

    :root[data-theme="light"] {
      --glass-bg: rgba(255, 255, 255, 0.55);
      --glass-bg-strong: rgba(255, 255, 255, 0.8);
      --glass-border: rgba(15, 23, 42, 0.10);
      --glass-highlight: rgba(255, 255, 255, 0.9);
      --inner-bg: rgba(255, 255, 255, 0.6);
      --inner-border: rgba(15, 23, 42, 0.10);
      --text-main: #0f172a;
      --text-muted: #334155;
      --text-dim: #64748b;
      --grid-line: rgba(15, 23, 42, 0.09);
      --shadow: rgba(30, 41, 59, 0.14);
      --good: #16a34a;
      --warn: #d97706;
      --bad: #dc2626;
      --blue: #0284c7;
      --orange: #ea580c;
      --option-bg: #ffffff;
      --body-bg:
        radial-gradient(circle at 12% 15%, rgba(56, 189, 248, 0.30), transparent 42%),
        radial-gradient(circle at 88% 18%, rgba(74, 222, 128, 0.26), transparent 40%),
        radial-gradient(circle at 50% 88%, rgba(249, 115, 22, 0.16), transparent 45%),
        linear-gradient(145deg, #eef4fb 0%, #e4edf7 55%, #eaf1f8 100%);
    }

    *, *::before, *::after {
      box-sizing: border-box;
      font-family: "Segoe UI", system-ui, -apple-system, Roboto, sans-serif;
    }

    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text-main);
      background: var(--body-bg);
      background-attachment: fixed;
      padding: 22px;
      transition: color 0.25s ease;
    }

    .container { width: 100%; max-width: 1280px; margin: 0 auto; }

    .glass {
      background: var(--glass-bg);
      backdrop-filter: blur(18px) saturate(150%);
      -webkit-backdrop-filter: blur(18px) saturate(150%);
      border: 1px solid var(--glass-border);
      box-shadow: 0 12px 32px var(--shadow), inset 0 1px 0 var(--glass-highlight);
      border-radius: 20px;
    }

    button, select { font: inherit; }

    :focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }

    /* ---------- Header ---------- */
    .header {
      padding: 16px 22px;
      margin-bottom: 14px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
    }

    h1 { margin: 0; font-size: 1.35rem; font-weight: 700; letter-spacing: -0.01em; }
    .sub { color: var(--text-dim); font-size: 0.82rem; margin-top: 4px; }

    .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }

    select, .btn {
      background: var(--glass-bg-strong);
      color: var(--text-main);
      border: 1px solid var(--glass-border);
      padding: 8px 12px;
      border-radius: 12px;
      font-size: 0.84rem;
      cursor: pointer;
      backdrop-filter: blur(12px);
      transition: transform 0.15s ease, border-color 0.2s ease;
    }
    select option { background: var(--option-bg); color: var(--text-main); }
    .btn:hover, select:hover { border-color: var(--glass-highlight); transform: translateY(-1px); }
    .btn.small { padding: 5px 10px; font-size: 0.76rem; border-radius: 10px; }

    .live {
      display: inline-flex; align-items: center; gap: 8px;
      padding: 7px 12px; border-radius: 999px; font-size: 0.82rem; font-weight: 600;
      background: var(--glass-bg-strong); border: 1px solid var(--glass-border);
    }
    .live .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--good); }
    .live.on .dot { animation: pulse 1.6s ease-in-out infinite; }
    .live.paused .dot { background: var(--warn); }
    .live.off .dot { background: var(--bad); }
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.6); }
      70% { box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
      100% { box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
    }

    /* ---------- Alert ---------- */
    .alert-bar {
      margin-bottom: 14px; padding: 12px 18px; border-radius: 16px;
      border: 1px solid; font-size: 0.88rem;
    }
    .alert-bar.warn { background: rgba(251, 191, 36, 0.14); border-color: rgba(251, 191, 36, 0.5); }
    .alert-bar.bad  { background: rgba(248, 113, 113, 0.16); border-color: rgba(248, 113, 113, 0.55); }
    .alert-bar ul { margin: 0; padding-left: 18px; }
    .alert-bar li { margin: 2px 0; }
    .alert-title { font-weight: 700; margin-bottom: 4px; }
    .alert-bar[hidden] { display: none; }

    /* ---------- Grid ---------- */
    .grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }
    .s3 { grid-column: span 3; } .s4 { grid-column: span 4; } .s6 { grid-column: span 6; }
    .s8 { grid-column: span 8; } .s12 { grid-column: span 12; }
    @media (max-width: 1000px) { .s3 { grid-column: span 6; } .s4, .s6, .s8 { grid-column: span 12; } }
    @media (max-width: 560px) { .s3 { grid-column: span 12; } }

    .panel { padding: 18px; min-width: 0; }
    .section-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 12px; }
    .panel-title { margin: 0; font-size: 1.02rem; font-weight: 650; }
    .sub-title { margin: 0 0 10px 0; font-size: 0.9rem; font-weight: 600; color: var(--text-muted); }

    .mini-card { background: var(--inner-bg); border: 1px solid var(--inner-border); border-radius: 16px; padding: 14px; min-width: 0; }
    .chart-box { position: relative; height: 250px; }
    .chart-box.tall { height: 290px; }

    /* ---------- KPI ---------- */
    .kpi { padding: 14px 16px; min-width: 0; display: flex; flex-direction: column; gap: 6px; }
    .kpi-top { display: flex; justify-content: space-between; align-items: center; }
    .kpi-label { font-size: 0.78rem; color: var(--text-dim); font-weight: 600; }
    .delta { font-size: 0.76rem; font-weight: 700; }
    .delta.good { color: var(--good); } .delta.bad { color: var(--bad); } .delta.flat { color: var(--text-dim); }

    .gauge-wrap { position: relative; width: 100%; max-width: 190px; margin: 0 auto; }
    .gauge { width: 100%; display: block; }
    .g-track, .g-val { fill: none; stroke-width: 10; stroke-linecap: round; }
    .g-track { stroke: var(--grid-line); }
    .g-val { stroke: var(--good); transition: stroke-dasharray 0.6s ease, stroke 0.4s ease; }
    .g-num { position: absolute; left: 0; right: 0; bottom: 2px; text-align: center; font-size: 1.55rem; font-weight: 700; line-height: 1; }
    .g-num small { font-size: 0.8rem; font-weight: 600; color: var(--text-dim); margin-left: 2px; }
    .spark { width: 100%; height: 28px; display: block; }

    .status-list { display: flex; flex-direction: column; gap: 9px; font-size: 0.86rem; }
    .status-row { display: flex; justify-content: space-between; gap: 10px; align-items: center; }
    .status-row span:first-child { color: var(--text-dim); }
    .pill { padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; border: 1px solid transparent; }
    .pill.good { color: var(--good); background: rgba(74, 222, 128, 0.14); border-color: rgba(74, 222, 128, 0.4); }
    .pill.warn { color: var(--warn); background: rgba(251, 191, 36, 0.14); border-color: rgba(251, 191, 36, 0.4); }
    .pill.bad  { color: var(--bad);  background: rgba(248, 113, 113, 0.14); border-color: rgba(248, 113, 113, 0.4); }

    /* ---------- Heatmap ---------- */
    .hm-wrap { display: flex; flex-wrap: wrap; gap: 14px; max-height: 300px; overflow-y: auto; }
    .hm-month { flex: 1 1 220px; min-width: 200px; }
    .hm-title { font-size: 0.8rem; font-weight: 600; color: var(--text-muted); margin-bottom: 6px; text-transform: capitalize; }
    .hm-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 3px; }
    .hm-dow { font-size: 0.65rem; color: var(--text-dim); text-align: center; }
    .hm-cell { aspect-ratio: 1; border-radius: 6px; font-size: 0.66rem; display: flex; align-items: center; justify-content: center; color: #fff; text-shadow: 0 1px 2px rgba(0,0,0,0.4); }
    .hm-cell.empty { background: transparent; }
    .hm-cell.cleaned { box-shadow: inset 0 0 0 2px var(--text-main); }
    .hm-legend { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 0.72rem; color: var(--text-dim); }
    .hm-bar { flex: 1; max-width: 160px; height: 8px; border-radius: 6px; background: linear-gradient(90deg, hsl(0 65% 42%), hsl(65 65% 42%), hsl(130 65% 42%)); }

    /* ---------- Cleaning list ---------- */
    .clean-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; max-height: 300px; overflow-y: auto; padding-right: 4px; }
    .clean-item { background: var(--glass-bg); border: 1px solid var(--inner-border); border-radius: 12px; padding: 10px 12px; font-size: 0.83rem; min-width: 0; }
    .clean-date { font-weight: 700; color: var(--good); }
    .clean-meta { color: var(--text-muted); font-size: 0.76rem; margin-top: 3px; word-break: break-word; }

    .footer { padding: 12px 18px; display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 0.82rem; color: var(--text-dim); }

    @media (prefers-reduced-motion: reduce) {
      .live.on .dot { animation: none; }
      .g-val, .btn, select { transition: none; }
    }
  </style>
</head>
<body>
  <div class="container">

    <!-- Header -->
    <div class="glass header">
      <div>
        <h1>🌿 Greenhouse Smart Monitoring PT. Nyalindung</h1>
        <div class="sub" id="updatedAt">Memuat data...</div>
      </div>
      <div class="controls">
        <span class="live on" id="liveBadge" role="status"><span class="dot"></span><span id="liveText">Live</span></span>
        <button class="btn" id="pauseBtn" type="button">⏸ Jeda</button>
        <label class="sub" for="intervalSel" style="margin:0;">Interval</label>
        <select id="intervalSel" aria-label="Interval pembaruan realtime">
          <option value="3000">3 detik</option>
          <option value="5000" selected>5 detik</option>
          <option value="10000">10 detik</option>
          <option value="30000">30 detik</option>
        </select>
        <button class="btn" id="exportMonthlyBtn" type="button">⬇ CSV Bulan</button>
        <button class="btn" id="themeBtn" type="button" aria-label="Ganti tema">🌙 Gelap</button>
        <button class="btn" id="refreshBtn" type="button">🔄 Refresh</button>
      </div>
    </div>

    <!-- Smart alert -->
    <div class="alert-bar" id="alertBar" role="alert" aria-live="polite" hidden></div>

    <!-- KPI: gauge + sparkline + status -->
    <div class="grid" id="kpiGrid">
      <div class="glass kpi s3" id="card-score"></div>
      <div class="glass kpi s3" id="card-light"></div>
      <div class="glass kpi s3" id="card-dirty"></div>
      <div class="glass kpi s3">
        <div class="kpi-label">Status sistem</div>
        <div class="status-list">
          <div class="status-row"><span>AI Status</span><span class="pill" id="aiStatus">-</span></div>
          <div class="status-row"><span>Rekomendasi</span><span class="pill" id="rec">-</span></div>
          <div class="status-row"><span>System Health</span><span class="pill" id="health">-</span></div>
          <div class="status-row"><span>Estimasi air siklus</span><b id="water">-</b></div>
        </div>
      </div>
    </div>

    <!-- Realtime -->
    <div class="grid">
      <div class="glass panel s12">
        <div class="section-head">
          <div>
            <h2 class="panel-title">⚡ Grafik Realtime</h2>
          </div>
          <button class="btn small" id="resetZoomBtn" type="button">Reset zoom</button>
        </div>
        <div class="chart-box tall"><canvas id="realtimeChart"></canvas></div>
      </div>
    </div>

    <!-- Daily section -->
    <div class="glass panel" style="margin-bottom:14px;">
      <div class="section-head">
        <div>
          <h2 class="panel-title" id="dailyTitle">📅 Summary Harian</h2>
        </div>
        <div class="controls">
          <label for="monthFilter" class="sub" style="margin:0;">Filter bulan</label>
          <select id="monthFilter"></select>
        </div>
      </div>

      <div class="grid" style="margin-bottom:0;">
        <div class="mini-card s12">
          <h3 class="sub-title">Roof Dirty vs Light Transmission (▲ = hari pembersihan)</h3>
          <div class="chart-box"><canvas id="comboChart"></canvas></div>
        </div>

        <div class="mini-card s6">
          <h3 class="sub-title">📈 AI Score (%)</h3>
          <div class="chart-box"><canvas id="scoreChart"></canvas></div>
        </div>
        <div class="mini-card s6">
          <h3 class="sub-title">💧 Penggunaan Air (Liter)</h3>
          <div class="chart-box"><canvas id="waterChart"></canvas></div>
        </div>

        <div class="mini-card s6">
          <div class="section-head" style="margin-bottom:8px;">
            <h3 class="sub-title" style="margin:0;">Heatmap kalender</h3>
            <select id="heatMetric" aria-label="Metrik heatmap">
              <option value="roof_dirty">Roof Dirty</option>
              <option value="light_transmission">Light Transmission</option>
              <option value="ai_score">AI Score</option>
            </select>
          </div>
          <div class="hm-wrap" id="heatmap"></div>
          <div class="hm-legend"><span>buruk</span><span class="hm-bar"></span><span>baik</span><span>· kotak bergaris = dibersihkan</span></div>
        </div>

        <div class="mini-card s6">
          <h3 class="sub-title" id="cleanTitle">🧹 Riwayat Pembersihan</h3>
          <div class="clean-grid" id="cleaningList"></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    /* =========================================================
       Konfigurasi & helper
       ========================================================= */
    const CFG = {
      dirtyWarn: 15, dirtyCrit: 20, dirtyBarRed: 20,
      lightWarn: 70, lightCrit: 30,
      suddenDrop: 8,            // penurunan light (poin %) antar data realtime
      dailyRefreshMs: 60000
    };

    const $ = (id) => document.getElementById(id);
    const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    const toneColor = (t) => css(t === "good" ? "--good" : t === "warn" ? "--warn" : "--bad");

    const toneScore = (v) => (v >= 82 ? "good" : v >= 60 ? "warn" : "bad");
    const toneLight = (v) => (v >= 75 ? "good" : v >= CFG.lightWarn ? "warn" : "bad");
    const toneDirty = (v) => (v < CFG.dirtyWarn ? "good" : v <= CFG.dirtyCrit ? "warn" : "bad");
    const toneStatus = (s) => (s === "GOOD" ? "good" : s === "WARNING" ? "warn" : "bad");

    const state = {
      rt: null, history: [], daily: [], months: [], month: "",
      paused: false, interval: 5000, online: true,
      rtTimer: null, heatMetric: "roof_dirty"
    };
    const charts = {};

    function monthLabel(m) {
      const [y, mo] = m.split("-").map(Number);
      return new Date(y, mo - 1, 1).toLocaleDateString("id-ID", { month: "long", year: "numeric" });
    }

    function filteredDaily() {
      return state.month === "ALL" ? state.daily : state.daily.filter((d) => d.month === state.month);
    }

    /* =========================================================
       KPI: gauge + sparkline
       ========================================================= */
    function kpiCardHTML(id, label, unit) {
      return `
        <div class="kpi-top"><span class="kpi-label">${label}</span><span class="delta" id="d-${id}"></span></div>
        <div class="gauge-wrap">
          <svg viewBox="0 0 120 70" class="gauge" role="img" aria-label="${label}">
            <path d="M10 60 A50 50 0 0 1 110 60" pathLength="100" class="g-track"></path>
            <path d="M10 60 A50 50 0 0 1 110 60" pathLength="100" class="g-val" id="gv-${id}" stroke-dasharray="0 100"></path>
          </svg>
          <div class="g-num"><span id="gn-${id}">-</span><small>${unit}</small></div>
        </div>
        <svg class="spark" id="sp-${id}" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"></svg>`;
    }

    function setGauge(id, value, tone) {
      const el = $("gv-" + id);
      el.setAttribute("stroke-dasharray", `${clamp(value, 0.5, 100)} 100`);
      el.style.stroke = toneColor(tone);
      $("gn-" + id).textContent = value;
    }

    function setDelta(id, cur, prev, upIsGood) {
      const el = $("d-" + id);
      if (prev == null) { el.textContent = ""; return; }
      const d = +(cur - prev).toFixed(1);
      if (d === 0) { el.textContent = "— 0"; el.className = "delta flat"; return; }
      el.textContent = `${d > 0 ? "▲" : "▼"} ${Math.abs(d)}`;
      el.className = "delta " + ((d > 0) === upIsGood ? "good" : "bad");
    }

    function setSpark(id, values, tone) {
      const el = $("sp-" + id);
      if (values.length < 2) { el.innerHTML = ""; return; }
      const min = Math.min(...values), max = Math.max(...values), rng = max - min || 1;
      const pts = values.map((v, i) =>
        `${((i / (values.length - 1)) * 100).toFixed(2)},${(26 - ((v - min) / rng) * 24).toFixed(2)}`
      );
      el.innerHTML = `<polyline points="${pts.join(" ")}" fill="none" stroke="${toneColor(tone)}"
        stroke-width="1.6" stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>`;
    }

    function setPill(id, text, tone) {
      const el = $(id);
      el.textContent = text;
      el.className = "pill " + tone;
    }

    /* =========================================================
       Alert pintar
       ========================================================= */
    function buildAlerts(r, hist) {
      const a = [];
      if (r.ai_status === "CRITICAL") a.push({ lvl: "bad", text: `AI mendeteksi kondisi CRITICAL (skor ${r.ai_score}%).` });
      if (r.roof_dirty > CFG.dirtyCrit) a.push({ lvl: "bad", text: `Roof Dirty ${r.roof_dirty}% melewati batas CRITICAL (${CFG.dirtyCrit}%).` });
      else if (r.roof_dirty >= CFG.dirtyWarn) a.push({ lvl: "warn", text: `Roof Dirty ${r.roof_dirty}% mendekati batas pembersihan (${CFG.dirtyCrit}%).` });
      if (r.light_transmission < CFG.lightWarn) a.push({ lvl: "bad", text: `Light Transmission turun menjadi ${r.light_transmission}% (di bawah batas ${CFG.lightWarn}%).` });
      else if (r.light_transmission < 75) a.push({ lvl: "warn", text: `Light Transmission ${r.light_transmission}% mulai menurun.` });
      if (r.system_health === "BAD") a.push({ lvl: "warn", text: "System Health BAD: periksa sensor atau perangkat." });
      if (hist.length >= 2) {
        const drop = hist[hist.length - 2].light_transmission - r.light_transmission;
        if (drop >= CFG.suddenDrop) a.push({ lvl: "bad", text: `Light Transmission turun mendadak ${drop.toFixed(1)} poin dari data sebelumnya.` });
      }
      return a;
    }

    function renderAlerts(r, hist) {
      const bar = $("alertBar");
      const alerts = buildAlerts(r, hist);
      if (!alerts.length) { bar.hidden = true; return; }
      const worst = alerts.some((x) => x.lvl === "bad") ? "bad" : "warn";
      bar.className = "alert-bar " + worst;
      bar.innerHTML = `<div class="alert-title">${worst === "bad" ? "🚨 Perlu tindakan segera" : "⚠️ Perlu perhatian"}</div>
        <ul>${alerts.map((x) => `<li>${x.text}</li>`).join("")}</ul>`;
      bar.hidden = false;
    }

    /* =========================================================
       Chart
       ========================================================= */
    const dirtyBarColor = (v) => (v > CFG.dirtyBarRed ? css("--bad") : v >= CFG.dirtyWarn ? css("--warn") : css("--good"));
    const scoreBarColor = (v) => toneColor(toneScore(v));

    function annotationLine(y, text, color) {
      return {
        type: "line", yMin: y, yMax: y, borderColor: color, borderDash: [6, 6], borderWidth: 1,
        label: { display: true, content: text, position: "start", backgroundColor: "transparent", color, font: { size: 10 } }
      };
    }

    function initCharts() {
      Chart.defaults.color = css("--text-muted");
      Chart.defaults.borderColor = css("--grid-line");

      charts.rt = new Chart($("realtimeChart"), {
        type: "line",
        data: {
          labels: [],
          datasets: [
            { label: "Light Transmission (%)", data: [], borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.16)", tension: 0.3, pointRadius: 2 },
            { label: "Roof Dirty (%)", data: [], borderColor: "#f97316", backgroundColor: "rgba(249,115,22,.16)", tension: 0.3, pointRadius: 2 },
            { label: "AI Score (%)", data: [], borderColor: "#4ade80", backgroundColor: "rgba(74,222,128,.16)", tension: 0.3, pointRadius: 2 }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: "index", intersect: false },
          scales: { x: { ticks: { maxTicksLimit: 12 } }, y: { min: 0, max: 100 } },
          plugins: {
            annotation: { annotations: {
              dirtyLimit: annotationLine(CFG.dirtyCrit, `Batas dirty ${CFG.dirtyCrit}%`, "rgba(248,113,113,.85)"),
              lightLimit: annotationLine(CFG.lightWarn, `Batas light ${CFG.lightWarn}%`, "rgba(56,189,248,.8)")
            } },
            zoom: {
              zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
              pan: { enabled: true, mode: "x" }
            }
          }
        }
      });

      charts.combo = new Chart($("comboChart"), {
        type: "bar",
        data: {
          labels: [],
          datasets: [
            { type: "bar", label: "Roof Dirty (%)", data: [], borderRadius: 4, order: 2,
              backgroundColor: (c) => dirtyBarColor(c.parsed ? c.parsed.y : 0) },
            { type: "line", label: "Light Transmission (%)", data: [], borderColor: "#38bdf8", borderWidth: 2, tension: 0.3, pointRadius: 0, order: 1 },
            { type: "line", label: "Pembersihan", data: [], showLine: false, pointStyle: "triangle", pointRadius: 7,
              pointBackgroundColor: "#4ade80", pointBorderColor: "#fff", order: 0 }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false, animation: false,
          interaction: { mode: "index", intersect: false },
          scales: { x: { ticks: { maxTicksLimit: 15 } }, y: { min: 0, max: 100 } },
          plugins: { annotation: { annotations: {
            dirtyLimit: annotationLine(CFG.dirtyCrit, `Batas dirty ${CFG.dirtyCrit}%`, "rgba(248,113,113,.85)")
          } } }
        }
      });

      const barOpts = (suffix, extra) => ({
        responsive: true, maintainAspectRatio: false, animation: false,
        scales: { x: { ticks: { maxTicksLimit: 15 } }, y: Object.assign({ min: 0 }, extra) },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (i) => i.parsed.y == null ? null : `${i.dataset.label}: ${i.formattedValue}${suffix}` } }
        }
      });

      charts.score = new Chart($("scoreChart"), {
        type: "bar",
        data: { labels: [], datasets: [{ label: "AI Score", data: [], borderRadius: 5,
          backgroundColor: (c) => scoreBarColor(c.parsed ? c.parsed.y : 100) }] },
        options: barOpts("%", { max: 100 })
      });

      charts.water = new Chart($("waterChart"), {
        type: "bar",
        data: { labels: [], datasets: [{ label: "Penggunaan Air", data: [], borderRadius: 5,
          backgroundColor: "rgba(56,189,248,.78)", borderColor: "#38bdf8", borderWidth: 1 }] },
        options: barOpts(" L", { suggestedMax: 150 })
      });
    }

    /* =========================================================
       Render realtime
       ========================================================= */
    function renderRealtime() {
      const r = state.rt;
      if (!r) return;
      const h = state.history;
      const prev = h.length > 1 ? h[h.length - 2] : null;

      const tScore = toneScore(r.ai_score), tLight = toneLight(r.light_transmission), tDirty = toneDirty(r.roof_dirty);
      setGauge("score", r.ai_score, tScore);
      setGauge("light", r.light_transmission, tLight);
      setGauge("dirty", r.roof_dirty, tDirty);

      setDelta("score", r.ai_score, prev && prev.ai_score, true);
      setDelta("light", r.light_transmission, prev && prev.light_transmission, true);
      setDelta("dirty", r.roof_dirty, prev && prev.roof_dirty, false);
      if (!prev) ["score", "light", "dirty"].forEach((k) => ($("d-" + k).textContent = ""));

      setSpark("score", h.map((p) => p.ai_score), tScore);
      setSpark("light", h.map((p) => p.light_transmission), tLight);
      setSpark("dirty", h.map((p) => p.roof_dirty), tDirty);

      setPill("aiStatus", r.ai_status, toneStatus(r.ai_status));
      setPill("rec", r.cleaning_recommendation, r.cleaning_recommendation === "CLEANING" ? "bad" : "good");
      setPill("health", r.system_health, r.system_health === "NORMAL" ? "good" : "bad");
      const estSec = Number(r.spray_seconds || 0);
      const estMin = (estSec / 60).toFixed(1);
      $("water").textContent = `${r.estimated_water_liters} L (~${estMin} mnt / ${estSec}s)`;
      $("updatedAt").textContent = `Update terakhir: ${r.updated_at}`;

      const c = charts.rt;
      c.data.labels = h.map((p) => p.time);
      c.data.datasets[0].data = h.map((p) => p.light_transmission);
      c.data.datasets[1].data = h.map((p) => p.roof_dirty);
      c.data.datasets[2].data = h.map((p) => p.ai_score);
      c.update("none");

      renderAlerts(r, h);
    }

    /* =========================================================
       Render harian
       ========================================================= */
    function populateMonths() {
      const sel = $("monthFilter");
      sel.innerHTML = "";
      state.months.forEach((m) => {
        const o = document.createElement("option");
        o.value = m; o.textContent = monthLabel(m);
        sel.appendChild(o);
      });
      const all = document.createElement("option");
      all.value = "ALL"; all.textContent = "Semua bulan (sejak 2026-07)";
      sel.appendChild(all);
      if (!state.month || ![...sel.options].some((o) => o.value === state.month)) {
        state.month = state.months[0] || "ALL";
      }
      sel.value = state.month;
    }

    function heatColor(metric, v) {
      let good;
      if (metric === "roof_dirty") good = 1 - clamp(v / CFG.dirtyCrit, 0, 1);
      else if (metric === "light_transmission") good = clamp((v - 48) / 42, 0, 1);
      else good = clamp((v - 40) / 58, 0, 1);
      return `hsl(${Math.round(good * 130)} 65% 42%)`;
    }

    function renderHeatmap() {
      const metric = state.heatMetric;
      const unit = "%";
      const names = { roof_dirty: "Roof Dirty", light_transmission: "Light", ai_score: "AI Score" };
      const dow = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"].map((d) => `<span class="hm-dow">${d}</span>`).join("");
      const byMonth = {};
      filteredDaily().forEach((d) => { (byMonth[d.month] = byMonth[d.month] || []).push(d); });
      const months = Object.keys(byMonth).sort().reverse();

      $("heatmap").innerHTML = months.map((m) => {
        const [y, mo] = m.split("-").map(Number);
        const offset = (new Date(y, mo - 1, 1).getDay() + 6) % 7;
        const cells = [];
        for (let i = 0; i < offset; i++) cells.push('<span class="hm-cell empty"></span>');
        byMonth[m].forEach((d) => {
          const v = d[metric];
          cells.push(`<span class="hm-cell${d.cleaned ? " cleaned" : ""}" style="background:${heatColor(metric, v)}"
            title="${d.date} · ${names[metric]}: ${v}${unit}${d.cleaned ? " · dibersihkan" : ""}">${+d.date.slice(8)}</span>`);
        });
        return `<div class="hm-month"><div class="hm-title">${monthLabel(m)}</div><div class="hm-grid">${dow}${cells.join("")}</div></div>`;
      }).join("") || '<div class="sub">Belum ada data.</div>';
    }

    function renderCleaningList(fd) {
      const ev = fd.filter((d) => d.cleaned).slice().reverse();
      $("cleanTitle").textContent = `🧹 Riwayat Pembersihan (${ev.length}x${state.month !== "ALL" ? " · " + monthLabel(state.month) : ""})`;
      $("cleaningList").innerHTML = ev.length
        ? ev.map((d) => {
            const dirtyInfo = d.roof_dirty_before_clean != null
              ? `Dirty ${d.roof_dirty_before_clean}% → ${d.roof_dirty}%`
              : `Dirty ${d.roof_dirty}%`;
            return `<div class="clean-item"><div class="clean-date">🧹 ${d.date}</div>
              <div class="clean-meta">Waktu: ${d.cleaned_at || "-"}</div>
              <div class="clean-meta">Air: ${d.estimated_water_liters} L · ${dirtyInfo}</div></div>`;
          }).join("")
        : '<div class="clean-item"><div class="clean-meta">Tidak ada pembersihan pada periode ini.</div></div>';
    }

    function renderDaily() {
      const fd = filteredDaily();
      const labels = fd.map((d) => d.date.slice(5));
      const cleanedDays = fd.filter((d) => d.cleaned);

      $("dailyTitle").textContent = state.month === "ALL"
        ? `📅 Summary Harian — Semua Bulan (${fd.length} hari)`
        : `📅 Summary Harian — ${monthLabel(state.month)} (${fd.length} hari)`;

      const c = charts.combo;
      c.data.labels = labels;
      c.data.datasets[0].data = fd.map((d) => d.roof_dirty);
      c.data.datasets[1].data = fd.map((d) => d.light_transmission);
      c.data.datasets[2].data = fd.map((d) => (d.cleaned ? d.light_transmission : null));
      c.update("none");

      charts.score.data.labels = labels;
      charts.score.data.datasets[0].data = fd.map((d) => d.ai_score);
      charts.score.update("none");

      charts.water.data.labels = cleanedDays.map((d) => d.date.slice(5));
      charts.water.data.datasets[0].data = cleanedDays.map((d) => d.estimated_water_liters);
      charts.water.update("none");

      renderHeatmap();
      renderCleaningList(fd);
    }

    /* =========================================================
       Fetch & penjadwalan
       ========================================================= */
    function setLive(mode) {
      const b = $("liveBadge");
      b.className = "live " + mode;
      $("liveText").textContent = mode === "on" ? "Live" : mode === "paused" ? "Dijeda" : "Offline";
    }

    async function fetchRealtime(force = false) {
      try {
        const res = await fetch("/api/realtime" + (force ? "?force=1" : ""), { cache: "no-store" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const p = await res.json();
        state.online = true;
        state.rt = p.report;
        state.history = p.realtime_history || [];
        setLive(state.paused ? "paused" : "on");
        renderRealtime();
      } catch (err) {
        state.online = false;
        setLive("off");
      }
    }

    async function fetchDaily() {
      try {
        const res = await fetch("/api/daily", { cache: "no-store" });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const p = await res.json();
        state.daily = p.daily_summaries || [];
        state.months = p.available_months || [];
        populateMonths();
        renderDaily();
      } catch (err) {
        /* biarkan data lama; indikator Offline diurus oleh fetchRealtime */
      }
    }

    function scheduleRealtime() {
      clearTimeout(state.rtTimer);
      if (state.paused) return;
      state.rtTimer = setTimeout(async () => {
        if (!document.hidden) await fetchRealtime(false);
        scheduleRealtime();
      }, state.interval);
    }

    /* =========================================================
       Ekspor, tema, simulasi
       ========================================================= */
    function saveBlob(blob, name) {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }

    function toCsv(rows, cols) {
      const esc = (v) => {
        const s = v == null ? "" : String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
      };
      return [cols.join(",")].concat(rows.map((r) => cols.map((c) => esc(r[c])).join(","))).join("\n");
    }

    function exportMonthDailyCsv() {
      const cols = [
        "date",
        "month",
        "light_transmission",
        "roof_dirty",
        "ai_score",
        "ai_status",
        "estimated_water_liters",
        "cleaned",
        "cleaned_at",
      ];
      const tag = state.month === "ALL" ? "semua_bulan" : state.month;
      saveBlob(
        new Blob([toCsv(filteredDaily(), cols)], { type: "text/csv;charset=utf-8;" }),
        `harian_${tag}.csv`
      );
    }

    function applyTheme(theme) {
      document.documentElement.setAttribute("data-theme", theme);
      $("themeBtn").textContent = theme === "dark" ? "🌙 Gelap" : "☀️ Terang";
      try { localStorage.setItem("gh-theme", theme); } catch (e) { /* abaikan */ }
      if (!charts.rt) return;
      Chart.defaults.color = css("--text-muted");
      Chart.defaults.borderColor = css("--grid-line");
      Object.values(charts).forEach((c) => c.update("none"));
      renderRealtime();
      renderDaily();
    }

    async function simulate(kind) {
      try {
        await fetch("/api/simulate/" + kind, { method: "POST" });
      } catch (e) { /* abaikan */ }
      await fetchRealtime(true);
      await fetchDaily();
    }

    /* =========================================================
       Init
       ========================================================= */
    $("card-score").innerHTML = kpiCardHTML("score", "AI Score", "%");
    $("card-light").innerHTML = kpiCardHTML("light", "Light Transmission", "%");
    $("card-dirty").innerHTML = kpiCardHTML("dirty", "Roof Dirty", "%");

    let savedTheme = "dark";
    try { savedTheme = localStorage.getItem("gh-theme") || "dark"; } catch (e) { /* abaikan */ }
    document.documentElement.setAttribute("data-theme", savedTheme);
    $("themeBtn").textContent = savedTheme === "dark" ? "🌙 Gelap" : "☀️ Terang";

    initCharts();

    $("pauseBtn").addEventListener("click", () => {
      state.paused = !state.paused;
      $("pauseBtn").textContent = state.paused ? "▶ Lanjut" : "⏸ Jeda";
      if (state.paused) { clearTimeout(state.rtTimer); setLive("paused"); }
      else { setLive(state.online ? "on" : "off"); fetchRealtime(false); scheduleRealtime(); }
    });
    $("intervalSel").addEventListener("change", (e) => { state.interval = +e.target.value; scheduleRealtime(); });
    $("refreshBtn").addEventListener("click", () => { fetchRealtime(true); fetchDaily(); });
    $("resetZoomBtn").addEventListener("click", () => charts.rt.resetZoom());
    $("themeBtn").addEventListener("click", () =>
      applyTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark"));
    $("exportMonthlyBtn").addEventListener("click", exportMonthDailyCsv);
    $("monthFilter").addEventListener("change", (e) => { state.month = e.target.value; renderDaily(); });
    $("heatMetric").addEventListener("change", (e) => { state.heatMetric = e.target.value; renderHeatmap(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !state.paused) fetchRealtime(false); });

    fetchDaily().then(() => fetchRealtime(false)).then(scheduleRealtime);
    setInterval(() => { if (!document.hidden) fetchDaily(); }, CFG.dailyRefreshMs);
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return HTML_PAGE


@app.get("/api/realtime")
async def realtime(force: int = 0) -> JSONResponse:
    """Ringan: hanya laporan terbaru + riwayat realtime (dipanggil tiap beberapa detik)."""
    report = get_gh_report(force_refresh=bool(force))
    state = _load_state()
    return JSONResponse(
        {
            "report": report,
            "realtime_history": state.get("realtime_history") or [],
        }
    )


@app.get("/api/daily")
async def daily() -> JSONResponse:
    """Berat: summary harian semua bulan (dipanggil jarang; filter bulan dilakukan di browser)."""
    payload = get_dashboard_payload(force_refresh=False, month="ALL")
    return JSONResponse(
        {
            "available_months": payload["available_months"],
            "daily_summaries": payload["daily_summaries"],
            "cleaning_events": payload["cleaning_events"],
        }
    )


@app.post("/api/simulate/dirty")
async def simulate_dirty() -> JSONResponse:
    force_dirty_state()
    return JSONResponse({"ok": True})


@app.post("/api/simulate/clean")
async def simulate_clean() -> JSONResponse:
    mark_cleaning_completed()
    return JSONResponse({"ok": True})


@app.get("/api/telemetry")
async def telemetry(force: int = 0, month: str | None = None) -> JSONResponse:
    """Endpoint lama, dipertahankan agar kompatibel dengan klien lain."""
    payload = get_dashboard_payload(force_refresh=bool(force), month=month)
    return JSONResponse(payload)