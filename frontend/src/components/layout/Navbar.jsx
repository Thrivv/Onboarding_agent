// frontend/src/components/layout/Navbar.jsx

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import LanguageToggle from '../common/LanguageToggle';
import logo from '../../assets/logo-growx.svg';
import { LogOut, User, ChevronDown, Menu, X, ShieldCheck } from 'lucide-react';
const Navbar = () => {
  const { user, logout, isAdmin } = useAuth();
  const { t } = useLanguage();
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
              <img src={logo} alt="GrowX Logo" className="h-8 w-auto" />
            </Link>
          </div>

          {/* Desktop Navigation */}
          <div className="hidden md:flex items-center space-x-4">
            {user && (
              <>
                  <Link
                    to="/dashboard"
                    className="text-gray-700 hover:text-brand-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                  >
                    📊 {t('nav.dashboard')}
                  </Link>
                <Link
                  to="/ai-assistant"
                  className="text-gray-700 hover:text-brand-primary px-3 py-2 rounded-md text-sm font-medium transition-colors"
                >
                  💬 {t('nav.aiAssistant')}
                </Link>

                <LanguageToggle />

                {/* User Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setShowDropdown(!showDropdown)}
                    className="flex items-center space-x-2 text-gray-700 hover:text-brand-primary px-3 py-2 rounded-md text-sm font-medium transition-colors border border-gray-100 bg-gray-50/50 hover:bg-white"
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
                      <div className="absolute right-0 mt-2 w-56 bg-white rounded-xl shadow-2xl py-3 z-20 border border-gray-100 ring-4 ring-slate-100/30 overflow-hidden">
                        <div className="px-5 py-3 border-b border-gray-100 bg-slate-50/50">
                          <p className="text-xs font-black text-slate-400 uppercase tracking-widest mb-1">{t('nav.signedInAs')}</p>
                          <p className="text-sm font-black text-slate-800 leading-tight truncate">{user.name}</p>
                          <p className="text-[11px] font-bold text-slate-500 truncate">{user.email}</p>
                        </div>
                        
                        <div className="p-2 space-y-1">
                          {isAdmin() && (
                            <Link
                              to="/dashboard"
                              onClick={() => setShowDropdown(false)}
                              className="w-full text-left px-4 py-2 text-[13px] font-bold text-slate-700 hover:bg-indigo-50 hover:text-indigo-600 rounded-lg flex items-center gap-2 group transition-all"
                            >
                              <ShieldCheck className="h-4 w-4 opacity-40 group-hover:opacity-100" />
                              {t('nav.adminDashboard')}
                            </Link>
                          )}
                        </div>
                      </div>
                    </>
                  )}
                </div>

                {/* Independent Logout Button */}
                <button
                  onClick={handleLogout}
                  className="flex items-center gap-2 px-5 py-2.5 bg-slate-900 border border-slate-900 rounded-xl text-[11px] font-black text-white uppercase tracking-[0.2em] hover:bg-red-600 hover:border-red-600 transition-all shadow-xl shadow-slate-200 active:scale-95"
                >
                  <LogOut className="h-4 w-4" />
                  {t('nav.logout')}
                </button>
              </>
            )}
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden">
            <button
              onClick={() => setShowMobileMenu(!showMobileMenu)}
              className="text-gray-700 hover:text-brand-primary p-2"
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
        <div className="md:hidden border-t border-gray-200 bg-white shadow-inner">
          <div className="px-4 pt-2 pb-6 space-y-4">
            <div className="space-y-1">
              {isAdmin() && (
                <Link
                  to="/dashboard"
                  className="flex items-center gap-3 px-4 py-3 rounded-xl text-[15px] font-black text-slate-700 hover:bg-indigo-50 hover:text-indigo-600 border border-transparent hover:border-indigo-100"
                  onClick={() => setShowMobileMenu(false)}
                >
                  🛡️ {t('nav.adminDashboard')}
                </Link>
              )}
              
              <Link
                to="/ai-assistant"
                className="flex items-center gap-3 px-4 py-3 rounded-xl text-[15px] font-black text-slate-700 hover:bg-indigo-50 hover:text-indigo-600 border border-transparent hover:border-indigo-100"
                onClick={() => setShowMobileMenu(false)}
              >
                💬 {t('nav.aiAssistant')}
              </Link>

              <div className="px-1">
                <LanguageToggle />
              </div>
            </div>

            <div className="pt-4 border-t border-gray-100 space-y-4">
              <div className="px-4 py-4 bg-slate-50 rounded-2xl border border-slate-100">
                <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">{t('nav.activeUser')}</p>
                <p className="text-base font-black text-slate-800">{user.name}</p>
                <p className="text-[12px] font-bold text-slate-500">{user.email}</p>
              </div>
              
              <button
                onClick={() => {
                  setShowMobileMenu(false);
                  handleLogout();
                }}
                className="w-full flex items-center justify-center gap-2 py-4 bg-red-50 border border-red-100 text-red-600 rounded-2xl font-black uppercase tracking-widest text-[13px] hover:bg-red-600 hover:text-white hover:border-red-600 transition-all active:scale-95 shadow-lg shadow-red-100"
              >
                <LogOut className="h-5 w-5" />
                {t('nav.logoutAccount')}
              </button>
            </div>
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;