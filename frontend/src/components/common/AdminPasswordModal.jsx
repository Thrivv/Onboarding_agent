// frontend/src/components/common/AdminPasswordModal.jsx

import React, { useState } from 'react';
import { Lock, Eye, EyeOff, Shield, X } from 'lucide-react';
import toast from 'react-hot-toast';

const AdminPasswordModal = ({ onSubmit, onClose }) => {
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!password.trim()) {
      toast.error('Please enter a password');
      return;
    }

    setIsLoading(true);
    
    // Simulate a brief delay for better UX
    await new Promise(resolve => setTimeout(resolve, 500));
    
    if (password === 'Admin@123') {
      toast.success('✅ Access Granted!');
      onSubmit(password);
    } else {
      toast.error('❌ Incorrect Password');
      setPassword('');
    }
    
    setIsLoading(false);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleSubmit(e);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full transform transition-all">
        {/* Header */}
        <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-t-2xl p-6 text-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="bg-white bg-opacity-20 p-3 rounded-lg">
                <Shield className="h-8 w-8" />
              </div>
              <div>
                <h2 className="text-2xl font-bold">Admin Access</h2>
                <p className="text-blue-100 text-sm mt-1">Protected Dashboard</p>
              </div>
            </div>
            {onClose && (
              <button
                onClick={onClose}
                className="text-white hover:bg-white hover:bg-opacity-20 rounded-lg p-2 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            )}
          </div>
        </div>

        {/* Content */}
        <div className="p-8">
          <div className="mb-6">
            <div className="flex items-center gap-2 text-gray-600 mb-4">
              <Lock className="h-5 w-5" />
              <p className="text-sm">This dashboard requires administrator credentials</p>
            </div>
          </div>

          <form onSubmit={handleSubmit}>
            {/* Password Input */}
            <div className="mb-6">
              <label className="block text-sm font-semibold text-gray-700 mb-2">
                Admin Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onKeyPress={handleKeyPress}
                  placeholder="Enter admin password"
                  className="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-200 transition-all outline-none pr-12"
                  disabled={isLoading}
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700 transition-colors"
                  disabled={isLoading}
                >
                  {showPassword ? (
                    <EyeOff className="h-5 w-5" />
                  ) : (
                    <Eye className="h-5 w-5" />
                  )}
                </button>
              </div>
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={isLoading}
              className={`w-full py-3 rounded-lg font-semibold text-white transition-all ${
                isLoading
                  ? 'bg-gray-400 cursor-not-allowed'
                  : 'bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 shadow-lg hover:shadow-xl'
              }`}
            >
              {isLoading ? (
                <div className="flex items-center justify-center gap-2">
                  <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                  <span>Verifying...</span>
                </div>
              ) : (
                'Access Dashboard'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};

export default AdminPasswordModal;