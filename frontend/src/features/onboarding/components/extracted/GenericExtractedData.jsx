import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';
import { formatLabel } from '../../utils/formatters';
import { useReportI18n } from '../../utils/reportI18n';

const GenericExtractedData = ({ data }) => {
  const { L, R } = useReportI18n();
  const [showAll, setShowAll] = useState(false);
  if (!data || typeof data !== 'object') {
    return <p className="text-sm text-gray-600">{R('noData')}</p>;
  }

  const entries = Object.entries(data).filter(([key, value]) =>
    value !== null && value !== undefined && typeof value !== 'object'
  );

  const visibleEntries = showAll ? entries : entries.slice(0, 8);

  return (
    <div className="bg-white p-3 rounded-lg">
      <div className="space-y-1 text-sm text-gray-700">
        {visibleEntries.map(([key, value]) => (
          <InfoRow key={key} label={L(formatLabel(key))} value={value} />
        ))}
      </div>
      {entries.length > 8 && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="mt-3 text-[10px] font-black text-brand-primary uppercase tracking-widest hover:text-brand-secondary transition-colors flex items-center gap-1"
        >
          {showAll ? (
            <><ChevronUp className="h-3 w-3" /> {R('showLess')}</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> {R('moreFields', { count: entries.length - 8 })}</>
          )}
        </button>
      )}
    </div>
  );
};

// ============================================================================
// EXTRACTED DATA DISPLAY COMPONENT
// ============================================================================

export { GenericExtractedData };
