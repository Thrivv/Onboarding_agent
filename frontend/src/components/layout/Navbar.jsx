// frontend/src/components/layout/Navbar.jsx

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { LogOut, User, ChevronDown, Menu, X } from 'lucide-react';

const Navbar = () => {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();
  const [showDropdown, setShowDropdown] = useState(false);
  const [showMobileMenu, setShowMobileMenu] = useState(false);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <nav className="bg-white shadow-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          {/* Logo */}
          <div className="flex items-center">
            <Link to="/" className="flex items-center space-x-2">
              <span className="text-2xl font-bold gradient-text">🏦 Thrivv</span>
            </Link>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center space-x-4">
            {user && (
              <>
                {isAdmin() && (
                  <Link
                    to="/dashboard"
                    className="text-gray-700 hover:text-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    📊 Dashboard
                  </Link>
                )}
                
                <Link
                  to="/ai-assistant"
                  className="text-gray-700 hover:text-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  💬 AI Assistant
                </Link>
                
                <Link
                  to="/document-upload"
                  className="text-gray-700 hover:text-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  📄 Documents
                </Link>

                {/* User Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setShowDropdown(!showDropdown)}
                    className="flex items-center space-x-2 text-gray-700 hover:text-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    <User className="h-5 w-5" />
                    <span>{user.name}</span>
                    <ChevronDown className="h-4 w-4" />
                  </button>

                  {showDropdown && (
                    <>
                      {/* Backdrop */}
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setShowDropdown(false)}
                      ></div>

                      {/* Dropdown Menu */}
                      <div className="absolute right-0 mt-2 w-48 bg-white rounded-lg shadow-xl py-2 z-20">
                        <div className="px-4 py-2 border-b border-gray-200">
                          <p className="text-sm font-medium text-gray-900">{user.name}</p>
                          <p className="text-xs text-gray-500">{user.email}</p>
                          <p className="text-xs text-primary font-semibold mt-1">
                            {user.role === 'admin' ? '👑 Admin' : '👤 User'}
                          </p>
                        </div>
                        
                        <button
                          onClick={handleLogout}
                          className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50 flex items-center space-x-2"
                        >
                          <LogOut className="h-4 w-4" />
                          <span>Logout</span>
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </>
            )}
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden">
            <button
              onClick={() => setShowMobileMenu(!showMobileMenu)}
              className="text-gray-700 hover:text-primary p-2"
            >
              {showMobileMenu ? (
                <X className="h-6 w-6" />
              ) : (
                <Menu className="h-6 w-6" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu */}
      {showMobileMenu && user && (
        <div className="md:hidden border-t border-gray-200">
          <div className="px-2 pt-2 pb-3 space-y-1">
            {isAdmin() && (
              <Link
                to="/dashboard"
                className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 hover:text-primary hover:bg-gray-50"
                onClick={() => setShowMobileMenu(false)}
              >
                📊 Dashboard
              </Link>
            )}
            
            <Link
              to="/ai-assistant"
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 hover:text-primary hover:bg-gray-50"
              onClick={() => setShowMobileMenu(false)}
            >
              💬 AI Assistant
            </Link>
            
            <Link
              to="/document-upload"
              className="block px-3 py-2 rounded-md text-base font-medium text-gray-700 hover:text-primary hover:bg-gray-50"
              onClick={() => setShowMobileMenu(false)}
            >
              📄 Documents
            </Link>

            <div className="border-t border-gray-200 pt-2">
              <div className="px-3 py-2">
                <p className="text-sm font-medium text-gray-900">{user.name}</p>
                <p className="text-xs text-gray-500">{user.email}</p>
              </div>
              
              <button
                onClick={() => {
                  setShowMobileMenu(false);
                  handleLogout();
                }}
                className="w-full text-left px-3 py-2 text-base font-medium text-red-600 hover:bg-red-50"
              >
                <LogOut className="h-4 w-4 inline mr-2" />
                Logout
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;