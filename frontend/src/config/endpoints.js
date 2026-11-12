// frontend/src/config/endpoints.js
/**
 * Every backend path the frontend calls, defined once.
 *
 * Before Stage B6 these were 42 string literals scattered through
 * AIAssistant.jsx, Sidebar.jsx, Dashboard.jsx and AuthContext.jsx. A backend
 * route rename broke the UI silently at runtime — there was nothing to grep
 * and nothing to fail at build time. Now a rename is one edit here, and the
 * backend contract suite asserts that every path in this file resolves to a
 * real route.
 *
 * Conventions
 * -----------
 * - Paths are relative to the axios `baseURL` (`/onboarding/ai/api`), so they
 *   start with a single slash and never repeat the base.
 * - Anything with a path parameter is a FUNCTION, not a template string, so
 *   the encoding happens here rather than being re-derived at each call site.
 *   Every user-supplied segment goes through `encodeURIComponent` — several of
 *   the original call sites interpolated raw emails, which breaks on a `+` in
 *   an address.
 *
 * ⚠️ Known typo, preserved deliberately
 * -------------------------------------
 * `REGISTERED_THIS_WEEK` is `/register/regisetered-this-week` — misspelled.
 * The backend route is misspelled identically, so the pair works. Fixing it
 * means changing both sides in the same deploy; doing it here alone would
 * break the admin dashboard. Flagged, not silently "corrected".
 */

const enc = encodeURIComponent;

export const AUTH = {
  LOGIN: '/auth/login',
  LOGOUT: '/auth/logout',
  VERIFY_SESSION: '/auth/verify-session',
  REQUEST_PASSWORD_RESET: '/auth/request-password-reset',
  RESET_PASSWORD: '/auth/reset-password',
};

export const REGISTER = {
  SIGNUP: '/register/signup',
  LIST_USERS: '/register/list-users',
  TOTAL_USERS: '/register/get-total-users',
  VERIFIED_USERS_COUNT: '/register/get-verified-users-count',
  PENDING_VERIFICATION_COUNT: '/register/get-pending-verification-count',
  REGISTERED_TODAY: '/register/registered-today',
  // See the note above — the misspelling is intentional and matched by the backend.
  REGISTERED_THIS_WEEK: '/register/regisetered-this-week',
  ACCOUNT_TYPE_SUMMARY: '/register/account-type-summary',
  ONBOARDING_SUMMARY: '/register/onboarding-summary',
  BEDROCK_STATUS: '/register/bedrock-status',
};

export const OTP = {
  GENERATE: '/otp/generate-otp',
  VERIFY: '/otp/verify-otp',
};

export const ONBOARDING = {
  START_CONVERSATION: '/chatupload/start-conversation',
  CHAT: '/chatupload/chat-conversational',
  UPLOAD: '/chatupload/upload-conversational',
  // Bulk sibling of UPLOAD — same pipeline, several files in one request.
  // See backend/app/api/routes/onboarding/upload.py's
  // upload_conversational_bulk for which stages accept it.
  UPLOAD_BULK: '/chatupload/upload-conversational-bulk',
  STATUS: (email) => `/chatupload/get-onboarding-status/${enc(email)}`,
  CONVERSATION_LOGS: (email) => `/chatupload/conversation-logs/${enc(email)}`,
  OWNERSHIP_TYPE_SAVE: '/chatupload/ownership-type/save',
  MISMATCH_ASSIGN_ROLE: '/chatupload/mismatch/assign-role',
  UBO_CONFIRM: '/chatupload/member/ubo-confirm',
};

export const COMPLIANCE = {
  FATCA_SUBMIT: '/chatupload/fatca/submit',
  FATCA_NOT_APPLICABLE: '/chatupload/fatca/not-applicable',
  FATCA_STATUS: (email) => `/chatupload/fatca/status/${enc(email)}`,

  PEP_SUBMIT: '/chatupload/pep/submit',
  PEP_STATUS: (email) => `/chatupload/pep/status/${enc(email)}`,

  SELF_DECLARATION_CONFIRM: '/chatupload/self-declaration/confirm',
  SELF_DECLARATION_SUMMARY: (email) =>
    `/chatupload/self-declaration/summary/${enc(email)}`,
  SELF_DECLARATION_STATUS: (email) =>
    `/chatupload/self-declaration/status/${enc(email)}`,
};

export const KEY_INDIVIDUALS = {
  MOA_AS_SELECTION: '/chatupload/ki/moa-as-selection',
  SO_AS_SELECTION: '/chatupload/ki/so-as-selection',
  ADD_AI: '/chatupload/ki/add-ai',
  CONTACT_INFO: '/chatupload/ki/contact-info',
  LOOP_FINALIZE: '/chatupload/ki/loop-finalize',
};

export const PRODUCTS = {
  SAVE: '/chatupload/product-package/save',
  STATUS: (email) => `/chatupload/product-package/status/${enc(email)}`,
  RECOMMEND: (email) => `/chatupload/product-package/recommend?email=${enc(email)}`,
};

export const DOCUMENTS = {
  REQUIREMENTS: '/documentupload/get-document-requirements',
  STATUS: (email) => `/documentupload/document-status/${enc(email)}`,
};
