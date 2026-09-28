// Live frame preview for artwork/thumbnail frame picking (LM-2, library.html / show.html).
//
// Every `[data-frame-picker]` form also works as a plain GET (it reloads the page with
// ?art_t=/?thumb_t=), so this script only saves a round trip once a preview is already
// showing; nothing here is required for the page to work.

function parseTime(value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":").map(Number);
  if (parts.length > 3 || parts.some((n) => Number.isNaN(n))) return null;
  return parts.reduce((acc, n) => acc * 60 + n, 0);
}

function wireFramePicker(form) {
  const timeInput = form.querySelector("[data-frame-time]");
  const episodeInput = form.querySelector("[data-frame-episode]");
  const preview = form.parentElement.querySelector("[data-frame-preview]");
  if (!timeInput || !preview || !preview.dataset.frameUrlTemplate) return;

  function update() {
    const seconds = parseTime(timeInput.value);
    if (seconds === null) return;
    const episodeId = episodeInput ? episodeInput.value : "";
    const url = preview.dataset.frameUrlTemplate.replace("{ep}", episodeId).replace("{t}", String(seconds));
    preview.src = url;
  }

  timeInput.addEventListener("change", update);
  if (episodeInput) episodeInput.addEventListener("change", update);
}

document.querySelectorAll("[data-frame-picker]").forEach(wireFramePicker);
