// frontend/src/utils/logger.js
/**
 * Thin wrapper around console.* that is silent in production builds.
 *
 * The app previously called console.log/console.error/console.warn directly
 * in ~150 places, several of them printing user emails and session ids
 * straight into the browser's devtools console (e.g. "[AUTH] Attempting
 * login for: <email>") — visible to anyone with devtools open, including
 * through browser extensions that read console output, and retained in
 * whatever the user's browser/OS keeps around. `log`/`warn`/`info` below are
 * gated behind NODE_ENV so that debug narration never ships to production;
 * `error` always prints (production error visibility is still useful, and
 * error call sites in this app pass exception objects/messages rather than
 * raw user identifiers).
 *
 * This does not by itself change WHAT each call site logs — see the call
 * sites still passing an email or session id for the ones that should also
 * stop doing that regardless of environment.
 */

const isDev = process.env.NODE_ENV !== 'production';

export const logger = {
  log: (...args) => {
    if (isDev) console.log(...args);
  },
  info: (...args) => {
    if (isDev) console.info(...args);
  },
  warn: (...args) => {
    if (isDev) console.warn(...args);
  },
  error: (...args) => {
    // Errors stay visible in production too — this is the one level where
    // that's usually worth the tradeoff — but call sites should still avoid
    // interpolating raw emails/session ids into the message itself.
    console.error(...args);
  },
};

export default logger;
