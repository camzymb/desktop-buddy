// Daily Summary Callout — page behavior.
//
// The checkboxes toggle natively (real <input> elements styled with CSS), so
// the only script here fills in today's date. Kept tiny on purpose; richer
// data wiring happens later when this is connected to the buddy.

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

document.addEventListener("DOMContentLoaded", showTodayDate);
