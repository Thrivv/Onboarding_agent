import React, { useEffect, useState } from 'react';
import { getFatcaStatus, markFatcaNotApplicable, submitFatca } from '../../../../api/compliance';
import Sidebar from '../../../../components/layout/Sidebar';
import { Building, CheckCircle, Edit, FileText, Loader, ShieldCheck, X } from 'lucide-react';
import toast from 'react-hot-toast';
import { FormSection } from '../../../../components/ui/FormSection';

const FatcaInlineCard = ({ userEmail, onConfirmed, onDismiss, isEditMode = false }) => {
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
      const res = await markFatcaNotApplicable({ email: userEmail });
      toast.success('FATCA recorded as Not Applicable');
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
      toast.error('Failed to save FATCA status');
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
    if (missing.length > 0) { toast.error('Please fill in all required fields'); return; }
    setIsSubmitting(true);
    try {
      const res = await submitFatca({ email: userEmail, ...formData });
      if (!res.data.success) { toast.error(res.data.message || 'Submission failed'); return; }
      toast.success('FATCA declaration submitted');
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
      toast.error('Failed to submit FATCA form');
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
          >{v === 'yes' ? 'Yes' : 'No'}</button>
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
            <h3 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Compliance Check</h3>
          </div>
          <button
            onClick={() => { setDone(false); setStep('form'); }}
            className="flex items-center gap-2 px-4 py-2.5 bg-brand-primary hover:opacity-90 rounded-xl text-[10px] font-black text-white uppercase tracking-widest transition-all active:scale-95 shadow-lg shadow-indigo-200"
          >
            <Edit className="h-3.5 w-3.5" />
            Edit FATCA
          </button>
        </div>

        <div className="p-6">
          <div className="flex items-start gap-5 mb-6">
            <div className="h-16 w-16 bg-brand-primary rounded-2xl flex items-center justify-center shadow-lg shadow-indigo-200 shrink-0">
              <ShieldCheck className="h-8 w-8 text-white" />
            </div>
            <div className="pt-2">
              <p className="text-2xl font-black text-slate-900 tracking-tight leading-none">
                FATCA Declaration
              </p>
              <p className="text-[11px] font-bold text-indigo-600 uppercase tracking-widest mt-2 bg-indigo-50 px-2 py-0.5 rounded-md w-fit">
                Verified
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <p className="text-[10px] font-black text-slate-400 uppercase tracking-wider ml-1">Verification Details</p>
            <div className="flex flex-wrap gap-2">
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">Entity: {formData.entity_type || 'N/A'}</span>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">Residency: {formData.country_of_tax_residence}</span>
              </div>
              <div className="px-3 py-1.5 bg-slate-50 border border-slate-100 rounded-xl flex items-center gap-2 transition-all hover:border-indigo-200 group">
                <div className="h-1.5 w-1.5 rounded-full bg-indigo-400 group-hover:bg-indigo-500 transition-colors" />
                <span className="text-[11px] font-black text-slate-600 tracking-tight">US Nexus Clear</span>
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
            {isEditMode ? 'Edit FATCA Declaration' : 'FATCA Declaration'}
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
                <p className="text-sm font-semibold text-gray-900 mb-1">Is FATCA applicable to your entity?</p>
                <p className="text-xs text-gray-500">
                  Applies if your entity has US connections — incorporation, ownership, address, or income from US sources.
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={handleNotApplicable} disabled={isSubmitting}
                className="flex-1 py-2 border-2 border-gray-200 text-gray-700 rounded-lg text-sm font-semibold hover:border-gray-300 hover:bg-gray-50 transition-all disabled:opacity-50 flex items-center justify-center gap-1">
                {isSubmitting ? <Loader className="h-3 w-3 animate-spin" /> : <X className="h-3 w-3" />}
                Not Applicable
              </button>
              <button onClick={() => setStep('form')} disabled={isSubmitting}
                className="flex-1 py-2 bg-brand-primary text-white rounded-lg text-sm font-semibold hover:opacity-90 transition-all disabled:opacity-50 flex items-center justify-center gap-1">
                <CheckCircle className="h-3 w-3" />
                Yes, Fill Form
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <button onClick={() => setStep('question')}
              className="flex items-center gap-1.5 text-[10px] font-black text-slate-900 uppercase tracking-widest hover:translate-x-1 transition-transform mb-2">
              <span className="text-sm">←</span> Back
            </button>

            <FormSection title="Entity & Tax Residence" icon={Building}>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">Entity Type</label>
                <select value={formData.entity_type} onChange={e => handleChange('entity_type', e.target.value)}
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all">
                  <option value="">Select type...</option>
                  <option value="LLC">LLC</option>
                  <option value="Free Zone">Free Zone Company</option>
                  <option value="Offshore">Offshore Company</option>
                  <option value="Partnership">Partnership</option>
                  <option value="Branch">Branch Office</option>
                  <option value="Other">Other</option>
                </select>
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">Country of Tax Residence</label>
                <input type="text" value={formData.country_of_tax_residence}
                  onChange={e => handleChange('country_of_tax_residence', e.target.value)}
                  placeholder="e.g. UAE"
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
            </FormSection>

            <FormSection title="US Nexus Checks" icon={ShieldCheck}>
              {renderYesNoField("entity_incorporated_in_usa", "Incorporated in the USA?")}
              {renderYesNoField("entity_has_us_ownership", "US ownership ≥ 25%?")}
              {renderYesNoField("address_or_phone_in_usa", "US address / phone?")}
              {renderYesNoField("payment_instruction_to_usa", "US Payment instructions?")}
              {renderYesNoField("income_from_us_sources", "US Source income?")}
            </FormSection>

            <FormSection title="Compliance Detail" icon={FileText}>
              {renderYesNoField("irs_form_obtained", "IRS Form (W8/W9) obtained?")}
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">US Tax ID / EIN (if any)</label>
                <input type="text" value={formData.us_tax_id}
                  onChange={e => handleChange('us_tax_id', e.target.value)}
                  placeholder="ID Number..."
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-black text-slate-500 uppercase tracking-wider ml-1">Passive NFFE Ownership %</label>
                <input type="text" value={formData.passive_nffe_us_ownership}
                  onChange={e => handleChange('passive_nffe_us_ownership', e.target.value)}
                  placeholder="e.g. 0%"
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-semibold focus:ring-2 focus:ring-indigo-500 focus:bg-white outline-none transition-all" />
              </div>
            </FormSection>

            <button onClick={handleSubmitForm} disabled={isSubmitting}
              className="w-full py-4 mt-4 bg-brand-primary text-white rounded-2xl text-[11px] font-black uppercase tracking-[0.2em] hover:opacity-90 shadow-xl shadow-slate-200 transition-all disabled:opacity-50 flex items-center justify-center gap-3">
              {isSubmitting
                ? <><Loader className="h-5 w-5 animate-spin" /> Processing...</>
                : <><ShieldCheck className="h-5 w-5" /> Submit Declaration</>}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export { FatcaInlineCard };
