// frontend/src/components/common/ProgressTracker.jsx
import React from 'react';
import { CheckCircle, Circle, Clock, FileText } from 'lucide-react';

const ProgressTracker = ({ 
  requiredDocuments = [], 
  submittedDocuments = [], 
  currentStage = 'identification',
  compact = false 
}) => {
  const getDocumentStatus = (docType) => {
    return submittedDocuments.find(
      doc => doc.document_type?.toLowerCase() === docType.toLowerCase() ||
             doc.type?.toLowerCase() === docType.toLowerCase()
    );
  };

  const getStatusIcon = (docType) => {
    const doc = getDocumentStatus(docType);
    if (doc) {
      if (doc.is_valid) {
        return <CheckCircle className="h-6 w-6 text-green-600" />;
      }
      return <Clock className="h-6 w-6 text-yellow-600" />;
    }
    return <Circle className="h-6 w-6 text-gray-400" />;
  };

  const getDisplayName = (docType) => {
    const names = {
      'eid': 'Emirates ID',
      'commercial': 'Commercial License',
      'moa': 'Memorandum of Association',
      'ejari': 'Ejari Contract',
      'passport': 'Passport',
      'bank_statement': 'Bank Statement'
    };
    return names[docType.toLowerCase()] || docType.toUpperCase();
  };

  const completedCount = requiredDocuments.filter(doc => 
    getDocumentStatus(doc)?.is_valid
  ).length;

  const progress = requiredDocuments.length > 0 
    ? (completedCount / requiredDocuments.length) * 100 
    : 0;

  if (compact) {
    return (
      <div className="bg-white rounded-lg shadow-sm p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-semibold text-gray-700">Document Progress</span>
          <span className="text-sm font-bold text-indigo-600">{progress.toFixed(0)}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2.5">
          <div
            className="bg-gradient-to-r from-indigo-600 to-purple-600 h-2.5 rounded-full transition-all duration-500"
            style={{ width: `${progress}%` }}
          ></div>
        </div>
        <p className="text-xs text-gray-500 mt-2">
          {completedCount} of {requiredDocuments.length} documents verified
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl shadow-sm p-6">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-lg font-bold text-gray-800 flex items-center gap-2">
          <FileText className="h-5 w-5 text-indigo-600" />
          Document Checklist
        </h3>
        <div className="text-right">
          <div className="text-2xl font-bold text-indigo-600">{progress.toFixed(0)}%</div>
          <div className="text-xs text-gray-500">Complete</div>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="w-full bg-gray-200 rounded-full h-4 mb-6 overflow-hidden">
        <div
          className="bg-gradient-to-r from-indigo-600 via-purple-600 to-pink-600 h-4 rounded-full transition-all duration-700 ease-out relative"
          style={{ width: `${progress}%` }}
        >
          <div className="absolute inset-0 bg-white opacity-20 animate-pulse"></div>
        </div>
      </div>

      {/* Document List */}
      <div className="space-y-3">
        {requiredDocuments.map((docType, index) => {
          const status = getDocumentStatus(docType);
          const isCompleted = status?.is_valid;
          const isPending = status && !status.is_valid;
          const isRequired = !status;

          return (
            <div
              key={index}
              className={`
                flex items-center gap-4 p-4 rounded-lg border-2 transition-all
                ${isCompleted ? 'bg-green-50 border-green-300' : ''}
                ${isPending ? 'bg-yellow-50 border-yellow-300' : ''}
                ${isRequired ? 'bg-gray-50 border-gray-200 hover:border-indigo-300' : ''}
              `}
            >
              {/* Status Icon */}
              <div className="flex-shrink-0">
                {getStatusIcon(docType)}
              </div>

              {/* Document Info */}
              <div className="flex-1">
                <div className="font-semibold text-gray-800">
                  {getDisplayName(docType)}
                </div>
                <div className={`
                  text-sm mt-1
                  ${isCompleted ? 'text-green-600 font-medium' : ''}
                  ${isPending ? 'text-yellow-600' : ''}
                  ${isRequired ? 'text-gray-500' : ''}
                `}>
                  {isCompleted && '✓ Verified & Accepted'}
                  {isPending && '⏳ Submitted - Awaiting Verification'}
                  {isRequired && '→ Required - Please Upload'}
                </div>
                {status?.uploaded_at && (
                  <div className="text-xs text-gray-500 mt-1">
                    Uploaded: {new Date(status.uploaded_at).toLocaleDateString()}
                  </div>
                )}
              </div>

              {/* Badge */}
              <div className={`
                px-3 py-1 rounded-full text-xs font-bold
                ${isCompleted ? 'bg-green-200 text-green-800' : ''}
                ${isPending ? 'bg-yellow-200 text-yellow-800' : ''}
                ${isRequired ? 'bg-gray-200 text-gray-600' : ''}
              `}>
                {isCompleted && 'VERIFIED'}
                {isPending && 'PENDING'}
                {isRequired && 'REQUIRED'}
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary Footer */}
      <div className="mt-6 pt-6 border-t border-gray-200">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-600">
            Current Stage: <span className="font-semibold text-gray-800 capitalize">
              {currentStage.replace(/_/g, ' ')}
            </span>
          </span>
          <span className="text-gray-600">
            {completedCount} / {requiredDocuments.length} Completed
          </span>
        </div>
      </div>
    </div>
  );
};

export default ProgressTracker;