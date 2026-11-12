// frontend/src/api/onboarding.js
/**
 * Onboarding conversation and document-upload calls.
 *
 * Each function is a thin, named wrapper over one endpoint. The value is not
 * abstraction — it is that a backend rename now breaks in exactly one file
 * instead of silently at runtime in whichever card happened to call it.
 *
 * Every wrapper returns the axios promise unchanged, so existing call sites
 * keep using `response.data` exactly as before.
 */

import api from './client';
import { ONBOARDING } from '../config/endpoints';

export const startConversation = (payload) =>
  api.post(ONBOARDING.START_CONVERSATION, payload);

export const sendChatMessage = (payload) => api.post(ONBOARDING.CHAT, payload);

/**
 * Document upload. Takes a FormData body.
 *
 * `config` is passed through so callers can supply `onUploadProgress` and, in
 * particular, their own `headers` — the shared client sets a JSON content type
 * that must be overridden for multipart.
 */
export const uploadDocument = (formData, config = {}) =>
  api.post(ONBOARDING.UPLOAD, formData, config);

/**
 * Bulk document upload — same FormData shape as uploadDocument but with
 * several `files` entries appended. Only valid at the stages the backend
 * lists in upload_conversational_bulk (corporate documents batch, member
 * identity documents batch); the single-file path above keeps working
 * everywhere else and is unaffected by this existing.
 */
export const uploadDocumentsBulk = (formData, config = {}) =>
  api.post(ONBOARDING.UPLOAD_BULK, formData, config);

export const getOnboardingStatus = (email) => api.get(ONBOARDING.STATUS(email));

// `config` lets a caller pass extra axios request config alongside the
// query params — currently only used for `{ skipAuthRedirect: true }` by
// the language-toggle's history re-fetch (see OnboardingPage.jsx), which
// already fails open on any error and should never trigger client.js's
// interceptor into force-logging the user out over a transient 401 on this
// one background read. Ordinary callers omit it and get the old behaviour.
export const getConversationLogs = (email, params, config = {}) =>
  api.get(ONBOARDING.CONVERSATION_LOGS(email), { ...config, ...(params ? { params } : {}) });

export const saveOwnershipType = (payload) =>
  api.post(ONBOARDING.OWNERSHIP_TYPE_SAVE, payload);

export const assignMismatchRole = (payload) =>
  api.post(ONBOARDING.MISMATCH_ASSIGN_ROLE, payload);

export const confirmUbo = (payload) => api.post(ONBOARDING.UBO_CONFIRM, payload);
