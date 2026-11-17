import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown, ChevronUp, Globe, ShieldCheck, User } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';

const EIDExtractedData = ({ data }) => {
  const [showMore, setShowMore] = useState(false);
  const isPassport = !!(data.passport_number || data.given_names || data.surname);

  const fullName = data.Name || data.name ||
    ([data.surname, data.given_names].filter(Boolean).join(' ') || '');
  const idNumber = data['ID Number'] || data.id_number || data.passport_number || '';
  const nationality = data.Nationality || data.nationality || '';
  const sex = data.Sex || data.sex || '';
  const dob = data['Date of Birth'] || data.date_of_birth || '';
  const issuingDate = data['Issuing Date'] || data.issuing_date || data.date_of_issue || '';
  const expiryDate = data['Expiry Date'] || data.expiry_date || data.date_of_expiry || '';

  const idLabel = isPassport ? 'Passport Number' : 'Emirates ID';

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-5">
        <InfoRow label="Full Name" value={fullName} fullWidth icon={User} />
        <InfoRow label={idLabel} value={idNumber} icon={ShieldCheck} />
      </div>

      <div className="flex justify-center -mt-2">
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
          className="grid grid-cols-2 gap-5"
        >
          <InfoRow label="Nationality" value={nationality} icon={Globe} />
          <InfoRow label="Date of Birth" value={dob} showAge />
          <InfoRow label="Gender" value={sex} />
          <InfoRow label="Issue Date" value={issuingDate} />
          <InfoRow label="Expiry Date" value={expiryDate} />
        </motion.div>
      )}
    </div>
  );
};

// ============================================================================
// EJARI (TENANCY CONTRACT) DISPLAY
// ============================================================================

export { EIDExtractedData };
