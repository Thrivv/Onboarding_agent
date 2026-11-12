// frontend/src/pages/Login.jsx 
import React, { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useLanguage } from '../context/LanguageContext';
import { toast } from 'react-hot-toast';
import logo from '../assets/logo-growx.svg';
import { Mail, Lock, Eye, EyeOff, Loader } from 'lucide-react';
import PremiumLoader from '../components/layout/PremiumLoader';
import logger from '../utils/logger';
import LanguageToggle from '../components/common/LanguageToggle';


const Login = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, user, loading: authLoading } = useAuth();
  const { t } = useLanguage();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });
  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});
  const [showPassword, setShowPassword] = useState(false);

  // Redirect if already logged in
  useEffect(() => {
    if (!authLoading && user) {
      const from = location.state?.from?.pathname || (user.role === 'admin' ? '/dashboard' : '/ai-assistant');
      navigate(from, { replace: true });
    }
  }, [user, authLoading, navigate, location]);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));

    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
  };

  const validateForm = () => {
    const newErrors = {};

    if (!formData.email.trim()) {
      newErrors.email = t('auth.login.errorEmailRequired');
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      newErrors.email = t('auth.login.errorEmailInvalid');
    }

    if (!formData.password) {
      newErrors.password = t('auth.login.errorPasswordRequired');
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!validateForm()) {
      return;
    }

    setLoading(true);

    try {
      await login(formData.email, formData.password);
    } catch (error) {
      logger.error('[LOGIN] Unexpected error:', error);
      toast.error(t('auth.login.unexpectedError'));
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) {
    return <PremiumLoader />;
  }

  return (
    <div className="gx-main-layout">
      <div className="fixed top-4 right-4 z-10">
        <LanguageToggle />
      </div>
      <div className="max-w-md w-full">
        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="flex justify-center mb-4 w-full">
              <img src={logo} alt="Thrivv.ai Logo" className="h-16 w-auto max-w-full object-contain" />
            </div>
            <h1 className="gx-welcome">
              {t('auth.login.welcomeBack')}
            </h1>
            <h2 className="gx-sub">
              {t('auth.login.loginTo')} <span className='gx-get-started'>{t('auth.login.yourAccount')}</span>
            </h2>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email Field */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1.5 ml-1">
                {t('auth.login.emailAddress')}
              </label>
              <div className="relative group">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                  <Mail className="h-5 w-5" />
                </div>
                <input
                  type="email"
                  name="email"
                  value={formData.email}
                  onChange={handleChange}
                  className={`gx-input gx-input-icon ${errors.email ? "gx-input-error" : ""
                    }`}
                  placeholder="name@example.com"
                  disabled={loading}
                />
              </div>
              {errors.email && (
                <p className="text-red-600 text-xs mt-1.5 ml-1">
                  {errors.email}
                </p>
              )}
            </div>

            {/* Password Field */}
            <div>
              <div className="flex items-center justify-between px-1 mb-1.5">
                <label className="block text-sm font-medium text-gray-700">
                  {t('auth.login.password')}
                </label>
                <Link to="/reset-password" className="text-xs text-brand-primary hover:text-gray-700 font-medium">
                  {t('auth.login.forgotPassword')}
                </Link>
              </div>
              <div className="relative group">
                <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                  <Lock className="h-5 w-5" />
                </div>
                <input
                  type={showPassword ? "text" : "password"}
                  name="password"
                  value={formData.password}
                  onChange={handleChange}
                  className={`gx-input gx-input-password ${errors.password ? "gx-input-error" : ""
                    }`}
                  placeholder="••••••••"
                  disabled={loading}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500"
                >
                  {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                </button>
              </div>
              {errors.password && (
                <p className="text-red-600 text-xs mt-1.5 ml-1">
                  {errors.password}
                </p>
              )}
            </div>

            {/* Submit Button */}
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-brand-primary hover:bg-brand-primary-dark text-white py-3 rounded-xl font-semibold shadow-lg transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading ? (
                <Loader className="h-5 w-5 animate-spin mx-auto text-white" />
              ) : (
                t('auth.login.signIn')
              )}
            </button>
          </form>

          {/* Footer Link */}
          <div className="mt-8 text-center text-sm">
            <p className="text-gray-600">
              {t('auth.login.noAccount')}{' '}
              <Link to="/signup" className="text-brand-primary hover:text-gray-700 font-medium">
                {t('auth.login.createOne')}
              </Link>
            </p>
          </div>
        </div>

        {/* Copyright */}
        <p className="text-center text-xs text-gray-400 mt-8">
          © {new Date().getFullYear()} Thrivv.AI • All rights reserved.
        </p>
      </div>
    </div>
  );
};

export default Login;