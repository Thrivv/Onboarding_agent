// frontend/src/context/LanguageContext.jsx
//
// Single source of truth for the app's language preference — read by the
// language toggle (components/common/LanguageToggle.jsx), by every
// translated screen via useLanguage().t(), and by the onboarding chat
// (features/onboarding/OnboardingPage.jsx), which also sends `language` on
// every chat/upload API call so the backend generates its reply in the same
// language (see backend/app/services/message_generator.py).
//
// Persists to the same 'preferredLanguage' localStorage key the onboarding
// chat already used before this context existed, so nothing needs migrating.
// Language values are the same lowercase strings the backend expects
// ("english" | "arabic" | "spanish") — no en/ar/es remapping anywhere.
//
// LANGUAGE_TOGGLE_ENABLED kill switch (set in .env.docker, read by
// app/config.py, enforced server-side by app/utils/language.py's
// normalize_language()): on mount this context fetches
// GET {BASE_PATH}/system/config to find out whether the toggle is enabled.
// When it isn't, `languageToggleEnabled` is exposed as false so
// LanguageToggle can hide itself, `language` is pinned to 'english' even if
// a different value was saved in localStorage from before the flag was
// flipped off, and setLanguage() becomes a no-op for anything but English.
// This is a UI convenience only — the backend enforces the same rule
// independently of whatever the client sends, so there's no way to bypass
// it by calling the API directly.

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { translations } from '../i18n/translations';
import api from '../api/client';
import { setRequestLanguage, isPseudoLocale } from '../api/languageState';

export const SUPPORTED_LANGUAGES = ['english', 'arabic', 'spanish'];
const STORAGE_KEY = 'preferredLanguage';

const BCP47 = { english: 'en', arabic: 'ar', spanish: 'es' };

function readStoredLanguage() {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && SUPPORTED_LANGUAGES.includes(saved)) return saved;
  } catch (e) {
    // localStorage unavailable (private browsing, etc.) — fall back silently
  }
  return 'english';
}

const PSEUDO = isPseudoLocale();

// Email of the logged-in user from the non-sensitive display cache that
// client.js / auth already maintain in localStorage ('user').
function readCachedEmail() {
  try {
    const u = JSON.parse(window.localStorage.getItem('user') || 'null');
    return (u && u.email) || null;
  } catch (e) {
    return null;
  }
}

function resolvePath(obj, path) {
  return path.split('.').reduce((acc, key) => (acc && acc[key] !== undefined ? acc[key] : undefined), obj);
}

const LanguageContext = createContext(null);

export const LanguageProvider = ({ children }) => {
  const [language, setLanguageState] = useState(readStoredLanguage);
  // Optimistic default: true, matching app/config.py's own default
  // (LANGUAGE_TOGGLE_ENABLED = env_bool("LANGUAGE_TOGGLE_ENABLED", True)), so
  // the toggle renders immediately in the common case instead of flashing
  // in once the config call resolves. If the flag turns out to be off, the
  // effect below flips this (and `language`) right after the fetch settles.
  const [languageToggleEnabled, setLanguageToggleEnabled] = useState(true);

  useEffect(() => {
    let cancelled = false;
    // skipAuthRedirect: this is a public, no-auth endpoint fetched on every
    // page mount (including Login/Signup, before any session exists) — it
    // should never be able to trigger client.js's 401 interceptor into
    // clearing the cached user / force-navigating to /login. This call
    // already fails open in the .catch() below regardless of why it failed.
    api.get('/system/config', { skipAuthRedirect: true })
      .then((res) => {
        if (cancelled) return;
        const enabled = res?.data?.language_toggle_enabled !== false;
        setLanguageToggleEnabled(enabled);
        if (!enabled) {
          setLanguageState((prev) => (prev === 'english' ? prev : 'english'));
        }
      })
      .catch(() => {
        // Config endpoint unreachable (offline, backend restarting, etc.) —
        // fail open on the UI so a transient network blip doesn't lock
        // everyone to English. The backend's own normalize_language() is
        // the real enforcement point regardless of what the UI shows.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const dir = language === 'arabic' ? 'rtl' : 'ltr';

  // Drives the built-in Tailwind rtl:/ltr: variants (they key off a `dir`
  // attribute on an ancestor) and the [dir="rtl"] font-stack rule in
  // index.css — see docs/multilingual-support-plan.html, Phase 3.
  useEffect(() => {
    document.documentElement.setAttribute('dir', dir);
    document.documentElement.setAttribute('lang', BCP47[language] || 'en');
  }, [dir, language]);

  const setLanguage = useCallback((next) => {
    if (!SUPPORTED_LANGUAGES.includes(next)) return;
    if (!languageToggleEnabled && next !== 'english') return;
    // Push to the request layer synchronously, BEFORE React re-renders, so a
    // request fired in the same tick as the toggle already carries the new
    // language (api/client.js interceptor).
    setRequestLanguage(next);
    setLanguageState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch (e) {
      // best-effort persistence only
    }
    // Save to the account so another device / a fresh login / the email and
    // PDF paths use it too. Fire-and-forget: a failure here must never
    // block or undo the switch.
    const email = readCachedEmail();
    if (email) {
      api.post('/system/user-language', { email, language: next },
        { skipAuthRedirect: true, skipLanguageBody: true }).catch(() => {});
    }
  }, [languageToggleEnabled]);

  // Adopt the language saved on the account — only when THIS browser has no
  // explicit choice of its own (first login on a new device / cleared
  // storage). Returns the language now in effect so a caller (the chat's
  // initializeChat) can await it before starting the conversation.
  const syncFromAccount = useCallback(async (email) => {
    let hasLocal = false;
    try { hasLocal = !!window.localStorage.getItem(STORAGE_KEY); } catch (e) { /* ignore */ }
    if (hasLocal || !email || !languageToggleEnabled) return null;
    try {
      const res = await api.get(`/system/user-language/${encodeURIComponent(email)}`,
        { skipAuthRedirect: true });
      const saved = res?.data?.language;
      if (saved && SUPPORTED_LANGUAGES.includes(saved)) {
        setRequestLanguage(saved);
        setLanguageState(saved);
        try { window.localStorage.setItem(STORAGE_KEY, saved); } catch (e) { /* ignore */ }
        return saved;
      }
    } catch (e) {
      // fail open — keep current language
    }
    return null;
  }, [languageToggleEnabled]);

  const t = useCallback((key, vars) => {
    let str = resolvePath(translations[language], key);
    if (str === undefined) str = resolvePath(translations.english, key);
    if (str === undefined) return key;
    if (vars) {
      Object.keys(vars).forEach((k) => {
        str = str.replace(new RegExp(`\\{${k}\\}`, 'g'), vars[k]);
      });
    }
    return PSEUDO ? `⟦${str}⟧` : str;
  }, [language]);

  const effectiveLanguage = languageToggleEnabled ? language : 'english';
  // Keep the request layer in step with the effective language (covers the
  // kill-switch pin to English and the initial render).
  setRequestLanguage(effectiveLanguage);

  const value = useMemo(
    () => ({ language: effectiveLanguage, setLanguage, dir, t, languageToggleEnabled, syncFromAccount }),
    [effectiveLanguage, setLanguage, dir, t, languageToggleEnabled, syncFromAccount]
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
};

export const useLanguage = () => {
  const ctx = useContext(LanguageContext);
  if (!ctx) {
    throw new Error('useLanguage() must be called within a <LanguageProvider>');
  }
  return ctx;
};
