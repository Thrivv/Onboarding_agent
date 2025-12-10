// frontend/src/components/documents/MemberProgress.jsx - COMPLETE

import React from 'react';
import { CheckCircle, Clock } from 'lucide-react';

const MemberProgress = ({ membersInfo }) => {
  if (!membersInfo) return null;

  const { total, verified, all_members, verified_members } = membersInfo;
  const progress = total > 0 ? (verified / total) * 100 : 0;

  return (
    <div className="bg-white rounded-xl shadow-lg p-6 mb-6">
      <h2 className="text-2xl font-bold text-gray-800 mb-4 flex items-center gap-2">
        👥 Member Progress
      </h2>

      {/* Progress Bar */}
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm font-medium text-gray-700">
            EID Verification Progress
          </span>
          <span className="text-sm font-bold text-indigo-600">
            {verified}/{total} Members
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-8 overflow-hidden">
          <div
            className="bg-gradient-to-r from-green-500 to-green-600 h-full flex items-center justify-center text-white text-sm font-bold transition-all duration-500"
            style={{ width: `${progress}%` }}
          >
            {progress > 10 && `${Math.round(progress)}%`}
          </div>
        </div>
      </div>

      {/* Member List */}
      <div className="space-y-3">
        {all_members && all_members.map((memberName, index) => {
          const isVerified = verified_members && verified_members.includes(memberName);
          return (
            <div
              key={index}
              className={`flex items-center justify-between p-4 rounded-lg border-2 transition-all ${
                isVerified
                  ? 'bg-green-50 border-green-300'
                  : 'bg-yellow-50 border-yellow-300'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                  isVerified ? 'bg-green-200' : 'bg-yellow-200'
                }`}>
                  <span className="text-xl">👤</span>
                </div>
                <span className="font-semibold text-gray-800">{memberName}</span>
              </div>
              
              <div className={`flex items-center gap-2 px-4 py-2 rounded-full font-medium ${
                isVerified
                  ? 'bg-green-200 text-green-800'
                  : 'bg-yellow-200 text-yellow-800'
              }`}>
                {isVerified ? (
                  <>
                    <CheckCircle className="h-5 w-5" />
                    Verified
                  </>
                ) : (
                  <>
                    <Clock className="h-5 w-5" />
                    Pending
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default MemberProgress;