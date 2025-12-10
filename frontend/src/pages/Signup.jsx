// frontend/src/pages/Signup.jsx

import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '../services/api';
import { toast } from 'react-hot-toast';
import {ChevronLeft, ChevronRight, CheckCircle } from 'lucide-react';

const Signup = () => {
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  
  const [formData, setFormData] = useState({
    // Step 1: Basic Info
    name: '',
    dob: '',
    phone_number: '',
    email: '',
    password: '',
    confirmPassword: '',
    
    // Step 2: Business Info (for all account types)
    business_name: '',
    
    // Step 3: Account Type
    account_type: 'Savings',
    
    // Step 4: Ownership Type (Corporate only)
    ownership_type: '',
    
    // Step 5: Partnership Details (Corporate Multiple Owners only)
    partnership_details: '',
    
    // Step 6: Annual Turnover (ALL ACCOUNT TYPES)
    annual_turnover: '',
    
    // Final: Terms
    terms_accepted: false,
  });

  const [errors, setErrors] = useState({});

  // Calculate age from DOB
  const calculateAge = (dob) => {
    const birthDate = new Date(dob);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const monthDiff = today.getMonth() - birthDate.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }
    return age;
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));
    // Clear error when user starts typing
    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
  };

  // Validation functions
  const validateStep1 = () => {
    const newErrors = {};
    
    if (!formData.name.trim()) newErrors.name = 'Full name is required';
    if (!formData.dob) {
      newErrors.dob = 'Date of birth is required';
    } else {
      const age = calculateAge(formData.dob);
      if (age < 18) newErrors.dob = 'You must be at least 18 years old';
    }
    if (!formData.phone_number.trim()) {
      newErrors.phone_number = 'Phone number is required';
    } else if (!/^\+?[\d\s-()]+$/.test(formData.phone_number)) {
      newErrors.phone_number = 'Invalid phone number format';
    }
    if (!formData.email.trim()) {
      newErrors.email = 'Email is required';
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      newErrors.email = 'Invalid email format';
    }
    if (!formData.password) {
      newErrors.password = 'Password is required';
    } else if (formData.password.length < 8) {
      newErrors.password = 'Password must be at least 8 characters';
    }
    if (formData.password !== formData.confirmPassword) {
      newErrors.confirmPassword = 'Passwords do not match';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep2 = () => {
    const newErrors = {};
    if (!formData.business_name.trim()) {
      newErrors.business_name = 'Business name is required';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep4 = () => {
    const newErrors = {};
    if (!formData.ownership_type) {
      newErrors.ownership_type = 'Please select ownership type';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep5 = () => {
    const newErrors = {};
    if (!formData.partnership_details) {
      newErrors.partnership_details = 'Please select partnership details';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateStep6 = () => {
    const newErrors = {};
    if (!formData.annual_turnover.trim()) {
      newErrors.annual_turnover = 'Expected annual turnover is required';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const validateFinal = () => {
    const newErrors = {};
    if (!formData.terms_accepted) {
      newErrors.terms_accepted = 'You must accept the terms and conditions';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Navigation handlers
  const handleNext = () => {
    let isValid = false;

    if (step === 1) isValid = validateStep1();
    else if (step === 2) isValid = validateStep2();
    else if (step === 3) isValid = true;
    else if (step === 4) isValid = validateStep4();
    else if (step === 5) isValid = validateStep5();
    else if (step === 6) isValid = validateStep6();

    if (!isValid) return;

    if (step === 2) {
      setStep(3);
    } else if (step === 3) {
      if (formData.account_type === 'Savings') {
        setStep(6);
      } else {
        setStep(4);
      }
    } else if (step === 4) {
      if (formData.ownership_type === 'Single Owner') {
        setStep(6);
      } else {
        setStep(5);
      }
    } else if (step === 5) {
      setStep(6);
    } else if (step === 6) {
      setStep(7);
    } else {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step === 7) {
      setStep(6);
    } else if (step === 6) {
      if (formData.account_type === 'Savings') {
        setStep(3);
      } else if (formData.ownership_type === 'Single Owner') {
        setStep(4);
      } else {
        setStep(5);
      }
    } else if (step === 5) {
      setStep(4);
    } else if (step === 4) {
      setStep(3);
    } else {
      setStep(step - 1);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!validateFinal()) return;

    setLoading(true);

    try {
      const payload = {
        email: formData.email,
        password: formData.password,
        name: formData.name,
        dob: formData.dob,
        phone_number: formData.phone_number,
        business_name: formData.business_name,
        account_type: formData.account_type,
        ownership_type: formData.ownership_type || null,
        partnership_details: formData.partnership_details || null,
        annual_turnover: formData.annual_turnover,
        terms_accepted: formData.terms_accepted,
      };

      await api.post('/register/signup', payload);
      
      toast.success('Account created successfully! Please login.');
      navigate('/login');
      
    } catch (error) {
      console.error('Signup error:', error);
      if (error.response?.status === 409) {
        toast.error('Email already registered. Please login.');
      } else {
        toast.error(error.response?.data?.detail || 'Signup failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const getProgress = () => {
    const totalSteps = 7;
    return (step / totalSteps) * 100;
  };

  const getTotalSteps = () => {
    return 7;
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-blue-50 to-indigo-100 flex items-center justify-center p-4">
      <div className="max-w-2xl w-full">
        {/* Progress Bar */}
        <div className="mb-6">
          <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-primary to-primary-dark transition-all duration-300"
              style={{ width: `${getProgress()}%` }}
            />
          </div>
          <p className="text-sm text-gray-600 mt-2 text-center">
            Step {step} of {getTotalSteps()}
          </p>
        </div>

        <div className="bg-white rounded-2xl shadow-xl p-8">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold gradient-text mb-2">Create Account</h1>
            <p className="text-gray-600">Join Thrivv Banking today</p>
          </div>

          <form onSubmit={handleSubmit}>
            {/* STEP 1: BASIC INFORMATION */}
            {step === 1 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Basic Information</h2>
                
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Full Name *
                  </label>
                  <input
                    type="text"
                    name="name"
                    value={formData.name}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.name ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="Enter your full name"
                  />
                  {errors.name && <p className="text-red-500 text-sm mt-1">{errors.name}</p>}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Date of Birth *
                  </label>
                  <input
                    type="date"
                    name="dob"
                    value={formData.dob}
                    onChange={handleChange}
                    max={new Date().toISOString().split('T')[0]}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.dob ? 'border-red-500' : 'border-gray-300'
                    }`}
                  />
                  {errors.dob && <p className="text-red-500 text-sm mt-1">{errors.dob}</p>}
                  {formData.dob && (
                    <p className="text-sm text-gray-600 mt-1">
                      Age: {calculateAge(formData.dob)} years
                    </p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Phone Number *
                  </label>
                  <input
                    type="tel"
                    name="phone_number"
                    value={formData.phone_number}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.phone_number ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="+971 50 123 4567"
                  />
                  {errors.phone_number && <p className="text-red-500 text-sm mt-1">{errors.phone_number}</p>}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Email *
                  </label>
                  <input
                    type="email"
                    name="email"
                    value={formData.email}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.email ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="your@email.com"
                  />
                  {errors.email && <p className="text-red-500 text-sm mt-1">{errors.email}</p>}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Password *
                  </label>
                  <input
                    type="password"
                    name="password"
                    value={formData.password}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.password ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="Minimum 8 characters"
                  />
                  {errors.password && <p className="text-red-500 text-sm mt-1">{errors.password}</p>}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Confirm Password *
                  </label>
                  <input
                    type="password"
                    name="confirmPassword"
                    value={formData.confirmPassword}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.confirmPassword ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="Re-enter password"
                  />
                  {errors.confirmPassword && <p className="text-red-500 text-sm mt-1">{errors.confirmPassword}</p>}
                </div>
              </div>
            )}

            {/* STEP 2: BUSINESS NAME */}
            {step === 2 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Business Information</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4">
                  <h3 className="font-medium mb-2">Previously Answered:</h3>
                  <p className="text-sm text-gray-700">Name: {formData.name}</p>
                  <p className="text-sm text-gray-700">Email: {formData.email}</p>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Business Name *
                  </label>
                  <input
                    type="text"
                    name="business_name"
                    value={formData.business_name}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.business_name ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="Enter your business name"
                  />
                  {errors.business_name && <p className="text-red-500 text-sm mt-1">{errors.business_name}</p>}
                </div>
              </div>
            )}

            {/* STEP 3: ACCOUNT TYPE */}
            {step === 3 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Account Type</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4">
                  <h3 className="font-medium mb-2">Previously Answered:</h3>
                  <p className="text-sm text-gray-700">Business: {formData.business_name}</p>
                </div>

                <p className="text-gray-700 mb-4">What kind of account do you want to open?</p>
                
                <div className="space-y-3">
                  {['Savings', 'Corporate'].map((type) => (
                    <label
                      key={type}
                      className={`block p-4 border-2 rounded-lg cursor-pointer transition-all ${
                        formData.account_type === type
                          ? 'border-primary bg-blue-50'
                          : 'border-gray-300 hover:border-primary'
                      }`}
                    >
                      <input
                        type="radio"
                        name="account_type"
                        value={type}
                        checked={formData.account_type === type}
                        onChange={handleChange}
                        className="mr-3"
                      />
                      <span className="font-medium">{type} Account</span>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* STEP 4: OWNERSHIP TYPE (Corporate only) */}
            {step === 4 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Ownership Type</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4">
                  <h3 className="font-medium mb-2">Previously Answered:</h3>
                  <p className="text-sm text-gray-700">Account Type: {formData.account_type}</p>
                </div>

                <p className="text-gray-700 mb-4">Do you want to open a single owner or multiple owners account?</p>
                
                <div className="space-y-3">
                  {['Single Owner', 'Multiple Owners'].map((type) => (
                    <label
                      key={type}
                      className={`block p-4 border-2 rounded-lg cursor-pointer transition-all ${
                        formData.ownership_type === type
                          ? 'border-primary bg-blue-50'
                          : 'border-gray-300 hover:border-primary'
                      }`}
                    >
                      <input
                        type="radio"
                        name="ownership_type"
                        value={type}
                        checked={formData.ownership_type === type}
                        onChange={handleChange}
                        className="mr-3"
                      />
                      <span className="font-medium">{type}</span>
                    </label>
                  ))}
                </div>
                {errors.ownership_type && <p className="text-red-500 text-sm mt-1">{errors.ownership_type}</p>}
              </div>
            )}

            {/* STEP 5: PARTNERSHIP DETAILS (Multiple Owners only) */}
            {step === 5 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Partnership Information</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4">
                  <h3 className="font-medium mb-2">Previously Answered:</h3>
                  <p className="text-sm text-gray-700">Ownership: {formData.ownership_type}</p>
                </div>

                <p className="text-gray-700 mb-4">Are all shareholders in your business individual persons or not?</p>
                
                <div className="space-y-3">
                  {[
                    'All shareholders are individual persons',
                    'One or more shareholders are companies or other legal entities'
                  ].map((detail) => (
                    <label
                      key={detail}
                      className={`block p-4 border-2 rounded-lg cursor-pointer transition-all ${
                        formData.partnership_details === detail
                          ? 'border-primary bg-blue-50'
                          : 'border-gray-300 hover:border-primary'
                      }`}
                    >
                      <input
                        type="radio"
                        name="partnership_details"
                        value={detail}
                        checked={formData.partnership_details === detail}
                        onChange={handleChange}
                        className="mr-3"
                      />
                      <span className="text-sm">{detail}</span>
                    </label>
                  ))}
                </div>
                {errors.partnership_details && <p className="text-red-500 text-sm mt-1">{errors.partnership_details}</p>}
              </div>
            )}

            {/* STEP 6: ANNUAL TURNOVER (ALL ACCOUNT TYPES) */}
            {step === 6 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Financial Information</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4">
                  <h3 className="font-medium mb-2">Previously Answered:</h3>
                  <p className="text-sm text-gray-700">Account Type: {formData.account_type}</p>
                  {formData.ownership_type && (
                    <p className="text-sm text-gray-700">Ownership: {formData.ownership_type}</p>
                  )}
                  {formData.partnership_details && (
                    <p className="text-sm text-gray-700">Partnership: {formData.partnership_details}</p>
                  )}
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Expected Annual Turnover *
                  </label>
                  <input
                    type="text"
                    name="annual_turnover"
                    value={formData.annual_turnover}
                    onChange={handleChange}
                    className={`w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-primary focus:border-transparent ${
                      errors.annual_turnover ? 'border-red-500' : 'border-gray-300'
                    }`}
                    placeholder="e.g., AED 500,000 - 1,000,000"
                  />
                  {errors.annual_turnover && <p className="text-red-500 text-sm mt-1">{errors.annual_turnover}</p>}
                  <p className="text-xs text-gray-500 mt-1">
                    Enter your estimated annual business turnover
                  </p>
                </div>
              </div>
            )}

            {/* ✅ STEP 7: FINAL CONFIRMATION WITH REAL TERMS & CONDITIONS */}
            {step === 7 && (
              <div className="space-y-4">
                <h2 className="text-xl font-semibold mb-4">Final Confirmation</h2>
                
                <div className="bg-blue-50 p-4 rounded-lg mb-4 space-y-2">
                  <h3 className="font-medium mb-3">Review Your Information:</h3>
                  <p className="text-sm"><strong>Name:</strong> {formData.name}</p>
                  <p className="text-sm"><strong>Email:</strong> {formData.email}</p>
                  <p className="text-sm"><strong>Phone:</strong> {formData.phone_number}</p>
                  <p className="text-sm"><strong>DOB:</strong> {formData.dob} (Age: {calculateAge(formData.dob)})</p>
                  <p className="text-sm"><strong>Business:</strong> {formData.business_name}</p>
                  <p className="text-sm"><strong>Account Type:</strong> {formData.account_type}</p>
                  {formData.ownership_type && (
                    <p className="text-sm"><strong>Ownership:</strong> {formData.ownership_type}</p>
                  )}
                  {formData.partnership_details && (
                    <p className="text-sm"><strong>Partnership:</strong> {formData.partnership_details}</p>
                  )}
                  <p className="text-sm"><strong>Annual Turnover:</strong> {formData.annual_turnover}</p>
                </div>

                {/* ✅ REAL TERMS & CONDITIONS */}
                <div className="border-2 border-gray-300 rounded-lg p-4">
                  <h3 className="font-bold text-lg mb-3 text-gray-800">Terms and Conditions - Data Sharing and Privacy</h3>
                  <div className="max-h-64 overflow-y-auto bg-gray-50 p-4 rounded text-sm space-y-3 border border-gray-200">
                    
                    <div>
                      <p className="font-semibold text-gray-800 mb-1">1. Data Collection and Use:</p>
                      <p className="text-gray-700">
                        We collect personal and financial information including but not limited to identification documents, income statements, transaction history, and contact details to provide banking services, comply with regulatory requirements, and improve our offerings. This information may be processed both domestically and internationally.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">2. Information Sharing with Regulatory Bodies:</p>
                      <p className="text-gray-700">
                        Your personal and account information may be shared with regulatory authorities including the Central Bank, Financial Intelligence Unit, tax authorities, and other governmental bodies as required by applicable laws and regulations for compliance, investigation, or reporting purposes.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">3. Third-Party Service Providers:</p>
                      <p className="text-gray-700">
                        We may share your information with trusted third-party service providers including credit bureaus, payment processors, technology vendors, and outsourcing partners who assist in delivering banking services. These parties are contractually bound to maintain confidentiality and use data only for specified purposes.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">4. Credit Reporting and Risk Assessment:</p>
                      <p className="text-gray-700">
                        Your credit information, payment history, and account behavior may be shared with credit bureaus and used for credit scoring, risk assessment, and fraud prevention. This information may affect your ability to obtain credit from other financial institutions.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">5. Anti-Money Laundering (AML) and Know Your Customer (KYC):</p>
                      <p className="text-gray-700">
                        We are required to collect, verify, and share customer information with relevant authorities for AML and KYC compliance. This includes monitoring transactions, reporting suspicious activities, and maintaining records as mandated by law.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">6. Data Retention and Storage:</p>
                      <p className="text-gray-700">
                        Personal information will be retained for the minimum period required by law, typically 5-10 years after account closure. Data is stored securely using industry-standard encryption and may be stored in multiple jurisdictions with adequate data protection standards.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">7. Cross-Border Data Transfers:</p>
                      <p className="text-gray-700">
                        Your information may be transferred to and processed in countries outside the UAE for operational, regulatory, or service delivery purposes. We ensure such transfers comply with applicable data protection laws and maintain adequate safeguards.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">8. Marketing and Communication Consent:</p>
                      <p className="text-gray-700">
                        By accepting these terms, you consent to receive marketing communications about our products and services through various channels including email, SMS, phone calls, and postal mail. You may opt-out of marketing communications at any time.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">9. Data Security and Breach Notification:</p>
                      <p className="text-gray-700">
                        We implement robust security measures to protect your information. In the event of a data breach that may affect your personal information, we will notify you and relevant authorities within the timeframes required by applicable law.
                      </p>
                    </div>

                    <div>
                      <p className="font-semibold text-gray-800 mb-1">10. Customer Rights and Access:</p>
                      <p className="text-gray-700">
                        You have the right to access, correct, update, or request deletion of your personal information subject to legal and regulatory requirements. You may also withdraw consent for certain data processing activities, though this may affect our ability to provide services to you.
                      </p>
                    </div>
                  </div>
                  
                  <label className="flex items-start cursor-pointer mt-4 p-3 bg-yellow-50 border border-yellow-300 rounded-lg">
                    <input
                      type="checkbox"
                      name="terms_accepted"
                      checked={formData.terms_accepted}
                      onChange={handleChange}
                      className="mt-1 mr-3 h-5 w-5"
                    />
                    <span className="text-sm text-gray-800 font-medium">
                      I have read and agree to the Terms and Conditions regarding Data Sharing and Privacy *
                    </span>
                  </label>
                  {errors.terms_accepted && (
                    <p className="text-red-500 text-sm mt-2 font-medium">{errors.terms_accepted}</p>
                  )}
                </div>
              </div>
            )}

            {/* Navigation Buttons */}
            <div className="flex gap-4 mt-8">
              {step > 1 && (
                <button
                  type="button"
                  onClick={handleBack}
                  className="flex-1 flex items-center justify-center gap-2 px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
                  disabled={loading}
                >
                  <ChevronLeft className="h-5 w-5" />
                  Back
                </button>
              )}
              
              {step < 7 ? (
                <button
                  type="button"
                  onClick={handleNext}
                  className="flex-1 flex items-center justify-center gap-2 gradient-btn text-white px-6 py-3 rounded-lg hover:opacity-90 transition-opacity"
                  disabled={loading}
                >
                  Continue
                  <ChevronRight className="h-5 w-5" />
                </button>
              ) : (
                <button
                  type="submit"
                  className="flex-1 flex items-center justify-center gap-2 gradient-btn text-white px-6 py-3 rounded-lg hover:opacity-90 transition-opacity disabled:opacity-50"
                  disabled={loading || !formData.terms_accepted}
                >
                  {loading ? (
                    <>
                      <div className="spinner-sm" />
                      Creating Account...
                    </>
                  ) : (
                    <>
                      <CheckCircle className="h-5 w-5" />
                      Complete Registration
                    </>
                  )}
                </button>
              )}
            </div>
          </form>

          <div className="mt-6 text-center">
            <p className="text-gray-600">
              Already have an account?{' '}
              <Link to="/login" className="text-primary hover:underline font-medium">
                Login here
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Signup;