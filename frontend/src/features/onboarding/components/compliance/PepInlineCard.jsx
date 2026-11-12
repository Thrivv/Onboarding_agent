import React, { useEffect, useState } from 'react';
import { getPepStatus, submitPep } from '../../../../api/compliance';
import Sidebar from '../../../../components/layout/Sidebar';
import { motion } from 'framer-motion';
import { CheckCircle, Edit, Globe, Loader, ShieldCheck, Users, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { FormSection } from '../../../../components/ui/FormSection';
import { stripFormatting } from '../../utils/formatters';
import { useLanguage } from '../../../../context/LanguageContext';

const PepInlineCard = ({ userEmail, onConfirmed, onDismiss, isEditMode = false }) => {
  const { t, language } = useLanguage();
  const [domesticStatus, setDomesticStatus] = useState(null); // null | true | false
  const [foreignStatus, setForeignStatus] = useState(null);
  const [domesticName, setDomesticName] = useState('');
  const [domesticPosition, setDomesticPosition] = useState('');
  const [foreignCountry, setForeignCountry] = useState('');
  const [foreignName, setForeignName] = useState('');
  const [foreignPosition, setForeignPosition] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  // In edit mode, pre-load existing PEP data so the user sees what they filled before
  useEffect(() => {
    if (!userEmail) return;
    getPepStatus(userEmail)
      .then(res => {
        const d = res.data?.data;
        if (d) {
          // Support for new nested format
          if (d.domestic_pep && typeof d.domestic_pep === 'object') {
            setDomesticStatus(d.domestic_pep.status ?? null);
            setDomesticName(d.domestic_pep.name || '');
            setDomesticPosition(d.domestic_pep.position || '');
          } else {
            // Legacy fallback
            setDomesticStatus(d.domestic_pep);
            setDomesticName(d.domestic_pep_name || '');
            setDomesticPosition(d.domestic_pep_position || '');
          }

          if (d.foreign_pep && typeof d.foreign_pep === 'object') {
            setForeignStatus(d.foreign_pep.status ?? null);
            setForeignCountry(d.foreign_pep.country || '');
            setForeignName(d.foreign_pep.name || '');
            setForeignPosition(d.foreign_pep.position || '');
          } else {
            // Legacy fallback
            setForeignStatus(d.foreign_pep);
            setForeignCountry(d.foreign_pep_country || '');
            setForeignName(d.foreign_pep_name || '');
            setForeignPosition(d.foreign_pep_position || '');
          }
          if (res.data?.status === 'completed') setDone(true);
        }
      })
      .catch(() => { });
  }, [isEditMode, userEmail]);

  const handleSubmit = async () => {
    if (domesticStatus === null || foreignStatus === null) {
      toast.error(t('cards.pep.toastBothRequired'));
      return;
    }
    if (domesticStatus && (!domesticName.trim() || !domesticPosition.trim())) {
      toast.error(t('cards.pep.toastDomesticRequired'));
      return;
    }
    if (foreignStatus && (!foreignCountry.trim() || !foreignName.trim() || !foreignPosition.trim())) {
      toast.error(t('cards.pep.toastForeignRequired'));
      return;
    }
    setIsSubmitting(true);
    try {
      const payload = {
        email: userEmail,
        language,
        domestic_pep: {
          status: domesticStatus,
          name: domesticName,
          position: domesticPosition
        },
        foreign_pep: {
          status: foreignStatus,
          country: foreignCountry,
          name: foreignName,
          position: foreignPosition
        }
      };
      const res = await submitPep(payload);
      toast.success(t('cards.pep.toastSaved'));
      setDone(true);
      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
      onConfirmed && onConfirmed({
        message: res.data?.message,
        product_package_trigger: res.data?.product_package_trigger || false,
        self_declaration_trigger: res.data?.self_declaration_trigger || false,
        ...payload
      });
    } catch (err) {
      toast.error(t('cards.pep.toastFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  if (done) {
    return (
      <div className="mt-3 bg-white border border-slate-100 rounded-[32px] overflow-hidden shadow-2xl shadow-slate-200/50 animate-in zoom-in-95 duration-700">
        {/* Top bar */}
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 bg-indigo-100 rounded-lg">
              <CheckCircle className="h-3.5 w-3.5 text-indigo-600" />
            </div>
            <h3 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">{t('cards.pep.identityCheck')}</h3>
          </div>
          <button
            onClick={() => setDone(false)}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary hover:opacity-90 rounded-xl text-[10px] font-black text-white uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-indigo-200"
          >
            <Edit className="h-3.5 w-3.5" />
            {t('cards.pep.editPep')}
          </button>
        </div>

        <div className="p-6">
          <div className="flex items-start gap-5 mb-6">
            <div className="h-16 w-16 bg-brand-primary rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-200 shrink-0">
              <Users className="h-8 w-8 text-white" />
            </div>
            <div className="pt-2">
              <p className="text-2xl font-black text-slate-900 tracking-tight leading-none">
                {t('cards.pep.title')}
              </p>
              <p className="text-[11px] font-bold text-indigo-600 uppercase tracking-widest mt-2 bg-indigo-50 px-2 py-0.5 rounded-md w-fit">
                {t('cards.pep.confirmed')}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <p className="text-[10px] font-black text-slate-400 uppercase tracking-wider ml-1">{t('cards.pep.screeningSummary')}</p>
            <div className="flex flex-wrap gap-2">
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className={`h-1.5 w-1.5 rounded-full ${domesticStatus ? 'bg-amber-400' : 'bg-indigo-400'} group-hover:scale-110 transition-transform`} />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">{t('cards.pep.domesticLabel', { status: domesticStatus ? t('cards.pep.identified') : t('cards.pep.clear') })}</span>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className={`h-1.5 w-1.5 rounded-full ${foreignStatus ? 'bg-amber-400' : 'bg-indigo-400'} group-hover:scale-110 transition-transform`} />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">{t('cards.pep.foreignLabel', { status: foreignStatus ? t('cards.pep.identified') : t('cards.pep.clear') })}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // FormSection hoisted globally

  return (
    <div className="mt-3 border-2 border-blue-200 rounded-3xl overflow-hidden shadow-xl shadow-indigo-100/30">
      {/* Header */}
      <div className="bg-brand-primary px-5 py-4 flex items-center justify-between">
        <div>
          <p className="text-white font-black text-sm uppercase tracking-tight">{isEditMode ? t('cards.pep.headerTitleEdit') : t('cards.pep.headerTitle')}</p>
          <p className="text-indigo-100 text-[10px] font-bold opacity-80 mt-1 leading-tight max-w-[280px]">
            {t('cards.pep.headerSubtitle')}
          </p>
        </div>
        {onDismiss && (
          <button onClick={onDismiss}
            className="p-1.5 hover:bg-white/20 rounded-full transition-colors ml-2 bg-white/10 border border-white/20">
            <X className="h-4 w-4 text-white" />
          </button>
        )}
      </div>

      <div className="bg-white p-5">
        {/* Domestic PEP */}
        <FormSection title={t('cards.pep.domesticCheckTitle')} icon={ShieldCheck}>
          <div className="space-y-4">
            <div className="flex flex-col gap-2 p-4 bg-slate-50 border border-slate-100 rounded-2xl hover:border-indigo-100 transition-all">
              <p className="text-[11px] font-bold text-slate-700 leading-tight">
                {t('cards.pep.domesticQuestion')}
              </p>
              <div className="flex bg-white/60 p-1 rounded-xl gap-1 border border-slate-200/50 mt-1">
                {[true, false].map(val => (
                  <button key={String(val)} onClick={() => setDomesticStatus(val)}
                    className={`flex-1 py-2 text-[10px] font-black uppercase rounded-lg transition-all duration-300 ${domesticStatus === val
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-200'
                      : 'text-slate-400 hover:text-slate-600'
                      }`}
                  >{val ? t('cards.common.yes') : t('cards.common.no')}</button>
                ))}
              </div>
            </div>
            {domesticStatus === true && (
              <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="space-y-3 p-4 bg-indigo-50/50 rounded-2xl border border-indigo-100">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.pep.fullName')}</label>
                  <input className="w-full px-4 py-3 bg-white border border-indigo-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                    placeholder={t('cards.pep.namePlaceholderDomestic')} value={domesticName} onChange={e => setDomesticName(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.pep.position')}</label>
                  <input className="w-full px-4 py-3 bg-white border border-indigo-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 outline-none transition-all"
                    placeholder={t('cards.pep.positionPlaceholderDomestic')} value={domesticPosition} onChange={e => setDomesticPosition(e.target.value)} />
                </div>
              </motion.div>
            )}
          </div>
        </FormSection>

        {/* Foreign PEP */}
        <FormSection title={t('cards.pep.foreignCheckTitle')} icon={Globe}>
          <div className="space-y-4">
            <div className="flex flex-col gap-2 p-4 bg-slate-50 border border-slate-100 rounded-2xl hover:border-indigo-100 transition-all">
              <p className="text-[11px] font-bold text-slate-700 leading-tight">
                {t('cards.pep.foreignQuestion')}
              </p>
              <div className="flex bg-white/60 p-1 rounded-xl gap-1 border border-slate-200/50 mt-1">
                {[true, false].map(val => (
                  <button key={String(val)} onClick={() => setForeignStatus(val)}
                    className={`flex-1 py-2 text-[10px] font-black uppercase rounded-lg transition-all duration-300 ${foreignStatus === val
                      ? 'bg-blue-600 text-white shadow-lg shadow-blue-200'
                      : 'text-slate-400 hover:text-slate-600'
                      }`}
                  >{val ? t('cards.common.yes') : t('cards.common.no')}</button>
                ))}
              </div>
            </div>
            {foreignStatus === true && (
              <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} className="space-y-3 p-4 bg-blue-50/50 rounded-2xl border border-blue-100">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.pep.country')}</label>
                  <input className="w-full px-4 py-3 bg-white border border-blue-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-blue-500 outline-none transition-all"
                    placeholder={t('cards.pep.countryPlaceholder')} value={foreignCountry} onChange={e => setForeignCountry(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.pep.fullName')}</label>
                  <input className="w-full px-4 py-3 bg-white border border-blue-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-blue-500 outline-none transition-all"
                    placeholder={t('cards.pep.namePlaceholderForeign')} value={foreignName} onChange={e => setForeignName(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.pep.position')}</label>
                  <input className="w-full px-4 py-3 bg-white border border-blue-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-blue-500 outline-none transition-all"
                    placeholder={t('cards.pep.positionPlaceholderForeign')} value={foreignPosition} onChange={e => setForeignPosition(e.target.value)} />
                </div>
              </motion.div>
            )}
          </div>
        </FormSection>

        <button onClick={handleSubmit} disabled={isSubmitting || domesticStatus === null || foreignStatus === null}
          className="w-full py-4 mt-6 bg-blue-600 hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 text-white text-[11px] font-black uppercase tracking-[0.2em] rounded-2xl shadow-xl shadow-blue-100 transition-all flex items-center justify-center gap-3">
          {isSubmitting
            ? <><Loader className="h-5 w-5 animate-spin" /> {t('cards.pep.processing')}</>
            : <><ShieldCheck className="h-5 w-5" /> {t('cards.pep.submitDeclaration')}</>}
        </button>
      </div>
    </div>
  );
};


/**
 * stripFormatting — strips raw Markdown syntax and emoji characters from LLM output.
 * Preserves newlines, numbered lists, and plain punctuation so that structured
 * content (e.g. numbered member lists) continues to render correctly.
 */

export { PepInlineCard };
