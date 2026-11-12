import React from 'react';
import { calculateAge } from '../../features/onboarding/utils/formatters';
import { useLanguage } from '../../context/LanguageContext';
import { translateValue } from '../../features/onboarding/utils/reportI18n';

const InfoRow = ({ label, value, icon: Icon, fullWidth = false, showAge = false }) => {
  const { t } = useLanguage();
  if (!value || value === 'N/A' || value === 'null' || value === 'undefined') {
    return null;
  }

  const isPositive = ['yes', 'true', 'identified'].includes(String(value).toLowerCase());
  const isNegative = ['no', 'clear'].includes(String(value).toLowerCase());
  const isDanger = ['false'].includes(String(value).toLowerCase());
  const isStatus = isPositive || isNegative || isDanger;

  return (
    <div className={`flex flex-col gap-1.5 ${fullWidth ? 'col-span-2' : ''}`}>
      {/* Field label */}
      <div className="flex items-center gap-1.5 px-1">
        {Icon && <Icon className="h-3 w-3 text-slate-400 flex-shrink-0" />}
        <span className="text-[9px] font-black text-slate-400 uppercase tracking-[0.2em] leading-none">{label}</span>
      </div>
      {/* Value container */}
      <div className={`px-4 py-3 rounded-2xl border transition-all duration-300 ${isDanger ? 'bg-rose-50/30 border-rose-100/50' :
        isPositive ? 'bg-emerald-50/30 border-emerald-100/50' :
          isNegative ? 'bg-emerald-50/30 border-emerald-100/50' :
            'bg-slate-50 border-slate-100 hover:border-slate-200'
        }`}>
        <div className="flex items-center justify-between gap-3">
          <p className={`text-[13px] font-bold tracking-tight leading-tight break-words ${isDanger ? 'text-rose-700' :
            isPositive ? 'text-emerald-700' :
              isNegative ? 'text-emerald-700' :
                'text-slate-800'
            }`}>
            {/* Fixed answers (Yes/No/True/False/Identified/Clear) are shown in the
                UI language; everything else is document data, shown exactly as
                extracted. <bdi> keeps IDs, dates and Latin names in order inside
                right-to-left text. Status colouring above still uses the raw value. */}
            <bdi>{String(translateValue(t, value))}</bdi>
          </p>
          {(showAge || isStatus) && (
            <div className="flex-shrink-0">
              {showAge ? (
                <span className="text-[10px] font-black text-slate-400 bg-slate-50 px-2 py-0.5 rounded-full border border-slate-100 shadow-sm">
                  {calculateAge(value)}
                </span>
              ) : isStatus ? (
                <div className={`h-2 w-2 rounded-full ${isDanger ? 'bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.5)]' :
                  isPositive ? 'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]' :
                    'bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]'
                  }`} />
              ) : null}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export { InfoRow };
