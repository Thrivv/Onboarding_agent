// frontend/src/App.jsx

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { AuthProvider } from './context/AuthContext';
import ProtectedRoute from './components/auth/ProtectedRoute';
import AdminProtectedRoute from './components/auth/AdminProtectedRoute';

// Pages
import Login from './pages/Login';
import Signup from './pages/Signup';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import AIAssistant from './pages/AIAssistant';
import DocumentUpload from './pages/DocumentUpload';
import NotFound from './pages/NotFound';

function App() {
  return (
    <Router>
      <AuthProvider>
        <div className="min-h-screen bg-gradient-to-r from-blue-100 via-purple-100 to-pink-100">
          <Toaster position="top-right" />
          
          <Routes>
            {/* Public Routes */}
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/register" element={<Register />} />

            {/* Protected Routes */}
            {/* Dashboard with Admin Protection */}
            <Route 
              path="/dashboard" 
              element={
                <ProtectedRoute>
                  <AdminProtectedRoute>
                    <Dashboard />
                  </AdminProtectedRoute>
                </ProtectedRoute>
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
            
            <Route 
              path="/document-upload" 
              element={
                <ProtectedRoute>
                  <DocumentUpload />
                </ProtectedRoute>
              } 
            />

            {/* Default Redirect */}
            <Route 
              path="/" 
              element={
                <ProtectedRoute>
                  <Navigate to="/ai-assistant" replace />
                </ProtectedRoute>
              } 
            />

            {/* 404 Not Found */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </AuthProvider>
    </Router>
  );
}

export default App;