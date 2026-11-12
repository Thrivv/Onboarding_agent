import React, { useState } from 'react';
import { ChevronDown, ChevronUp, FileText } from 'lucide-react';
import { CoIExtractedData } from './CoIExtractedData';
import { CommercialExtractedData } from './CommercialExtractedData';
import { EIDExtractedData } from './EIDExtractedData';
import { EjariExtractedData } from './EjariExtractedData';
import { GenericExtractedData } from './GenericExtractedData';
import { MOAExtractedData } from './MOAExtractedData';
import { useReportI18n } from '../../utils/reportI18n';

const ExtractedDataDisplay = ({ data, documentType, isMinimal = false }) => {
  const { R } = useReportI18n();
  const [open, setOpen] = useState(isMinimal);
  if (!data) return null;

  const englishData = data.english || data;

  const renderContent = () => {
    switch (documentType?.toLowerCase()) {
      case 'eid':
      case 'passport':
        return <EIDExtractedData data={englishData} />;
      case 'ejari':
      case 'tenancy':
        return <EjariExtractedData data={englishData} />;
      case 'commercial':
        return <CommercialExtractedData data={data} />;
      case 'moa':
      case 'memorandum':
        return <MOAExtractedData data={englishData} />;
      case 'certificate_of_incorporation':
      case 'coi':
        return <CoIExtractedData data={data} />;
      default:
        return <GenericExtractedData data={englishData} />;
    }
  };

  if (isMinimal) {
    return (
      <div className="mt-2 space-y-1">
        {renderContent()}
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-lg border border-indigo-200 overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-indigo-50 hover:bg-indigo-100 transition-colors"
      >
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-brand-primary" />
          <span className="text-xs font-semibold text-indigo-800">{R('extractedInfo')}</span>
        </div>
        {open
          ? <ChevronUp className="h-4 w-4 text-indigo-500" />
          : <ChevronDown className="h-4 w-4 text-indigo-500" />}
      </button>
      {open && (
        <div className="p-3 bg-brand-primary">
          {renderContent()}
        </div>
      )}
    </div>
  );
};

// ============================================================================
// MAIN COMPONENT
// ============================================================================

// ============================================================================
// RAZORPAY-STYLE SIDE PANEL (THE "RIGHT SIDE" CONTENT)
// ============================================================================

export { ExtractedDataDisplay };
