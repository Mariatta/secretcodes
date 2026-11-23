/* Timezone type-in field on the availability page.
 *
 * The server renders the page in the timezone named by the `tz` query
 * parameter. This script fills that parameter in from the browser on a first
 * visit, turns the plain text input into a type-ahead (Tagify, vendored
 * locally), and offers a way back to the browser's own timezone. Without JS
 * the input still works: type a zone or a city and press Show. */
(function () {
  var MAX_SUGGESTIONS = 8;

  function deviceTimezone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (e) {
      return "";
    }
  }

  function urlFor(tz) {
    var params = new URLSearchParams(window.location.search);
    params.set("tz", tz);
    return window.location.pathname + "?" + params.toString();
  }

  function zoneChoices(aliases, suggested) {
    /* Every zone the browser knows, with the suggested ones first: they are
       what the list shows before anything is typed. */
    var known = [];
    try {
      known = Intl.supportedValuesOf("timeZone").slice();
    } catch (e) {
      return [];
    }
    var names = [];
    suggested.concat(known, Object.keys(aliases)).forEach(function (name) {
      if (name && names.indexOf(name) === -1) names.push(name);
    });
    return names.map(function (name) {
      var cities = aliases[name] || [];
      return {
        value: name,
        label: cities.length ? name + " (" + cities.join(", ") + ")" : name,
        searchBy: name.replace(/[_\/]/g, " ") + " " + cities.join(" "),
      };
    });
  }

  var matchCount = 0;

  function citiesFirst(matches, query) {
    /* "lis" should offer Lisbon before Indianapolis: put zones where a word
       starts with the typed text ahead of ones that only contain it. */
    matchCount = matches.length;
    var wanted = " " + String(query || "").toLowerCase();
    function rank(item) {
      return (" " + String(item.searchBy).toLowerCase()).indexOf(wanted) === -1 ? 1 : 0;
    }
    return matches
      .map(function (item, index) { return { item: item, index: index }; })
      .sort(function (a, b) { return rank(a.item) - rank(b.item) || a.index - b.index; })
      .slice(0, MAX_SUGGESTIONS)
      .map(function (entry) { return entry.item; });
  }

  function listHeader() {
    /* Says the list is searchable: it is a type-in field, not a fixed menu. */
    return (
      "<header data-selector='tagify-suggestions-header' class='" +
      this.settings.classNames.dropdownHeader +
      "'>Type a city or timezone to search</header>"
    );
  }

  function listFooter(shown) {
    /* Says how many zones are not shown, so the list never looks complete. */
    var typed = this.state.dropdown.query;
    var total = typed ? matchCount : this.settings.whitelist.length;
    var more = total - shown.length;
    if (more <= 0) return "";
    return (
      "<footer data-selector='tagify-suggestions-footer' class='" +
      this.settings.classNames.dropdownFooter +
      "'>" + more + " more. " +
      (typed ? "Keep typing to narrow it down." : "Start typing to find yours.") +
      "</footer>"
    );
  }

  function describeDevice(note, displayTz, deviceTz) {
    if (!note || !deviceTz) return;
    if (deviceTz === displayTz) {
      note.textContent = "Detected from your device. Type to see a different timezone.";
      return;
    }
    var back = document.createElement("a");
    back.href = urlFor(deviceTz);
    back.textContent = "Back to my timezone (" + deviceTz + ")";
    note.appendChild(back);
  }

  function init() {
    var form = document.querySelector("[data-tz-picker]");
    if (!form) return;
    var displayTz = form.getAttribute("data-display-tz");
    var deviceTz = deviceTimezone();
    var hasChoice = new URLSearchParams(window.location.search).has("tz");

    if (deviceTz && !hasChoice && deviceTz !== displayTz) {
      window.location.replace(urlFor(deviceTz));
      return;
    }
    describeDevice(form.querySelector("[data-tz-device-note]"), displayTz, deviceTz);

    var input = form.querySelector("input[name='tz']");
    var aliasData = document.getElementById("tz-city-aliases");
    var aliases = aliasData ? JSON.parse(aliasData.textContent) : {};
    var hostTz = form.getAttribute("data-host-tz");
    var choices = zoneChoices(aliases, [deviceTz, displayTz, hostTz, "UTC"]);
    if (typeof Tagify === "undefined" || !choices.length) return;

    var tagify = new Tagify(input, {
      mode: "select",
      enforceWhitelist: true,
      whitelist: choices,
      dropdown: {
        enabled: 0,
        maxItems: MAX_SUGGESTIONS,
        highlightFirst: true,
        closeOnSelect: true,
        searchKeys: ["value", "searchBy"],
        mapValueTo: "label",
        sortby: citiesFirst,
      },
      templates: { dropdownHeader: listHeader, dropdownFooter: listFooter },
      originalInputValueFormat: function (values) {
        return values.length ? String(values[0].value) : "";
      },
    });
    var submit = form.querySelector("[data-tz-submit]");
    if (submit) submit.hidden = true;

    function goToChosen() {
      var chosen = tagify.value.length ? tagify.value[0].value : "";
      if (chosen && chosen !== displayTz) window.location.assign(urlFor(chosen));
    }
    function selectTypedText() {
      /* Select the current zone on focus so typing replaces it. */
      var range = document.createRange();
      var text = tagify.DOM.scope.querySelector(".tagify__tag-text");
      range.selectNodeContents(text || tagify.DOM.input);
      var selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
    }
    tagify.on("focus", selectTypedText);
    tagify.on("add", goToChosen);
    tagify.on("change", goToChosen);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
