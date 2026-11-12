import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Building, ChevronDown, ChevronUp, FileText, Home } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';
import { useReportI18n } from '../../utils/reportI18n';

const EjariExtractedData = ({ data }) => {
  const { L, R } = useReportI18n();
  const [showMore, setShowMore] = useState(false);
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3">
        <InfoRow label={L('Contract Number')} value={data.contract_number} fullWidth icon={FileText} />
        <InfoRow label={L('Registration Date')} value={data.registration_date} />
        <InfoRow label={L('Project Name')} value={data.building_name} icon={Home} />
      </div>

      <div className="flex justify-center -mt-2">
        <button
          onClick={() => setShowMore(!showMore)}
          className="px-5 py-1.5 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-full text-[9px] font-black text-indigo-600 uppercase tracking-widest transition-all flex items-center gap-1.5 shadow-sm"
        >
          {showMore ? (
            <><ChevronUp className="h-3 w-3" /> {R('showLess')}</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> {R('viewAll')}</>
          )}
        </button>
      </div>

      {showMore && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-6"
        >
          <div className="grid grid-cols-2 gap-3">
            <InfoRow label={L('Contract Value')} value={data.contract_value} />
            <InfoRow label={L('Start Date')} value={data.start_date} />
            <InfoRow label={L('End Date')} value={data.end_date} />
            <InfoRow label={L('Property Use')} value={data.usage} icon={Building} />
            <InfoRow label={L('Emirates')} value={data.emirates} />
            <InfoRow label={L('Area / Community')} value={data.area || data.community} fullWidth />
          </div>

          <div className="rounded-2xl border border-slate-200 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-blue-50 border-b border-blue-100">
              <div className="w-1.5 h-1.5 rounded-full bg-blue-400" />
              <p className="text-[9px] font-black text-blue-500 uppercase tracking-[0.18em]">{R('headings.engagementParties')}</p>
            </div>
            <div className="p-4 grid grid-cols-2 gap-3 bg-white">
              <InfoRow label={L('Lessor Name')} value={data.owner_name || data.lessor_name} />
              <InfoRow label={L('Tenant Company')} value={data.tenant_company} />
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
};

// ============================================================================
// CERTIFICATE OF INCORPORATION (CoI) DISPLAY
// ============================================================================

export { EjariExtractedData };
