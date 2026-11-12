// frontend/src/context/AuthContext.jsx

import React, { createContext, useState, useContext, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
// Aliased deliberately: this file defines its own `login` / `logout` callbacks
// on the context. Importing the API functions under the same names made the
// local consts shadow them, so `login()` called ITSELF — infinite recursion,
// no network request, and a generic "Login failed" in the UI.
import { login as loginRequest, logout as logoutRequest, verifySession } from '../api/auth';
import { toast } from 'react-hot-toast';
import logger from '../utils/logger';

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  // Initialize - Check for existing session on mount.
  //
  // The session id is now an httpOnly cookie (see api/client.js's
  // withCredentials) rather than something read out of localStorage — so
  // there is no longer a client-readable flag for "a session might exist".
  // We always ask the backend via verifySession(); the browser attaches the
  // cookie automatically if one is present, and the backend reports
  // success:false if not. `user` is still cached in localStorage, but only
  // as a non-sensitive display value for the brief instant before this
  // check resolves — it is never what grants access to anything.
  useEffect(() => {
    const initAuth = async () => {
      const storedUser = localStorage.getItem('user');
      logger.log('[AUTH] Initializing auth...');

      try {
        const response = await verifySession();

        if (response.data.success) {
          // Prefer the freshly-verified identity; fall back to the cached
          // copy only for fields the verify-session response doesn't carry.
          const cached = storedUser ? JSON.parse(storedUser) : {};
          const userData = { ...cached, ...response.data.session };
          setUser(userData);
          localStorage.setItem('user', JSON.stringify(userData));
          logger.log('[AUTH] Session restored');
        } else {
          logger.log('[AUTH] No valid session — clearing cached user');
          localStorage.removeItem('user');
          setUser(null);
        }
      } catch (error) {
        logger.error('[AUTH] Session verification failed:', error);
        localStorage.removeItem('user');
        setUser(null);
      }

      setLoading(false);
    };

    initAuth();
  }, []);

  const login = React.useCallback(async (email, password) => {
    try {
      logger.log('[AUTH] Attempting login for:', email);

      const response = await loginRequest({ email, password });

      logger.log('[AUTH] Login response:', response.data);

      if (response.data.success) {
        const { user: userData } = response.data;

        // Store in state
        setUser(userData);

        // The session itself now lives in an httpOnly cookie set by the
        // backend response (see app/api/routes/auth.py's login handler) —
        // nothing to store for it here. `user` is kept in localStorage only
        // as a non-sensitive display cache (name/role for instant UI paint
        // on the next load); it grants no access on its own.
        localStorage.setItem('user', JSON.stringify(userData));

        logger.log('[AUTH] Login successful, role:', userData.role);

        // Show success message — fallback through first+last → email prefix
        const displayName = userData.name
          || `${userData.first_name || ''} ${userData.last_name || ''}`.trim()
          || userData.email.split('@')[0];
        toast.success(`Welcome back, ${displayName}!`);

        // Small delay to ensure state updates
        setTimeout(() => {
          // Redirect based on role
          navigate('/ai-assistant', { replace: true });
        }, 100);

        return { success: true };
      } else {
        throw new Error('Login failed');
      }
    } catch (error) {
      logger.error('[AUTH] Login error:', error);

      const code = error.response?.data?.code;
      const errorMessage = error.response?.data?.detail || 'Login failed. Please try again.';

      if (code === 'PasswordResetRequiredError') {
        // Distinct from a wrong-password failure: this account's hash
        // predates the current password scheme (or was invalidated by the
        // password-reset migration) and can never verify — send the user
        // straight to the reset flow instead of leaving them to retry a
        // login that will never succeed. See ResetPassword.jsx.
        toast(errorMessage, { icon: '🔐' });
        navigate('/reset-password', { state: { email }, replace: false });
        return { success: false, error: errorMessage, code };
      }

      toast.error(errorMessage);
      return { success: false, error: errorMessage, code };
    }
  }, [navigate]);

  const logout = React.useCallback(async () => {
    try {
      logger.log('[AUTH] Logging out...');
      // No session id to pass — the backend reads it from the httpOnly
      // cookie and clears that cookie in the response. See
      // app/api/routes/auth.py's logout handler.
      await logoutRequest({});
    } catch (error) {
      logger.error('[AUTH] Logout error:', error);
    } finally {
      // Clear everything
      setUser(null);
      localStorage.removeItem('user');

      logger.log('[AUTH] Logged out successfully');
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
