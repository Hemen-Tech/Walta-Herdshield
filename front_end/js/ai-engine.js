let comparisonChart = null;

document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("forecastForm");
    const dateInput = document.getElementById("assessmentDate");
    if (!form || !dateInput) return;

    const latestSelectableDate = new Date();
    latestSelectableDate.setDate(latestSelectableDate.getDate() - 7);
    dateInput.max = latestSelectableDate.toISOString().slice(0, 10);
    dateInput.value = dateInput.max;
    form.addEventListener("submit", runAssessment);
});

async function runAssessment(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const button = document.getElementById("runBtn");
    const loading = document.getElementById("loading");
    const results = document.getElementById("results");
    const error = document.getElementById("assessmentError");
    const region = document.getElementById("region").value;
    const assessmentDate = document.getElementById("assessmentDate").value;

    button.disabled = true;
    loading.style.display = "block";
    results.style.display = "none";
    error.style.display = "none";

    try {
        const query = new URLSearchParams({
            region,
            assessment_date: assessmentDate
        });
        const response = await fetch(`/api/forecast?${query}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Could not assess rainfall observations.");
        }

        renderAssessment(payload);
        results.style.display = "block";
    } catch (requestError) {
        error.textContent = requestError.message;
        error.style.display = "block";
    } finally {
        loading.style.display = "none";
        button.disabled = false;
    }
}

function renderAssessment(payload) {
    const rows = document.getElementById("resultRows");
    rows.replaceChildren();

    const comparison = payload.comparison || payload;
    const measurements = [
        ["Observed rainfall (90 days)", `${comparison.current_rainfall_mm} mm`],
        ["Historical mean for same dates", `${comparison.historical_mean_mm} mm`],
        ["Difference from historical mean", `${comparison.difference_percent}%`],
        ["Historical percentile", `${comparison.historical_percentile}th`],
        ["Available comparison years", comparison.comparison_years],
        ["Base risk score", `${payload.risk_score || 0}`],
        ["Risk level", payload.risk_level || comparison.category]
    ];

    measurements.forEach(([label, value]) => {
        const row = document.createElement("p");
        row.className = "result-row";
        row.textContent = `${label}: ${value}`;
        rows.appendChild(row);
    });

    const category = document.createElement("p");
    category.className = "result-category";
    category.textContent = payload.risk_level || comparison.category;
    rows.prepend(category);

    const caveat = payload.caveat || comparison.caveat || "";
    document.getElementById("assessmentCaveat").textContent =
        `${caveat} Data: ${payload.source || comparison.source || "Open-Meteo"}. CC BY 4.0.`;
    renderComparisonChart(comparison, payload.risk_score || 0);
}

function renderComparisonChart(payload, riskScore = 0) {
    const canvas = document.getElementById("trendChart");
    if (comparisonChart) comparisonChart.destroy();

    comparisonChart = new Chart(canvas, {
        type: "bar",
        data: {
            labels: ["Observed 90-day rainfall", "Historical mean", "Baseline risk score"],
            datasets: [{
                data: [payload.current_rainfall_mm, payload.historical_mean_mm, riskScore],
                backgroundColor: ["#183D32", "#AEB6B0", riskScore > 60 ? "#9B514C" : riskScore > 35 ? "#A9762D" : "#68765A"],
                borderRadius: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { grid: { display: false }, border: { display: false }, ticks: { color: "#68736D" } },
                y: {
                    beginAtZero: true,
                    border: { display: false },
                    grid: { color: "#E5E9E5" },
                    ticks: { color: "#68736D" },
                    title: { display: true, text: "Rainfall (mm) / risk score", color: "#68736D" }
                }
            }
        }
    });
}
