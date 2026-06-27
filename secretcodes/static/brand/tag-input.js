/* Self-contained tag/chip input — no dependencies, no network, no cookies.
 *
 * Progressive enhancement: any text input with `data-tag-input` is turned into
 * a chip box. The original input is hidden and kept in sync with a normalized
 * "#a #b" value, so the form still submits a plain string (and works without
 * JS — you just type space/comma-separated text). */
(function () {
  function parse(value) {
    return (value || "")
      .split(/[\s,]+/)
      .map(function (t) { return t.replace(/^#+/, "").trim(); })
      .filter(Boolean);
  }

  function initTagInput(input) {
    var tags = parse(input.value);
    input.type = "hidden";

    var box = document.createElement("div");
    box.className = "sc-taginput form-control";
    var field = document.createElement("input");
    field.type = "text";
    field.className = "sc-taginput-field";
    field.setAttribute("aria-label", "Add a hashtag");
    field.placeholder = input.getAttribute("data-placeholder") || "";
    input.parentNode.insertBefore(box, input.nextSibling);

    function sync() {
      input.value = tags.map(function (t) { return "#" + t; }).join(" ");
    }

    function render() {
      Array.prototype.slice.call(box.querySelectorAll(".sc-tag")).forEach(
        function (c) { c.remove(); }
      );
      tags.forEach(function (tag, i) {
        var chip = document.createElement("span");
        chip.className = "sc-tag";
        chip.textContent = "#" + tag;
        var x = document.createElement("button");
        x.type = "button";
        x.className = "sc-tag-x";
        x.setAttribute("aria-label", "Remove " + tag);
        x.textContent = "×";
        x.addEventListener("click", function () {
          tags.splice(i, 1);
          render();
          field.focus();
        });
        chip.appendChild(x);
        box.insertBefore(chip, field);
      });
      sync();
    }

    function commit() {
      parse(field.value).forEach(function (tag) {
        var exists = tags.some(function (t) {
          return t.toLowerCase() === tag.toLowerCase();
        });
        if (!exists) tags.push(tag);
      });
      field.value = "";
      render();
    }

    field.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === "," || e.key === " ") {
        e.preventDefault();
        commit();
      } else if (e.key === "Backspace" && !field.value && tags.length) {
        tags.pop();
        render();
      }
    });
    field.addEventListener("blur", commit);
    box.addEventListener("click", function () { field.focus(); });

    box.appendChild(field);
    render();
  }

  document.addEventListener("DOMContentLoaded", function () {
    Array.prototype.slice
      .call(document.querySelectorAll("[data-tag-input]"))
      .forEach(initTagInput);
  });
})();
