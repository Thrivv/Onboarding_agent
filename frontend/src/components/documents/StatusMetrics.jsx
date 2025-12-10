// frontend/src/components/documents/StatusMetrics.jsx

import React from 'react';
import { FileText, Clock, CheckCircle } from 'lucide-react';

const StatusMetrics = ({ submitted, remaining, isComplete }) => {
  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      {/* Submitted */}
      <div className="bg-white rounded-xl shadow-lg p-6 border-2 border-blue-200 hover:shadow-xl transition-shadow">
        <div className="flex items-center justify-center mb-3">
          <FileText className="h-8 w-8 text-blue-600" />
        </div>
        <div className="text-center">
          <div className="text-4xl font-bold text-blue-600">{submitted}</div>
          <div className="text-sm text-gray-600 font-medium mt-1">Submitted</div>
        </div>
      </div>

      {/* Remaining */}
      <div className="bg-white rounded-xl shadow-lg p-6 border-2 border-yellow-200 hover:shadow-xl transition-shadow">
        <div className="flex items-center justify-center mb-3">
          <Clock className="h-8 w-8 text-yellow-600" />
        </div>
        <div className="text-center">
          <div className="text-4xl font-bold text-yellow-600">{remaining}</div>
          <div className="text-sm text-gray-600 font-medium mt-1">Remaining</div>
        </div>
      </div>

      {/* Status */}
      <div className={`bg-white rounded-xl shadow-lg p-6 border-2 ${
        isComplete ? 'border-green-200' : 'border-yellow-200'
      } hover:shadow-xl transition-shadow`}>
        <div className="flex items-center justify-center mb-3">
          {isComplete ? (
            <CheckCircle className="h-8 w-8 text-green-600" />
          ) : (
            <Clock className="h-8 w-8 text-yellow-600" />
          )}
        </div>
        <div className="text-center">
          <div className={`text-2xl font-bold ${
            isComplete ? 'text-green-600' : 'text-yellow-600'
          }`}>
            {isComplete ? 'Complete' : 'In Progress'}
          </div>
          <div className="text-sm text-gray-600 font-medium mt-1">Status</div>
        </div>
      </div>
    </div>
  );
};

export default StatusMetrics;