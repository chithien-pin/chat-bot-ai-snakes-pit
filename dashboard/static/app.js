const charts = {};
const COLORS = [
  "#d70018", "#38bdf8", "#22c55e", "#f59e0b", "#a78bfa",
  "#fb7185", "#2dd4bf", "#f97316", "#818cf8", "#94a3b8",
];

function fmtNum(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("vi-VN");
}

function fmtTs(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString("vi-VN", { hour12: false });
  } catch {
    return ts;
  }
}

function statusBadge(status) {
  const s = status || "unknown";
  let cls = "neutral";
  if (s === "success") cls = "success";
  else if (s === "error" || s.startsWith("not_")) cls = "error";
  else if (s.startsWith("intent_") || s === "ask_province") cls = "warn";
  return `<span class="badge ${cls}">${s}</span>`;
}

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function doughnut(id, labels, values) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  if (!ctx || !labels.length) return;
  charts[id] = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: COLORS.slice(0, labels.length),
        borderWidth: 0,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: "bottom", labels: { color: "#8b9cb3", boxWidth: 12 } } },
    },
  });
}

function barChart(id, labels, datasets) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type: "bar",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#8b9cb3" } } },
      scales: {
        x: { ticks: { color: "#8b9cb3" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { ticks: { color: "#8b9cb3" }, grid: { color: "rgba(255,255,255,0.05)" }, beginAtZero: true },
      },
    },
  });
}

function lineChart(id, labels, datasets) {
  destroyChart(id);
  const ctx = document.getElementById(id);
  if (!ctx) return;
  charts[id] = new Chart(ctx, {
    type: "line",
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: "#8b9cb3" } } },
      scales: {
        x: { ticks: { color: "#8b9cb3", maxRotation: 45 }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: { ticks: { color: "#8b9cb3" }, grid: { color: "rgba(255,255,255,0.05)" }, beginAtZero: true },
      },
    },
  });
}

function renderKpis(ov) {
  const lat = ov.latency?.total || {};
  const fb = ov.feedback || {};
  const llm = ov.llm || {};
  const items = [
    { label: "Tin nhắn", value: fmtNum(ov.total_messages), sub: "chat_message events", cls: "info" },
    { label: "Success rate", value: `${ov.success_rate ?? 0}%`, sub: `${ov.status_counts?.success || 0} thành công`, cls: "ok" },
    { label: "Latency p95", value: `${fmtNum(lat.p95)} ms`, sub: `avg ${fmtNum(lat.avg)} ms`, cls: "" },
    { label: "Tokens in", value: fmtNum(llm.prompt_tokens), sub: `avg ${fmtNum(llm.avg_prompt_tokens)}/msg`, cls: "warn" },
    { label: "Tokens out", value: fmtNum(llm.completion_tokens), sub: `avg ${fmtNum(llm.avg_completion_tokens)}/msg`, cls: "ok" },
    { label: "Tokens total", value: fmtNum(llm.total_tokens), sub: `${fmtNum(llm.messages_with_tokens)} LLM calls`, cls: "warn" },
    { label: "Feedback 👍", value: fb.helpful_rate != null ? `${fb.helpful_rate}%` : "—", sub: `${fb.helpful || 0} / ${fb.total || 0}`, cls: "ok" },
    { label: "Shop stock", value: fmtNum(ov.shop_stock_queries), sub: "câu hỏi tồn CH", cls: "" },
    { label: "Compare", value: fmtNum(ov.compare_queries), sub: "so sánh SP", cls: "" },
    { label: "Ambiguous", value: fmtNum(ov.ambiguous_search), sub: "search mơ hồ", cls: "warn" },
  ];
  document.getElementById("kpis").innerHTML = items.map((k) => `
    <div class="kpi ${k.cls}">
      <div class="kpi-label">${k.label}</div>
      <div class="kpi-value">${k.value}</div>
      <div class="kpi-sub">${k.sub}</div>
    </div>
  `).join("");
}

function renderPipeline(funnel) {
  const el = document.getElementById("pipeline");
  if (!funnel?.length) {
    el.innerHTML = '<p class="empty">Chưa có dữ liệu pipeline</p>';
    return;
  }
  const max = funnel[0].count || 1;
  el.innerHTML = funnel.map((row) => {
    const pct = Math.round((row.count / max) * 100);
    return `
      <div class="pipeline-row">
        <span>${row.stage}</span>
        <div class="pipeline-bar"><div class="pipeline-fill" style="width:${pct}%"></div></div>
        <strong>${row.count}</strong>
      </div>`;
  }).join("");
}

function renderMessages(rows) {
  const tbody = document.getElementById("messages-table");
  if (!rows?.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="empty">Chưa có metrics.log — gửi tin nhắn qua bot để thu thập</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((r) => `
    <tr>
      <td>${fmtTs(r.ts)}</td>
      <td>${r.platform || "—"}</td>
      <td>${statusBadge(r.status)}</td>
      <td><code>${r.resolve_source || "—"}</code></td>
      <td>${(r.search_keywords || "—").slice(0, 40)}</td>
      <td>${fmtNum(r.total_latency_ms)}<br><small style="color:var(--muted)">kw ${fmtNum(r.latency_keyword_ms)} · fetch ${fmtNum(r.latency_fetch_ms)} · llm ${fmtNum(r.latency_gemini_ms)}</small></td>
      <td>${r.prompt_tokens != null ? fmtNum(r.prompt_tokens) : "—"}</td>
      <td>${r.completion_tokens != null ? fmtNum(r.completion_tokens) : "—"}</td>
      <td>${r.total_tokens ? `${fmtNum(r.total_tokens)}<br><small>${r.gemini_model || ""}</small>` : (r.gemini_model || "—")}</td>
      <td>${r.product_id || "—"}${r.error ? `<br><small style="color:var(--err)">${r.error}</small>` : ""}</td>
    </tr>
  `).join("");
}

function renderSessions(data) {
  const tbody = document.getElementById("sessions-table");
  const rows = data?.sessions || [];
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="empty">Không có session</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((s) => `
    <tr>
      <td><code>${(s.session_key || "").slice(0, 28)}</code></td>
      <td>${fmtTs(s.updated_at)}</td>
      <td>${s.turn_count}</td>
      <td>${(s.last_keywords || "—").slice(0, 30)}</td>
      <td>${(s.last_product || "—").slice(0, 40)}</td>
      <td>${s.pending_province_for || "—"}</td>
    </tr>
  `).join("");
}

function renderFeedback(rows) {
  const tbody = document.getElementById("feedback-table");
  if (!rows?.length) {
    tbody.innerHTML = '<tr><td colspan="3" class="empty">Chưa có feedback</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((r) => `
    <tr>
      <td>${fmtTs(r.ts)}</td>
      <td>${r.rating === "helpful" ? "👍" : "👎"}</td>
      <td>${r.platform || "—"}</td>
    </tr>
  `).join("");
}

function renderDataHealth(data) {
  const el = document.getElementById("data-health");
  const blocks = [
    { key: "menu_category_map", title: "Menu → Category map" },
    { key: "category_attributes_map", title: "Category attributes" },
  ];
  el.innerHTML = blocks.map(({ key, title }) => {
    const m = data[key] || {};
    if (!m.exists) {
      return `<div class="health-item"><strong>${title}</strong><p class="empty">File chưa có</p></div>`;
    }
    return `
      <div class="health-item">
        <strong>${title}</strong>
        <dl>
          <dt>File</dt><dd>${m.path}</dd>
          <dt>Size</dt><dd>${m.size_mb} MB</dd>
          <dt>Modified</dt><dd>${fmtTs(m.modified_at)}</dd>
          <dt>Synced at</dt><dd>${fmtTs(m.updated_at)}</dd>
          <dt>Categories</dt><dd>${fmtNum(m.category_count || m.menu_entries)}</dd>
          <dt>Progress</dt><dd>${fmtNum(m.processed_ids)} processed</dd>
        </dl>
      </div>`;
  }).join("");
}

async function loadDashboard() {
  const hours = document.getElementById("hours").value;
  const [overview, timeline, messages, feedback, sessions, health] = await Promise.all([
    fetch(`/api/overview?hours=${hours}`).then((r) => r.json()),
    fetch(`/api/timeline?hours=${hours}`).then((r) => r.json()),
    fetch(`/api/messages?hours=${hours}&limit=40`).then((r) => r.json()),
    fetch(`/api/feedback?hours=${hours}`).then((r) => r.json()),
    fetch("/api/sessions?limit=25").then((r) => r.json()),
    fetch("/api/data-health").then((r) => r.json()),
  ]);

  const ov = overview.overview || {};
  renderKpis(ov);
  renderPipeline(overview.pipeline_funnel);

  lineChart("chartTimeline", timeline.labels || [], [
    { label: "Total", data: timeline.total || [], borderColor: COLORS[0], tension: 0.3 },
    { label: "Success", data: timeline.success || [], borderColor: COLORS[2], tension: 0.3 },
    { label: "Error", data: timeline.error || [], borderColor: COLORS[3], tension: 0.3 },
  ]);

  const tok = timeline.tokens || {};
  if ((tok.labels || []).length) {
    lineChart("chartTokens", tok.labels, [
      { label: "In (prompt)", data: tok.prompt_tokens || [], borderColor: COLORS[0], tension: 0.3 },
      { label: "Out (completion)", data: tok.completion_tokens || [], borderColor: COLORS[2], tension: 0.3 },
    ]);
  }

  const sc = ov.status_counts || {};
  doughnut("chartStatus", Object.keys(sc), Object.values(sc));

  const rs = ov.resolve_source_counts || {};
  doughnut("chartResolve", Object.keys(rs), Object.values(rs));

  const lat = ov.latency || {};
  barChart("chartLatency", ["Keyword", "Fetch", "LLM", "Total"], [{
    label: "p95 (ms)",
    data: [
      lat.keyword?.p95, lat.fetch?.p95, lat.llm?.p95, lat.total?.p95,
    ],
    backgroundColor: COLORS.slice(0, 4),
  }]);

  const api = overview.api_calls || {};
  barChart("chartApi", Object.keys(api), [{
    label: "Calls",
    data: Object.values(api),
    backgroundColor: COLORS[1],
  }]);

  const scen = overview.scenario_enrichment || {};
  const scenLabels = Object.keys(scen);
  barChart("chartScenarios", scenLabels, [{
    label: "Count",
    data: scenLabels.map((k) => scen[k]),
    backgroundColor: COLORS[4],
  }]);

  renderMessages(messages.messages);
  renderFeedback(feedback.feedback);
  renderSessions(sessions);
  renderDataHealth(health);

  document.getElementById("last-updated").textContent =
    `Cập nhật: ${new Date().toLocaleTimeString("vi-VN")}`;
}

document.getElementById("refresh").addEventListener("click", loadDashboard);
document.getElementById("hours").addEventListener("change", loadDashboard);
loadDashboard().catch((err) => {
  console.error(err);
  alert("Không tải được dashboard — kiểm tra dashboard_api đang chạy.");
});
