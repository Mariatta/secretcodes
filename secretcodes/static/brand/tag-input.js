/* Initialize Tagify (vendored locally — no CDN, no cookies) on any text input
 * marked with `data-tag-input`. Tags are written back to the original input as
 * a normalized "#a #b" string, so the form still submits a plain value and the
 * field degrades to a normal text input when JS is unavailable. */
(function () {
  function init() {
    if (typeof Tagify === "undefined") return;
    var inputs = document.querySelectorAll("[data-tag-input]");
    Array.prototype.slice.call(inputs).forEach(function (input) {
      new Tagify(input, {
        delimiters: ",| ",
        placeholder: input.getAttribute("data-placeholder") || "",
        originalInputValueFormat: function (values) {
          return values
            .map(function (v) { return "#" + String(v.value).replace(/^#+/, ""); })
            .join(" ");
        },
      });
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
