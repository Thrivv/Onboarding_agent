// frontend/src/components/auth/ProtectedRoute.jsx
import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  console.log('[PROTECTED ROUTE] Loading:', loading, 'User:', user?.email);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-lg">Loading...</div>
      </div>
    );
  }

  // ✅ ALL AUTHENTICATED USERS ALLOWED - NO ROLE CHECKS
  if (!user) {
    console.log('[PROTECTED ROUTE] Not authenticated, redirecting to login');
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // ✅ ALL USERS (admin + regular) can access - render children
  return children;
};

export default ProtectedRoute;
