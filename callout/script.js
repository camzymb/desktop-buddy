// Daily Summary Callout — page behavior.
//
// Fills in today's date and loads today's real Google Calendar events from the
// local server's /api/today endpoint, replacing the sample event rows. The
// checkboxes toggle natively (real <input> elements styled with CSS).
//
// When the page is opened without callout_server.py (e.g. a plain static
// server), the events fetch quietly fails and the sample rows are left in
// place, so the standalone preview still looks complete.

const EVENTS_API = "/api/today";

/** Write today's date into the header, e.g. "Thursday, May 28". */
function showTodayDate() {
  const dateElement = document.getElementById("today-date");
  if (!dateElement) {
    return;
  }
  const today = new Date();
  dateElement.textContent = today.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

/** Fetch today's events and render them; leave the sample rows on any failure. */
async function loadTodaysEvents() {
  const list = document.getElementById("event-list");
  if (!list) {
    return;
  }

  // Make the fallback sample rows clickable too, in case the fetch fails.
  for (const row of list.querySelectorAll(".event")) {
    makeRowToggleable(row, false);
  }

  let payload;
  try {
    const response = await fetch(EVENTS_API);
    if (!response.ok) {
      return; // Not served by callout_server — keep the sample rows.
    }
    payload = await response.json();
  } catch {
    return; // Offline or no API — keep the sample rows.
  }

  if (payload.error) {
    renderMessage(list, payload.error);
  } else if (!payload.events.length) {
    renderMessage(list, "Nothing on your calendar today. 🤍");
  } else {
    renderEvents(list, payload.events);
  }
}

/** Replace the list with one row per event. */
function renderEvents(list, events) {
  list.replaceChildren(...events.map(buildEventRow));
}

/** Build a single event row: soft icon + title + time. */
function buildEventRow(event) {
  const row = document.createElement("li");
  row.className = "event";

  const icon = document.createElement("span");
  icon.className = "event-icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "🌸";

  const name = document.createElement("span");
  name.className = "event-name";
  name.textContent = event.title;

  const time = document.createElement("span");
  time.className = "event-time";
  time.textContent = event.all_day ? "All day" : event.start;

  row.append(icon, name, time);
  // Events that have already ended start in the "done" state; clicking toggles.
  makeRowToggleable(row, event.past);
  return row;
}

/** Let an event row be marked "done" (strike-through + fade) by click or keyboard. */
function makeRowToggleable(row, done) {
  row.classList.toggle("done", done);
  row.setAttribute("role", "button");
  row.setAttribute("tabindex", "0");
  row.setAttribute("aria-pressed", String(done));

  const toggle = () => {
    const isDone = row.classList.toggle("done");
    row.setAttribute("aria-pressed", String(isDone));
  };

  row.addEventListener("click", toggle);
  row.addEventListener("keydown", (keyEvent) => {
    if (keyEvent.key === "Enter" || keyEvent.key === " ") {
      keyEvent.preventDefault();
      toggle();
    }
  });
}

/** Replace the list with a single friendly message row. */
function renderMessage(list, message) {
  const row = document.createElement("li");
  row.className = "event event-message";
  row.textContent = message;
  list.replaceChildren(row);
}

document.addEventListener("DOMContentLoaded", () => {
  showTodayDate();
  loadTodaysEvents();
});
