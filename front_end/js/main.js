let rainfallChart = null;
let temperatureChart = null;
let evapotranspirationChart = null;

document.addEventListener("DOMContentLoaded", () => {
    initializeMenu();
    const regionSelector = document.getElementById("regionSelector");
    if (regionSelector) {
        regionSelector.addEventListener("change", () => {
            loadObservations();
            updateCoverageMap(regionSelector.value, "Loading");
            loadRainfallRisk(regionSelector.value);
        });
        regionSelector.value = "Afar";
        updateCoverageMap(regionSelector.value, "Loading");
    }
    const policyRegion = document.getElementById("policyRegion");
    const refreshPolicy = document.getElementById("refreshPolicy");
    if (policyRegion && refreshPolicy) {
        refreshPolicy.addEventListener("click", () => loadPolicyRecommendations(policyRegion.value));
        policyRegion.value = "Afar";
    }
    if (document.body.dataset.page === "index") {
        loadObservations();
        loadRainfallRisk(regionSelector ? regionSelector.value : "Afar");
    }
    if (document.body.dataset.page === "policy") {
        const currentRegion = policyRegion ? policyRegion.value : "Afar";
        loadPolicyRecommendations(currentRegion);
    }
});

async function loadRainfallRisk(region) {
    const panel = document.getElementById("rainRiskPanel");
    const scoreElement = document.getElementById("rainRiskScore");
    const levelElement = document.getElementById("rainRiskLevel");
    const fill = document.getElementById("rainRiskFill");
    const meter = panel ? panel.querySelector(".risk-meter") : null;
    const dateElement = document.getElementById("rainRiskDate");
    const caveat = document.getElementById("riskCaveat");
    if (!panel || !scoreElement || !levelElement || !fill || !meter || !dateElement || !caveat) return;

    updateCoverageMap(region, "Loading");
    panel.className = "risk-result";
    scoreElement.textContent = "--";
    levelElement.textContent = "Loading";
    fill.style.width = "0%";
    meter.setAttribute("aria-valuenow", "0");
    dateElement.textContent = "";

    try {
        const response = await fetch(`/api/forecast?region=${encodeURIComponent(region)}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Rainfall risk screening is unavailable.");
        }

        const score = Number(payload.risk_score);
        if (!Number.isFinite(score) || typeof payload.risk_level !== "string") {
            throw new Error("The rainfall screening returned incomplete data.");
        }
        const boundedScore = Math.max(0, Math.min(100, score));
        const level = payload.risk_level.toLowerCase();
        panel.classList.add(`risk-${level}`);
        updateCoverageMap(region, payload.risk_level);
        scoreElement.textContent = boundedScore.toFixed(1);
        levelElement.textContent = payload.risk_level;
        fill.style.width = `${boundedScore}%`;
        meter.setAttribute("aria-valuenow", boundedScore.toFixed(1));

        const comparison = payload.comparison || {};
        dateElement.textContent = comparison.period_start && comparison.period_end
            ? `${comparison.period_start} to ${comparison.period_end} · ${comparison.category || "Historical comparison"}`
            : `Assessment date: ${payload.assessment_date}`;
        caveat.textContent = payload.caveat ||
            "Baseline screening only · not a validated drought diagnosis or future forecast.";
    } catch (error) {
        levelElement.textContent = "Unavailable";
        caveat.textContent = error.message;
        updateCoverageMap(region, "Unavailable");
    }
}

function updateCoverageMap(region, riskLevel) {
    const regionLabel = document.getElementById("coverageRegion");
    const riskLabel = document.getElementById("coverageRisk");
    const points = document.querySelectorAll(".coverage-points [data-region]");
    if (!regionLabel || !riskLabel || points.length === 0) return;
    const regionSelector = document.getElementById("regionSelector");
    if (regionSelector && regionSelector.value !== region) return;

    regionLabel.textContent = region;
    riskLabel.textContent = riskLevel;
    points.forEach((point) => {
        point.classList.toggle("is-selected", point.dataset.region === region);
    });
}

function initializeMenu() {
    const menuToggle = document.getElementById("menuToggle");
    const sidebar = document.getElementById("sidebar");
    const overlay = document.getElementById("overlay");

    if (!menuToggle || !sidebar || !overlay) return;

    menuToggle.addEventListener("click", () => {
        sidebar.classList.toggle("open");
        overlay.classList.toggle("active");
        menuToggle.classList.toggle("active");
    });

    overlay.addEventListener("click", () => {
        sidebar.classList.remove("open");
        overlay.classList.remove("active");
        menuToggle.classList.remove("active");
    });
}

async function loadObservations() {
    const attribution = document.getElementById("dataAttribution");
    const regionSelector = document.getElementById("regionSelector");
    const region = regionSelector ? regionSelector.value : "Afar";

    try {
        const response = await fetch(`/api/observations?region=${encodeURIComponent(region)}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Could not load climate observations.");
        }

        const summary = payload.summary;
        setText("rainfallTotal", formatMeasurement(summary.precipitation_90d_mm, "mm"));
        setText("meanTemperature", formatMeasurement(summary.mean_temperature_90d_c, "°C"));
        setText("evapotranspirationTotal", formatMeasurement(summary.et0_90d_mm, "mm"));
        setText("observationsWindow", `${summary.days} days`);
        drawObservationCharts(payload);
        if (attribution) {
            attribution.textContent =
                `${payload.region} · ${payload.period_start} to ${payload.period_end} · ` +
                `${payload.source}. CC BY 4.0.`;
            attribution.href = payload.source_url;
        }
    } catch (error) {
        showError(error.message);
        if (attribution) {
            attribution.textContent = "Live climate observations could not be loaded.";
        }
    }
}

function drawObservationCharts(payload) {
    if (typeof Chart === "undefined") {
        showError("Chart library did not load. Check your internet connection and reload.");
        return;
    }

    const labels = payload.dates;
    const configs = [
        {
            id: "rainChart",
            previous: rainfallChart,
            color: "#183D32",
            label: "Precipitation (mm)",
            values: payload.precipitation_mm,
            assign: (chart) => { rainfallChart = chart; }
        },
        {
            id: "temperatureChart",
            previous: temperatureChart,
            color: "#A9762D",
            label: "Mean temperature (°C)",
            values: payload.temperature_c,
            assign: (chart) => { temperatureChart = chart; }
        },
        {
            id: "evapotranspirationChart",
            previous: evapotranspirationChart,
            color: "#68765A",
            label: "Reference ET₀ (mm/day)",
            values: payload.et0_mm,
            assign: (chart) => { evapotranspirationChart = chart; }
        }
    ];

    configs.forEach((config) => {
        const canvas = document.getElementById(config.id);
        if (!canvas) return;
        if (config.previous) config.previous.destroy();

        config.assign(new Chart(canvas, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: config.label,
                    data: config.values,
                    borderColor: config.color,
                    backgroundColor: `${config.color}22`,
                    fill: true,
                    tension: 0.3,
                    spanGaps: false,
                    pointRadius: 0,
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        border: { display: false },
                        ticks: { maxTicksLimit: 7, color: "#68736D" }
                    },
                    y: {
                        beginAtZero: true,
                        border: { display: false },
                        grid: { color: "#E5E9E5" },
                        ticks: { color: "#68736D" }
                    }
                }
            }
        }));
    });
}

function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
}

function formatMeasurement(value, unit) {
    return Number.isFinite(value) ? `${value.toFixed(1)} ${unit}` : "Unavailable";
}

function showError(message) {
    const error = document.getElementById("errorMessage");
    if (!error) return;
    error.textContent = message;
    error.style.display = "block";
}

async function loadPolicyRecommendations(region) {
    const summary = document.getElementById("policySummary");
    const list = document.getElementById("policyRecommendationList");
    const caveat = document.getElementById("policyCaveat");
    if (!summary || !list || !caveat) return;

    try {
        const response = await fetch(`/api/policy-recommendations?region=${encodeURIComponent(region)}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Policy guidance could not be loaded.");
        }

        summary.textContent = `${payload.region} • risk score ${payload.risk_score} • ${payload.risk_level}`;
        list.replaceChildren();
        payload.recommendations.forEach((item) => {
            const li = document.createElement("li");
            li.innerHTML = `<strong>${item.priority}</strong>: ${item.action}`;
            list.appendChild(li);
        });
        caveat.textContent = payload.caveat;
    } catch (error) {
        summary.textContent = "Policy guidance unavailable";
        list.replaceChildren();
        const fallback = document.createElement("li");
        fallback.textContent = error.message;
        list.appendChild(fallback);
        caveat.textContent = "Could not derive recommendations from the live climate signals.";
    }
}
