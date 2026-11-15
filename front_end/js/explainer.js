document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("loadEvidence");
    const regionSelect = document.getElementById("evidenceRegion");
    if (!button || !regionSelect) return;

    button.addEventListener("click", loadEvidence);
    loadEvidence();
});

async function loadEvidence() {
    const button = document.getElementById("loadEvidence");
    const loading = document.getElementById("evidenceLoading");
    const error = document.getElementById("evidenceError");
    const results = document.getElementById("evidenceResults");
    const region = document.getElementById("evidenceRegion").value;

    button.disabled = true;
    loading.style.display = "block";
    error.style.display = "none";
    results.style.display = "none";

    try {
        const query = new URLSearchParams({ region });
        const response = await fetch(`/api/observations?${query}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Could not load climate observations.");
        }

        const summary = payload.summary;
        document.getElementById("evidenceLocation").textContent =
            `${payload.region}: representative grid-point observations`;
        document.getElementById("evidencePeriod").textContent =
            `${payload.period_start} to ${payload.period_end} (${summary.days} daily records)`;
        document.getElementById("evidenceRain").textContent =
            `${summary.precipitation_90d_mm?.toFixed(1) ?? "Unavailable"} mm`;
        document.getElementById("evidenceTemperature").textContent =
            `${summary.mean_temperature_90d_c?.toFixed(1) ?? "Unavailable"} °C`;
        document.getElementById("evidenceEt0").textContent =
            `${summary.et0_90d_mm?.toFixed(1) ?? "Unavailable"} mm`;

        const attribution = document.getElementById("evidenceAttribution");
        attribution.replaceChildren();
        attribution.append(
            document.createTextNode(`Source: ${payload.source}. Licence: ${payload.licence}. `)
        );
        const sourceLink = document.createElement("a");
        sourceLink.href = payload.source_url;
        sourceLink.target = "_blank";
        sourceLink.rel = "noopener noreferrer";
        sourceLink.textContent = "Source documentation";
        attribution.append(sourceLink);
        results.style.display = "block";
    } catch (requestError) {
        error.textContent = requestError.message;
        error.style.display = "block";
    } finally {
        loading.style.display = "none";
        button.disabled = false;
    }
}
