// frontend/src/components/common/ConfirmationModal.jsx
import React from 'react';
import { CheckCircle, X, AlertTriangle } from 'lucide-react';

const ConfirmationModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  documents = [],
  isLoading = false,
  crossValidationErrors = null
}) => {
  if (!isOpen) return null;

  const hasErrors = crossValidationErrors && crossValidationErrors.length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className={`
          flex items-center justify-between p-6 border-b rounded-t-2xl
          ${hasErrors ? 'bg-gradient-to-r from-yellow-500 to-orange-500' : 'bg-gradient-to-r from-green-500 to-emerald-600'}
          text-white
        `}>
          <div className="flex items-center gap-3">
            {hasErrors ? (
              <AlertTriangle className="h-8 w-8" />
            ) : (
              <CheckCircle className="h-8 w-8" />
            )}
            <div>
              <h2 className="text-xl font-bold">
                {hasErrors ? 'Review Required' : 'Confirm Document Submission'}
              </h2>
              <p className="text-sm opacity-90 mt-1">
                {hasErrors 
                  ? 'Please review the validation errors below'
                  : 'Please review your documents before final submission'
                }
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-white/20 rounded-lg transition-colors"
            disabled={isLoading}
          >
            <X className="h-6 w-6" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* Cross Validation Errors */}
          {hasErrors && (
            <div className="mb-6 p-4 bg-yellow-50 border-2 border-yellow-300 rounded-lg">
              <h3 className="font-bold text-yellow-800 mb-3 flex items-center gap-2">
                <AlertTriangle className="h-5 w-5" />
                Validation Issues Detected
              </h3>
              <ul className="space-y-2">
                {crossValidationErrors.map((error, index) => (
                  <li key={index} className="flex items-start gap-2 text-sm text-yellow-900">
                    <span className="text-yellow-600 font-bold">•</span>
                    <span>{error}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-sm text-yellow-800 font-medium">
                ⚠️ Please review and re-upload documents if necessary before proceeding.
              </p>
            </div>
          )}

          {/* Documents List */}
          <div className="space-y-3">
            <h3 className="font-bold text-gray-800 mb-3">
              Documents to be Submitted ({documents.length})
            </h3>
            {documents.map((doc, index) => (
              <div
                key={index}
                className={`
                  p-4 rounded-lg border-2 
                  ${doc.is_valid 
                    ? 'bg-green-50 border-green-300' 
                    : 'bg-yellow-50 border-yellow-300'
                  }
                `}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-gray-800">
                        {doc.document_type?.toUpperCase().replace(/_/g, ' ')}
                      </span>
                      <span className={`
                        px-2 py-0.5 text-xs font-bold rounded-full
                        ${doc.is_valid 
                          ? 'bg-green-200 text-green-800' 
                          : 'bg-yellow-200 text-yellow-800'
                        }
                      `}>
                        {doc.is_valid ? 'VALID' : 'NEEDS REVIEW'}
                      </span>
                    </div>
                    <div className="text-sm text-gray-600 mt-1">
                      📎 {doc.filename}
                    </div>
                    
                    {/* Key Fields Preview */}
                    {doc.extracted_data && Object.keys(doc.extracted_data).length > 0 && (
                      <div className="mt-3 grid grid-cols-2 gap-2">
                        {Object.entries(doc.extracted_data).slice(0, 4).map(([key, value]) => (
                          <div key={key} className="text-xs">
                            <span className="text-gray-500">{key}:</span>
                            <span className="text-gray-800 font-medium ml-1">{value}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Information Box */}
          <div className="mt-6 p-4 bg-indigo-50 border border-indigo-200 rounded-lg">
            <h4 className="font-semibold text-indigo-900 mb-2">📋 What happens next?</h4>
            <ul className="space-y-1 text-sm text-indigo-800">
              <li>✓ Your documents will be sent for verification</li>
              <li>✓ Our team will review within 3-4 business days</li>
              <li>✓ You'll receive account details via email</li>
              <li>✓ A summary PDF will be generated</li>
            </ul>
          </div>
        </div>

        {/* Footer */}
        <div className="p-6 border-t bg-gray-50 rounded-b-2xl">
          <div className="flex items-center justify-between gap-4">
            <button
              onClick={onClose}
              disabled={isLoading}
              className="px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-lg font-semibold hover:bg-gray-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isLoading}
              className={`
                px-6 py-3 rounded-lg font-semibold text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed
                ${hasErrors 
                  ? 'bg-gradient-to-r from-yellow-500 to-orange-500 hover:opacity-90' 
                  : 'bg-gradient-to-r from-green-500 to-emerald-600 hover:opacity-90'
                }
              `}
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                  Processing...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <CheckCircle className="h-5 w-5" />
                  {hasErrors ? 'Submit Anyway' : 'Confirm & Submit'}
                </span>
              )}
            </button>
          </div>
          {hasErrors && (
            <p className="text-xs text-gray-600 mt-3 text-center">
              By clicking "Submit Anyway", you acknowledge the validation issues above
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default ConfirmationModal;