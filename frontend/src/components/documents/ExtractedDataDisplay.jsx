// frontend/src/components/documents/ExtractedDataDisplay.jsx

import React from 'react';

const DataRow = ({ label, value }) => (
  <div className="flex justify-between items-start py-2 border-b border-gray-100 last:border-0">
    <span className="text-sm text-gray-600 font-medium">{label}:</span>
    <span className="text-sm text-gray-800 font-semibold text-right ml-4">
      {value || 'N/A'}
    </span>
  </div>
);

const ExtractedDataDisplay = ({ documentType, displayName, extractedData }) => {
  if (!extractedData || Object.keys(extractedData).length === 0) {
    return (
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
        <p className="text-sm text-gray-600">No extracted data available</p>
      </div>
    );
  }

  const renderData = () => {
    // Emirates ID (EID) - Flat structure
    if (displayName === 'Emirates ID (EID)' || documentType === 'eid') {
      return (
        <div className="bg-blue-50 border-2 border-blue-200 rounded-lg p-4">
          <h5 className="text-sm font-bold text-blue-900 mb-3">👤 Personal Information</h5>
          <div className="space-y-1">
            <DataRow 
              label="Name" 
              value={extractedData.Name || extractedData.name} 
            />
            <DataRow 
              label="ID Number" 
              value={extractedData['ID Number'] || extractedData.id_number} 
            />
            <DataRow 
              label="Nationality" 
              value={extractedData.Nationality || extractedData.nationality} 
            />
            <DataRow 
              label="Expiry Date" 
              value={extractedData['Expiry Date'] || extractedData.expiry_date} 
            />
          </div>
        </div>
      );
    }

    // Commercial License - Nested structure
    if (displayName === 'Commercial License' || documentType === 'commercial_license') {
      const eng = extractedData.english || {};
      return (
        <div className="bg-green-50 border-2 border-green-200 rounded-lg p-4">
          <h5 className="text-sm font-bold text-green-900 mb-3">🏢 Company Information</h5>
          <div className="space-y-1">
            <DataRow 
              label="Company Name" 
              value={eng.company_name_english} 
            />
            <DataRow 
              label="License Number" 
              value={eng.license_number} 
            />
            <DataRow 
              label="Legal Type" 
              value={eng.legal_type} 
            />
            <DataRow 
              label="Status" 
              value={eng.status} 
            />
            <DataRow 
              label="Expiry Date" 
              value={eng.expiry_date} 
            />
          </div>
        </div>
      );
    }

    // Ejari (Tenancy Contract) - Nested structure
    if (displayName === 'Ejari (Tenancy Contract)' || documentType === 'ejari') {
      const eng = extractedData.english || {};
      return (
        <div className="bg-yellow-50 border-2 border-yellow-200 rounded-lg p-4">
          <h5 className="text-sm font-bold text-yellow-900 mb-3">🏠 Tenancy Information</h5>
          <div className="space-y-1">
            <DataRow 
              label="Contract Number" 
              value={eng.contract_number} 
            />
            <DataRow 
              label="Owner Name" 
              value={eng.owner_name} 
            />
            <DataRow 
              label="Tenant" 
              value={eng.tenant_company || eng.tenant_name} 
            />
            <DataRow 
              label="Start Date" 
              value={eng.start_date} 
            />
            <DataRow 
              label="End Date" 
              value={eng.end_date} 
            />
            <DataRow 
              label="Property Type" 
              value={eng.property_type} 
            />
            <DataRow 
              label="Area" 
              value={eng.area} 
            />
          </div>
        </div>
      );
    }

    // MOA - Nested structure
    if (displayName === 'Memorandum of Association (MOA)' || documentType === 'moa') {
      const eng = extractedData.english || {};
      return (
        <div className="bg-purple-50 border-2 border-purple-200 rounded-lg p-4">
          <h5 className="text-sm font-bold text-purple-900 mb-3">📜 MOA Information</h5>
          <div className="space-y-1">
            <DataRow 
              label="Company Name" 
              value={eng.company_name} 
            />
            <DataRow 
              label="Owner Name" 
              value={eng.owner_name} 
            />
            <DataRow 
              label="Date of Execution" 
              value={eng.date_of_execution} 
            />
            <DataRow 
              label="Number of Shares" 
              value={eng.number_of_shares} 
            />
          </div>
        </div>
      );
    }

    // Default: Show first 5 fields
    return (
      <div className="bg-gray-50 border-2 border-gray-200 rounded-lg p-4">
        <h5 className="text-sm font-bold text-gray-900 mb-3">📋 Document Information</h5>
        <div className="space-y-1">
          {Object.entries(extractedData).slice(0, 5).map(([key, value]) => (
            <DataRow key={key} label={key} value={String(value)} />
          ))}
        </div>
      </div>
    );
  };

  return <div>{renderData()}</div>;
};

export default ExtractedDataDisplay;