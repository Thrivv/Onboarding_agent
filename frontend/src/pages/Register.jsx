// frontend/src/pages/Register.jsx

import React, { useState } from 'react';
import Layout from '../components/layout/Layout';
import api from '../services/api';
import { toast } from 'react-hot-toast';
import { UserPlus, ChevronLeft, ChevronRight } from 'lucide-react';

const Register = () => {
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    phone_number: '',
    dob: '',
    business_name: '',
    account_type: 'Savings',
    ownership_type: '',
    partnership_details: '',
    annual_turnover: '',
    terms_accepted: false,
  });

  const [loading, setLoading] = useState(false);
  const [errors, setErrors] = useState({});

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value,
    }));

    if (errors[name]) {
      setErrors((prev) => ({ ...prev, [name]: '' }));
    }
  };

  const validateStep = () => {
    const newErrors = {};

    if (step === 1) {
      if (!formData.name.trim()) newErrors.name = 'Name is required';
      if (!formData.email.trim()) newErrors.email = 'Email is required';
      if (!formData.phone_number.trim()) newErrors.phone_number = 'Phone is required';
      if (!formData.business_name.trim()) newErrors.business_name = 'Business name is required';
    }

    if (step === 2) {
      if (!formData.account_type) newErrors.account_type = 'Account type is required';
    }

    if (step === 3 && formData.account_type === 'Corporate') {
      if (!formData.ownership_type) newErrors.ownership_type = 'Ownership type is required';
    }

    if (step === 4 && formData.ownership_type === 'Partnership') {
      if (!formData.partnership_details) newErrors.partnership_details = 'Partnership details required';
    }

    if (step === 5) {
      if (!formData.annual_turnover.trim()) newErrors.annual_turnover = 'Annual turnover is required';
    }

    if (step === 6) {
      if (!formData.terms_accepted) newErrors.terms_accepted = 'You must accept terms';
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleNext = () => {
    if (!validateStep()) return;

    if (step === 2 && formData.account_type === 'Savings') {
      setStep(5);
    } else if (step === 3 && formData.ownership_type === 'Single Owner') {
      setStep(5);
    } else if (step === 4 && formData.ownership_type !== 'Partnership') {
      setStep(5);
    } else {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step === 5 && formData.account_type === 'Savings') {
      setStep(2);
    } else if (step === 5 && formData.ownership_type === 'Single Owner') {
      setStep(3);
    } else {
      setStep(step - 1);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!validateStep()) return;

    setLoading(true);

    try {
      const response = await api.post('/register', formData);

      if (response.data) {
        toast.success('✅ User registered successfully!');
        
        setFormData({
          name: '',
          email: '',
          phone_number: '',
          dob: '',
          business_name: '',
          account_type: 'Savings',
          ownership_type: '',
          partnership_details: '',
          annual_turnover: '',
          terms_accepted: false,
        });
        setStep(1);
      }
    } catch (error) {
      console.error('Registration error:', error);
      const errorMsg = error.response?.data?.detail || 'Registration failed';
      toast.error(`❌ ${errorMsg}`);
    } finally {
      setLoading(false);
    }
  };

  const renderStep = () => {
    switch (step) {
      case 1:
        return (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">📋 Basic Information</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Full Name *</label>
              <input
                type="text"
                name="name"
                value={formData.name}
                onChange={handleChange}
                className={`w-full px-4 py-2 border ${errors.name ? 'border-red-500' : 'border-gray-300'} rounded-lg focus:outline-none focus:ring-2 focus:ring-primary`}
                placeholder="John Doe"
              />
              {errors.name && <p className="mt-1 text-sm text-red-600">{errors.name}</p>}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Date of Birth</label>
              <input
                type="date"
                name="dob"
                value={formData.dob}
                onChange={handleChange}
                max={new Date().toISOString().split('T')[0]}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Phone Number *</label>
              <input
                type="tel"
                name="phone_number"
                value={formData.phone_number}
                onChange={handleChange}
                className={`w-full px-4 py-2 border ${errors.phone_number ? 'border-red-500' : 'border-gray-300'} rounded-lg focus:outline-none focus:ring-2 focus:ring-primary`}
                placeholder="+971-XX-XXX-XXXX"
              />
              {errors.phone_number && <p className="mt-1 text-sm text-red-600">{errors.phone_number}</p>}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Email *</label>
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                className={`w-full px-4 py-2 border ${errors.email ? 'border-red-500' : 'border-gray-300'} rounded-lg focus:outline-none focus:ring-2 focus:ring-primary`}
                placeholder="john.doe@example.com"
              />
              {errors.email && <p className="mt-1 text-sm text-red-600">{errors.email}</p>}
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">Business Name *</label>
              <input
                type="text"
                name="business_name"
                value={formData.business_name}
                onChange={handleChange}
                className={`w-full px-4 py-2 border ${errors.business_name ? 'border-red-500' : 'border-gray-300'} rounded-lg focus:outline-none focus:ring-2 focus:ring-primary`}
                placeholder="Your Company LLC"
              />
              {errors.business_name && <p className="mt-1 text-sm text-red-600">{errors.business_name}</p>}
            </div>
          </div>
        );

      case 2:
        return (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">🏦 Account Type</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-4">
                What kind of account do you want to open? *
              </label>
              
              <div className="space-y-3">
                <label className="flex items-center p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="account_type"
                    value="Savings"
                    checked={formData.account_type === 'Savings'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary"
                  />
                  <span className="ml-3 text-gray-900 font-medium">Savings Account</span>
                </label>

                <label className="flex items-center p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="account_type"
                    value="Corporate"
                    checked={formData.account_type === 'Corporate'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary"
                  />
                  <span className="ml-3 text-gray-900 font-medium">Corporate Account</span>
                </label>
              </div>
              {errors.account_type && <p className="mt-2 text-sm text-red-600">{errors.account_type}</p>}
            </div>
          </div>
        );

      case 3:
        return (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">👥 Ownership Type</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-4">
                Do you want to open a single owner or partnership account? *
              </label>
              
              <div className="space-y-3">
                <label className="flex items-center p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="ownership_type"
                    value="Single Owner"
                    checked={formData.ownership_type === 'Single Owner'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary"
                  />
                  <span className="ml-3 text-gray-900 font-medium">Single Owner</span>
                </label>

                <label className="flex items-center p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="ownership_type"
                    value="Partnership"
                    checked={formData.ownership_type === 'Partnership'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary"
                  />
                  <span className="ml-3 text-gray-900 font-medium">Partnership</span>
                </label>
              </div>
              {errors.ownership_type && <p className="mt-2 text-sm text-red-600">{errors.ownership_type}</p>}
            </div>
          </div>
        );

      case 4:
        return (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">🤝 Partnership Details</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-4">
                Are all shareholders in your business individual persons or not? *
              </label>
              
              <div className="space-y-3">
                <label className="flex items-start p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="partnership_details"
                    value="All shareholders are individual persons"
                    checked={formData.partnership_details === 'All shareholders are individual persons'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary mt-1"
                  />
                  <span className="ml-3 text-gray-900">All shareholders are individual persons</span>
                </label>

                <label className="flex items-start p-4 border-2 border-gray-300 rounded-lg cursor-pointer hover:border-primary transition-colors">
                  <input
                    type="radio"
                    name="partnership_details"
                    value="One or more shareholders are companies or other legal entities"
                    checked={formData.partnership_details === 'One or more shareholders are companies or other legal entities'}
                    onChange={handleChange}
                    className="h-4 w-4 text-primary focus:ring-primary mt-1"
                  />
                  <span className="ml-3 text-gray-900">One or more shareholders are companies or other legal entities</span>
                </label>
              </div>
              {errors.partnership_details && <p className="mt-2 text-sm text-red-600">{errors.partnership_details}</p>}
            </div>
          </div>
        );

      case 5:
        return (
          <div className="space-y-4">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">💰 Financial Information</h3>
            
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                What is your expected annual turnover? *
              </label>
              <input
                type="text"
                name="annual_turnover"
                value={formData.annual_turnover}
                onChange={handleChange}
                className={`w-full px-4 py-2 border ${errors.annual_turnover ? 'border-red-500' : 'border-gray-300'} rounded-lg focus:outline-none focus:ring-2 focus:ring-primary`}
                placeholder="e.g., $500,000"
              />
              {errors.annual_turnover && <p className="mt-1 text-sm text-red-600">{errors.annual_turnover}</p>}
            </div>
          </div>
        );

      case 6:
        return (
          <div className="space-y-6">
            <h3 className="text-xl font-semibold text-gray-800 mb-4">✅ Final Confirmation</h3>
            
            <div className="bg-gray-50 p-6 rounded-lg space-y-3">
              <h4 className="font-semibold text-gray-800 mb-3">📋 Review Your Information:</h4>
              <div className="space-y-2 text-sm">
                <p><strong>Name:</strong> {formData.name}</p>
                <p><strong>Email:</strong> {formData.email}</p>
                <p><strong>Phone:</strong> {formData.phone_number}</p>
                {formData.dob && <p><strong>DOB:</strong> {formData.dob}</p>}
                <p><strong>Business:</strong> {formData.business_name}</p>
                <p><strong>Account Type:</strong> {formData.account_type}</p>
                {formData.ownership_type && <p><strong>Ownership:</strong> {formData.ownership_type}</p>}
                {formData.partnership_details && <p><strong>Partnership:</strong> {formData.partnership_details}</p>}
                <p><strong>Annual Turnover:</strong> {formData.annual_turnover}</p>
              </div>
            </div>

            <div>
              <div className="flex items-start">
                <input
                  id="terms_accepted"
                  name="terms_accepted"
                  type="checkbox"
                  checked={formData.terms_accepted}
                  onChange={handleChange}
                  className="h-4 w-4 text-primary focus:ring-primary border-gray-300 rounded mt-1"
                />
                <label htmlFor="terms_accepted" className="ml-3 block text-sm text-gray-700">
                  I have read and agree to the{' '}
                  <button 
                    type="button"
                    onClick={() => window.open('/terms', '_blank')}
                    className="text-primary hover:text-primary-dark font-medium underline"
                  >
                    Terms and Conditions
                  </button>{' '}
                  and{' '}
                  <button 
                    type="button"
                    onClick={() => window.open('/privacy', '_blank')}
                    className="text-primary hover:text-primary-dark font-medium underline"
                  >
                    Privacy Policy
                  </button>{' '}
                  *
                </label>
              </div>
              {errors.terms_accepted && (
                <p className="mt-2 text-sm text-red-600">{errors.terms_accepted}</p>
              )}
            </div>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <Layout>
      <div className="max-w-3xl mx-auto">
        <div className="bg-white rounded-xl shadow-lg p-8 fade-in">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold gradient-text mb-2">📋 Register New User</h1>
            <p className="text-gray-600">Complete the onboarding process</p>
          </div>

          <div className="mb-8">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium text-gray-700">Step {step} of 6</span>
              <span className="text-sm font-medium text-primary">{Math.round((step / 6) * 100)}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <div
                className="bg-gradient-to-r from-primary to-primary-dark h-2 rounded-full transition-all duration-300"
                style={{ width: `${(step / 6) * 100}%` }}
              ></div>
            </div>
          </div>

          <form onSubmit={step === 6 ? handleSubmit : (e) => e.preventDefault()}>
            {renderStep()}

            <div className="flex justify-between mt-8">
              <button
                type="button"
                onClick={handleBack}
                disabled={step === 1}
                className="flex items-center px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft className="h-5 w-5 mr-2" />
                Back
              </button>

              {step < 6 ? (
                <button
                  type="button"
                  onClick={handleNext}
                  className="flex items-center px-6 py-2 gradient-btn text-white rounded-lg hover:opacity-90 transition-opacity"
                >
                  Continue
                  <ChevronRight className="h-5 w-5 ml-2" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={loading}
                  className="flex items-center px-6 py-2 gradient-btn text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
                >
                  {loading ? (
                    <>
                      <div className="spinner mr-2" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div>
                      Submitting...
                    </>
                  ) : (
                    <>
                      <UserPlus className="h-5 w-5 mr-2" />
                      Complete Registration
                    </>
                  )}
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    </Layout>
  );
};

export default Register;