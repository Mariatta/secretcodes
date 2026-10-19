/* Row grids (`[data-bulk-form]`): the "Add several" expenses grid, and the
 * People page's "Add people" grid, which has no dates or copied fields.
 *
 * Empty dates start as today's local date (the server runs on UTC). "+ Add
 * row" clones the formset's empty row, numbers it, and copies the date,
 * currency, payer and ticked people from the row above, since a batch of
 * receipts usually shares them. Without JS the five starting rows still
 * work; dates just have to be picked by hand. */
(function () {
  function localToday() {
    var now = new Date();
    var month = String(now.getMonth() + 1).padStart(2, "0");
    var day = String(now.getDate()).padStart(2, "0");
    return now.getFullYear() + "-" + month + "-" + day;
  }

  function init(form) {
    var body = form.querySelector("[data-bulk-rows]");
    var template = form.querySelector("[data-bulk-template]");
    var total = form.querySelector('[name$="-TOTAL_FORMS"]');

    Array.prototype.slice.call(body.querySelectorAll('input[type="date"]')).forEach(function (input) {
      if (!input.value) {
        input.value = localToday();
      }
    });

    function copyFromPrevious(row, previous) {
      if (!previous) {
        return;
      }
      ["paid_at", "original_currency", "payer"].forEach(function (name) {
        var from = previous.querySelector('[name$="-' + name + '"]');
        var to = row.querySelector('[name$="-' + name + '"]');
        if (from && to && from.value) {
          to.value = from.value;
        }
      });
      var fromBoxes = previous.querySelectorAll('[name$="-shared_by"]');
      var toBoxes = row.querySelectorAll('[name$="-shared_by"]');
      Array.prototype.slice.call(toBoxes).forEach(function (box, index) {
        if (fromBoxes[index]) {
          box.checked = fromBoxes[index].checked;
        }
      });
    }

    form.querySelector("[data-add-row]").addEventListener("click", function () {
      var index = parseInt(total.value, 10);
      var html = template.innerHTML.replace(/__prefix__/g, String(index));
      var holder = document.createElement("tbody");
      holder.innerHTML = html;
      var row = holder.querySelector("[data-bulk-row]");
      var rows = body.querySelectorAll("[data-bulk-row]");
      copyFromPrevious(row, rows[rows.length - 1]);
      var date = row.querySelector('input[type="date"]');
      if (date && !date.value) {
        date.value = localToday();
      }
      body.appendChild(row);
      total.value = String(index + 1);
      var first = row.querySelector('[name$="-description"]') || row.querySelector("input");
      if (first) {
        first.focus();
      }
    });
  }

  function start() {
    Array.prototype.slice.call(document.querySelectorAll("[data-bulk-form]")).forEach(init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
