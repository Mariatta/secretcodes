/* Live split preview for the expense form (`[data-expense-form]`).
 *
 * Shows the fields for the chosen split mode and fills in what each ticked
 * person owes. The itemized formula mirrors expenses/services/splitting.py
 * (itemized_amounts): items + shared part, + surcharge % of that, + table
 * charge part, + tax %, + tip % on the total after tax. The server
 * recalculates on save, so this is only a preview. Without JS every field
 * shows and the form still submits. */
(function () {
  function num(input) {
    var value = parseFloat(input && input.value);
    return isNaN(value) ? 0 : value;
  }

  function init(form) {
    var field = function (name) {
      return form.querySelector('[name="' + name + '"]');
    };
    var rows = Array.prototype.slice.call(form.querySelectorAll("[data-participant]"));
    var total = form.querySelector("[data-split-total]");

    function mode() {
      var checked = form.querySelector('[name="split_mode"]:checked');
      return checked ? checked.value : "equal";
    }

    function update() {
      var current = mode();
      Array.prototype.slice.call(form.querySelectorAll("[data-split-show]")).forEach(function (el) {
        el.hidden = el.getAttribute("data-split-show") !== current;
      });

      var currency = (field("original_currency").value || "").toUpperCase();
      var included = rows.filter(function (row) {
        return row.querySelector('[name="shared_by"]').checked;
      });
      var count = included.length;
      var owes = new Map();

      if (count && current === "itemized") {
        var sharedEach = num(field("shared_amount")) / count;
        var tableEach = num(field("table_charge")) / count;
        var surcharge = num(field("surcharge_percent")) / 100;
        var tax = num(field("tax_percent")) / 100;
        var tip = num(field("tip_percent")) / 100;
        included.forEach(function (row) {
          var item = num(row.querySelector('[data-split-show="itemized"] input'));
          var food = item + sharedEach;
          var preTax = food + food * surcharge + tableEach;
          var afterTax = preTax + preTax * tax;
          owes.set(row, afterTax + afterTax * tip);
        });
      } else if (count) {
        var each = num(field("original_amount")) / count;
        included.forEach(function (row) {
          owes.set(row, each);
        });
      }

      var sum = 0;
      rows.forEach(function (row) {
        var cell = row.querySelector("[data-owes]");
        if (owes.has(row)) {
          sum += owes.get(row);
          cell.textContent = owes.get(row).toFixed(2) + " " + currency;
        } else {
          cell.textContent = "–";
        }
      });
      total.textContent = count ? sum.toFixed(2) + " " + currency : "–";
    }

    form.addEventListener("input", update);
    form.addEventListener("change", update);
    update();
  }

  function start() {
    Array.prototype.slice.call(document.querySelectorAll("[data-expense-form]")).forEach(init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }
})();
