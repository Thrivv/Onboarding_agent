import React, { useState } from 'react';
import { useLanguage } from '../../../../context/LanguageContext';
import { markFatcaNotApplicable, submitFatca } from '../../../../api/compliance';
import { CheckCircle, FileText, Loader, X } from 'lucide-react';
import toast from 'react-hot-toast';

const FatcaModal = ({ isOpen, onClose, onConfirmed, userEmail }) => {
  const { t } = useLanguage();
  const [step, setStep] = useState('question'); // 'question' | 'form'
  const [isSubmitting, setIsSubmitting] = useState(false);
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

  const handleNotApplicable = async () => {
    setIsSubmitting(true);
    try {
      const res = await markFatcaNotApplicable({ email: userEmail });
      toast.success(t('ui.fatcaNotApplicableToast'));
      onConfirmed({
        applicable: false,
        message: res.data.message,
        so_as_trigger: res.data.so_as_trigger || false,
        so_owner: res.data.so_owner || null,
      });
      onClose();
    } catch (e) {
      toast.error(t('ui.fatcaSaveFailed'));
    } finally {
      setIsSubmitting(false);
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
    if (missing.length > 0) {
      toast.error(t('ui.fillAllRequired'));
      return;
    }
    setIsSubmitting(true);
    try {
      const res = await submitFatca({ email: userEmail, ...formData });
      if (!res.data.success) {
        toast.error(res.data.message || t('ui.submissionFailed'));
        return;
      }
      toast.success(t('ui.fatcaSubmittedToast'));
      onConfirmed({
        applicable: true,
        message: res.data.message,
        so_as_trigger: res.data.so_as_trigger || false,
        so_owner: res.data.so_owner || null,
      });
      onClose();
    } catch (e) {
      toast.error(t('ui.fatcaSubmitFailed'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleChange = (field, value) => {
    setFormData(prev => ({ ...prev, [field]: value }));
  };

  if (!isOpen) return null;

  const yesNoOptions = [
    { value: 'yes', label: t('ui.yes') },
    { value: 'no', label: t('ui.no') },
  ];

  const YesNoSelect = ({ field, label, required = true }) => (
    <div className="flex flex-col gap-1">
      <label className="text-xs font-semibold text-gray-700">
        {label}{required && <span className="text-red-500 ms-1">*</span>}
      </label>
      <div className="flex gap-2">
        {yesNoOptions.map(opt => (
          <button
            key={opt.value}
            onClick={() => handleChange(field, opt.value)}
            className={`flex-1 py-2 rounded-lg border-2 text-sm font-medium transition-all ${formData[field] === opt.value
              ? 'bg-brand-primary border-indigo-600 text-white'
              : 'bg-white border-gray-300 text-gray-700 hover:border-indigo-400'
              }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-primary bg-opacity-60 p-4">
      <div className="bg-white rounded-[32px] overflow-hidden shadow-2xl max-w-md w-full m-4 max-h-[90vh] flex flex-col">
        {/* Header - BRAND GRADIENT */}
        <div className="bg-brand-primary px-8 py-6 text-white relative flex justify-between items-center shrink-0">
          <div>
            <h2 className="text-xl font-black tracking-tight leading-tight">{t('ui.fatcaTitle')}</h2>
            <p className="text-[11px] font-bold text-white/70 uppercase tracking-widest mt-1">{t('ui.fatcaSubtitle')}</p>
          </div>
          <button onClick={onClose} className="p-2 hover:bg-white/10 rounded-full transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-8 pt-6 pb-8 custom-scrollbar">
          {step === 'question' ? (
            <div className="text-center space-y-5">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto">
                <FileText className="h-8 w-8 text-brand-primary" />
              </div>
              <div>
                <h3 className="text-base font-bold text-gray-900 mb-2">{t('ui.fatcaApplicableQ')}</h3>
                <p className="text-sm text-gray-600">
                  {t('ui.fatcaApplicableHint')}
                </p>
              </div>
              <div className="flex gap-3 justify-center pt-2">
                <button
                  onClick={handleNotApplicable}
                  disabled={isSubmitting}
                  className="px-6 py-3 border-2 border-gray-300 text-gray-700 rounded-xl font-semibold hover:border-gray-400 hover:bg-gray-50 transition-all disabled:opacity-50 flex items-center gap-2"
                >
                  {isSubmitting ? <Loader className="h-4 w-4 animate-spin" /> : <X className="h-4 w-4" />}
                  {t('ui.notApplicable')}
                </button>
                <button
                  onClick={() => setStep('form')}
                  disabled={isSubmitting}
                  className="px-6 py-3 bg-brand-primary text-white rounded-xl font-semibold hover:opacity-90 transition-all disabled:opacity-50 flex items-center gap-2"
                >
                  <CheckCircle className="h-4 w-4" />
                  {t('ui.yesFillForm')}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <button
                onClick={() => setStep('question')}
                className="text-xs text-brand-primary hover:underline flex items-center gap-1"
              >
                {t('ui.backToQuestion')}
              </button>

              <div className="space-y-3">
                {/* Entity Type */}
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-gray-700">
                    {t('ui.entityType')} <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={formData.entity_type}
                    onChange={e => handleChange('entity_type', e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  >
                    <option value="">{t('ui.selectEntityType')}</option>
                    <option value="LLC">{t('ui.entityLLC')}</option>
                    <option value="Free Zone">{t('ui.entityFreeZone')}</option>
                    <option value="Offshore">{t('ui.entityOffshore')}</option>
                    <option value="Partnership">{t('ui.entityPartnership')}</option>
                    <option value="Branch">{t('ui.entityBranch')}</option>
                    <option value="Other">{t('ui.entityOther')}</option>
                  </select>
                </div>

                {/* Country of Tax Residence */}
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-gray-700">
                    {t('ui.countryTaxResidence')} <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    value={formData.country_of_tax_residence}
                    onChange={e => handleChange('country_of_tax_residence', e.target.value)}
                    placeholder={t('ui.countryPlaceholder')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>

                {/* Passive NFFE */}
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-gray-700">
                    {t('ui.passiveNffe')}
                  </label>
                  <input
                    type="text"
                    value={formData.passive_nffe_us_ownership}
                    onChange={e => handleChange('passive_nffe_us_ownership', e.target.value)}
                    placeholder={t('ui.nffePlaceholder')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>

                <YesNoSelect field="entity_incorporated_in_usa" label={t('ui.fatcaQIncorporated')} />
                <YesNoSelect field="entity_has_us_ownership" label={t('ui.fatcaQUsOwnership')} />
                <YesNoSelect field="address_or_phone_in_usa" label={t('ui.fatcaQUsAddress')} />
                <YesNoSelect field="payment_instruction_to_usa" label={t('ui.fatcaQUsPayment')} />
                <YesNoSelect field="income_from_us_sources" label={t('ui.fatcaQUsIncome')} />
                <YesNoSelect field="irs_form_obtained" label={t('ui.fatcaQIrsForm')} />

                {/* US Tax ID */}
                <div className="flex flex-col gap-1">
                  <label className="text-xs font-semibold text-gray-700">{t('ui.usTaxIdOptional')}</label>
                  <input
                    type="text"
                    value={formData.us_tax_id}
                    onChange={e => handleChange('us_tax_id', e.target.value)}
                    placeholder={t('ui.usTaxIdPlaceholder')}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  />
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer for form step */}
        {step === 'form' && (
          <div className="p-5 border-t bg-gray-50 rounded-b-2xl">
            <button
              onClick={handleSubmitForm}
              disabled={isSubmitting}
              className="w-full py-3 bg-brand-primary text-white rounded-xl font-bold hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {isSubmitting ? (
                <><Loader className="h-5 w-5 animate-spin" /> {t('ui.submitting')}</>
              ) : (
                <><CheckCircle className="h-5 w-5" /> {t('ui.submitFatca')}</>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};


// ============================================================================
// FINAL SUCCESS MODAL
// ============================================================================

export { FatcaModal };
