import React, { useRef, useState } from 'react';
import { generateOtp, verifyOtp } from '../../../../api/auth';
import { saveKeyIndividualContactInfo } from '../../../../api/keyIndividuals';
import Sidebar from '../../../../components/layout/Sidebar';
import { CheckCircle, Loader, Mail, Phone, PieChart, Send, ShieldCheck } from 'lucide-react';
import toast from 'react-hot-toast';
import { useLanguage } from '../../../../context/LanguageContext';

const KiDetailsCard = ({ userEmail, kiName, kiRole, onConfirmed }) => {
  const { t } = useLanguage();
  const [contactEmail, setContactEmail] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [otpDigits, setOtpDigits] = useState(['', '', '', '', '', '']);
  const [otpVerified, setOtpVerified] = useState(false);
  const [phoneNumber, setPhoneNumber] = useState('');
  const [sharePercentage, setSharePercentage] = useState('');
  const [isSendingOtp, setIsSendingOtp] = useState(false);
  const [isVerifyingOtp, setIsVerifyingOtp] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [otpError, setOtpError] = useState('');
  const otpRefs = useRef([]);

  const displayRole = (() => {
    const r = String(kiRole || '').toUpperCase().replace(/_/g, ' ');
    if (r === 'AS' || r === 'AUTHORISED SIGNATORY') return t('cards.common.authorisedSignatory');
    if (r === 'MEMBER') return t('cards.common.member');
    return kiRole || t('cards.common.keyIndividual');
  })();

  const initials = (kiName || '?').split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();

  // ── OTP: send ──────────────────────────────────────────────────────────
  const handleSendOtp = async () => {
    if (!contactEmail.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contactEmail.trim())) {
      toast.error(t('cards.kiDetails.toastEnterValidEmail'));
      return;
    }
    setIsSendingOtp(true);
    setOtpError('');
    try {
      await generateOtp({ email: contactEmail.trim() });
      setOtpSent(true);
      toast.success(t('cards.kiDetails.toastOtpSent'));
      setTimeout(() => otpRefs.current[0]?.focus(), 100);
    } catch (err) {
      toast.error(t('cards.kiDetails.toastOtpFailed'));
    } finally {
      setIsSendingOtp(false);
    }
  };

  // ── OTP: digit input ───────────────────────────────────────────────────
  const handleOtpDigit = (idx, val) => {
    const digit = val.replace(/\D/g, '').slice(-1);
    const next = [...otpDigits];
    next[idx] = digit;
    setOtpDigits(next);
    setOtpError('');
    if (digit && idx < 5) otpRefs.current[idx + 1]?.focus();
    if (next.every(d => d !== '') && next.join('').length === 6) {
      handleVerifyOtp(next.join(''));
    }
  };

  const handleOtpKeyDown = (idx, e) => {
    if (e.key === 'Backspace' && !otpDigits[idx] && idx > 0) {
      otpRefs.current[idx - 1]?.focus();
    }
  };

  // ── OTP: verify ────────────────────────────────────────────────────────
  const handleVerifyOtp = async (code) => {
    const pin = code || otpDigits.join('');
    if (pin.length !== 6) return;
    setIsVerifyingOtp(true);
    setOtpError('');
    try {
      await verifyOtp({ email: contactEmail.trim(), otp: pin });
      setOtpVerified(true);
      toast.success(t('cards.kiDetails.toastEmailVerified'));
    } catch (err) {
      setOtpError(t('cards.kiDetails.otpInvalid'));
      setOtpDigits(['', '', '', '', '', '']);
      setTimeout(() => otpRefs.current[0]?.focus(), 100);
    } finally {
      setIsVerifyingOtp(false);
    }
  };

  // ── Confirm all details ────────────────────────────────────────────────
  const handleConfirm = async () => {
    if (!otpVerified) { toast.error(t('cards.kiDetails.toastEmailFirst')); return; }
    if (!phoneNumber.trim()) { toast.error(t('cards.kiDetails.toastPhoneRequired')); return; }
    const sharePct = sharePercentage !== '' ? parseFloat(sharePercentage) : null;
    if (sharePercentage !== '' && (isNaN(sharePct) || sharePct < 0 || sharePct > 100)) {
      toast.error(t('cards.kiDetails.toastShareRange'));
      return;
    }
    setIsSaving(true);
    try {
      const res = await saveKeyIndividualContactInfo({
        email: userEmail,
        ki_name: kiName,
        system_role: 'Self Admin',
        contact_email: contactEmail.trim(),
        phone_number: phoneNumber.trim(),
        share_percentage: sharePct,
      });
      setSaved(true);
      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
      if (onConfirmed) onConfirmed({
        ki_name: kiName,
        contact_email: contactEmail.trim(),
        phone_number: phoneNumber.trim(),
        share_percentage: sharePct,
        ownershipMap: res.data?.ownershipMap || {},
        kiContactMap: res.data?.kiContactMap || {},
        message: res.data?.message || '',
      });
    } catch (err) {
      toast.error(t('cards.kiDetails.toastSaveFailed'));
    } finally {
      setIsSaving(false);
    }
  };


  if (saved) {
    const sharePct = sharePercentage !== '' ? parseFloat(sharePercentage) : null;
    return (
      <div className="rounded-[20px] border border-emerald-200 bg-emerald-50 p-4 space-y-3 animate-in fade-in slide-in-from-bottom-3 duration-500">
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0">
            <CheckCircle className="h-3.5 w-3.5 text-white" />
          </div>
          <p className="text-[12px] font-black text-emerald-700 uppercase tracking-tight">{t('cards.kiDetails.detailsSavedFor', { name: kiName })}</p>
        </div>
        <div className="grid grid-cols-1 gap-1.5 pl-8">
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Mail className="h-3 w-3 text-blue-400 flex-shrink-0" />
            <span>{contactEmail}</span>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Phone className="h-3 w-3 text-emerald-400 flex-shrink-0" />
            <span>{phoneNumber}</span>
          </div>
          {sharePct !== null && (
            <div className="flex items-center gap-2 text-[11px] text-slate-500">
              <PieChart className="h-3 w-3 text-purple-400 flex-shrink-0" />
              <span>{t('cards.kiDetails.share')} <span className="font-black text-brand-secondary bg-blue-50 border border-blue-100 px-1.5 py-0.5 rounded-lg">{sharePct}%</span></span>
            </div>
          )}
        </div>
        <p className="text-[10px] text-slate-400 pl-8 italic">{t('cards.kiDetails.savedToRecord')}</p>
      </div>
    );
  }

  const canConfirm = otpVerified && phoneNumber.trim().length > 0;

  return (
    <div className="rounded-[24px] border border-slate-100 bg-white shadow-xl shadow-slate-200/40 p-5 space-y-5 animate-in fade-in slide-in-from-bottom-4 duration-700">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-2xl bg-indigo-600 flex items-center justify-center text-[12px] font-black text-white shadow-lg shadow-indigo-100 flex-shrink-0">
            {initials}
          </div>
          <div>
            <p className="text-[14px] font-black text-slate-800 tracking-tight">{kiName}</p>
            <span className="text-[10px] font-black uppercase tracking-[0.15em] text-indigo-400">{displayRole}</span>
          </div>
        </div>
        {otpVerified && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-emerald-50 border border-emerald-100 rounded-full">
            <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[9px] font-black text-emerald-600 uppercase tracking-wider">{t('cards.kiDetails.verified')}</span>
          </div>
        )}
      </div>

      <div className="h-px bg-slate-50" />

      {/* Email + OTP Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-[10px] font-black uppercase tracking-[0.1em] text-slate-400 flex items-center gap-1.5">
            <Mail className="h-3 w-3" />
            {t('cards.kiDetails.emailAddress')}
          </label>
        </div>

        <div className="relative group">
          <input
            type="email"
            value={contactEmail}
            onChange={e => { setContactEmail(e.target.value); setOtpSent(false); setOtpVerified(false); setOtpDigits(['', '', '', '', '', '']); }}
            disabled={otpVerified}
            placeholder="individual@company.ae"
            className={`w-full h-11 rounded-2xl border px-4 pl-10 text-[13px] font-bold outline-none transition-all duration-300 ${otpVerified
              ? 'border-emerald-300 bg-emerald-50/50 text-emerald-700'
              : 'border-slate-200 bg-slate-50/50 text-slate-800 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/5'
              }`}
          />
          {otpSent && !otpVerified && (
            <p className="mt-1.5 ml-2 text-[10px] font-bold text-brand-primary animate-in fade-in slide-in-from-top-1 duration-300">
              {t('cards.kiDetails.otpSentToEmail')}
            </p>
          )}
          <Mail className={`absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 transition-colors ${otpVerified ? 'text-emerald-500' : 'text-slate-300 group-focus-within:text-blue-500'}`} />

          <div className="absolute right-1.5 top-1.5 flex gap-1.5">
            {!otpVerified && (
              <button
                onClick={handleSendOtp}
                disabled={isSendingOtp || !contactEmail.trim() || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(contactEmail.trim())}
                className="h-8 px-4 rounded-xl bg-brand-primary text-[10px] font-black uppercase tracking-wider disabled:opacity-30 hover:bg-brand-secondary transition-all active:scale-95 shadow-md shadow-blue-100 flex items-center gap-2"
              >
                {isSendingOtp ? <Loader className="h-3 w-3 animate-spin" /> : <><Send className="h-3 w-3" /> {otpSent ? t('cards.kiDetails.resend') : t('cards.kiDetails.sendOtp')}</>}
              </button>
            )}
            {otpVerified && (
              <div className="h-8 w-8 rounded-xl bg-emerald-500 flex items-center justify-center shadow-lg shadow-emerald-100 animate-in zoom-in duration-300">
                <CheckCircle className="h-4 w-4 text-white" />
              </div>
            )}
          </div>
        </div>


        {/* OTP Input Grid */}
        {otpSent && !otpVerified && (
          <div className="space-y-3 pt-1 animate-in fade-in slide-in-from-top-2 duration-500">
            <p className="text-[10px] text-slate-500 font-bold flex items-center gap-1.5 ml-1">
              <ShieldCheck className="h-3 w-3 text-blue-500" />
              {t('cards.kiDetails.enterCode')} <span className="text-slate-300 font-medium">{t('cards.kiDetails.devHint')}</span>
            </p>
            <div className="flex gap-2">
              {otpDigits.map((d, idx) => (
                <input
                  key={idx}
                  ref={el => otpRefs.current[idx] = el}
                  type="text"
                  inputMode="numeric"
                  maxLength={1}
                  value={d}
                  onChange={e => handleOtpDigit(idx, e.target.value)}
                  onKeyDown={e => handleOtpKeyDown(idx, e)}
                  disabled={isVerifyingOtp}
                  className={`w-10 h-12 rounded-xl border text-center text-[18px] font-black outline-none transition-all duration-200 ${d ? 'border-blue-500 bg-blue-50 text-brand-secondary ring-2 ring-blue-500/5' : 'border-slate-200 bg-slate-50/50 text-slate-800 focus:border-blue-400 focus:bg-white'
                    }`}
                />
              ))}
              {isVerifyingOtp && <Loader className="h-5 w-5 animate-spin text-blue-500 self-center ml-2" />}
            </div>
            {otpError && (
              <div className="flex items-center gap-1.5 px-2 py-1.5 bg-red-50 rounded-lg border border-red-100 animate-shake">
                <p className="text-[10px] text-red-500 font-bold">{otpError}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Phone Number Input */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.1em] text-slate-400 flex items-center gap-1.5">
          <Phone className="h-3 w-3" />
          {t('cards.kiDetails.phoneNumber')}
        </label>
        <div className="relative group">
          <input
            type="tel"
            value={phoneNumber}
            onChange={e => setPhoneNumber(e.target.value)}
            placeholder="+971 50 123 4567"
            className="w-full h-11 rounded-2xl border border-slate-200 bg-slate-50/50 px-4 pl-10 text-[13px] font-bold text-slate-800 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/5"
          />
          <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-300 group-focus-within:text-blue-500 transition-colors" />
        </div>
      </div>

      {/* Share Percentage Input */}
      <div className="space-y-2">
        <label className="text-[10px] font-black uppercase tracking-[0.1em] text-slate-400 flex items-center justify-between">
          <span className="flex items-center gap-1.5"><PieChart className="h-3 w-3" /> {t('cards.kiDetails.sharePercentage')}</span>
          <span className="text-slate-300 normal-case font-medium">{t('cards.kiDetails.optional')}</span>
        </label>
        <div className="flex items-center gap-3">
          <div className="relative group w-32">
            <input
              type="number"
              min="0"
              max="100"
              step="0.01"
              value={sharePercentage}
              onChange={e => setSharePercentage(e.target.value)}
              placeholder="e.g. 25"
              className="w-full h-11 rounded-2xl border border-slate-200 bg-slate-50/50 px-4 pl-9 text-[13px] font-bold text-slate-800 outline-none transition-all duration-300 focus:border-blue-500 focus:bg-white focus:ring-4 focus:ring-blue-500/5"
            />
            <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[13px] font-black text-slate-300 group-focus-within:text-blue-500 transition-colors">%</span>
          </div>
          {sharePercentage !== '' && !isNaN(parseFloat(sharePercentage)) && (
            <div className="flex-1 px-4 py-2 bg-blue-50/50 border border-blue-100 rounded-2xl flex items-center justify-between animate-in zoom-in duration-300">
              <span className="text-[11px] font-bold text-brand-primary">{t('cards.kiDetails.ownership')}</span>
              <span className="text-[13px] font-black text-brand-secondary">{parseFloat(sharePercentage)}%</span>
            </div>
          )}
        </div>
      </div>

      {/* Action Button */}
      <button
        onClick={handleConfirm}
        disabled={!canConfirm || isSaving}
        className={`w-full h-12 rounded-[20px] text-[13px] font-black uppercase tracking-widest transition-all duration-300 flex items-center justify-center gap-3 shadow-lg ${canConfirm && !isSaving
          ? 'bg-brand-primary text-white shadow-emerald-200 hover:shadow-emerald-300 active:scale-[0.98]'
          : 'bg-slate-100 text-slate-400 cursor-not-allowed shadow-none'
          }`}
      >
        {isSaving ? (
          <><Loader className="h-4 w-4 animate-spin" /> {t('cards.kiDetails.savingDetails')}</>
        ) : (
          <><CheckCircle className="h-4 w-4" /> {t('cards.kiDetails.confirmContinue')}</>
        )}
      </button>
    </div>
  );
};




// ============================================================================
// OWNERSHIP TYPE CARD
// Ownership Type used to be collected on the signup wizard (removed — signup
// is now a single page with no ownership choice). This is now the first
// onboarding question the assistant asks, gated by the backend's
// ownership_selection_pending flag (see get_onboarding_status()).
// ============================================================================

export { KiDetailsCard };
