// frontend/src/api/documents.js
/**
 * Document requirements and per-document verification status.
 */

import api from './client';
import { DOCUMENTS } from '../config/endpoints';

export const getDocumentRequirements = (payload) =>
  api.post(DOCUMENTS.REQUIREMENTS, payload);

export const getDocumentStatus = (email) => api.get(DOCUMENTS.STATUS(email));
