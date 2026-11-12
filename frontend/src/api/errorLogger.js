// frontend/src/api/errorLogger.js
//
// Best-effort client-side error reporting. Captures:
//   - Uncaught JS errors            (window.onerror)
//   - Unhandled promise rejections  (window.addEventListener('unhandledrejection'))
//   - React render errors           (called from ErrorBoundary.componentDidCatch)
//
// and POSTs them to the backend, which appends them to logs/frontend/
// (see backend/app/api/routes/frontend_logs.py). Never throws — a failure
// here must not itself crash the app or create a reporting loop.

const API_URL = process.env.REACT_APP_API_URL || '/onboarding/ai/api';

let lastSentAt = 0;
const MIN_INTERVAL_MS = 500; // light client-side throttle to complement server rate limit

export function reportClientError({ message, stack, source, componentStack, email }) {
  try {
    const now = Date.now();
    if (now - lastSentAt < MIN_INTERVAL_MS) return;
    lastSentAt = now;

    const payload = {
      message: String(message || 'Unknown error').slice(0, 2000),
      stack: stack ? String(stack).slice(0, 5000) : null,
      source: source || 'unknown',
      componentStack: componentStack ? String(componentStack).slice(0, 5000) : null,
      url: window.location.href,
      userAgent: navigator.userAgent,
      email: email || (() => {
        try {
          const stored = JSON.parse(localStorage.getItem('user') || 'null');
          return stored?.email || null;
        } catch {
          return null;
        }
      })(),
    };

    // Fire-and-forget via fetch + keepalive so it still fires during
    // unload/navigation. Deliberately not using the shared axios `api`
    // instance to avoid its interceptors (e.g. 401 redirect) reacting to a
    // logging call, and to avoid a reporting loop if the API itself errors.
    fetch(`${API_URL}/logs/frontend`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => {
      // Swallow — logging must never surface a secondary error to the user.
    });
  } catch {
    // Swallow — see above.
  }
}

export function initGlobalErrorLogging() {
  window.addEventListener('error', (event) => {
    reportClientError({
      message: event.message,
      stack: event.error?.stack,
      source: 'window.onerror',
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason;
    reportClientError({
      message: reason?.message || String(reason),
      stack: reason?.stack,
      source: 'unhandledrejection',
    });
  });
}
