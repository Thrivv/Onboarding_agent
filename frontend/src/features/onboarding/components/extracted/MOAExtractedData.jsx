import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Building, ChevronDown, ChevronUp, FileText, User } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';

const MOAExtractedData = ({ data }) => {
  const [showMore, setShowMore] = useState(false);

  // Collect business activities
  const activities = Object.keys(data)
    .filter(key => key.startsWith('activity_'))
    .map(key => data[key])
    .filter(Boolean);

  return (
    <div className="space-y-3 text-sm">
      {/* Company Details */}
      <div className="bg-white p-5 rounded-[24px] border border-slate-50">
        <p className="font-semibold text-indigo-900 mb-3 flex items-center gap-2">
          <Building className="h-4 w-4" />
          Company Details
        </p>
        <div className="grid grid-cols-2 gap-4">
          <InfoRow label="Company Name" value={data.company_name || data['Company Name (EN)']} fullWidth />
          <InfoRow label="Company Type" value={data.company_type} />
          <InfoRow label="Execution Date" value={data.date_of_execution || data['Execution Date']} />
          <InfoRow label="Owner Name" value={data.owner_name || data['Owner Name (EN)']} />
          <InfoRow label="Manager Name" value={data.manager_name || data['Manager Name (EN)']} />
        </div>
      </div>

      <div className="flex justify-center">
        <button
          onClick={() => setShowMore(!showMore)}
          className="px-5 py-1.5 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-full text-[9px] font-black text-indigo-600 uppercase tracking-widest transition-all flex items-center gap-1.5 shadow-sm"
        >
          {showMore ? (
            <><ChevronUp className="h-3 w-3" /> Show Less</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> View All Details</>
          )}
        </button>
      </div>

      {showMore && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-3"
        >
          {/* Owner Background */}
          <div className="bg-white p-5 rounded-[24px] border border-slate-50">
            <p className="font-semibold text-indigo-900 mb-3 flex items-center gap-2">
              <User className="h-4 w-4" />
              Owner Background
            </p>
            <div className="grid grid-cols-2 gap-4">
              <InfoRow label="Nationality" value={data.owner_nationality} />
              <InfoRow label="Passport No" value={data.passport_number} />
              <InfoRow label="Date of Birth" value={data.date_of_birth} />
              <InfoRow label="Residence" value={data.owner_residence} />
            </div>
          </div>

          {/* Business Activities */}
          {activities.length > 0 && (
            <div className="bg-white p-5 rounded-[24px] border border-slate-50">
              <p className="font-semibold text-indigo-900 mb-3 flex items-center gap-2">
                <FileText className="h-4 w-4" />
                Licensed Activities
              </p>
              <div className="grid grid-cols-2 gap-3 mt-2">
                {activities.map((act, idx) => (
                  <div key={idx} className="flex gap-3 p-3 bg-slate-50 rounded-xl border border-slate-100 transition-all hover:bg-white hover:border-indigo-100">
                    <span className="flex-shrink-0 w-5 h-5 flex items-center justify-center bg-white rounded-full border border-slate-200 text-[10px] font-black text-indigo-600 shadow-sm">{idx + 1}</span>
                    <p className="text-[11px] font-bold text-slate-700 leading-snug">{act}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Share & Capital */}
          <div className="bg-white p-5 rounded-[24px] border border-slate-50">
            <p className="font-semibold text-indigo-900 mb-3">Share & Capital Structure</p>
            <div className="grid grid-cols-2 gap-4">
              <InfoRow label="Capital" value={data.capital || data['Capital']} />
              <InfoRow label="No. of Shares" value={data.number_of_shares || data['Number of Shares']} />
              <InfoRow label="Value per Share" value={data.value_per_share || data['Value per Share']} />
              <InfoRow label="Share Type" value={data.share_type || data['Share Type']} />
              <InfoRow label="Payment Status" value={data.payment_status} fullWidth />
            </div>
          </div>

          {/* Office & Terms */}
          <div className="bg-white p-5 rounded-[24px] border border-slate-50">
            <p className="font-semibold text-indigo-900 mb-3">Office & Duration</p>
            <div className="grid grid-cols-2 gap-4">
              <InfoRow label="HQ Location" value={data.head_office_location} />
              <InfoRow label="Office Address" value={data.company_address} />
              <InfoRow label="Duration" value={data.company_duration} />
              <InfoRow label="Start Date" value={data.duration_start_date} />
            </div>
          </div>

          {/* Legal & Financial */}
          <div className="bg-white p-5 rounded-[24px] border border-slate-50">
            <p className="font-semibold text-indigo-900 mb-3">Legal & Financial Clauses</p>
            <div className="grid grid-cols-2 gap-4">
              <InfoRow label="Financial Year" value={`${data.financial_year_start} - ${data.financial_year_end}`} />
              <InfoRow label="Legal Reserve" value={data.legal_reserve_percentage} />
              <InfoRow label="Profit Distribution" value={data.profit_loss_distribution} />
              <InfoRow label="Audit Period" value={data.balance_sheet_submission} />
            </div>
          </div>
        </motion.div>
      )}
    </div>
  );
};

// ============================================================================
// FATCA MODAL
// ============================================================================

export { MOAExtractedData };
