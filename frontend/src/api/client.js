// frontend/src/api/client.js

import axios from 'axios';
import logger from '../utils/logger';
import { getRequestLanguage, isPseudoLocale } from './languageState';

// Default: same-origin under the /onboarding/ai base path (nginx proxies /onboarding/ai/api → backend)
const API_URL = process.env.REACT_APP_API_URL || '/onboarding/ai/api';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 600000, // 10 minutes
  // The session id now travels as an httpOnly cookie set by the backend
  // (see app/api/routes/auth.py's _set_session_cookie) rather than being
  // read out of localStorage and attached as an X-Session-ID header — a
  // value in localStorage is readable by any script on the page, so a
  // single XSS vector anywhere could exfiltrate a live session. An httpOnly
  // cookie is invisible to JavaScript; `withCredentials: true` is what
  // makes axios actually send it (and accept Set-Cookie from responses).
  // The backend's CORS config already allows this (`allow_credentials=True`
  // in app/main.py), and requests are same-origin in production (nginx
  // proxies /onboarding/ai/api to the backend), so this does not widen
  // what any other origin can do.
  withCredentials: true,
});

// Request interceptor — the session cookie goes along automatically
// (withCredentials above). This also stamps every call with the UI
// language so the backend never has to guess it:
//   * X-User-Language header on every request (backend middleware puts it
//     in a contextvar; normalize_language(None) resolves to it), and
//   * `language` in JSON / FormData bodies, overwriting any value the
//     caller passed — the caller's copy can lag a render behind a toggle
//     (e.g. OnboardingPage's mirrored selectedLanguage), while
//     languageState is updated synchronously by LanguageContext.
api.interceptors.request.use(
  (config) => {
    logger.log('[API] Request:', config.method.toUpperCase(), config.url);
    const lang = getRequestLanguage();
    config.headers = config.headers || {};
    config.headers['X-User-Language'] = lang;
    if (isPseudoLocale()) config.headers['X-I18n-Pseudo'] = '1';
    const method = (config.method || 'get').toLowerCase();
    if (method !== 'get' && !config.skipLanguageBody) {
      const d = config.data;
      if (typeof FormData !== 'undefined' && d instanceof FormData) {
        d.set('language', lang);
      } else if (d && typeof d === 'object' && !Array.isArray(d)) {
        config.data = { ...d, language: lang };
      }
    }
    return config;
  },
  (error) => {
    logger.error('[API] Request error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor - Handle errors
api.interceptors.response.use(
  (response) => {
    logger.log('[API] Response:', response.status, response.config.url);
    // The user switched language while this (non-GET) request was in flight:
    // its reply was generated in the old language. Tell the chat to re-sync
    // its history once so the reply is re-rendered in the current language.
    try {
      const sentIn = response.config?.headers?.['X-User-Language'];
      const method = (response.config?.method || 'get').toLowerCase();
      if (method !== 'get' && sentIn && sentIn !== getRequestLanguage()) {
        window.dispatchEvent(new CustomEvent('i18n:stale-response', { detail: { sentIn, url: response.config?.url } }));
      }
    } catch (e) { /* never block a response over this */ }
    return response;
  },
  (error) => {
    logger.error('[API] Response error:', error.response?.status, error.config?.url);

    // Handle 401 Unauthorized - Session expired
    //
    // BUGFIX: this used to fire the hard redirect for *every* 401 from
    // *any* call made through this shared client — including background,
    // best-effort reads a caller already treats as fail-open (the
    // language-toggle's history re-fetch in OnboardingPage.jsx, the
    // language-toggle-enabled check in LanguageContext.jsx). Those callers
    // already catch their own errors and quietly keep showing what was on
    // screen — but this interceptor ran first and force-navigated the user
    // to /login regardless, which is what made "switch the language
    // mid-flow" look like a random, unexplained logout: any transient 401
    // from one of those passive calls (a slow/failed translation request,
    // a backend restart, a proxy hiccup) blew away the whole session
    // instead of just that one background read failing quietly like it was
    // designed to. A call now opts out with `skipAuthRedirect: true` in its
    // axios config when a 401 from it should never end the session by
    // itself — see api/onboarding.js's getConversationLogs and
    // context/LanguageContext.jsx's /system/config check for the two
    // current opt-outs.
    if (error.response?.status === 401 && !error.config?.skipAuthRedirect) {
      logger.log('[API] Unauthorized - clearing local user cache');
      // No session token to remove from localStorage anymore — the cookie
      // that actually authorizes requests is httpOnly and gets cleared
      // server-side (or has simply expired). `user` is kept only as a
      // non-sensitive display cache for the UI; clear it so a stale name/
      // role doesn't linger after the backend has stopped honoring the
      // session.
      localStorage.removeItem('user');

      // Redirect to login if not already there
      if (!window.location.pathname.includes('/login')) {
        window.location.href = `${process.env.PUBLIC_URL || '/onboarding/ai'}/login`;
      }
    } else if (error.response?.status === 401) {
      logger.log('[API] Unauthorized on a background call (skipAuthRedirect) - not ending the session');
    }

    return Promise.reject(error);
  }
);

export default api;
