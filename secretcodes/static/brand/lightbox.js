/* Lightbox using Bootstrap's Modal (already loaded — no extra dependency).
 * Any element with data-lightbox="<url>" opens that image/video in a popup
 * with an X to close, instead of navigating away. Falls back to the element's
 * href (e.g. open in a new tab) when JS or Bootstrap is unavailable. */
(function () {
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-lightbox]");
    if (!trigger || typeof bootstrap === "undefined") return;
    e.preventDefault();

    var modal = document.getElementById("sc-lightbox");
    var body = document.getElementById("sc-lightbox-body");
    var title = document.getElementById("sc-lightbox-title");
    if (!modal || !body) return;

    title.textContent = trigger.getAttribute("data-lightbox-title") || "";
    body.innerHTML = "";
    var media;
    if (trigger.getAttribute("data-lightbox-type") === "video") {
      media = document.createElement("video");
      media.controls = true;
      media.autoplay = true;
    } else {
      media = document.createElement("img");
      media.alt = title.textContent;
    }
    media.src = trigger.getAttribute("data-lightbox");
    media.className = "img-fluid";
    body.appendChild(media);

    bootstrap.Modal.getOrCreateInstance(modal).show();
  });

  var modal = document.getElementById("sc-lightbox");
  if (modal) {
    modal.addEventListener("hidden.bs.modal", function () {
      document.getElementById("sc-lightbox-body").innerHTML = "";
    });
  }
})();
