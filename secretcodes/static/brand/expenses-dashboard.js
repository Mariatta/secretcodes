/* Expenses event dashboard charts. Reads the json_script data blocks rendered
   by event_dashboard.html and draws them with the vendored Chart.js. No data
   is fetched; everything is server-rendered into the page. */
(function () {
    "use strict";
    if (typeof Chart === "undefined") {
        return;
    }

    function read(id) {
        var el = document.getElementById(id);
        return el ? JSON.parse(el.textContent) : [];
    }
    function labels(rows) {
        return rows.map(function (r) {
            return r.label;
        });
    }
    function values(rows) {
        return rows.map(function (r) {
            return r.value;
        });
    }

    var currencyEl = document.getElementById("dashboard-currency");
    var currency = currencyEl ? currencyEl.dataset.currency : "";

    function money(value) {
        return (
            value.toLocaleString(undefined, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }) +
            " " +
            currency
        );
    }

    // Brand palette: signal red, decoded gold, deep water, lilac, navy, warm.
    var palette = [
        "#D84C2F",
        "#C79A3A",
        "#2E6E6A",
        "#8A7AB8",
        "#0E1730",
        "#F0A06B",
        "#1B2747",
        "#E8C464"
    ];

    var dark = document.documentElement.classList.contains("sc-dark");
    Chart.defaults.color = dark ? "#F2ECDD" : "#1B2747";
    Chart.defaults.borderColor = dark
        ? "rgba(242, 236, 221, 0.15)"
        : "rgba(14, 23, 48, 0.1)";
    Chart.defaults.font.family =
        "'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif";

    var moneyTooltip = {
        callbacks: {
            label: function (ctx) {
                var v =
                    ctx.parsed.y != null
                        ? ctx.parsed.y
                        : ctx.parsed.x != null
                          ? ctx.parsed.x
                          : ctx.parsed;
                return money(v);
            }
        }
    };

    function makeBar(canvasId, rows, color) {
        var canvas = document.getElementById(canvasId);
        if (!canvas || !rows.length) {
            return;
        }
        new Chart(canvas, {
            type: "bar",
            data: {
                labels: labels(rows),
                datasets: [{ data: values(rows), backgroundColor: color }]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: moneyTooltip }
            }
        });
    }

    var category = read("data-category");
    var categoryCanvas = document.getElementById("chart-category");
    if (categoryCanvas && category.length) {
        new Chart(categoryCanvas, {
            type: "doughnut",
            data: {
                labels: labels(category),
                datasets: [{ data: values(category), backgroundColor: palette }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: "right" },
                    tooltip: {
                        callbacks: {
                            label: function (ctx) {
                                return ctx.label + ": " + money(ctx.parsed);
                            }
                        }
                    }
                }
            }
        });
    }

    makeBar("chart-payer", read("data-payer"), "#2E6E6A");
    makeBar("chart-share", read("data-share"), "#8A7AB8");

    var time = read("data-time");
    var timeCanvas = document.getElementById("chart-time");
    if (timeCanvas && time.length) {
        new Chart(timeCanvas, {
            type: "line",
            data: {
                labels: labels(time),
                datasets: [
                    {
                        data: values(time),
                        borderColor: "#D84C2F",
                        backgroundColor: "rgba(216, 76, 47, 0.15)",
                        fill: true,
                        tension: 0.3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: moneyTooltip }
            }
        });
    }
})();
