// frontend/src/api/keyIndividuals.js
/**
 * Key-individual (KI) loop calls — owners, partners, directors and the
 * authorised signatory extracted from the MOA and trade licence.
 */

import api from './client';
import { KEY_INDIVIDUALS } from '../config/endpoints';

export const selectMoaAuthorisedSignatory = (payload) =>
  api.post(KEY_INDIVIDUALS.MOA_AS_SELECTION, payload);

export const selectSingleOwnerAuthorisedSignatory = (payload) =>
  api.post(KEY_INDIVIDUALS.SO_AS_SELECTION, payload);

export const addKeyIndividualViaAi = (payload) =>
  api.post(KEY_INDIVIDUALS.ADD_AI, payload);

export const saveKeyIndividualContactInfo = (payload) =>
  api.post(KEY_INDIVIDUALS.CONTACT_INFO, payload);

export const finalizeKeyIndividualLoop = (payload) =>
  api.post(KEY_INDIVIDUALS.LOOP_FINALIZE, payload);
