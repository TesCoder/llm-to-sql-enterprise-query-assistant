function qs(sel) {
  const el = document.querySelector(sel);
  if (!el) throw new Error(`Missing element: ${sel}`);
  return el;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setStatus(text, kind) {
  const el = qs("#status");
  el.textContent = text;
  el.classList.remove("ok", "bad");
  if (kind) el.classList.add(kind);
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

function renderTable(rows) {
  const wrap = qs("#tableWrap");
  if (!rows || rows.length === 0) {
    wrap.classList.add("muted");
    wrap.textContent = "Query returned 0 rows.";
    return;
  }

  // Build a stable column list (union of keys, in first-row order where possible)
  const cols = [];
  const seen = new Set();
  for (const row of rows) {
    for (const k of Object.keys(row)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
    }
  }

  const thead = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const tbody = rows
    .map((r) => {
      const tds = cols
        .map((c) => {
          const v = Object.prototype.hasOwnProperty.call(r, c) ? r[c] : null;
          return `<td>${escapeHtml(v ?? "")}</td>`;
        })
        .join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");

  wrap.classList.remove("muted");
  wrap.innerHTML = `<table><thead><tr>${thead}</tr></thead><tbody>${tbody}</tbody></table>`;
}

async function runQuery() {
  clearError();
  setStatus("Running…", null);
  qs("#run").disabled = true;

  const sql = qs("#sql").value.trim();
  if (!sql) {
    setStatus("Idle", null);
    qs("#run").disabled = false;
    showError("Please enter a SELECT query.");
    return;
  }

  try {
    const resp = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sql }),
    });

    const json = await resp.json().catch(() => null);
    if (!resp.ok) {
      const detail =
        json && typeof json === "object" && json.detail ? String(json.detail) : `HTTP ${resp.status}`;
      throw new Error(detail);
    }

    qs("#executedSql").textContent = json.sql ?? "—";
    qs("#rowCount").textContent = String(json.row_count ?? "—");
    renderTable(json.rows ?? []);
    setStatus("OK", "ok");
  } catch (err) {
    setStatus("Error", "bad");
    showError(err instanceof Error ? err.message : String(err));
  } finally {
    qs("#run").disabled = false;
  }
}

function init() {
  const sample = qs("#sample");
  const sql = qs("#sql");
  const run = qs("#run");

  sample.addEventListener("change", () => {
    if (sample.value) {
      sql.value = sample.value;
      sample.value = "";
      sql.focus();
    }
  });

  run.addEventListener("click", () => runQuery());

  sql.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      runQuery();
    }
  });

  setStatus("Idle", null);
}

document.addEventListener("DOMContentLoaded", init);

