// Add page (CI-1, CI-7). Everything works without JS; this only adds conveniences.
//
// 1. A preview fetch can take 10-60 s, so disable the buttons and show a "Fetching…" note
//    against a double submit. Buttons are disabled on the next tick so the clicked button's
//    name/value (the "mode" of a video-or-playlist choice) is still sent.
// 2. Playlist preview: keep "Add N videos" in sync with the ticks, and offer select all / none.

import { tn } from "./i18n.js";

for (const form of document.querySelectorAll("form.fetch-form")) {
  form.addEventListener("submit", () => {
    setTimeout(() => {
      for (const button of form.querySelectorAll("button")) button.disabled = true;
    });
    const note = form.querySelector(".fetching");
    if (note) note.hidden = false;
  });
}

const playlist = document.getElementById("playlist-form");
if (playlist) {
  const boxes = [...playlist.querySelectorAll('input[name="video"]:not(:disabled)')];
  const submit = document.getElementById("playlist-submit");
  const update = () => {
    const n = boxes.filter((b) => b.checked).length;
    submit.textContent = tn("Add %(num)d video", "Add %(num)d videos", n);
    submit.disabled = n === 0;
  };
  playlist.addEventListener("change", update);
  const tools = playlist.querySelector(".select-tools");
  if (tools && boxes.length > 1) {
    tools.hidden = false;
    tools.addEventListener("click", (event) => {
      const which = event.target.closest("[data-select]");
      if (!which) return;
      for (const b of boxes) b.checked = which.dataset.select === "all";
      update();
    });
  }
  playlist.addEventListener("submit", () => {
    setTimeout(() => { submit.disabled = true; });
  });
  update();
}
