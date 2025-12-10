// frontend/src/utils/constants.js - FIXED VERSION (No ESLint Warnings)

// API Configuration
export const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8080';
export const SESSION_TIMEOUT = parseInt(process.env.REACT_APP_SESSION_TIMEOUT) || 300000; // 5 minutes

// Account Types
export const ACCOUNT_TYPES = {
  SAVINGS: 'Savings',
  CORPORATE: 'Corporate',
};

// Ownership Types
export const OWNERSHIP_TYPES = {
  SINGLE: 'Single Owner',
  PARTNERSHIP: 'Partnership',
  MULTIPLE: 'Multiple Owners',
};

// Onboarding Steps
export const ONBOARDING_STEPS = {
  WELCOME: 'welcome',
  BASIC_INFO: 'basic_info',
  ACCOUNT_TYPE: 'account_type',
  OWNERSHIP: 'ownership_type',
  PARTNERSHIP: 'partnership_details',
  TURNOVER: 'annual_turnover',
  IDENTIFICATION: 'identification',
  MEMBER_EIDS: 'member_eids',
  DOCUMENT_VERIFICATION: 'document_verification',
  COMPLETE: 'verification_complete',
};

// Document Types
export const DOCUMENT_TYPES = {
  EID: 'eid',
  PASSPORT: 'passport',
  COMMERCIAL_LICENSE: 'commercial_license',
  MOA: 'moa',
  EJARI: 'ejari',
  BANK_STATEMENT: 'bank_statement',
};

// User Roles
export const USER_ROLES = {
  USER: 'user',
  ADMIN: 'admin',
};

// File Upload
export const ALLOWED_FILE_TYPES = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
export const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB

// Toast Messages
export const TOAST_MESSAGES = {
  LOGIN_SUCCESS: 'Welcome back!',
  LOGIN_ERROR: 'Invalid credentials',
  SIGNUP_SUCCESS: 'Account created successfully! Please login.',
  SIGNUP_ERROR: 'Failed to create account',
  LOGOUT_SUCCESS: 'Logged out successfully',
  SESSION_EXPIRED: 'Session expired. Please login again.',
  UPLOAD_SUCCESS: 'Document uploaded successfully',
  UPLOAD_ERROR: 'Failed to upload document',
  VALIDATION_ERROR: 'Please check your input',
};

// Validation Rules
export const VALIDATION_RULES = {
  PASSWORD_MIN_LENGTH: 8,
  PASSWORD_REGEX: /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$/,
  EMAIL_REGEX: /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/,
  // ✅ FIXED: Removed unnecessary backslashes before + and .
  PHONE_REGEX: /^[+]?[(]?[0-9]{3}[)]?[-\s.]?[0-9]{3}[-\s.]?[0-9]{4,6}$/,
};

// Status Colors
export const STATUS_COLORS = {
  success: 'bg-green-100 text-green-800',
  warning: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
  info: 'bg-blue-100 text-blue-800',
  pending: 'bg-gray-100 text-gray-800',
};

// ✅ FIXED: Assign to variable before exporting as default
const constants = {
  API_BASE_URL,
  SESSION_TIMEOUT,
  ACCOUNT_TYPES,
  OWNERSHIP_TYPES,
  ONBOARDING_STEPS,
  DOCUMENT_TYPES,
  USER_ROLES,
  ALLOWED_FILE_TYPES,
  MAX_FILE_SIZE,
  TOAST_MESSAGES,
  VALIDATION_RULES,
  STATUS_COLORS,
};

export default constants;