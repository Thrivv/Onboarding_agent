// frontend/src/components/layout/Sidebar.jsx

import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, 
  MessageSquare, 
  Upload, 
  LogOut,
  ChevronRight,
  User,
  ChevronDown,
  ChevronUp,
  Mail,
  Calendar,
  Shield
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import toast from 'react-hot-toast';

const Sidebar = () => {
  const location = useLocation();
  const { user, logout } = useAuth();
  const [showUserDetails, setShowUserDetails] = useState(false);

  const handleLogout = () => {
    logout();
    toast.success('Logged out successfully');
  };

  // Get user initials
  const getUserInitials = (name) => {
    if (!name) return '?';
    const parts = name.split(' ');
    if (parts.length >= 2) {
      return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    }
    return name[0].toUpperCase();
  };

  // Navigation items array
  const navigationItems = [
    { 
      name: 'Dashboard', 
      path: '/dashboard', 
      icon: LayoutDashboard,
      description: 'Overview & Analytics'
    },
    { 
      name: 'AI Assistant', 
      path: '/ai-assistant', 
      icon: MessageSquare,
      description: 'Chat & Document Help'
    },
    { 
      name: 'Document Upload', 
      path: '/document-upload', 
      icon: Upload,
      description: 'Upload & Manage Docs'
    }
  ];

  return (
    <div className="h-screen w-64 bg-gradient-to-b from-gray-900 via-gray-800 to-gray-900 text-white flex flex-col shadow-2xl fixed left-0 top-0">
      {/* Header */}
      <div className="p-6 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <div className="bg-gradient-to-r from-blue-500 to-purple-600 p-2 rounded-lg">
            <LayoutDashboard className="h-6 w-6 text-white" />
          </div>
          <div>
            <h2 className="text-xl font-bold">Thrivv</h2>
            <p className="text-xs text-gray-400">Onboarding Portal</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4 py-6 space-y-2 overflow-y-auto">
        {navigationItems.map((item) => {
          const isActive = location.pathname === item.path;
          const Icon = item.icon;

          return (
            <Link
              key={item.path}
              to={item.path}
              className={`group flex items-center justify-between px-4 py-3 rounded-lg transition-all duration-200 ${
                isActive
                  ? 'bg-gradient-to-r from-blue-600 to-purple-600 shadow-lg'
                  : 'hover:bg-gray-800 hover:shadow-md'
              }`}
            >
              <div className="flex items-center gap-3 flex-1">
                <Icon 
                  className={`h-5 w-5 ${
                    isActive ? 'text-white' : 'text-gray-400 group-hover:text-white'
                  }`} 
                />
                <div className="flex-1">
                  <p className={`font-semibold ${
                    isActive ? 'text-white' : 'text-gray-300 group-hover:text-white'
                  }`}>
                    {item.name}
                  </p>
                  <p className={`text-xs ${
                    isActive ? 'text-blue-100' : 'text-gray-500 group-hover:text-gray-400'
                  }`}>
                    {item.description}
                  </p>
                </div>
              </div>
              
              {isActive && (
                <ChevronRight className="h-4 w-4 text-white" />
              )}
            </Link>
          );
        })}
      </nav>

      {/* User Info Section */}
      <div className="px-4 pb-4 border-t border-gray-700">
        <div className="mt-4">
          {/* User Card - Clickable */}
          <button
            onClick={() => setShowUserDetails(!showUserDetails)}
            className="w-full bg-gray-800 hover:bg-gray-750 rounded-lg p-3 transition-all duration-200 border border-gray-700 hover:border-gray-600"
          >
            <div className="flex items-center gap-3">
              {/* Avatar */}
              <div className="bg-gradient-to-br from-blue-500 to-purple-600 w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm">
                {getUserInitials(user?.name)}
              </div>
              
              {/* User Info */}
              <div className="flex-1 text-left">
                <p className="font-semibold text-white text-sm truncate">
                  {user?.name || 'User'}
                </p>
                <p className="text-xs text-gray-400 truncate">
                  {user?.email?.length > 20 
                    ? `${user.email.substring(0, 20)}...` 
                    : user?.email}
                </p>
              </div>
              
              {/* Expand Icon */}
              {showUserDetails ? (
                <ChevronUp className="h-4 w-4 text-gray-400" />
              ) : (
                <ChevronDown className="h-4 w-4 text-gray-400" />
              )}
            </div>
          </button>

          {/* Expandable Details Panel */}
          <div 
            className={`overflow-hidden transition-all duration-300 ease-in-out ${
              showUserDetails ? 'max-h-64 opacity-100 mt-2' : 'max-h-0 opacity-0'
            }`}
          >
            <div className="bg-gray-800 rounded-lg p-4 border border-gray-700 space-y-3">
              {/* Full Email */}
              <div className="flex items-start gap-3">
                <Mail className="h-4 w-4 text-blue-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-400 mb-0.5">Email</p>
                  <p className="text-sm text-white break-all">{user?.email}</p>
                </div>
              </div>

              {/* Account Type */}
              {user?.accountType && (
                <div className="flex items-start gap-3">
                  <Shield className="h-4 w-4 text-purple-400 mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-xs text-gray-400 mb-0.5">Account Type</p>
                    <p className="text-sm text-white">{user.accountType}</p>
                  </div>
                </div>
              )}

              {/* Status */}
              {user?.status && (
                <div className="flex items-start gap-3">
                  <User className="h-4 w-4 text-green-400 mt-0.5 flex-shrink-0" />
                  <div className="flex-1">
                    <p className="text-xs text-gray-400 mb-0.5">Status</p>
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${
                        user.status === 'active' ? 'bg-green-500' : 'bg-yellow-500'
                      }`}></div>
                      <p className="text-sm text-white capitalize">{user.status}</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Member Since */}
              <div className="flex items-start gap-3">
                <Calendar className="h-4 w-4 text-yellow-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1">
                  <p className="text-xs text-gray-400 mb-0.5">Member Since</p>
                  <p className="text-sm text-white">
                    {user?.createdAt 
                      ? new Date(user.createdAt).toLocaleDateString('en-US', { 
                          month: 'short', 
                          year: 'numeric' 
                        })
                      : 'Recently'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Logout Button */}
        <button
          onClick={handleLogout}
          className="w-full mt-4 flex items-center gap-3 px-4 py-3 rounded-lg bg-red-600 hover:bg-red-700 transition-all duration-200 shadow-lg hover:shadow-xl"
        >
          <LogOut className="h-5 w-5" />
          <span className="font-semibold">Logout</span>
        </button>
      </div>
    </div>
  );
};

export default Sidebar;