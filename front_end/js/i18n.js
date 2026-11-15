const languageSwitcher = document.getElementById("languageSwitcher");
const page = document.body.dataset.page;
const supportedLanguages = ["en", "am", "om"];
const storedLanguage = localStorage.getItem("lang");
let currentLang = supportedLanguages.includes(storedLanguage) ? storedLanguage : "en";

async function loadLanguage(lang) {
    if (!supportedLanguages.includes(lang)) {
        console.error(`Unsupported language: ${lang}`);
        return;
    }

    try {
        const response = await fetch(`lang/${lang}.json`);
        if (!response.ok) {
            throw new Error(`Language file request failed with HTTP ${response.status}`);
        }
        const translations = await response.json();
        const pageTranslations = translations[page] || {};

        document.querySelectorAll("[data-i18n]").forEach((element) => {
            const key = element.getAttribute("data-i18n");
            if (pageTranslations[key]) element.textContent = pageTranslations[key];
        });

        localStorage.setItem("lang", lang);
        if (languageSwitcher) languageSwitcher.value = lang;
    } catch (error) {
        console.error(`Could not load ${lang} translations:`, error);
    }
}

loadLanguage(currentLang);

if (languageSwitcher) {
    languageSwitcher.value = currentLang;
    languageSwitcher.addEventListener("change", (event) => {
        loadLanguage(event.target.value);
    });
}
