import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import PremiumLoader from '../layout/PremiumLoader';
import logger from '../../utils/logger';

const ProtectedRoute = ({ children }) => {
  const { user, loading } = useAuth();
  const location = useLocation();

  logger.log('[PROTECTED ROUTE] Loading:', loading, 'User:', user?.email);

  if (loading) {
    return <PremiumLoader />;
  }

  // ✅ ALL AUTHENTICATED USERS ALLOWED - NO ROLE CHECKS
  if (!user) {
    logger.log('[PROTECTED ROUTE] Not authenticated, redirecting to login');
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // ✅ ALL USERS (admin + regular) can access - render children
  return children;
};

export default ProtectedRoute;
