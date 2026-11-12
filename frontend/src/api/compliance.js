// frontend/src/api/compliance.js
/**
 * FATCA, PEP and self-declaration calls.
 *
 * FATCA and PEP apply to Partnership / Multiple Owner accounts only — Single
 * Owner skips both. That rule lives on the backend; these wrappers make no
 * assumption about it.
 */

import api from './client';
import { COMPLIANCE } from '../config/endpoints';

export const submitFatca = (payload) => api.post(COMPLIANCE.FATCA_SUBMIT, payload);

export const markFatcaNotApplicable = (payload) =>
  api.post(COMPLIANCE.FATCA_NOT_APPLICABLE, payload);

export const getFatcaStatus = (email) => api.get(COMPLIANCE.FATCA_STATUS(email));

export const submitPep = (payload) => api.post(COMPLIANCE.PEP_SUBMIT, payload);

export const getPepStatus = (email) => api.get(COMPLIANCE.PEP_STATUS(email));

export const confirmSelfDeclaration = (payload) =>
  api.post(COMPLIANCE.SELF_DECLARATION_CONFIRM, payload);

export const getSelfDeclarationSummary = (email) =>
  api.get(COMPLIANCE.SELF_DECLARATION_SUMMARY(email));

export const getSelfDeclarationStatus = (email) =>
  api.get(COMPLIANCE.SELF_DECLARATION_STATUS(email));
