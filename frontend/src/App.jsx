// frontend/src/App.jsx

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster, toast } from 'react-hot-toast';
import { AuthProvider } from './context/AuthContext';
import { LanguageProvider } from './context/LanguageContext';
import { tStatic } from './i18n/tStatic';
import ProtectedRoute from './components/auth/ProtectedRoute';
import AdminProtectedRoute from './components/auth/AdminProtectedRoute';

// Pages
import Login from './pages/Login';
import Signup from './pages/Signup';
import ResetPassword from './pages/ResetPassword';
import Dashboard from './pages/Dashboard';
import AIAssistant from './features/onboarding/OnboardingPage';
import NotFound from './pages/NotFound';

function App() {
  return (
    <Router basename={process.env.PUBLIC_URL || '/onboarding/ai'}>
      <LanguageProvider>
      <AuthProvider>
        <div className="min-h-screen bg-brand-primary">
          <Toaster 
            position="top-right" 
            toastOptions={{
              className: 'font-bold text-sm tracking-tight',
              duration: 4000,
              style: {
                background: '#fff',
                color: '#333',
                padding: '16px 20px',
                borderRadius: '16px',
                border: '1px solid #f1f5f9',
                boxShadow: '0 10px 15px -3px rgba(27, 82, 174, 0.1)',
                width: '400px',
                maxWidth: 'none',
              },
            }}
          >
             {(t) => (
              <div 
                className={`flex items-center justify-between gap-4 p-4 bg-white rounded-2xl shadow-2xl border border-gray-100 transition-all ${
                  t.visible ? 'animate-enter' : 'animate-leave'
                }`}
                style={{ width: '400px' }}
              >
                <div className="flex items-center gap-3 flex-1">
                  <div className="text-gray-800 text-sm font-bold tracking-tight">
                    {typeof t.message === 'function' ? t.message(t) : t.message}
                  </div>
                </div>
                {t.type !== 'loading' && (
                  <button 
                    onClick={(e) => {
                      e.stopPropagation();
                      toast.dismiss(t.id);
                    }}
                    className="flex-shrink-0 px-3 py-1.5 bg-gray-50 hover:bg-gray-100 text-gray-500 hover:text-gray-900 rounded-lg transition-all text-xs font-black border border-gray-200"
                  >
                    {tStatic('ui.close').toUpperCase()}
                  </button>
                )}
              </div>
            )}
          </Toaster>

          <Routes>
            {/* Public Routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            {/* Added alongside the bcrypt password-hashing migration — see
                ResetPassword.jsx and app/api/routes/auth.py's
                request-password-reset / reset-password endpoints. */}
            <Route path="/reset-password" element={<ResetPassword />} />
            {/* /register removed: Register.jsx was orphaned — nothing linked to
                or navigated to it, and its only API call (POST /register) hit an
                endpoint that does not exist, so the page 404'd on submit. The
                live signup flow is Signup.jsx (OTP -> POST /register/signup). */}

            {/* Protected Routes */}
            <Route
              path="/dashboard"
              element={
                <AdminProtectedRoute>
                  <Dashboard />
                </AdminProtectedRoute>
              }
            />
            <Route
              path="/open-dashboard"
              element={
                <AdminProtectedRoute>
                  <Dashboard />
                </AdminProtectedRoute>
              }
            />

            <Route
              path="/ai-assistant"
              element={
                <ProtectedRoute>
                  <AIAssistant />
                </ProtectedRoute>
              }
            />

            {/* Default root → Signup (landing screen) */}
            <Route path="/" element={<Navigate to="/signup" replace />} />

            {/* 404 Not Found */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </AuthProvider>
      </LanguageProvider>
    </Router>
  );
}

export default App;
