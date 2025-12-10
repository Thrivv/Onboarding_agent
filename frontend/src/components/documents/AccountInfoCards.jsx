// frontend/src/components/documents/AccountInfoCards.jsx

import React from 'react';

const AccountInfoCards = ({ accountType, ownershipType, stage }) => {
  const getStageDescription = (stage) => {
    if (stage === 'member_eids') return 'Member EID Collection';
    if (stage === 'identification') return 'Identification Stage';
    if (stage === 'complete') return 'Verification Complete';
    return 'General Account';
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
      {/* Account Type */}
      <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl shadow-lg p-6 text-white">
        <div className="text-sm font-medium opacity-90 mb-2">📊 Account Type</div>
        <div className="text-2xl font-bold">{accountType || 'N/A'}</div>
      </div>

      {/* Ownership Type */}
      <div className="bg-gradient-to-br from-purple-500 to-purple-600 rounded-xl shadow-lg p-6 text-white">
        <div className="text-sm font-medium opacity-90 mb-2">👥 Ownership</div>
        <div className="text-2xl font-bold">{ownershipType || 'N/A'}</div>
      </div>

      {/* Current Stage */}
      <div className="bg-gradient-to-br from-indigo-500 to-indigo-600 rounded-xl shadow-lg p-6 text-white">
        <div className="text-sm font-medium opacity-90 mb-2">📋 Current Stage</div>
        <div className="text-2xl font-bold">{getStageDescription(stage)}</div>
      </div>
    </div>
  );
};

export default AccountInfoCards;