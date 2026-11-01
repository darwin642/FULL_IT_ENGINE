"use strict";

/* CARTMAN — TRANSLATION LOADER */

const translations = Object.create(null);
const translationRequests = new Map();

async function loadTranslation(language) {
    if (translations[language]) return translations[language];

    if (!translationRequests.has(language)) {
        const request = fetch(
            `/static/translations/${encodeURIComponent(language)}.json`,
            { headers: { Accept: "application/json" } }
        ).then(async response => {
            if (!response.ok) {
                throw new Error(`Translation request failed: ${language}`);
            }

            const data = await response.json();

            if (!data || typeof data !== "object" || Array.isArray(data)) {
                throw new Error(`Invalid translation JSON: ${language}`);
            }

            translations[language] = data;
            return data;
        }).catch(error => {
            translationRequests.delete(language);
            throw error;
        });

        translationRequests.set(language, request);
    }

    return translationRequests.get(language);
}

