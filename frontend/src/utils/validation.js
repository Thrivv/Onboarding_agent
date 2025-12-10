// frontend/src/utils/validation.js

export const validateEmail = (email) => {
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(String(email).toLowerCase());
};

export const validatePassword = (password) => {
  const errors = [];
  let isValid = true;

  if (password.length < 8) {
    errors.push('Password must be at least 8 characters long');
    isValid = false;
  }

  if (!/[A-Z]/.test(password)) {
    errors.push('Password must contain at least one uppercase letter');
    isValid = false;
  }

  if (!/[a-z]/.test(password)) {
    errors.push('Password must contain at least one lowercase letter');
    isValid = false;
  }

  if (!/[0-9]/.test(password)) {
    errors.push('Password must contain at least one number');
    isValid = false;
  }

  if (!/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
    errors.push('Password must contain at least one special character');
    isValid = false;
  }

  return { isValid, errors };
};

export const validatePhoneNumber = (phone) => {
  // Remove all non-digit characters for validation
  const cleaned = phone.replace(/\D/g, '');
  
  // Check if it has 10-15 digits (international format)
  if (cleaned.length < 10 || cleaned.length > 15) {
    return false;
  }

  // Optional: More strict validation for specific formats
  const re = /^[+]?[(]?[0-9]{3}[)]?[-\s.]?[0-9]{3}[-\s.]?[0-9]{4,6}$/;
  return re.test(phone);
};

export const validateDate = (dateString) => {
  const date = new Date(dateString);
  const today = new Date();
  
  // Check if date is valid
  if (isNaN(date.getTime())) {
    return { isValid: false, error: 'Invalid date format' };
  }

  // Check if date is not in the future
  if (date > today) {
    return { isValid: false, error: 'Date cannot be in the future' };
  }

  // Check if person is at least 18 years old
  const age = today.getFullYear() - date.getFullYear();
  const monthDiff = today.getMonth() - date.getMonth();
  
  if (age < 18 || (age === 18 && monthDiff < 0)) {
    return { isValid: false, error: 'You must be at least 18 years old' };
  }

  // Check if date is not too old (e.g., 150 years)
  if (age > 150) {
    return { isValid: false, error: 'Please enter a valid date of birth' };
  }

  return { isValid: true };
};

export const validateRequired = (value, fieldName = 'This field') => {
  if (!value || (typeof value === 'string' && !value.trim())) {
    return { isValid: false, error: `${fieldName} is required` };
  }
  return { isValid: true };
};

export const validateLength = (value, min, max, fieldName = 'This field') => {
  const length = value ? value.length : 0;

  if (length < min) {
    return {
      isValid: false,
      error: `${fieldName} must be at least ${min} characters`,
    };
  }

  if (max && length > max) {
    return {
      isValid: false,
      error: `${fieldName} must not exceed ${max} characters`,
    };
  }

  return { isValid: true };
};

export const getPasswordStrength = (password) => {
  let strength = 0;
  const feedback = [];

  if (password.length >= 8) {
    strength++;
  } else {
    feedback.push('At least 8 characters');
  }

  if (/[A-Z]/.test(password)) {
    strength++;
  } else {
    feedback.push('One uppercase letter');
  }

  if (/[a-z]/.test(password)) {
    strength++;
  } else {
    feedback.push('One lowercase letter');
  }

  if (/[0-9]/.test(password)) {
    strength++;
  } else {
    feedback.push('One number');
  }

  if (/[!@#$%^&*(),.?":{}|<>]/.test(password)) {
    strength++;
  } else {
    feedback.push('One special character');
  }

  return { strength, feedback };
};

export const validateURL = (url) => {
  try {
    new URL(url);
    return { isValid: true };
  } catch (error) {
    return { isValid: false, error: 'Invalid URL format' };
  }
};

export const validateFileSize = (file, maxSizeMB = 10) => {
  const maxSize = maxSizeMB * 1024 * 1024; // Convert MB to bytes
  
  if (file.size > maxSize) {
    return {
      isValid: false,
      error: `File size must be less than ${maxSizeMB}MB`,
    };
  }

  return { isValid: true };
};

export const validateFileType = (file, allowedTypes) => {
  if (!allowedTypes.includes(file.type)) {
    return {
      isValid: false,
      error: `Invalid file type. Allowed types: ${allowedTypes.join(', ')}`,
    };
  }

  return { isValid: true };
};

export const sanitizeInput = (input) => {
  if (typeof input !== 'string') return input;
  
  return input
    .trim()
    .replace(/[<>]/g, '') // Remove < and > to prevent XSS
    .replace(/\s+/g, ' '); // Replace multiple spaces with single space
};

export const formatPhoneNumber = (phone) => {
  const cleaned = phone.replace(/\D/g, '');
  
  if (cleaned.length === 10) {
    return cleaned.replace(/(\d{3})(\d{3})(\d{4})/, '($1) $2-$3');
  }
  
  return phone;
};

export const formatCurrency = (amount, currency = 'USD') => {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: currency,
  }).format(amount);
};

export const validateCreditCard = (cardNumber) => {
  const cleaned = cardNumber.replace(/\D/g, '');
  
  if (cleaned.length < 13 || cleaned.length > 19) {
    return { isValid: false, error: 'Invalid card number length' };
  }

  // Luhn algorithm
  let sum = 0;
  let isEven = false;

  for (let i = cleaned.length - 1; i >= 0; i--) {
    let digit = parseInt(cleaned.charAt(i), 10);

    if (isEven) {
      digit *= 2;
      if (digit > 9) {
        digit -= 9;
      }
    }

    sum += digit;
    isEven = !isEven;
  }

  if (sum % 10 !== 0) {
    return { isValid: false, error: 'Invalid card number' };
  }

  return { isValid: true };
};