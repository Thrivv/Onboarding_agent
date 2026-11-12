// frontend/src/api/auth.js
/**
 * Authentication, signup, OTP, and the admin dashboard's aggregate counts.
 */

import api from './client';
import { AUTH, OTP, REGISTER } from '../config/endpoints';

export const login = (credentials) => api.post(AUTH.LOGIN, credentials);
export const logout = (payload) => api.post(AUTH.LOGOUT, payload);
export const verifySession = (config) => api.get(AUTH.VERIFY_SESSION, config);
export const requestPasswordReset = (payload) => api.post(AUTH.REQUEST_PASSWORD_RESET, payload);
export const resetPassword = (payload) => api.post(AUTH.RESET_PASSWORD, payload);

export const signup = (payload) => api.post(REGISTER.SIGNUP, payload);

export const generateOtp = (payload) => api.post(OTP.GENERATE, payload);
export const verifyOtp = (payload) => api.post(OTP.VERIFY, payload);

// ── Admin dashboard aggregates ──────────────────────────────────────────────
export const listUsers = () => api.get(REGISTER.LIST_USERS);
export const getTotalUsers = () => api.get(REGISTER.TOTAL_USERS);
export const getVerifiedUsersCount = () => api.get(REGISTER.VERIFIED_USERS_COUNT);
export const getPendingVerificationCount = () =>
  api.get(REGISTER.PENDING_VERIFICATION_COUNT);
export const getRegisteredToday = () => api.get(REGISTER.REGISTERED_TODAY);
export const getRegisteredThisWeek = () => api.get(REGISTER.REGISTERED_THIS_WEEK);
export const getAccountTypeSummary = () => api.get(REGISTER.ACCOUNT_TYPE_SUMMARY);
export const getOnboardingSummary = () => api.get(REGISTER.ONBOARDING_SUMMARY);
export const getBedrockStatus = () => api.get(REGISTER.BEDROCK_STATUS);
