function qs(sel) {
  const el = document.querySelector(sel);
  if (!el) throw new Error(`Missing element: ${sel}`);
  return el;
}

const MAX_TABLE_ROWS = 50;
let lastChartSpec = null;
const DEV_MODE_KEY = "llm2sql.dev_mode";
const MODAL_OPEN_CLASS = "modal-open";

function getDevMode() {
  try {
    return localStorage.getItem(DEV_MODE_KEY) === "1";
  } catch {
    return false;
  }
}

function setDevMode(on, { persist } = { persist: true }) {
  document.documentElement.classList.toggle("dev-mode", Boolean(on));

  const btn = document.getElementById("devToggle");
  if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");

  if (on) {
    const sqlDetails = document.getElementById("sqlDetails");
    if (sqlDetails && sqlDetails instanceof HTMLDetailsElement) {
      sqlDetails.open = true;
    }
  }

  if (persist) {
    try {
      localStorage.setItem(DEV_MODE_KEY, on ? "1" : "0");
    } catch {
      // ignore
    }
  }
}

function toggleDevMode() {
  const next = !document.documentElement.classList.contains("dev-mode");
  setDevMode(next);
}

// Modal helpers
function openModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.remove("hidden");
  document.documentElement.classList.add(MODAL_OPEN_CLASS);
}

function closeModal(modalId) {
  const modal = document.getElementById(modalId);
  if (!modal) return;
  modal.classList.add("hidden");
  document.documentElement.classList.remove(MODAL_OPEN_CLASS);
}

function wireModal(modalId, triggerId) {
  const trigger = document.getElementById(triggerId);
  if (trigger) {
    trigger.addEventListener("click", () => openModal(modalId));
  }

  const modal = document.getElementById(modalId);
  if (!modal) return;

  modal.querySelectorAll("[data-close=\"modal\"]").forEach((el) => {
    el.addEventListener("click", () => closeModal(modalId));
  });

  modal.addEventListener("click", (e) => {
    const target = e.target;
    if (target instanceof HTMLElement && target.dataset.close === "modal") {
      closeModal(modalId);
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal(modalId);
    }
  });
}

function setPill(text, kind) {
  const pill = qs("#status");
  pill.textContent = text;
  pill.classList.remove("ok", "bad", "muted");
  if (kind) pill.classList.add(kind);
}

function showError(message) {
  const el = qs("#error");
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearError() {
  const el = qs("#error");
  el.textContent = "";
  el.classList.add("hidden");
}

function elFromHtml(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return String(value);
  if (Math.abs(value) >= 1000) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function formatAxisNumber(value) {
  if (!Number.isFinite(value)) return String(value);
  // Axis tick labels should be short and readable.
  return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appendMessage(role, text) {
  const thread = qs("#thread");
  const safeText = escapeHtml(text);
  const node = elFromHtml(`
    <div class="msg ${role}">
      <div class="bubble">${safeText}</div>
    </div>
  `);
  thread.appendChild(node);
  thread.scrollTop = thread.scrollHeight;
}

function isNumeric(v) {
  if (v === null || v === undefined) return false;
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string" && v.trim() !== "") return Number.isFinite(Number(v));
  return false;
}

function inferVisualization(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return { kind: "none" };

  const keys = [];
  const seen = new Set();
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        keys.push(k);
      }
    }
  }

  const numericKeys = keys.filter((k) => {
    let hasAny = false;
    for (const row of rows) {
      const v = row?.[k];
      if (v === null || v === undefined || v === "") continue;
      if (!isNumeric(v)) return false;
      hasAny = true;
    }
    return hasAny;
  });

  const pickValueKey = () => {
    if (numericKeys.length === 1) return numericKeys[0];
    const preferred = ["sales", "revenue", "amount", "total", "count"];
    for (const p of preferred) {
      const hit = numericKeys.find((k) => k.toLowerCase().includes(p));
      if (hit) return hit;
    }
    return numericKeys[0] ?? null;
  };

  const valueKey = pickValueKey();
  if (!valueKey) return { kind: "none" };

  const labelKeys = keys.filter((k) => k !== valueKey);

  // KPI: single row + single numeric column
  if (rows.length === 1 && labelKeys.length === 0) {
    const onlyRow = rows[0];
    const v = Number(onlyRow?.[valueKey]);
    return { kind: "kpi", label: valueKey, value: v };
  }

  // Chart: numeric + label(s)
  if (labelKeys.length === 0) return { kind: "table", valueKey };

  const labels = rows.map((r) =>
    labelKeys
      .map((k) => r?.[k])
      .filter((x) => x !== null && x !== undefined && String(x).trim() !== "")
      .map((x) => String(x))
      .join(", ")
  );
  const values = rows.map((r) => Number(r?.[valueKey] ?? 0));

  const labelKeySingle = labelKeys.length === 1 ? labelKeys[0].toLowerCase() : "";
  const looksTemporal =
    labelKeys.length === 1 &&
    (labelKeySingle.includes("date") ||
      labelKeySingle.includes("month") ||
      labels.every((x) => /^\d{4}-\d{2}(-\d{2})?$/.test(x) || /^\d{4}-q[1-4]$/i.test(x)));

  return {
    kind: "chart",
    chartType: looksTemporal ? "line" : "bar",
    labelKeys,
    valueKey,
    labels,
    values,
  };
}

function setupCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  canvas.width = Math.max(1, Math.floor(w * dpr));
  canvas.height = Math.max(1, Math.floor(h * dpr));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas is not supported in this browser.");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function truncateLabel(s, max = 14) {
  const str = String(s);
  if (str.length <= max) return str;
  return `${str.slice(0, max - 1)}…`;
}

function renderBarChart(canvas, labels, values) {
  const { ctx, w, h } = setupCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const right = 18;
  const top = 18;
  const rotate = labels.some((l) => String(l).length > 10) || labels.length > 7;
  const angle = rotate ? Math.PI / 4 : 0;
  const fontSize = 12;
  const labelOffset = rotate ? 10 : 24;

  // Measure max label width to allocate enough bottom margin so labels don't clip.
  ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
  const texts = labels.map((l) => truncateLabel(l, rotate ? 16 : 12));
  const maxLabelW =
    texts.length > 0 ? Math.max(...texts.map((t) => ctx.measureText(String(t)).width)) : 0;

  const labelDown = rotate
    ? maxLabelW * Math.sin(angle) + fontSize * Math.cos(angle)
    : fontSize;

  const minPlotH = 160;
  const maxBottom = Math.max(54, h - top - minPlotH);
  const bottom = Math.min(maxBottom, Math.max(54, Math.ceil(labelOffset + labelDown + 10)));

  // Measure y-axis tick widths to allocate enough left margin so they don't overlap bars.
  const steps = 4;
  const maxVal = Math.max(...values, 0);
  const tickTexts = Array.from({ length: steps + 1 }, (_, i) =>
    formatAxisNumber(maxVal * (i / steps))
  );
  const maxTickW =
    tickTexts.length > 0 ? Math.max(...tickTexts.map((t) => ctx.measureText(t).width)) : 0;
  const left = Math.min(120, Math.max(52, Math.ceil(maxTickW + 22)));

  const plotW = w - left - right;
  const plotH = h - top - bottom;

  // grid
  ctx.strokeStyle = "rgba(226, 232, 240, 1)";
  ctx.fillStyle = "rgba(71, 85, 105, 0.9)";
  ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const y = top + plotH - t * plotH;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotW, y);
    ctx.stroke();
    ctx.fillText(tickTexts[i] ?? formatAxisNumber(maxVal * t), left - 10, y);
  }

  // bars
  const n = Math.max(1, labels.length);
  const step = plotW / n;
  const barW = Math.max(8, Math.min(44, step * 0.66));
  const grad = ctx.createLinearGradient(0, top, 0, top + plotH);
  grad.addColorStop(0, "rgba(15, 23, 42, 0.92)");
  grad.addColorStop(1, "rgba(15, 23, 42, 0.55)");

  ctx.fillStyle = grad;
  for (let i = 0; i < labels.length; i++) {
    const v = values[i] ?? 0;
    const frac = maxVal > 0 ? v / maxVal : 0;
    const barH = Math.max(0, frac * plotH);
    const x = left + i * step + (step - barW) / 2;
    const y = top + plotH - barH;
    ctx.fillRect(x, y, barW, barH);
  }

  // x labels
  ctx.fillStyle = "rgba(71, 85, 105, 0.95)";
  ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
  const axisY = top + plotH;
  for (let i = 0; i < labels.length; i++) {
    const x = left + i * step + step / 2;
    const y = axisY + labelOffset;
    const t = texts[i] ?? truncateLabel(labels[i], rotate ? 16 : 12);
    ctx.save();
    ctx.translate(x, y);
    if (rotate) ctx.rotate(-angle);
    ctx.textAlign = rotate ? "right" : "center";
    ctx.textBaseline = rotate ? "top" : "middle";
    ctx.fillText(t, 0, 0);
    ctx.restore();
  }
}

function renderLineChart(canvas, labels, values) {
  const { ctx, w, h } = setupCanvas(canvas);
  ctx.clearRect(0, 0, w, h);

  const right = 18;
  const top = 18;
  const bottom = 42;

  // sort by label to keep temporal order stable
  const pts = labels
    .map((l, i) => ({ l, v: values[i] ?? 0 }))
    .sort((a, b) => String(a.l).localeCompare(String(b.l)));

  const maxVal = Math.max(...pts.map((p) => p.v), 0);

  // grid
  ctx.strokeStyle = "rgba(226, 232, 240, 1)";
  ctx.fillStyle = "rgba(71, 85, 105, 0.9)";
  ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";

  const steps = 4;
  const tickTexts = Array.from({ length: steps + 1 }, (_, i) =>
    formatAxisNumber(maxVal * (i / steps))
  );
  const maxTickW =
    tickTexts.length > 0 ? Math.max(...tickTexts.map((t) => ctx.measureText(t).width)) : 0;
  const left = Math.min(120, Math.max(52, Math.ceil(maxTickW + 22)));

  const plotW = w - left - right;
  const plotH = h - top - bottom;

  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const y = top + plotH - t * plotH;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotW, y);
    ctx.stroke();
    ctx.fillText(tickTexts[i] ?? formatAxisNumber(maxVal * t), left - 10, y);
  }

  const n = pts.length;
  const xStep = n > 1 ? plotW / (n - 1) : 0;

  const xy = pts.map((p, i) => {
    const x = left + i * xStep;
    const frac = maxVal > 0 ? p.v / maxVal : 0;
    const y = top + plotH - frac * plotH;
    return { ...p, x, y };
  });

  // line
  ctx.strokeStyle = "rgba(15, 23, 42, 0.9)";
  ctx.lineWidth = 2;
  ctx.beginPath();
  xy.forEach((p, i) => {
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  });
  ctx.stroke();

  // points
  ctx.fillStyle = "rgba(15, 23, 42, 0.9)";
  for (const p of xy) {
    ctx.beginPath();
    ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
    ctx.fill();
  }

  // x labels (every 2 for density)
  ctx.fillStyle = "rgba(71, 85, 105, 0.95)";
  ctx.font = "12px ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  xy.forEach((p, i) => {
    if (n > 10 && i % 2 === 1) return;
    const t = truncateLabel(p.l, 10);
    ctx.fillText(t, p.x, top + plotH + 22);
  });
}

function renderTable(rows, limit = MAX_TABLE_ROWS) {
  const wrap = qs("#tableWrap");
  if (!rows || rows.length === 0) {
    wrap.classList.add("muted");
    wrap.textContent = "No rows returned.";
    return;
  }

  const slice = rows.slice(0, limit);

  const cols = [];
  const seen = new Set();
  for (const row of slice) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
    }
  }

  const thead = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const tbody = slice
    .map((r) => {
      const tds = cols
        .map((c) => {
          const v = Object.prototype.hasOwnProperty.call(r, c) ? r[c] : null;
          const out = typeof v === "number" ? formatNumber(v) : v ?? "";
          return `<td>${escapeHtml(out)}</td>`;
        })
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");

  wrap.classList.remove("muted");
  wrap.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

function displaySource(src) {
  if (!src) return "—";
  if (src === "preset") return "verified";
  return src;
}

function renderVisual(res) {
  const visual = qs("#visual");
  visual.classList.remove("hidden");

  const src = displaySource(res?.source);
  const publicMsg = qs("#publicMessage");
  const devMsg = document.getElementById("devMessage");

  if (src === "verified") {
    // Public UX: don't show internal implementation detail for preset hits.
    publicMsg.textContent = res?.question ? `Showing results for: ${res.question}` : "Showing results.";

    // Dev UX: show the backend message (e.g. "no LLM call") only when Dev is enabled.
    if (devMsg) {
      const msg = String(res?.message ?? "").trim();
      devMsg.textContent = msg;
      devMsg.classList.toggle("hidden", msg.length === 0);
    }
  } else {
    publicMsg.textContent = res?.message ?? "";
    if (devMsg) {
      devMsg.textContent = "";
      devMsg.classList.add("hidden");
    }
  }

  qs("#metaSource").textContent = src;
  qs("#metaPreset").textContent = res?.preset_id ?? "—";
  qs("#metaRows").textContent = String(res?.row_count ?? "—");

  const sql = res?.sql ?? null;
  const sqlDetails = qs("#sqlDetails");
  if (sql) {
    qs("#executedSql").textContent = sql;
    sqlDetails.classList.remove("hidden");
  } else {
    qs("#executedSql").textContent = "";
    sqlDetails.classList.add("hidden");
  }

  qs("#debugJson").textContent = JSON.stringify(res ?? {}, null, 2);

  const rows = Array.isArray(res?.rows) ? res.rows : [];
  const viz = inferVisualization(rows);
  lastChartSpec = null;

  // reset sections
  qs("#kpi").classList.add("hidden");
  qs("#chartSection").classList.add("hidden");
  qs("#tableSection").classList.add("hidden");
  qs("#chartCaption").textContent = "";
  qs("#tableCaption").textContent = "";

  if (viz.kind === "kpi") {
    qs("#kpiLabel").textContent = viz.label;
    qs("#kpiValue").textContent = formatNumber(viz.value);
    qs("#kpi").classList.remove("hidden");
    return;
  }

  if (viz.kind === "chart") {
    const caption = `${viz.labelKeys.join(", ")} → ${viz.valueKey}`;
    qs("#chartCaption").textContent = caption;
    qs("#chartSection").classList.remove("hidden");
    const canvas = qs("#chartCanvas");
    lastChartSpec = { type: viz.chartType, labels: viz.labels, values: viz.values };
    if (viz.chartType === "line") renderLineChart(canvas, viz.labels, viz.values);
    else renderBarChart(canvas, viz.labels, viz.values);
  }

  if (rows.length > 0) {
    const shown = Math.min(rows.length, MAX_TABLE_ROWS);
    const total = rows.length;
    qs("#tableCaption").textContent = total > shown ? `Showing ${shown} of ${total}` : `${total} row(s)`;
    qs("#tableSection").classList.remove("hidden");
    renderTable(rows, MAX_TABLE_ROWS);
  }
}

function rerenderChartIfNeeded() {
  if (!lastChartSpec) return;
  const canvas = qs("#chartCanvas");
  if (lastChartSpec.type === "line") renderLineChart(canvas, lastChartSpec.labels, lastChartSpec.values);
  else renderBarChart(canvas, lastChartSpec.labels, lastChartSpec.values);
}

async function postAsk(question) {
  const resp = await fetch("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });

  const json = await resp.json().catch(() => null);
  if (!resp.ok) {
    const detail = json && typeof json === "object" && json.detail ? String(json.detail) : `HTTP ${resp.status}`;
    throw new Error(detail);
  }
  return json;
}

async function onSubmit(e) {
  e.preventDefault();
  clearError();

  const questionEl = qs("#question");
  const askBtn = qs("#askBtn");
  const clearBtn = document.getElementById("clearBtn");
  const resultCard = qs("#resultCard");

  const question = questionEl.value.trim();
  if (!question) return;

  resultCard.classList.remove("hidden");
  qs("#visual").classList.remove("hidden");
  appendMessage("user", question);

  // questionEl.value = ""; # don't clear the question
  askBtn.disabled = true;
  const prevAskText = askBtn.textContent;
  askBtn.textContent = "Running…";
  askBtn.classList.add("loading");
  askBtn.setAttribute("aria-busy", "true");
  if (clearBtn) clearBtn.disabled = true;

  const statusEl = qs("#status");
  const prevText = statusEl.textContent;
  statusEl.textContent = "Running query…";
  statusEl.classList.add("loading");

  try {
    const res = await postAsk(question);
    const msg = res.message ?? "Received.";
    renderVisual(res);
    appendMessage("assistant", msg);
    setPill("OK", "ok");
  } catch (err) {
    setPill("Error", "bad");
    showError(err instanceof Error ? err.message : String(err));
  } finally {
    askBtn.disabled = false;
    askBtn.classList.remove("loading");
    askBtn.removeAttribute("aria-busy");
    askBtn.textContent = prevAskText || "Run";
    if (clearBtn) clearBtn.disabled = false;
    statusEl.classList.remove("loading");
    statusEl.textContent = prevText || "Idle";
    questionEl.focus();
  }
}

function wireChips() {
  document.querySelectorAll(".chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const q = btn.getAttribute("data-q") || "";
      const el = qs("#question");
      el.value = q;
      el.focus();
    });
  });
}

function wireEnterToSend() {
  const el = qs("#question");
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      qs("#askForm").requestSubmit();
    }
  });
}

function wireClear() {
  const clearBtn = document.getElementById("clearBtn");
  if (!clearBtn) return;
  clearBtn.addEventListener("click", () => {
    const el = qs("#question");
    el.value = "";
    el.focus();
    clearError();
  });
}

function init() {
  qs("#askForm").addEventListener("submit", onSubmit);
  wireChips();
  wireEnterToSend();
  wireClear();
  setPill("Idle", "muted");
  setDevMode(getDevMode(), { persist: false });

  const devBtn = document.getElementById("devToggle");
  if (devBtn) {
    devBtn.addEventListener("click", () => toggleDevMode());
  }

  wireModal("dataModal", "dataInfoBtn");

  window.addEventListener("resize", () => {
    // keep charts crisp when container width changes
    rerenderChartIfNeeded();
  });
}

document.addEventListener("DOMContentLoaded", init);
