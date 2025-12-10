// frontend/src/components/auth/AdminProtectedRoute.jsx

import React, { useState, useEffect } from 'react';
import { Lock, Eye, EyeOff, Shield } from 'lucide-react';

const ADMIN_PASSWORD = 'Admin@123';
const SESSION_KEY = 'admin_authenticated';

const AdminProtectedRoute = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isChecking, setIsChecking] = useState(true);

  useEffect(() => {
    // Check if already authenticated in this session
    const authenticated = sessionStorage.getItem(SESSION_KEY) === 'true';
    setIsAuthenticated(authenticated);
    setIsChecking(false);
  }, []);

  const handlePasswordSubmit = (e) => {
    e.preventDefault();
    
    if (password === ADMIN_PASSWORD) {
      // Store authentication in session
      sessionStorage.setItem(SESSION_KEY, 'true');
      setIsAuthenticated(true);
      setError('');
      setPassword('');
    } else {
      setError('Incorrect password. Please try again.');
      setPassword('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handlePasswordSubmit(e);
    }
  };

  // Show loading state while checking
  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-purple-600"></div>
      </div>
    );
  }

  // If authenticated, render children
  if (isAuthenticated) {
    return <>{children}</>;
  }

  // Show password modal
  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-purple-50 via-blue-50 to-pink-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-8 border border-gray-200">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-gradient-to-r from-purple-600 to-indigo-600 rounded-full mb-4 shadow-lg">
            <Shield className="h-8 w-8 text-white" />
          </div>
          <h2 className="text-2xl font-bold bg-gradient-to-r from-purple-600 to-indigo-600 bg-clip-text text-transparent mb-2">
            Admin Access Required
          </h2>
          <p className="text-gray-600 text-sm">
            Please enter the admin password to access the Dashboard
          </p>
        </div>

        {/* Password Form */}
        <form onSubmit={handlePasswordSubmit} className="space-y-6">
          <div className="relative">
            <label className="block text-sm font-semibold text-gray-700 mb-2">
              Admin Password
            </label>
            <div className="relative">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <Lock className="h-5 w-5 text-gray-400" />
              </div>
              <input
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError('');
                }}
                onKeyPress={handleKeyPress}
                placeholder="Enter admin password"
                autoFocus
                className={`block w-full pl-10 pr-12 py-3 border ${
                  error ? 'border-red-500 focus:ring-red-500' : 'border-gray-300 focus:ring-purple-500'
                } rounded-lg focus:ring-2 focus:border-transparent transition-all`}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-gray-600 transition-colors"
              >
                {showPassword ? (
                  <EyeOff className="h-5 w-5" />
                ) : (
                  <Eye className="h-5 w-5" />
                )}
              </button>
            </div>
            
            {/* Error Message */}
            {error && (
              <p className="mt-2 text-sm text-red-600 flex items-center gap-1">
                <span className="text-red-500">⚠</span>
                {error}
              </p>
            )}
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={!password.trim()}
            className="w-full bg-gradient-to-r from-purple-600 to-indigo-600 text-white py-3 px-4 rounded-lg font-semibold hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed shadow-lg hover:shadow-xl"
          >
            Unlock Dashboard
          </button>
        </form>

        {/* Info Footer */}
        <div className="mt-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
          <p className="text-xs text-gray-600 text-center">
            🔒 This page is protected. Contact your administrator if you need access.
          </p>
        </div>
      </div>
    </div>
  );
};

export default AdminProtectedRoute;