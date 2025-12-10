// frontend/src/services/api.js

import axios from 'axios';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8080';

const api = axios.create({
  baseURL: API_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 seconds
});

// Request interceptor - Add session ID to headers
api.interceptors.request.use(
  (config) => {
    const sessionId = localStorage.getItem('session_id');
    
    if (sessionId) {
      config.headers['X-Session-ID'] = sessionId;
    }
    
    console.log('[API] 📤 Request:', config.method.toUpperCase(), config.url);
    
    return config;
  },
  (error) => {
    console.error('[API] ❌ Request error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor - Handle errors
api.interceptors.response.use(
  (response) => {
    console.log('[API] 📥 Response:', response.status, response.config.url);
    return response;
  },
  (error) => {
    console.error('[API] ❌ Response error:', error.response?.status, error.config?.url);
    
    // Handle 401 Unauthorized - Session expired
    if (error.response?.status === 401) {
      console.log('[API] 🔒 Unauthorized - Clearing session');
      localStorage.removeItem('session_id');
      localStorage.removeItem('user');
      
      // Redirect to login if not already there
      if (!window.location.pathname.includes('/login')) {
        window.location.href = '/login';
      }
    }
    
    return Promise.reject(error);
  }
);

export default api;