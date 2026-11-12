import React from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { ChevronRight, Users } from 'lucide-react';

const RoleMismatchSelector = ({ options, onSelect }) => {
  const { t } = useLanguage();
  return (
    <div className="mt-3 p-5 bg-brand-primary border-2 border-amber-100 rounded-[32px] shadow-lg shadow-amber-500/5 animate-in zoom-in-95 duration-500">
      <div className="flex items-center gap-2.5 mb-4 px-1">
        <div className="p-2 bg-amber-100 rounded-xl">
          <Users className="h-4 w-4 text-amber-600" />
        </div>
        <div>
          <h4 className="text-[11px] font-black text-amber-900 uppercase tracking-widest leading-none mb-1">{t('ui.verifyMemberRole')}</h4>
          <p className="text-[9px] font-bold text-amber-600/60 uppercase tracking-widest">{t('ui.selectAccurateRole')}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2.5">
        {options.map((opt, i) => (
          <button
            key={i}
            onClick={() => onSelect(opt.value)}
            className="group flex flex-col p-4 bg-white border-2 border-white hover:border-amber-400 hover:shadow-xl hover:shadow-amber-100/50 rounded-2xl text-start transition-all duration-300 active:scale-[0.98]"
          >
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[12px] font-black text-slate-800 uppercase tracking-tight group-hover:text-amber-600 transition-colors">{opt.label}</span>
              <ChevronRight className="h-4 w-4 text-slate-200 group-hover:text-amber-400 ltr:group-hover:translate-x-1 rtl:group-hover:-translate-x-1 rtl:rotate-180 transition-all" />
            </div>
            <p className="text-[10px] font-bold text-slate-400 group-hover:text-slate-500 transition-colors leading-relaxed">{opt.desc}</p>
          </button>
        ))}
      </div>
    </div>
  );
};


// ============================================================================
// INLINE FORMS (FATCA & PEP)
// ============================================================================

export { RoleMismatchSelector };
