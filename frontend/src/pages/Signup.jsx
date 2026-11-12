// frontend/src/pages/Signup.jsx

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { generateOtp, signup, verifyOtp } from '../api/auth';
import logo from '../assets/logo-growx.svg';
import { toast } from 'react-hot-toast';
import { CheckCircle, Mail, ShieldCheck, Loader, Lock, Eye, EyeOff, Calendar, Check, X } from 'lucide-react';
import { validatePassword } from '../utils/validation';
import { useLanguage } from '../context/LanguageContext';
import LanguageToggle from '../components/common/LanguageToggle';

const TERMS_SECTIONS = [
  ['1. Data Collection and Use', 'We collect personal and financial information including identification documents, income statements, transaction history, and contact details to provide banking services, comply with regulatory requirements, and improve our offerings.'],
  ['2. Information Sharing with Regulatory Bodies', 'Your personal and account information may be shared with regulatory authorities including the Central Bank, Financial Intelligence Unit, tax authorities, and other governmental bodies as required by applicable laws.'],
  ['3. Third-Party Service Providers', 'We may share your information with trusted third-party service providers who assist in delivering banking services. These parties are contractually bound to maintain confidentiality.'],
  ['4. Credit Reporting and Risk Assessment', 'Your credit information, payment history, and account behavior may be shared with credit bureaus and used for credit scoring, risk assessment, and fraud prevention.'],
  ['5. AML and KYC', 'We are required to collect, verify, and share customer information with relevant authorities for AML and KYC compliance. This includes monitoring transactions and reporting suspicious activities.'],
  ['6. Data Retention', 'Personal information will be retained for the minimum period required by law, typically 5–10 years after account closure. Data is stored securely using industry-standard encryption.'],
  ['7. Cross-Border Transfers', 'Your information may be transferred to and processed in countries outside the UAE for operational or regulatory purposes in compliance with applicable data protection laws.'],
  ['8. Marketing Consent', 'By accepting these terms, you consent to receive marketing communications about our products. You may opt-out at any time.'],
  ['9. Data Security', 'We implement robust security measures to protect your information and will notify you and relevant authorities in the event of a data breach within timeframes required by applicable law.'],
  ['10. Customer Rights', 'You have the right to access, correct, update, or request deletion of your personal information subject to legal and regulatory requirements.'],
];

const Signup = () => {
  const navigate = useNavigate();
  const { t } = useLanguage();

  const [loading, setLoading] = useState(false);
  const [otpLoading, setOtpLoading] = useState(false);
  const [otpSent, setOtpSent] = useState(false);
  const [otpVerified, setOtpVerified] = useState(false);
  const [otpValue, setOtpValue] = useState('');
  const [showOtpPanel, setShowOtpPanel] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);

  const [formData, setFormData] = useState({
    first_name: '',
    last_name: '',
    dob: '',
    phone_number: '',
    email: '',
    business_name: '', // Company Name — field name kept for backend/API compatibility
    password: '',
    confirmPassword: '',
    account_type: 'Corporate',
    terms_accepted: false,
  });

  const [errors, setErrors] = useState({});

  const calculateAge = (dob) => {
    if (!dob) return null;
    const today = new Date();
    const birthDate = new Date(dob);
    let age = today.getFullYear() - birthDate.getFullYear();
    const m = today.getMonth() - birthDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return age;
  };

  // ── password rule checklist (live, as-you-type) ──
  const passwordChecks = {
    length: formData.password.length >= 8,
    uppercase: /[A-Z]/.test(formData.password),
    lowercase: /[a-z]/.test(formData.password),
    number: /[0-9]/.test(formData.password),
    special: /[!@#$%^&*(),.?":{}|<>]/.test(formData.password),
  };

  // ── helpers ──
  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;

    setFormData((prev) => ({ ...prev, [name]: type === 'checkbox' ? checked : value }));
    if (errors[name]) setErrors((prev) => ({ ...prev, [name]: '' }));

    if (name === 'email') {
      setOtpSent(false);
      setOtpVerified(false);
      setOtpValue('');
      setShowOtpPanel(false);
    }
  };

  // ── validation (whole form, single page) ──
  const validateForm = () => {
    const errs = {};
    if (!formData.first_name.trim()) errs.first_name = t('auth.signup.errorFirstNameRequired');
    if (!formData.last_name.trim()) errs.last_name = t('auth.signup.errorLastNameRequired');
    if (!formData.phone_number.trim()) {
      errs.phone_number = t('auth.signup.errorPhoneRequired');
    } else if (!/^\+?[\d\s\-()]+$/.test(formData.phone_number)) {
      errs.phone_number = t('auth.signup.errorPhoneInvalid');
    }
    if (!formData.email.trim()) {
      errs.email = t('auth.signup.errorEmailRequired');
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      errs.email = t('auth.signup.errorEmailInvalid');
    }
    if (!otpVerified) {
      errs.email = errs.email || t('auth.signup.errorEmailNotVerified');
    }
    if (!formData.business_name.trim()) errs.business_name = t('auth.signup.errorCompanyRequired');

    if (!formData.password) {
      errs.password = t('auth.signup.errorPasswordRequired');
    } else {
      const { isValid, errors: pwErrors } = validatePassword(formData.password);
      if (!isValid) errs.password = pwErrors[0];
    }
    if (formData.password !== formData.confirmPassword) {
      errs.confirmPassword = t('auth.signup.errorPasswordsMismatch');
    }
    if (!formData.terms_accepted) errs.terms_accepted = t('auth.signup.errorTermsRequired');

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const extractErrorMessage = (err) => {
    const detail = err.response?.data?.detail;
    if (!detail) return null;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map(d => (typeof d === 'object' ? (d.msg || d.message || JSON.stringify(d)) : String(d))).join(', ');
    }
    if (typeof detail === 'object') return detail.msg || detail.message || JSON.stringify(detail);
    return String(detail);
  };

  // ── OTP flow ──
  const isEmailValid = () =>
    formData.email.trim() && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email);

  const handleSendOtp = async () => {
    if (!isEmailValid()) {
      setErrors((prev) => ({ ...prev, email: t('auth.signup.errorEmailForOtp') }));
      return;
    }
    setOtpLoading(true);
    try {
      await generateOtp({ email: formData.email });
      setOtpSent(true);
      setShowOtpPanel(true);
      toast.success(t('auth.signup.toastOtpSent', { email: formData.email }));
    } catch (err) {
      toast.error(extractErrorMessage(err) || t('auth.signup.toastOtpFailed'));
    } finally {
      setOtpLoading(false);
    }
  };

  const handleVerifyOtp = async () => {
    if (!otpValue.trim() || otpValue.trim().length !== 6) {
      setErrors((prev) => ({ ...prev, otp: t('auth.signup.errorOtpRequired') }));
      return;
    }
    setOtpLoading(true);
    try {
      await verifyOtp({ email: formData.email, otp: otpValue });
      setOtpVerified(true);
      setShowOtpPanel(false);
      toast.success(t('auth.signup.toastEmailVerified'));
    } catch (err) {
      setErrors((prev) => ({ ...prev, otp: extractErrorMessage(err) || t('auth.signup.errorOtpInvalid') }));
    } finally {
      setOtpLoading(false);
    }
  };

  // ── submit ──
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validateForm()) return;
    setLoading(true);
    try {
      const payload = {
        email: formData.email,
        password: formData.password,
        first_name: formData.first_name.trim(),
        last_name: formData.last_name.trim(),
        name: `${formData.first_name.trim()} ${formData.last_name.trim()}`,
        dob: formData.dob || null,
        phone_number: formData.phone_number,
        business_name: formData.business_name,
        account_type: formData.account_type,
        channel: '',
        nature_of_business: [],
        terms_accepted: formData.terms_accepted,
      };
      const response = await signup(payload);
      if (response.data) {
        toast.success(t('auth.signup.toastSuccess'));
        setTimeout(() => {
          navigate('/login');
        }, 1500);
      }
    } catch (error) {
      if (error.response?.status === 409) {
        toast.error(t('auth.signup.toastEmailTaken'));
      } else {
        toast.error(extractErrorMessage(error) || t('auth.signup.toastSignupFailed'));
      }
    } finally {
      setLoading(false);
    }
  };

  const PasswordRule = ({ met, label }) => (
    <div
      className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
        met ? 'bg-green-50 border-green-200 text-green-700' : 'bg-white border-gray-200 text-gray-400'
      }`}
    >
      {met ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
      {label}
    </div>
  );

  // ── render ──
  return (
    <div className="gx-main-layout">
      <div className="fixed top-4 right-4 z-10">
        <LanguageToggle />
      </div>
      <div className="max-w-2xl w-full">
        <div className="bg-white rounded-2xl shadow-xl p-8">

          {/* HEADER */}
          <div className="text-center mb-8">
            <div className="flex justify-center mb-3 w-full">
              <img src={logo} alt="Thrivv.ai Logo" className="h-16 w-auto max-w-full object-contain" />
            </div>
            <h1 className="text-3xl font-bold gradient-text">
              {t('auth.signup.createAccount')}
            </h1>
          </div>

          <form onSubmit={handleSubmit}>
            <div className="space-y-4">

              {/* First Name + Last Name */}
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {t('auth.signup.firstName')} <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    name="first_name"
                    value={formData.first_name}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.first_name ? 'border-red-500' : 'border-gray-300'}`}
                    placeholder="First name"
                  />
                  {errors.first_name && <p className="text-red-500 text-sm mt-1">{errors.first_name}</p>}
                </div>
                <div className="flex-1">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    {t('auth.signup.lastName')} <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    name="last_name"
                    value={formData.last_name}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.last_name ? 'border-red-500' : 'border-gray-300'}`}
                    placeholder="Last name"
                  />
                  {errors.last_name && <p className="text-red-500 text-sm mt-1">{errors.last_name}</p>}
                </div>
              </div>

              {/* DOB optional */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('auth.signup.dateOfBirth')} <span className="text-gray-400 text-xs font-normal">{t('auth.signup.optional')}</span>
                </label>
                <input
                  type="date"
                  name="dob"
                  value={formData.dob}
                  onChange={handleChange}
                  max={new Date().toISOString().split('T')[0]}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                {formData.dob && (
                  <div className="flex items-center gap-2 text-xs text-gray-400 mt-2 opacity-70 animate-in slide-in-from-top-1 duration-300">
                    <Calendar className="h-3.5 w-3.5 text-gray-400" />
                    {t('auth.signup.age', { age: calculateAge(formData.dob) })}
                  </div>
                )}
              </div>

              {/* Phone */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('auth.signup.phoneNumber')} <span className="text-red-500">*</span>
                </label>
                <input
                  type="tel"
                  name="phone_number"
                  value={formData.phone_number}
                  onChange={handleChange}
                  className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.phone_number ? 'border-red-500' : 'border-gray-300'}`}
                  placeholder="+971-XX-XXX-XXXX"
                />
                {errors.phone_number && <p className="text-red-500 text-sm mt-1">{errors.phone_number}</p>}
              </div>

              {/* Email + OTP inline */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('auth.signup.email')} <span className="text-red-500">*</span>
                </label>
                <div className="flex gap-2">
                  <input
                    type="email"
                    name="email"
                    value={formData.email}
                    onChange={handleChange}
                    disabled={otpVerified}
                    className={`flex-1 px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.email ? 'border-red-500' : otpVerified ? 'border-green-400 bg-green-50' : 'border-gray-300'
                      }`}
                    placeholder="your@email.com"
                  />
                  {otpVerified ? (
                    <span className="flex items-center gap-1 px-3 py-2 bg-green-100 text-green-700 rounded-lg text-sm font-medium border border-green-300 whitespace-nowrap">
                      <CheckCircle className="h-4 w-4" /> {t('auth.signup.verified')}
                    </span>
                  ) : (
                    <button
                      type="button"
                      onClick={handleSendOtp}
                      disabled={otpLoading || !isEmailValid()}
                      className="flex items-center gap-1 px-4 py-2 gradient-btn text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40 whitespace-nowrap"
                    >
                      {otpLoading ? <Loader className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                      {otpSent ? t('auth.signup.resend') : t('auth.signup.sendOtp')}
                    </button>
                  )}
                </div>
                {errors.email && <p className="text-red-500 text-sm mt-1">{errors.email}</p>}
              </div>

              {/* OTP drop-down panel */}
              {showOtpPanel && !otpVerified && (
                <div
                  className="overflow-hidden transition-all duration-300"
                  style={{ animation: 'slideDown 0.3s ease-out' }}
                >
                  <style>{`
                  @keyframes slideDown {
                    from { opacity: 0; transform: translateY(-10px); }
                    to   { opacity: 1; transform: translateY(0); }
                  }
                `}</style>
                  <div className="border border-blue-200 bg-blue-50 rounded-xl p-4 space-y-3">
                    <div className="flex items-center gap-2 text-sm text-brand-secondary-dark">
                      <Mail className="h-4 w-4 flex-shrink-0" />
                      <span>{t('auth.signup.otpSentTo', { email: formData.email })}</span>
                    </div>
                    <div>
                      <input
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        value={otpValue}
                        onChange={(e) => {
                          setOtpValue(e.target.value.replace(/\D/g, ''));
                          if (errors.otp) setErrors((prev) => ({ ...prev, otp: '' }));
                        }}
                        className={`w-full px-4 py-3 text-center text-2xl tracking-[0.5em] border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent bg-white ${errors.otp ? 'border-red-400' : 'border-blue-300'}`}
                        placeholder={t('auth.signup.otpPlaceholder')}
                        autoFocus
                      />
                      {errors.otp && <p className="text-red-500 text-sm mt-1">{errors.otp}</p>}
                    </div>
                    <button
                      type="button"
                      onClick={handleVerifyOtp}
                      disabled={otpLoading || otpValue.length !== 6}
                      className="w-full flex items-center justify-center gap-2 gradient-btn text-white px-4 py-2 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-40 text-sm font-medium"
                    >
                      {otpLoading
                        ? <><Loader className="h-4 w-4 animate-spin" /> {t('auth.signup.verifying')}</>
                        : <><ShieldCheck className="h-4 w-4" /> {t('auth.signup.verifyAndConfirm')}</>}
                    </button>
                  </div>
                </div>
              )}

              {/* Company Name */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  {t('auth.signup.companyName')} <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  name="business_name"
                  value={formData.business_name}
                  onChange={handleChange}
                  className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.business_name ? 'border-red-500' : 'border-gray-300'}`}
                  placeholder="Your company LLC"
                />
                {errors.business_name && <p className="text-red-500 text-sm mt-1">{errors.business_name}</p>}
              </div>

              {/* Password — locked until OTP verified */}
              <div className={`transition-opacity duration-300 ${otpVerified ? 'opacity-100' : 'opacity-40 pointer-events-none'}`}>
                {!otpVerified && (
                  <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
                    <Lock className="h-3.5 w-3.5" />
                    {t('auth.signup.unlockPasswordHint')}
                  </div>
                )}
                <div className="space-y-2">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      {t('auth.signup.password')} <span className="text-red-500">*</span>
                    </label>
                    <div className="relative group">
                      <input
                        type={showPassword ? 'text' : 'password'}
                        name="password"
                        value={formData.password}
                        onChange={handleChange}
                        disabled={!otpVerified}
                        className={`w-full px-4 pr-12 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.password ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="Minimum 8 characters"
                      />
                      {formData.password && (
                        <button
                          type="button"
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 focus:outline-none transition-all duration-200"
                          onClick={() => setShowPassword(!showPassword)}
                          disabled={!otpVerified}
                        >
                          {showPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                        </button>
                      )}
                    </div>
                    {errors.password && <p className="text-red-500 text-sm mt-1">{errors.password}</p>}

                    {/* Real-time password requirements checklist */}
                    <div className="flex items-center gap-2 flex-wrap mt-2 p-3 bg-gray-50 rounded-lg">
                      <PasswordRule met={passwordChecks.length} label={t('auth.signup.ruleLength')} />
                      <PasswordRule met={passwordChecks.uppercase} label={t('auth.signup.ruleUppercase')} />
                      <PasswordRule met={passwordChecks.lowercase} label={t('auth.signup.ruleLowercase')} />
                      <PasswordRule met={passwordChecks.number} label={t('auth.signup.ruleNumber')} />
                      <PasswordRule met={passwordChecks.special} label={t('auth.signup.ruleSpecial')} />
                    </div>
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      {t('auth.signup.confirmPassword')} <span className="text-red-500">*</span>
                    </label>
                    <div className="relative group">
                      <input
                        type={showConfirmPassword ? 'text' : 'password'}
                        name="confirmPassword"
                        value={formData.confirmPassword}
                        onChange={handleChange}
                        disabled={!otpVerified}
                        className={`w-full px-4 pr-12 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${errors.confirmPassword ? 'border-red-500' : 'border-gray-300'}`}
                        placeholder="Re-enter password"
                      />
                      {formData.confirmPassword && (
                        <button
                          type="button"
                          className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 focus:outline-none transition-all duration-200"
                          onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                          disabled={!otpVerified}
                        >
                          {showConfirmPassword ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                        </button>
                      )}
                    </div>
                    {errors.confirmPassword && <p className="text-red-500 text-sm mt-1">{errors.confirmPassword}</p>}
                  </div>
                </div>
              </div>

              {/* Terms & Conditions — compact checkbox with hyperlink; full text opens in a popup */}
              <div className="mt-2">
                <label className="flex items-start cursor-pointer p-3 bg-yellow-50 border border-blue-300 rounded-lg">
                  <input
                    type="checkbox"
                    name="terms_accepted"
                    checked={formData.terms_accepted}
                    onChange={handleChange}
                    className="mt-1 mr-3 h-5 w-5"
                  />
                  <span className="text-sm text-gray-800 font-medium">
                    {t('auth.signup.agreeToTermsPrefix')}{' '}
                    <button
                      type="button"
                      onClick={() => setShowTermsModal(true)}
                      className="text-brand-primary underline font-semibold hover:text-gray-700"
                    >
                      {t('auth.signup.termsLinkText')}
                    </button>{' '}
                    <span className="text-red-500">*</span>
                  </span>
                </label>
                {errors.terms_accepted && (
                  <p className="text-red-500 text-sm mt-2 font-medium">{errors.terms_accepted}</p>
                )}
              </div>

              {/* Terms & Conditions — popup with full text */}
              {showTermsModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-primary bg-opacity-50 p-4">
                  <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col">
                    <div className="flex items-center justify-between p-5 border-b bg-brand-primary text-white rounded-t-2xl">
                      <h2 className="text-lg font-bold">{t('auth.signup.termsModalTitle')}</h2>
                      <button
                        type="button"
                        onClick={() => setShowTermsModal(false)}
                        className="p-2 hover:bg-white/20 rounded-lg transition-colors"
                      >
                        <X className="h-5 w-5" />
                      </button>
                    </div>
                    <div className="flex-1 overflow-y-auto p-6 space-y-3 text-sm">
                      {TERMS_SECTIONS.map(([title, body]) => (
                        <div key={title}>
                          <p className="font-semibold text-gray-800 mb-1">{title}:</p>
                          <p className="text-gray-700">{body}</p>
                        </div>
                      ))}
                    </div>
                    <div className="p-4 border-t bg-gray-50 rounded-b-2xl flex justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => setShowTermsModal(false)}
                        className="px-5 py-2.5 border-2 border-gray-300 text-gray-700 rounded-lg font-semibold hover:bg-gray-100 transition-colors"
                      >
                        {t('auth.signup.close')}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setFormData((prev) => ({ ...prev, terms_accepted: true }));
                          if (errors.terms_accepted) setErrors((prev) => ({ ...prev, terms_accepted: '' }));
                          setShowTermsModal(false);
                        }}
                        className="px-5 py-2.5 bg-brand-primary text-white rounded-lg font-semibold hover:opacity-90 transition-all"
                      >
                        {t('auth.signup.acceptAndClose')}
                      </button>
                    </div>
                  </div>
                </div>
              )}

              {/* SUBMIT — always visible, disabled until Terms & Conditions are accepted */}
              <div className="mt-8">
                <button
                  type="submit"
                  className="w-full flex items-center justify-center gap-2 gradient-btn text-white px-6 py-3 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                  disabled={loading || !formData.terms_accepted}
                >
                  {loading
                    ? <Loader className="h-5 w-5 animate-spin" />
                    : <><CheckCircle className="h-5 w-5" /> {t('auth.signup.completeRegistration')}</>}
                </button>
              </div>
            </div>
          </form>

          <div className="mt-6 text-center">
            <p className="text-gray-600">
              {t('auth.signup.alreadyHaveAccount')}{' '}
              <Link to="/login" className="text-brand-primary hover:text-gray-700 font-medium">
                {t('auth.signup.loginHere')}
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Signup;
