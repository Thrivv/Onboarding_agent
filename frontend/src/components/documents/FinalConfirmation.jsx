// frontend/src/components/documents/FinalConfirmation.jsx - FIXED (No ESLint Warning)

import React, { useState, useEffect, useCallback } from 'react'; // ✅ Added useCallback
import { toast } from 'react-hot-toast';
import { API_BASE_URL } from '../../utils/constants';

const FinalConfirmation = ({ email, onSuccess }) => {
  const [isConfirmed, setIsConfirmed] = useState(false);
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState(null);
  const [validationComplete, setValidationComplete] = useState(false);

  // ✅ FIXED: Wrap in useCallback to fix dependency warning
  const checkValidationStatus = useCallback(async () => {
    try {
      const response = await fetch(
        `${API_BASE_URL}/documentupload/check-confirmation-status/${email}`,
        {
          method: 'GET',
          headers: { 'Content-Type': 'application/json' }
        }
      );

      if (response.ok) {
        const data = await response.json();
        if (data.confirmation_sent) {
          setValidationComplete(true);
        }
      }
    } catch (error) {
      console.error('Error checking validation status:', error);
    }
  }, [email]); // ✅ Add email as dependency

  // ✅ FIXED: Now includes checkValidationStatus in dependency array
  useEffect(() => {
    checkValidationStatus();
  }, [checkValidationStatus]); // ✅ Include the function in dependencies

  const handleConfirmationChange = async (e) => {
    const checked = e.target.checked;
    setIsConfirmed(checked);

    // Start validation immediately when checkbox is checked
    if (checked) {
      await handleValidation();
    }
  };

  const handleValidation = async () => {
    setIsValidating(true);
    setValidationError(null);

    try {
      console.log('🔍 Starting validation for:', email);

      const response = await fetch(
        `${API_BASE_URL}/documentupload/send-completion-email`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        }
      );

      console.log('📡 Validation response status:', response.status);

      const data = await response.json();
      console.log('📊 Validation response data:', data);

      if (response.ok && data.success) {
        // ✅ VALIDATION PASSED
        console.log('✅ Validation successful!');
        setValidationComplete(true);
        toast.success('Document verification complete! Check your email.');
        
        // Call onSuccess callback
        if (onSuccess) {
          onSuccess();
        }
      } else {
        // ❌ VALIDATION FAILED
        console.error('❌ Validation failed:', data);
        
        const errorMessage = data.message || 'Validation failed. Please check your documents.';
        const validationErrors = data.validation_errors || [];
        
        setValidationError({
          message: errorMessage,
          errors: validationErrors
        });
        
        setIsConfirmed(false);
        toast.error('Document validation failed. Please review the errors.');
      }
    } catch (error) {
      console.error('❌ Validation error:', error);
      
      setValidationError({
        message: 'Network error during validation. Please try again.',
        errors: []
      });
      
      setIsConfirmed(false);
      toast.error('Connection error. Please check your internet and try again.');
    } finally {
      setIsValidating(false);
    }
  };

  const handleRetry = () => {
    setValidationError(null);
    setIsConfirmed(false);
    setValidationComplete(false);
  };

  // ============================================================================
  // SUCCESS STATE - Show when validation is complete
  // ============================================================================
  if (validationComplete) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
        <div className="bg-gradient-to-r from-green-50 to-emerald-50 border-2 border-green-400 rounded-lg p-8 text-center">
          <div className="text-6xl mb-4">🎉</div>
          <h2 className="text-3xl font-bold text-green-800 mb-4">
            Verification Complete!
          </h2>
          <div className="text-lg text-green-700 space-y-2">
            <p className="font-semibold">✅ All documents verified successfully</p>
            <p>📧 Confirmation email sent</p>
            <p>⏰ Account activation within 3-4 business days</p>
          </div>
          <div className="mt-6 p-4 bg-blue-50 border border-blue-300 rounded-lg">
            <p className="text-sm text-blue-800">
              💡 You can now close this page. We'll contact you via email once your account is activated.
            </p>
          </div>
        </div>
      </div>
    );
  }

  // ============================================================================
  // VALIDATION IN PROGRESS STATE
  // ============================================================================
  if (isValidating) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border-2 border-blue-400 rounded-lg p-8 text-center">
          <div className="flex justify-center mb-6">
            <div className="animate-spin rounded-full h-16 w-16 border-b-4 border-blue-600"></div>
          </div>
          <h2 className="text-2xl font-bold text-blue-800 mb-4">
            Validating Documents...
          </h2>
          <div className="text-blue-700 space-y-2">
            <p>🔍 Running cross-validation checks</p>
            <p>🏛️ Verifying with government databases</p>
            <p>📧 Preparing confirmation email</p>
          </div>
          <p className="text-sm text-blue-600 mt-4 italic">
            This may take 30-60 seconds. Please don't close this page.
          </p>
        </div>
      </div>
    );
  }

  // ============================================================================
  // ERROR STATE - Show when validation fails
  // ============================================================================
  if (validationError) {
    return (
      <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
        <div className="bg-gradient-to-r from-red-50 to-pink-50 border-2 border-red-400 rounded-lg p-8">
          <div className="text-center mb-6">
            <div className="text-6xl mb-4">❌</div>
            <h2 className="text-3xl font-bold text-red-800 mb-4">
              Validation Failed
            </h2>
          </div>

          <div className="bg-red-100 border-l-4 border-red-600 p-4 mb-6 rounded">
            <p className="text-red-800 font-semibold mb-2">
              {validationError.message}
            </p>
            {validationError.errors && validationError.errors.length > 0 && (
              <ul className="list-disc list-inside text-red-700 mt-3 space-y-1">
                {validationError.errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4 mb-6">
            <h3 className="font-semibold text-yellow-900 mb-2">
              What to do next:
            </h3>
            <ul className="text-sm text-yellow-800 space-y-2">
              <li>• Review your uploaded documents</li>
              <li>• Ensure all information matches across documents</li>
              <li>• Re-upload any documents with incorrect information</li>
              <li>• Try validating again once corrections are made</li>
            </ul>
          </div>

          <div className="text-center">
            <button
              onClick={handleRetry}
              className="px-8 py-4 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors font-semibold text-lg shadow-lg"
            >
              🔄 Try Again
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ============================================================================
  // NORMAL CONFIRMATION STATE - Show checkbox
  // ============================================================================
  return (
    <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h2 className="text-2xl font-bold text-gray-800 mb-4 flex items-center gap-2">
        ✅ Final Confirmation
      </h2>

      <div className="bg-yellow-50 border-2 border-yellow-300 rounded-lg p-6 mb-6">
        <p className="text-yellow-900 font-medium mb-4">
          ⚠️ Please review all your submitted documents before confirming
        </p>
        <ul className="text-yellow-800 space-y-2 text-sm">
          <li>• Ensure all information is accurate and matches your official documents</li>
          <li>• Verify that all required documents have been uploaded</li>
          <li>• Check that document images are clear and readable</li>
          <li>• Confirm member names are spelled correctly (for partnerships)</li>
        </ul>
      </div>

      <div className="bg-gradient-to-r from-indigo-50 to-purple-50 border-2 border-indigo-300 rounded-lg p-6">
        <label className="flex items-start gap-4 cursor-pointer">
          <input
            type="checkbox"
            checked={isConfirmed}
            onChange={handleConfirmationChange}
            disabled={isValidating}
            className="mt-1 w-6 h-6 text-indigo-600 border-gray-300 rounded focus:ring-indigo-500 cursor-pointer disabled:opacity-50"
          />
          <div className="flex-1">
            <p className="text-lg font-semibold text-gray-800 mb-2">
              I confirm that all document information is correct
            </p>
            <p className="text-sm text-gray-600">
              By checking this box, you confirm that:
            </p>
            <ul className="text-sm text-gray-600 mt-2 space-y-1">
              <li>✓ All uploaded documents are authentic and unmodified</li>
              <li>✓ All information provided is accurate and up-to-date</li>
              <li>✓ You understand that providing false information may result in account rejection</li>
              <li>✓ You agree to proceed with document verification</li>
            </ul>
          </div>
        </label>
      </div>

      <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
        <p className="text-sm text-blue-800">
          <strong>What happens next?</strong><br />
          When you confirm, we will automatically validate your documents with government databases. 
          This process takes 30-60 seconds. Once validated, you'll receive a confirmation email and 
          your account will be activated within 3-4 business days.
        </p>
      </div>
    </div>
  );
};

export default FinalConfirmation;