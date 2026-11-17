import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Building, ChevronDown, ChevronUp, ShieldCheck, Users } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';

const CoIExtractedData = ({ data }) => {
  const [showMore, setShowMore] = useState(false);
  const englishData = data.english || data;
  const directorsAndShareholders = data.directors_and_shareholders || data.directors || data.partners || [];

  return (
    <div className="space-y-3 text-sm">
      {data.tampering && (
        <div className="rounded-xl border border-indigo-200 overflow-hidden shadow-sm">
          <div className="flex items-center justify-between px-3 py-2 bg-brand-primary border-b border-indigo-100">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-indigo-600" />
              <p className="text-[9px] font-black text-indigo-800 uppercase tracking-widest">Document Forensics</p>
            </div>
            <div className={`px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-tighter ${data.tampering.status === 'AUTHENTIC' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
              }`}>
              {data.tampering.status}
            </div>
          </div>
          <div className="p-3 bg-white grid grid-cols-2 gap-x-4 gap-y-2">
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">Score</span>
              <span className="font-black text-slate-700">{data.tampering.score}</span>
            </div>
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">Decision</span>
              <span className="font-black text-slate-700">{data.tampering.decision}</span>
            </div>
          </div>
        </div>
      )}
      {/* Company Information */}
      <div className="bg-white p-3 rounded-lg">
        <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
          <Building className="h-4 w-4" />
          Company Information
        </p>
        <div className="space-y-1 text-gray-700">
          <InfoRow label="Company Name" value={englishData.company_name || englishData['Company Name']} />
          <InfoRow label="Registration Number" value={englishData.registration_number || englishData['Registration Number']} />
          <InfoRow label="Jurisdiction" value={englishData.jurisdiction || englishData['Jurisdiction']} />
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
          <div className="bg-white p-3 rounded-lg">
            <div className="space-y-1 text-gray-700">
              <InfoRow label="Incorporation Date" value={englishData.incorporation_date || englishData['Incorporation Date']} />
              <InfoRow label="Company Type" value={englishData.company_type || englishData['Company Type']} />
              <InfoRow label="Registered Agent" value={englishData.registered_agent || englishData['Registered Agent']} />
              <InfoRow label="Registered Office" value={englishData.registered_office || englishData['Registered Office']} />
              <InfoRow label="Share Capital" value={englishData.share_capital || englishData['Share Capital']} />
              <InfoRow label="Currency" value={englishData.currency || englishData['Currency']} />
            </div>
          </div>

          {/* Directors & Shareholders */}
          {directorsAndShareholders.length > 0 && (
            <div className="bg-white p-3 rounded-lg">
              <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
                <Users className="h-4 w-4" />
                Directors & Shareholders ({directorsAndShareholders.length})
              </p>
              <div className="space-y-2">
                {directorsAndShareholders.map((person, idx) => (
                  <div key={idx} className="text-gray-700 text-xs border-b border-gray-100 pb-2 last:border-0 last:pb-0">
                    <div className="font-medium text-gray-800">
                      {person.name || person.full_name || person.name_english || `Person ${idx + 1}`}
                    </div>
                    {(person.role || person.position) && (
                      <div className="text-gray-600">Role: {person.role || person.position}</div>
                    )}
                    {(person.share_percentage || person.shares || person.ownership) && (
                      <div className="text-gray-600">
                        Shares: {person.share_percentage || person.shares || person.ownership}
                        {(person.share_percentage || person.ownership) && !String(person.share_percentage || person.ownership).endsWith('%') ? '%' : ''}
                      </div>
                    )}
                    {(person.nationality || person.nationality_english) && (
                      <div className="text-gray-600">Nationality: {person.nationality || person.nationality_english}</div>
                    )}
                    {(person.passport_number || person.passport) && (
                      <div className="text-gray-600">Passport: {person.passport_number || person.passport}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
};

// ============================================================================
// COMMERCIAL LICENSE DISPLAY
// ============================================================================

export { CoIExtractedData };
