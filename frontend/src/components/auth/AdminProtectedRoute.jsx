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
    const authenticated = sessionStorage.getItem(SESSION_KEY) === 'true';
    setIsAuthenticated(authenticated);
    setIsChecking(false);
  }, []);

  const handlePasswordSubmit = (e) => {
    e.preventDefault();

    if (password === ADMIN_PASSWORD) {
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

  if (isChecking) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-brand-primary">
        <div className="animate-spin rounded-full h-12 w-12 border-4 border-white/30 border-t-white"></div>
      </div>
    );
  }

  if (isAuthenticated) {
    return <>{children}</>;
  }

  return (
    <div className="gx-main-layout">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-8 border border-gray-200">

        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-brand-primary rounded-full mb-4 shadow-lg">
            <Shield className="h-8 w-8 text-white" />
          </div>

          <h2 className="text-2xl font-bold text-brand-primary mb-2">
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
                  error
                    ? 'border-red-500 focus:ring-red-500'
                    : 'border-gray-300 focus:ring-brand-primary'
                } rounded-lg focus:ring-2 focus:border-transparent transition-all`}
              />

              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 pr-3 flex items-center text-gray-400 hover:text-brand-primary transition-colors"
              >
                {showPassword ? (
                  <EyeOff className="h-5 w-5" />
                ) : (
                  <Eye className="h-5 w-5" />
                )}
              </button>

            </div>

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
            className="w-full bg-brand-primary text-white py-3 px-4 rounded-lg font-semibold hover:bg-brand-primary-dark transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg hover:shadow-xl"
          >
            Unlock Dashboard
          </button>

        </form>

        {/* Footer */}
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