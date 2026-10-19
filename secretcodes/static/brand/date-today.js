/* Add a "Today" shortcut after any date input marked with `data-today-button`.
 * Clicking it fills in today's local date (not UTC, so late evenings stay on
 * the right day) and fires input/change so other scripts see the update.
 * An empty input also marked `data-default-today` starts out as today.
 * Without JS the field is a plain date input. */
(function () {
  function localToday() {
    var now = new Date();
    var month = String(now.getMonth() + 1).padStart(2, "0");
    var day = String(now.getDate()).padStart(2, "0");
    return now.getFullYear() + "-" + month + "-" + day;
  }

  function init() {
    var inputs = document.querySelectorAll("input[data-today-button]");
    Array.prototype.slice.call(inputs).forEach(function (input) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "btn btn-link btn-sm sc-today-button";
      button.textContent = "Today";
      button.addEventListener("click", function () {
        input.value = localToday();
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
      input.insertAdjacentElement("afterend", button);
      if (input.hasAttribute("data-default-today") && !input.value) {
        input.value = localToday();
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
