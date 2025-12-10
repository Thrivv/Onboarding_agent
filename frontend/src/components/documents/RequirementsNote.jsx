// frontend/src/components/documents/RequirementsNote.jsx

import React from 'react';
import { AlertCircle } from 'lucide-react';

const RequirementsNote = ({ accountType, ownershipType, stage }) => {
  const getRequirementsInfo = () => {
    // Savings Account
    if (accountType === 'Savings') {
      return {
        title: 'Savings Account Requirements',
        icon: '💰',
        items: [
          'Ejari (Tenancy Contract)',
          'Emirates ID (EID)'
        ],
        note: 'Only these 2 documents are required for Savings accounts',
        bgColor: 'from-green-50 to-green-100',
        borderColor: 'border-green-300',
        textColor: 'text-green-900'
      };
    }
    
    // Corporate Single Owner
    if (accountType === 'Corporate' && ownershipType === 'Single Owner') {
      return {
        title: 'Corporate Single Owner Requirements',
        icon: '🏢',
        items: [
          'Ejari (Tenancy Contract)',
          'Emirates ID (EID)',
          'Commercial License'
        ],
        note: 'All 3 documents required for single owner corporate accounts',
        bgColor: 'from-blue-50 to-blue-100',
        borderColor: 'border-blue-300',
        textColor: 'text-blue-900'
      };
    }
    
    // Corporate Partnership - Stage 1
    if (accountType === 'Corporate' && ownershipType === 'Partnership' && stage === 'identification') {
      return {
        title: 'Corporate Partnership - Stage 1',
        icon: '👥',
        items: [
          'Commercial License',
          'Memorandum of Association (MOA)'
        ],
        note: 'Upload both documents to proceed to Stage 2 (Member EIDs)',
        bgColor: 'from-purple-50 to-purple-100',
        borderColor: 'border-purple-300',
        textColor: 'text-purple-900'
      };
    }
    
    // Corporate Partnership - Stage 2
    if (accountType === 'Corporate' && ownershipType === 'Partnership' && stage === 'member_eids') {
      return {
        title: 'Corporate Partnership - Stage 2',
        icon: '👥',
        items: [
          'Emirates ID for all members listed in Commercial License'
        ],
        note: 'Upload EID for each partner/shareholder listed in your Commercial License',
        bgColor: 'from-indigo-50 to-indigo-100',
        borderColor: 'border-indigo-300',
        textColor: 'text-indigo-900'
      };
    }
    
    return null;
  };

  const requirements = getRequirementsInfo();
  
  if (!requirements) return null;

  return (
    <div className={`bg-gradient-to-r ${requirements.bgColor} border-2 ${requirements.borderColor} rounded-xl shadow-lg p-6 mb-6`}>
      <div className="flex items-start gap-4">
        <div className="text-5xl">{requirements.icon}</div>
        <div className="flex-1">
          <h3 className={`text-xl font-bold ${requirements.textColor} mb-3`}>
            {requirements.title}
          </h3>
          <ul className={`space-y-2 ${requirements.textColor} mb-4`}>
            {requirements.items.map((item, idx) => (
              <li key={idx} className="flex items-start gap-2">
                <span className="text-lg">✓</span>
                <span className="font-medium">{item}</span>
              </li>
            ))}
          </ul>
          <div className={`flex items-start gap-2 ${requirements.textColor} bg-white bg-opacity-50 p-3 rounded-lg`}>
            <AlertCircle className="h-5 w-5 mt-0.5 flex-shrink-0" />
            <p className="text-sm font-medium">{requirements.note}</p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default RequirementsNote;