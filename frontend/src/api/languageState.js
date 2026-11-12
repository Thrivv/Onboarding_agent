// frontend/src/api/languageState.js
//
// Module-level mirror of the UI language, readable outside React.
//
// LanguageContext is the single source of truth for the language the user
// picked; it pushes every change in here synchronously (setRequestLanguage),
// and api/client.js's request interceptor reads it to stamp EVERY backend
// call with it (X-User-Language header + `language` body field). That is
// what guarantees an endpoint answers in the current language even when
// the caller forgot to pass one — the backend resolves missing values from
// the header (app/utils/language.py::current_request_language).

let currentLanguage = 'english';
let pseudoLocale = false;

try {
  const saved = window.localStorage.getItem('preferredLanguage');
  if (saved === 'arabic' || saved === 'spanish' || saved === 'english') currentLanguage = saved;
  // Test-only pseudo-locale (see docs/multilingual-flow-approach.html, P4):
  // localStorage.setItem('i18nPseudo', '1') wraps every translated string
  // in ⟦ ⟧ on both frontend (t()) and backend (render_message), so any
  // untranslated text or English-keyed logic is visible in one run.
  pseudoLocale = window.localStorage.getItem('i18nPseudo') === '1';
} catch (e) {
  // storage unavailable — defaults stand
}

export const getRequestLanguage = () => currentLanguage;
export const setRequestLanguage = (lang) => { if (lang) currentLanguage = lang; };
export const isPseudoLocale = () => pseudoLocale;
