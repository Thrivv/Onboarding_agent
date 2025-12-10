// frontend/src/context/AuthContext.jsx

import React, { createContext, useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../services/api';
import { toast } from 'react-hot-toast';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // Initialize - Check for existing session on mount
  useEffect(() => {
    const initAuth = async () => {
      const sessionId = localStorage.getItem('session_id');
      const storedUser = localStorage.getItem('user');

      console.log('[AUTH] 🔍 Initializing auth...');
      console.log('[AUTH] Session ID:', sessionId ? 'Found' : 'Not found');
      console.log('[AUTH] Stored User:', storedUser ? 'Found' : 'Not found');

      if (sessionId && storedUser) {
        try {
          // Verify session is still valid
          const response = await api.get('/auth/verify-session', {
            params: { session_id: sessionId }
          });

          if (response.data.success) {
            const userData = JSON.parse(storedUser);
            setUser(userData);
            console.log('[AUTH] ✅ Session restored:', userData.email);
          } else {
            // Session invalid, clear storage
            console.log('[AUTH] ❌ Session invalid, clearing...');
            localStorage.removeItem('session_id');
            localStorage.removeItem('user');
            setUser(null);
          }
        } catch (error) {
          console.error('[AUTH] ❌ Session verification failed:', error);
          localStorage.removeItem('session_id');
          localStorage.removeItem('user');
          setUser(null);
        }
      } else {
        console.log('[AUTH] ℹ️ No existing session found');
      }

      setLoading(false);
    };

    initAuth();
  }, []);

  const login = async (email, password) => {
    try {
      console.log('[AUTH] 🔐 Attempting login for:', email);
      
      const response = await api.post('/auth/login', { email, password });

      console.log('[AUTH] 📦 Login response:', response.data);

      if (response.data.success) {
        const { user: userData, session_id } = response.data;

        // Store in state
        setUser(userData);

        // Store in localStorage
        localStorage.setItem('session_id', session_id);
        localStorage.setItem('user', JSON.stringify(userData));

        console.log('[AUTH] ✅ Login successful');
        console.log('[AUTH] 👤 User role:', userData.role);
        console.log('[AUTH] 🎫 Session ID:', session_id);

        // Show success message
        toast.success(`Welcome back, ${userData.name}!`);

        // Small delay to ensure state updates
        setTimeout(() => {
          // Redirect based on role
          console.log('[AUTH] 🔀 Redirecting to /ai-assistant');
          navigate('/ai-assistant', { replace: true });
        }, 100);

        return { success: true };
      } else {
        throw new Error('Login failed');
      }
    } catch (error) {
      console.error('[AUTH] ❌ Login error:', error);
      
      const errorMessage = error.response?.data?.detail || 'Login failed. Please try again.';
      toast.error(errorMessage);
      
      return { success: false, error: errorMessage };
    }
  };

  const logout = async () => {
    try {
      const sessionId = localStorage.getItem('session_id');
      
      console.log('[AUTH] 🚪 Logging out...');
      
      if (sessionId) {
        await api.post('/auth/logout', { session_id: sessionId });
      }
    } catch (error) {
      console.error('[AUTH] ❌ Logout error:', error);
    } finally {
      // Clear everything
      setUser(null);
      localStorage.removeItem('session_id');
      localStorage.removeItem('user');
      
      console.log('[AUTH] ✅ Logged out successfully');
      toast.success('Logged out successfully');
      
      navigate('/login', { replace: true });
    }
  };

  const isAdmin = () => {
    return user?.role === 'admin';
  };

  const value = {
    user,
    loading,
    login,
    logout,
    isAdmin,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};