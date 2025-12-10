// frontend/src/components/common/MemberSelector.jsx
import React from 'react';
import { CheckCircle, Circle, User } from 'lucide-react';

const MemberSelector = ({ members, currentIndex, onMemberSelect, selectedMember }) => {
  if (!members || members.length === 0) return null;

  return (
    <div className="bg-gradient-to-br from-purple-50 to-indigo-50 rounded-xl p-6 mb-6 border border-purple-200">
      <h3 className="text-lg font-bold text-gray-800 mb-4 flex items-center gap-2">
        <User className="h-5 w-5 text-purple-600" />
        Partnership Members Progress
      </h3>
      
      <div className="space-y-3">
        {members.map((member, index) => {
          const isCompleted = member.eid_uploaded || index < currentIndex;
          const isCurrent = index === currentIndex;
          const isUpcoming = index > currentIndex;

          return (
            <div
              key={index}
              onClick={() => !isCompleted && onMemberSelect && onMemberSelect(member.name)}
              className={`
                flex items-center gap-4 p-4 rounded-lg transition-all cursor-pointer
                ${isCompleted ? 'bg-green-50 border-2 border-green-300' : ''}
                ${isCurrent ? 'bg-white border-2 border-purple-500 shadow-md ring-2 ring-purple-200' : ''}
                ${isUpcoming ? 'bg-gray-50 border-2 border-gray-200 opacity-60' : ''}
                ${!isCompleted && !isCurrent ? 'hover:border-purple-400 hover:shadow-sm' : ''}
              `}
            >
              {/* Status Icon */}
              <div className="flex-shrink-0">
                {isCompleted ? (
                  <CheckCircle className="h-8 w-8 text-green-600" />
                ) : isCurrent ? (
                  <div className="h-8 w-8 rounded-full bg-gradient-to-br from-purple-500 to-indigo-600 flex items-center justify-center">
                    <Circle className="h-5 w-5 text-white animate-pulse" />
                  </div>
                ) : (
                  <Circle className="h-8 w-8 text-gray-400" />
                )}
              </div>

              {/* Member Info */}
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className={`
                    font-semibold
                    ${isCompleted ? 'text-green-800' : ''}
                    ${isCurrent ? 'text-purple-800' : ''}
                    ${isUpcoming ? 'text-gray-600' : ''}
                  `}>
                    {member.name}
                  </span>
                  {isCurrent && (
                    <span className="px-2 py-0.5 text-xs font-bold bg-purple-100 text-purple-700 rounded-full animate-pulse">
                      CURRENT
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <span className={`
                    text-sm
                    ${isCompleted ? 'text-green-600 font-medium' : ''}
                    ${isCurrent ? 'text-purple-600 font-medium' : ''}
                    ${isUpcoming ? 'text-gray-500' : ''}
                  `}>
                    {isCompleted ? '✓ EID Verified' : isCurrent ? '→ Upload EID Now' : '⏳ Pending'}
                  </span>
                </div>
              </div>

              {/* Step Number */}
              <div className={`
                flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center font-bold text-lg
                ${isCompleted ? 'bg-green-200 text-green-800' : ''}
                ${isCurrent ? 'bg-purple-200 text-purple-800' : ''}
                ${isUpcoming ? 'bg-gray-200 text-gray-600' : ''}
              `}>
                {index + 1}
              </div>
            </div>
          );
        })}
      </div>

      {/* Progress Bar */}
      <div className="mt-4 pt-4 border-t border-purple-200">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Overall Progress</span>
          <span className="text-sm font-bold text-purple-600">
            {Math.round((currentIndex / members.length) * 100)}%
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-3 overflow-hidden">
          <div
            className="bg-gradient-to-r from-purple-600 to-indigo-600 h-3 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${(currentIndex / members.length) * 100}%` }}
          ></div>
        </div>
        <p className="text-xs text-gray-600 mt-2">
          {currentIndex} of {members.length} members completed
        </p>
      </div>
    </div>
  );
};

export default MemberSelector;