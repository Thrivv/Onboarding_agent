// frontend/src/context/AuthContext.jsx

import React, { createContext, useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
// Aliased deliberately: this file defines its own `login` / `logout` callbacks
// on the context. Importing the API functions under the same names made the
// local consts shadow them, so `login()` called ITSELF — infinite recursion,
// no network request, and a generic "Login failed" in the UI.
import { login as loginRequest, logout as logoutRequest, verifySession } from '../api/auth';
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
          const response = await verifySession({
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

  const login = React.useCallback(async (email, password) => {
    try {
      console.log('[AUTH] 🔐 Attempting login for:', email);

      const response = await loginRequest({ email, password });

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

        // Show success message — fallback through first+last → email prefix
        const displayName = userData.name
          || `${userData.first_name || ''} ${userData.last_name || ''}`.trim()
          || userData.email.split('@')[0];
        toast.success(`Welcome back, ${displayName}!`);

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
  }, [navigate]);

  const logout = React.useCallback(async () => {
    try {
      const sessionId = localStorage.getItem('session_id');

      console.log('[AUTH]  डोर Logging out...');

      if (sessionId) {
        await logoutRequest({ session_id: sessionId });
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
  }, [navigate]);

  const isAdmin = React.useCallback(() => {
    return user?.role === 'admin';
  }, [user]);

  const value = React.useMemo(() => ({
    user,
    loading,
    login,
    logout,
    isAdmin,
  }), [user, loading, login, logout, isAdmin]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};