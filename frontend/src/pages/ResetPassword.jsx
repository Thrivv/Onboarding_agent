// frontend/src/pages/ResetPassword.jsx
//
// New page: a self-service password-reset flow, added alongside the switch
// to bcrypt password hashing (see backend/app/services/auth_service.py).
// Existing accounts had their SHA-256 hashes invalidated by
// backend/scripts/force_password_reset.py and cannot log in again without
// going through this — and login (AuthContext.jsx) redirects here
// automatically when the backend reports `PasswordResetRequiredError`.
//
// Two steps, both backed by the existing OTP infrastructure
// (app/services/email_otp_service.py): request a code by email, then submit
// the code plus a new password.

import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'react-hot-toast';
import { Mail, Lock, KeyRound, Eye, EyeOff, Loader } from 'lucide-react';
import logo from '../assets/logo-growx.svg';
import { requestPasswordReset, resetPassword } from '../api/auth';
import logger from '../utils/logger';
import { useLanguage } from '../context/LanguageContext';

const buildPasswordRules = (t) => [
  { test: (v) => v.length >= 8, label: t('auth.reset.ruleLength') },
  { test: (v) => /[A-Z]/.test(v), label: t('auth.reset.ruleUppercase') },
  { test: (v) => /[a-z]/.test(v), label: t('auth.reset.ruleLowercase') },
  { test: (v) => /\d/.test(v), label: t('auth.reset.ruleNumber') },
  { test: (v) => /[!@#$%^&*(),.?":{}|<>]/.test(v), label: t('auth.reset.ruleSpecial') },
];

const ResetPassword = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useLanguage();
  const PASSWORD_RULES = buildPasswordRules(t);

  const [step, setStep] = useState(1); // 1 = request code, 2 = set new password
  const [email, setEmail] = useState(location.state?.email || '');
  const [otp, setOtp] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleRequestCode = async (e) => {
    e.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError(t('auth.reset.errorEmailInvalid'));
      return;
    }
    setError('');
    setLoading(true);
    try {
      await requestPasswordReset({ email });
      toast.success(t('auth.reset.toastCodeSent'));
      setStep(2);
    } catch (err) {
      logger.error('[RESET] request-code error:', err);
      // The backend intentionally returns success even for unknown emails
      // (see auth.py's request_password_reset), so a caught error here means
      // something else went wrong (network, rate limit) — surface that.
      const msg = err.response?.data?.detail || t('auth.reset.toastCodeFailed');
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const failedRules = PASSWORD_RULES.filter((r) => !r.test(newPassword));

  const handleResetPassword = async (e) => {
    e.preventDefault();
    if (!otp.trim()) {
      setError(t('auth.reset.errorOtpRequired'));
      return;
    }
    if (failedRules.length > 0) {
      setError(t('auth.reset.errorPasswordRules'));
      return;
    }
    if (newPassword !== confirmPassword) {
      setError(t('auth.reset.errorPasswordsMismatch'));
      return;
    }

    setError('');
    setLoading(true);
    try {
      await resetPassword({ email, otp: otp.trim(), new_password: newPassword });
      toast.success(t('auth.reset.toastPasswordUpdated'));
      navigate('/login', { replace: true });
    } catch (err) {
      logger.error('[RESET] reset-password error:', err);
      const msg = err.response?.data?.detail || t('auth.reset.toastResetFailed');
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="gx-main-layout">
      <div className="max-w-md w-full">
        <div className="bg-white rounded-2xl shadow-xl p-8 border border-gray-100">
          <div className="text-center mb-8">
            <div className="flex justify-center mb-4 w-full">
              <img src={logo} alt="Thrivv.ai Logo" className="h-16 w-auto max-w-full object-contain" />
            </div>
            <h1 className="gx-welcome">{t('auth.reset.resetYourPassword')}</h1>
            <h2 className="gx-sub">
              {step === 1
                ? t('auth.reset.subtitleRequest')
                : t('auth.reset.subtitleReset')}
            </h2>
          </div>

          {step === 1 ? (
            <form onSubmit={handleRequestCode} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5 ml-1">
                  {t('auth.reset.emailAddress')}
                </label>
                <div className="relative group">
                  <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                    <Mail className="h-5 w-5" />
                  </div>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="gx-input gx-input-icon"
                    placeholder="name@example.com"
                    disabled={loading}
                  />
                </div>
              </div>

              {error && <p className="text-red-600 text-xs ml-1">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-brand-primary hover:bg-brand-primary-dark text-white py-3 rounded-xl font-semibold shadow-lg transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {loading ? <Loader className="h-5 w-5 animate-spin" /> : t('auth.reset.sendResetCode')}
              </button>
            </form>
          ) : (
            <form onSubmit={handleResetPassword} className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5 ml-1">
                  {t('auth.reset.resetCode')}
                </label>
                <div className="relative group">
                  <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                    <KeyRound className="h-5 w-5" />
                  </div>
                  <input
                    type="text"
                    value={otp}
                    onChange={(e) => setOtp(e.target.value)}
                    className="gx-input gx-input-icon"
                    placeholder="6-digit code"
                    disabled={loading}
                    maxLength={6}
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5 ml-1">
                  {t('auth.reset.newPassword')}
                </label>
                <div className="relative group">
                  <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                    <Lock className="h-5 w-5" />
                  </div>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    className="gx-input gx-input-password"
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
                {newPassword && (
                  <ul className="mt-2 ml-1 space-y-0.5">
                    {PASSWORD_RULES.map((rule) => (
                      <li
                        key={rule.label}
                        className={`text-xs ${rule.test(newPassword) ? 'text-green-600' : 'text-gray-400'}`}
                      >
                        {rule.test(newPassword) ? '✓' : '○'} {rule.label}
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1.5 ml-1">
                  {t('auth.reset.confirmNewPassword')}
                </label>
                <div className="relative group">
                  <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-brand-secondary">
                    <Lock className="h-5 w-5" />
                  </div>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    className="gx-input gx-input-password"
                    placeholder="••••••••"
                    disabled={loading}
                  />
                </div>
              </div>

              {error && <p className="text-red-600 text-xs ml-1">{error}</p>}

              <button
                type="submit"
                disabled={loading}
                className="w-full bg-brand-primary hover:bg-brand-primary-dark text-white py-3 rounded-xl font-semibold shadow-lg transition-all disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {loading ? <Loader className="h-5 w-5 animate-spin" /> : t('auth.reset.updatePassword')}
              </button>

              <button
                type="button"
                onClick={() => setStep(1)}
                className="w-full text-sm text-gray-500 hover:text-gray-700"
                disabled={loading}
              >
                {t('auth.reset.resendCode')}
              </button>
            </form>
          )}

          <div className="mt-8 text-center text-sm">
            <p className="text-gray-600">
              {t('auth.reset.rememberedPassword')}{' '}
              <Link to="/login" className="text-brand-primary hover:text-gray-700 font-medium">
                {t('auth.reset.backToLogin')}
              </Link>
            </p>
          </div>
        </div>

        <p className="text-center text-xs text-gray-400 mt-8">
          © {new Date().getFullYear()} Thrivv.AI • All rights reserved.
        </p>
      </div>
    </div>
  );
};

export default ResetPassword;
