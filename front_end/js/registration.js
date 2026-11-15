(() => {
  const form = document.getElementById("registrationForm");
  if (!form) return;

  const category = document.getElementById("category");
  const region = document.getElementById("region");
  const monthlyPrice = document.getElementById("monthlyPrice");
  const yearlyPrice = document.getElementById("yearlyPrice");
  const selectedPlan = document.getElementById("selectedPlan");
  const message = document.getElementById("registrationMessage");
  const submit = document.getElementById("submitRegistration");
  const success = document.getElementById("registrationSuccess");
  const summary = document.getElementById("registrationSummary");
  const smsResult = document.getElementById("smsResult");
  let prices = {};

  function selectedPeriod() {
    return form.querySelector('input[name="billing_period"]:checked')?.value || "monthly";
  }

  function formatPrice(value) {
    return `${Number(value).toLocaleString("en-ET")} ETB`;
  }

  function refreshPrices() {
    const plan = prices[category.value];
    document.querySelectorAll(".billing-option").forEach((option) => {
      option.classList.toggle(
        "is-selected",
        option.dataset.period === selectedPeriod()
      );
    });
    if (!plan) {
      monthlyPrice.textContent = "— ETB";
      yearlyPrice.textContent = "— ETB";
      selectedPlan.textContent = "Choose a stakeholder category to view its price.";
      return;
    }
    monthlyPrice.textContent = formatPrice(plan.monthly);
    yearlyPrice.textContent = formatPrice(plan.yearly);
    const period = selectedPeriod();
    const label = period === "monthly" ? "Monthly" : "Yearly";
    selectedPlan.textContent = `Selected: ${label} · ${formatPrice(plan[period])}`;
  }

  function showMessage(text, kind = "error") {
    message.textContent = text;
    message.dataset.kind = kind;
    message.hidden = false;
  }

  async function loadOptions() {
    try {
      const response = await fetch("/api/registration/options", {
        headers: { Accept: "application/json" },
      });
      const contentType = response.headers.get("content-type") || "";
      const data = contentType.includes("application/json")
        ? await response.json()
        : null;
      if (!response.ok) {
        throw new Error(
          data?.error || `Could not load registration options (HTTP ${response.status}).`
        );
      }
      if (
        !data
        || !Array.isArray(data.categories)
        || !Array.isArray(data.regions)
        || !data.prices
        || typeof data.prices !== "object"
        || data.categories.length === 0
        || data.regions.length === 0
        || data.categories.some((value) => (
          typeof value !== "string"
          || !Number.isFinite(data.prices[value]?.monthly)
          || !Number.isFinite(data.prices[value]?.yearly)
        ))
      ) {
        throw new Error("Registration options are incomplete. Please refresh or try again later.");
      }

      prices = data.prices;
      category.replaceChildren(new Option("Select your category", ""));
      for (const value of data.categories) {
        category.add(new Option(value, value));
      }
      region.replaceChildren(new Option("Select your region", ""));
      for (const value of data.regions) {
        region.add(new Option(value, value));
      }
      submit.disabled = false;
      refreshPrices();
    } catch (error) {
      showMessage(error.message);
    }
  }

  function showRegistration(data) {
    const lines = [
      ["Category", data.category],
      ["Region", data.region],
      ...(data.area ? [["Zone / district", data.area]] : []),
      ["Billing", data.billing_period === "monthly" ? "Monthly" : "Yearly"],
      ["Selected price", `${formatPrice(data.price_etb)} / ${data.billing_period === "monthly" ? "month" : "year"}`],
    ];
    summary.replaceChildren();
    for (const [label, value] of lines) {
      const term = document.createElement("dt");
      const description = document.createElement("dd");
      term.textContent = label;
      description.textContent = value;
      summary.append(term, description);
    }
    const smsMessages = {
      accepted: "Your personalized welcome SMS request was accepted by Africa’s Talking Sandbox.",
      not_configured: "Your registration is saved. The welcome SMS was not sent because SMS delivery is not configured.",
      pending_configuration: "Your registration is saved. The welcome SMS is pending configuration.",
      sandbox_required: "Your registration is saved, but SMS was not sent because the application is not in Sandbox mode.",
      failed: "Your registration is saved, but the welcome SMS could not be sent. Please contact the service administrator.",
      suppressed_opted_out: "Your registration is saved. SMS delivery is suppressed because this number has opted out.",
      status_recording_failed: "Your registration is saved, but the SMS status could not be recorded. Contact the service administrator.",
    };
    smsResult.textContent = smsMessages[data.sms_status] || "Your registration is saved; SMS status is pending.";
    form.hidden = true;
    success.hidden = false;
  }

  category.addEventListener("change", refreshPrices);
  form.querySelectorAll('input[name="billing_period"]').forEach((input) => {
    input.addEventListener("change", refreshPrices);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.hidden = true;
    if (!form.reportValidity()) return;
    if (!prices[category.value] || !["monthly", "yearly"].includes(selectedPeriod())) {
      showMessage("Select a valid stakeholder category and billing period.");
      return;
    }
    submit.disabled = true;
    submit.textContent = "Submitting…";

    const data = {
      full_name: document.getElementById("fullName").value.trim(),
      phone: document.getElementById("phone").value.trim(),
      region: region.value,
      area: document.getElementById("area").value.trim(),
      category: category.value,
      billing_period: selectedPeriod(),
      sms_consent: document.getElementById("smsConsent").checked,
    };

    try {
      const response = await fetch("/api/registrations", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(data),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Registration could not be submitted.");
      showRegistration(result);
    } catch (error) {
      showMessage(error.message);
    } finally {
      submit.disabled = false;
      submit.textContent = "Submit registration";
    }
  });

  document.getElementById("editRegistration").addEventListener("click", () => {
    success.hidden = true;
    form.hidden = false;
    window.scrollTo({ top: 0, behavior: "smooth" });
  });

  loadOptions();
})();
