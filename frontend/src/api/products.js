// frontend/src/api/products.js
/**
 * Product package selection.
 *
 * `recommend` scores on nature of business, annual turnover and ownership
 * type; the email is a query parameter rather than a path segment, which is
 * why it is built in `endpoints.js` rather than here.
 */

import api from './client';
import { PRODUCTS } from '../config/endpoints';

export const savePackage = (payload) => api.post(PRODUCTS.SAVE, payload);

export const getPackageStatus = (email) => api.get(PRODUCTS.STATUS(email));

export const getPackageRecommendation = (email) => api.get(PRODUCTS.RECOMMEND(email));
