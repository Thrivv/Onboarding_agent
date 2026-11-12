import React, { useEffect, useState } from 'react';
import { getFatcaStatus, markFatcaNotApplicable, submitFatca } from '../../../../api/compliance';
import Sidebar from '../../../../components/layout/Sidebar';
import { Building, CheckCircle, Edit, FileText, Loader, ShieldCheck, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { FormSection } from '../../../../components/ui/FormSection';
import { useLanguage } from '../../../../context/LanguageContext';

// The five US-indicia questions. Any "yes" means a US nexus was declared.
const US_INDICIA_FIELDS = [
  'entity_incorporated_in_usa',
  'entity_has_us_ownership',
  'address_or_phone_in_usa',
  'payment_instruction_to_usa',
  'income_from_us_sources',
];

const FatcaInlineCard = ({ userEmail, onConfirmed, onDismiss, isEditMode = false }) => {
  const { t, language } = useLanguage();
  const [step, setStep] = useState('question'); // 'question' | 'form'
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [formData, setFormData] = useState({
    entity_type: '',
    country_of_tax_residence: 'UAE',
    passive_nffe_us_ownership: '',
    entity_incorporated_in_usa: '',
    entity_has_us_ownership: '',
    address_or_phone_in_usa: '',
    payment_instruction_to_usa: '',
    income_from_us_sources: '',
    irs_form_obtained: '',
    us_tax_id: '',
  });

  // In edit mode, pre-load existing FATCA data so the user sees what they filled before
  useEffect(() => {
    if (!userEmail) return;
    getFatcaStatus(userEmail)
      .then(res => {
        const d = res.data?.data;
        if (d) {
          // Normalize boolean values from backend back to 'yes'/'no' for our toggle logic
          const normalized = { ...d };
          Object.keys(normalized).forEach(key => {
            if (normalized[key] === true) normalized[key] = 'yes';
            if (normalized[key] === false) normalized[key] = 'no';
          });
          setFormData(prev => ({ ...prev, ...normalized }));
          // Jump straight to done if data already exists
          if (res.data?.status === 'completed') setDone(true);
        }
      })
      .catch(() => { });
  }, [isEditMode, userEmail]);

  const handleNotApplicable = async () => {
    setIsSubmitting(true);
    try {
      const res = await markFatcaNotApplicable({ email: userEmail, language });
      toast.success(t('cards.fatca.toastFatcaNA'));
      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
      onConfirmed({
        applicable: false,
        message: res.data.message,
        pep_trigger: res.data.pep_trigger || false,
        product_package_trigger: res.data.product_package_trigger || false,
        self_declaration_trigger: res.data.self_declaration_trigger || false,
        data: { applicable: false }
      });
    } catch {
      toast.error(t('cards.fatca.toastFatcaSaveFailed'));
    } finally {
      setIsSubmitting(false);
      setDone(true);
    }
  };

  const handleSubmitForm = async () => {
    const required = [
      'entity_type', 'country_of_tax_residence',
      'entity_incorporated_in_usa', 'entity_has_us_ownership',
      'address_or_phone_in_usa', 'payment_instruction_to_usa',
      'income_from_us_sources', 'irs_form_obtained',
    ];
    const missing = required.filter(f => !formData[f]);
    if (missing.length > 0) { toast.error(t('cards.fatca.toastFillRequired')); return; }
    setIsSubmitting(true);
    try {
      const res = await submitFatca({ email: userEmail, language, ...formData });
      if (!res.data.success) { toast.error(res.data.message || t('cards.fatca.toastFatcaSubmitFailed')); return; }
      toast.success(t('cards.fatca.toastFatcaSubmitted'));
      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
      onConfirmed({
        applicable: true,
        message: res.data.message,
        pep_trigger: res.data.pep_trigger || false,
        product_package_trigger: res.data.product_package_trigger || false,
        self_declaration_trigger: res.data.self_declaration_trigger || false,
        ...formData
      });
    } catch {
      toast.error(t('cards.fatca.toastFatcaSubmitFailed'));
    } finally {
      setIsSubmitting(false);
      setDone(true);
    }
  };

  const handleChange = (field, value) => setFormData(prev => ({ ...prev, [field]: value }));

  const renderYesNoField = (field, label) => (
    <div className="flex flex-col gap-2 p-3 bg-white border border-slate-100 rounded-2xl hover:border-indigo-100 transition-all">
      <label className="text-[11px] font-bold text-slate-700 leading-normal">
        {label} <span className="text-amber-500 font-black">*</span>
      </label>
      <div className="flex bg-slate-50 p-1 rounded-xl gap-1">
        {['yes', 'no'].map(v => (
          <button key={v} onClick={() => handleChange(field, v)}
            className={`flex-1 py-2 text-[10px] font-black uppercase rounded-lg transition-all duration-300 ${formData[field] === v
              ? 'bg-brand-primary text-white shadow-lg shadow-slate-300'
              : 'text-slate-400 hover:text-slate-600'
              }`}
          >{v === 'yes' ? t('cards.common.yes') : t('cards.common.no')}</button>
        ))}
      </div>
    </div>
  );

  if (done) {
    return (
      <div className="mt-3 bg-white border border-slate-100 rounded-[32px] overflow-hidden shadow-2xl shadow-slate-200/50 animate-in zoom-in-95 duration-700">
        {/* Top bar */}
        <div className="px-6 py-4 bg-slate-50 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="p-1.5 bg-indigo-100 rounded-lg">
              <ShieldCheck className="h-3.5 w-3.5 text-indigo-600" />
            </div>
            <h3 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">{t('cards.fatca.complianceCheck')}</h3>
          </div>
          <button
            onClick={() => { setDone(false); setStep('form'); }}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary hover:opacity-90 rounded-xl text-[10px] font-black text-white uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-indigo-200"
          >
            <Edit className="h-3.5 w-3.5" />
            {t('cards.fatca.editFatca')}
          </button>
        </div>

        <div className="p-6">
          <div className="flex items-start gap-5 mb-6">
            <div className="h-16 w-16 bg-brand-primary rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-200 shrink-0">
              <ShieldCheck className="h-8 w-8 text-white" />
            </div>
            <div className="pt-2">
              <p className="text-2xl font-black text-slate-900 tracking-tight leading-none">
                {t('cards.fatca.fatcaDeclaration')}
              </p>
              <p className="text-[11px] font-bold text-indigo-600 uppercase tracking-widest mt-2 bg-indigo-50 px-2 py-0.5 rounded-md w-fit">
                {t('cards.fatca.verified')}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <p className="text-[10px] font-black text-slate-400 uppercase tracking-wider ml-1">{t('cards.fatca.verificationDetails')}</p>
            <div className="flex flex-wrap gap-2">
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">{t('cards.fatca.entity')} {formData.entity_type || 'N/A'}</span>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">{t('cards.fatca.residency')} {formData.country_of_tax_residence}</span>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                {/* Computed from the answers — this used to say "US Nexus Clear"
                    unconditionally, even when every US indicator was "Yes". */}
                <span className="text-[11px] font-black text-slate-600 tracking-tight">
                  {US_INDICIA_FIELDS.some(f => formData[f] === 'yes')
                    ? t('cards.fatca.usNexusFound', { count: US_INDICIA_FIELDS.filter(f => formData[f] === 'yes').length })
                    : t('cards.fatca.usNexusClear')}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mt-3 rounded-xl border-2 border-slate-200 bg-white overflow-hidden">
      {/* Card header */}
      <div className="flex items-center justify-between px-4 py-3 bg-white border-b border-slate-100">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-slate-900" />
          <span className="text-sm font-bold text-slate-900">
            {isEditMode ? t('cards.fatca.editFatcaDeclaration') : t('cards.fatca.fatcaDeclaration')}
          </span>
        </div>
        {onDismiss && (
          <button onClick={onDismiss}
            className="p-1 hover:bg-slate-100 rounded-full transition-colors ml-2">
            <X className="h-4 w-4 text-slate-500" />
          </button>
        )}
      </div>

      <div className="p-4">
        {step === 'question' ? (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 bg-blue-100 rounded-full flex items-center justify-center flex-shrink-0">
                <FileText className="h-5 w-5 text-brand-primary" />
              </div>
              <div>
                <p className="text-sm font-semibold text-gray-900 mb-1">{t('cards.fatca.isFatcaApplicable')}</p>
                <p className="text-xs text-gray-500">
                  {t('cards.fatca.fatcaAppliesIf')}
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={handleNotApplicable} disabled={isSubmitting}
                className="flex-1 py-2 border-2 border-gray-200 text-gray-700 rounded-lg text-sm font-semibold hover:border-gray-300 hover:bg-gray-50 transition-all disabled:opacity-50 flex items-center justify-center gap-1">
                {isSubmitting ? <Loader className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                {t('cards.fatca.notApplicable')}
              </button>
              <button onClick={() => setStep('form')} disabled={isSubmitting}
                className="flex-1 py-2 bg-brand-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-1">
                <CheckCircle className="h-3 w-3" />
                {t('cards.fatca.yesFillForm')}
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <button onClick={() => setStep('question')}
              className="flex items-center gap-1.5 text-[10px] font-black text-slate-900 uppercase tracking-widest hover:translate-x-1 transition-transform mb-2">
              <span className="text-sm">←</span> {t('cards.fatca.back')}
            </button>

            <FormSection title={t('cards.fatca.entityTaxResidence')} icon={Building}>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.fatca.entityType')}</label>
                <select value={formData.entity_type} onChange={e => handleChange('entity_type', e.target.value)}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all">
                  <option value="">{t('cards.fatca.selectType')}</option>
                  <option value="LLC">{t('cards.fatca.entityTypeLLC')}</option>
                  <option value="Free Zone">{t('cards.fatca.entityTypeFreeZone')}</option>
                  <option value="Offshore">{t('cards.fatca.entityTypeOffshore')}</option>
                  <option value="Partnership">{t('cards.fatca.entityTypePartnership')}</option>
                  <option value="Branch">{t('cards.fatca.entityTypeBranch')}</option>
                  <option value="Other">{t('cards.fatca.entityTypeOther')}</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.fatca.countryOfTaxResidence')}</label>
                <input type="text" value={formData.country_of_tax_residence}
                  onChange={e => handleChange('country_of_tax_residence', e.target.value)}
                  placeholder={t('cards.fatca.countryPlaceholder')}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
            </FormSection>

            <FormSection title={t('cards.fatca.usNexusChecks')} icon={ShieldCheck}>
              {renderYesNoField("entity_incorporated_in_usa", t('cards.fatca.incorporatedInUsa'))}
              {renderYesNoField("entity_has_us_ownership", t('cards.fatca.usOwnership25'))}
              {renderYesNoField("address_or_phone_in_usa", t('cards.fatca.usAddressPhone'))}
              {renderYesNoField("payment_instruction_to_usa", t('cards.fatca.usPaymentInstructions'))}
              {renderYesNoField("income_from_us_sources", t('cards.fatca.usSourceIncome'))}
            </FormSection>

            <FormSection title={t('cards.fatca.complianceDetail')} icon={FileText}>
              {renderYesNoField("irs_form_obtained", t('cards.fatca.irsFormObtained'))}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.fatca.usTaxId')}</label>
                <input type="text" value={formData.us_tax_id}
                  onChange={e => handleChange('us_tax_id', e.target.value)}
                  placeholder={t('cards.fatca.idNumberPlaceholder')}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">{t('cards.fatca.passiveNffe')}</label>
                <input type="text" value={formData.passive_nffe_us_ownership}
                  onChange={e => handleChange('passive_nffe_us_ownership', e.target.value)}
                  placeholder={t('cards.fatca.percentPlaceholder')}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
            </FormSection>

            <button onClick={handleSubmitForm} disabled={isSubmitting}
              className="w-full py-4 mt-4 bg-brand-primary text-white rounded-2xl text-[11px] font-black uppercase tracking-[0.2em] hover:opacity-90 shadow-xl shadow-slate-200 transition-all disabled:opacity-50 flex items-center justify-center gap-3">
              {isSubmitting
                ? <><Loader className="h-5 w-5 animate-spin" /> {t('cards.fatca.processing')}</>
                : <><ShieldCheck className="h-5 w-5" /> {t('cards.fatca.submitDeclaration')}</>}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export { FatcaInlineCard };
