import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Building, ChevronDown, ChevronUp, ShieldCheck, Users } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';
import { useReportI18n } from '../../utils/reportI18n';

const CoIExtractedData = ({ data }) => {
  const { L, R } = useReportI18n();
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
              <p className="text-[9px] font-black text-indigo-800 uppercase tracking-widest">{R('headings.documentForensics')}</p>
            </div>
            <div className={`px-2 py-0.5 rounded-full text-[8px] font-black uppercase tracking-tighter ${data.tampering.status === 'AUTHENTIC' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
              }`}>
              {data.tampering.status}
            </div>
          </div>
          <div className="p-3 bg-white grid grid-cols-2 gap-x-4 gap-y-2">
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">{R('headings.score')}</span>
              <span className="font-black text-slate-700">{data.tampering.score}</span>
            </div>
            <div className="flex justify-between items-center text-[10px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">{R('headings.decision')}</span>
              <span className="font-black text-slate-700">{data.tampering.decision}</span>
            </div>
          </div>
        </div>
      )}
      {/* Company Information */}
      <div className="bg-white p-3 rounded-lg">
        <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
          <Building className="h-4 w-4" />
          {R('headings.companyInformation')}
        </p>
        <div className="space-y-1 text-gray-700">
          <InfoRow label={L('Company Name')} value={englishData.company_name || englishData['Company Name']} />
          <InfoRow label={L('Registration Number')} value={englishData.registration_number || englishData['Registration Number']} />
          <InfoRow label={L('Jurisdiction')} value={englishData.jurisdiction || englishData['Jurisdiction']} />
        </div>
      </div>

      <div className="flex justify-center">
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
          className="space-y-3"
        >
          <div className="bg-white p-3 rounded-lg">
            <div className="space-y-1 text-gray-700">
              <InfoRow label={L('Incorporation Date')} value={englishData.incorporation_date || englishData['Incorporation Date']} />
              <InfoRow label={L('Company Type')} value={englishData.company_type || englishData['Company Type']} />
              <InfoRow label={L('Registered Agent')} value={englishData.registered_agent || englishData['Registered Agent']} />
              <InfoRow label={L('Registered Office')} value={englishData.registered_office || englishData['Registered Office']} />
              <InfoRow label={L('Share Capital')} value={englishData.share_capital || englishData['Share Capital']} />
              <InfoRow label={L('Currency')} value={englishData.currency || englishData['Currency']} />
            </div>
          </div>

          {/* Directors & Shareholders */}
          {directorsAndShareholders.length > 0 && (
            <div className="bg-white p-3 rounded-lg">
              <p className="font-semibold text-indigo-900 mb-2 flex items-center gap-2">
                <Users className="h-4 w-4" />
                {R('headings.directorsShareholders', { count: directorsAndShareholders.length })}
              </p>
              <div className="space-y-2">
                {directorsAndShareholders.map((person, idx) => (
                  <div key={idx} className="text-gray-700 text-xs border-b border-gray-100 pb-2 last:border-0 last:pb-0">
                    <div className="font-medium text-gray-800">
                      {person.name || person.full_name || person.name_english || `Person ${idx + 1}`}
                    </div>
                    {(person.role || person.position) && (
                      <div className="text-gray-600">{R('headings.role', { value: person.role || person.position })}</div>
                    )}
                    {(person.share_percentage || person.shares || person.ownership) && (
                      <div className="text-gray-600">
                        {R('headings.shares', { value: person.share_percentage || person.shares || person.ownership })}
                        {(person.share_percentage || person.ownership) && !String(person.share_percentage || person.ownership).endsWith('%') ? '%' : ''}
                      </div>
                    )}
                    {(person.nationality || person.nationality_english) && (
                      <div className="text-gray-600">{R('headings.nationality', { value: person.nationality || person.nationality_english })}</div>
                    )}
                    {(person.passport_number || person.passport) && (
                      <div className="text-gray-600">{R('headings.passport', { value: person.passport_number || person.passport })}</div>
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
