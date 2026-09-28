// Jobs page live updates (CI-3, CI-5). Polls GET /admin/api/jobs and patches the
// existing rows in place; the page works without this script (a reload shows the
// current state). Nothing here inserts or removes rows.

import { t } from "./i18n.js";

// Job statuses (tellybox.jobs.JobStatus) as the page shows them.
const STATUS_LABELS = {
  queued: t("queued"),
  downloading: t("downloading"),
  processing: t("processing"),
  ready: t("ready"),
  failed: t("failed"),
};

const RUNNING = new Set(["queued", "downloading", "processing"]);
const FAST_MS = 2000;
const SLOW_MS = 10000;

function applyRow(row, job) {
  const status = row.querySelector('[data-field="status"]');
  if (status) {
    const badge = status.querySelector(".badge");
    if (badge) {
      badge.textContent = STATUS_LABELS[job.status] ?? job.status;
      badge.className = job.badge ? `badge ${job.badge}` : "badge";
    }
  }
  const bar = row.querySelector('[data-field="progress"] > .progress > span');
  if (bar) {
    const pct = job.progress == null ? 0 : Math.round(job.progress * 100);
    bar.style.width = `${pct}%`;
  }
  const attempts = row.querySelector('[data-field="attempts"]');
  if (attempts) attempts.textContent = `${job.attempts} / ${job.max_attempts}`;
  const error = row.querySelector('[data-field="error"]');
  if (error) error.textContent = job.error || "";
  const retry = row.querySelector('[data-field="retry"]');
  if (retry) retry.hidden = !job.retryable;
}

async function tick() {
  let list = [];
  try {
    const res = await fetch("/admin/api/jobs", { headers: { Accept: "application/json" } });
    if (res.ok) list = await res.json();
  } catch {
    // offline, or the worker/web service is restarting; try again next tick
  }
  for (const job of list) {
    const row = document.querySelector(`tr[data-job-id="${job.id}"]`);
    if (row) applyRow(row, job);
  }
  const busy = list.some((job) => RUNNING.has(job.status));
  setTimeout(tick, busy ? FAST_MS : SLOW_MS);
}

const table = document.querySelector('table.list[data-live="jobs"]');
if (table) tick();
