import React, { useEffect, useState } from 'react';
import { confirmSelfDeclaration, getSelfDeclarationStatus, getSelfDeclarationSummary } from '../../../../api/compliance';
import Sidebar from '../../../../components/layout/Sidebar';
import { AlertCircle, CheckCircle, Clock, Copy, Loader, Lock, ShieldCheck } from 'lucide-react';
import toast from 'react-hot-toast';
import logger from '../../../../utils/logger';
import { useReportI18n } from '../../utils/reportI18n';

const SelfDeclarationCard = ({ userEmail, onConfirmed, isEnabled = false }) => {
  const { R } = useReportI18n();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [isConfirming, setIsConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [referenceId, setReferenceId] = useState(null);
  const [, setCrossValidating] = useState(false);
  const [crossValidResult, setCrossValidResult] = useState(null); // null | 'passed' | 'failed'
  const [cvMessage, setCvMessage] = useState('');

  useEffect(() => {
    // Automatically switch to Unified Report mode in sidebar when this shows
    if (window.setAiaSidebarMode) {
      window.setAiaSidebarMode('data');
    }
    const initialize = async () => {
      try {
        // Fetch summary
        const sumResp = await getSelfDeclarationSummary(userEmail);
        setSummary(sumResp.data);

        // Fetch status to check if already confirmed
        const statusResp = await getSelfDeclarationStatus(userEmail);
        if (statusResp.data?.confirmed) {
          setConfirmed(true);
          setReferenceId(statusResp.data.reference_number);
          setCrossValidResult(statusResp.data.cross_validation_passed ? 'passed' : 'failed');
          setCvMessage(statusResp.data.cross_validation_message || '');
        }
      } catch (e) {
        logger.error('[SELF-DECL] Initialization failed', e);
      } finally {
        setLoading(false);
      }
    };
    initialize();
  }, [userEmail]);

  const handleConfirm = async () => {
    setIsConfirming(true);
    setCrossValidating(true);
    try {
      const res = await confirmSelfDeclaration({ email: userEmail });
      toast.success(R('declaration.selfDeclConfirmedToast'));

      const cvData = res.data.crossValidation || res.data;
      const refNo = res.data.reference_number || cvData.reference_number;

      setConfirmed(true);
      setReferenceId(refNo);
      setCrossValidResult(cvData.passed ? 'passed' : 'failed');
      setCvMessage(cvData.message || '');

      window.dispatchEvent(new Event('compliance-updated')); // Trigger Sidebar refresh
      if (onConfirmed) onConfirmed({ ...res.data, crossValidation: cvData });

      // Redirect to verification progress after 3 seconds
      setTimeout(() => {
        // window.location.href = REDIRECT_URL;
      }, 3000);
    } catch (e) {
      toast.error(R('declaration.selfDeclFailedToast'));
    } finally {
      setIsConfirming(false);
      setCrossValidating(false);
    }
  };

  const copyToClipboard = () => {
    if (referenceId) {
      navigator.clipboard.writeText(referenceId);
      toast.success(R('declaration.refCopied2'));
    }
  };

  if (loading) {
    return (
      <div className="mt-3 p-4 bg-brand-primary rounded-xl border-2 border-green-200 flex items-center gap-3">
        <Loader className="h-5 w-5 animate-spin text-green-600" />
        <span className="text-sm text-green-700">{R('declaration.loadingSummary')}</span>
      </div>
    );
  }

  if (!summary && !confirmed) {
    return (
      <div className="mt-3 p-4 bg-brand-primary rounded-xl border-2 border-green-200">
        <div className="flex items-center gap-2 mb-3">
          <CheckCircle className="h-5 w-5 text-green-600" />
          <p className="text-sm font-bold text-green-900">{R('declaration.selfDeclaration')}</p>
        </div>
        <p className="text-xs text-gray-600 mb-3">
          {R('declaration.pleaseConfirm')}
        </p>
        <button
          onClick={handleConfirm}
          disabled={isConfirming || confirmed || !isEnabled}
          className="w-full py-2 px-4 bg-green-600 hover:bg-green-700 text-white text-sm font-semibold rounded-lg transition-colors disabled:opacity-50"
        >
          {confirmed ? R('declaration.confirmedShort') : isConfirming ? R('declaration.confirming') : R('declaration.iConfirmDeclare')}
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 p-6 bg-white border-2 border-green-100 rounded-[32px] shadow-xl shadow-green-500/5 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="flex items-center gap-2 mb-4">
        <CheckCircle className="h-5 w-5 text-green-600" />
        <p className="text-sm font-black text-green-900 uppercase tracking-tight">{R('declaration.summaryTitle')}</p>
      </div>

      {/* Declaration Text */}
      <div className="mb-6 p-4 bg-amber-50/50 border border-amber-100 rounded-2xl">
        <p className="text-xs text-slate-600 italic leading-relaxed font-medium">
          {R('declaration.text')}
        </p>
      </div>

      {!confirmed ? (
        <button
          onClick={handleConfirm}
          disabled={isConfirming || !isEnabled}
          className={`w-full py-4 rounded-2xl font-black text-[11px] uppercase tracking-[0.2em] transition-all flex items-center justify-center gap-3 shadow-xl ${!isEnabled
            ? 'bg-slate-100 text-slate-400 cursor-not-allowed border border-slate-200 shadow-none'
            : 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-indigo-100'
            }`}
        >
          {isConfirming ? (
            <><Loader className="h-5 w-5 animate-spin" /> {R('declaration.finalizing')}</>
          ) : !isEnabled ? (
            <><Lock className="h-5 w-5 opacity-40" /> {R('declaration.completeReportFirst')}</>
          ) : (
            <><CheckCircle className="h-5 w-5" /> {R('declaration.submitConfirm')}</>
          )}
        </button>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-2 justify-center py-4 px-6 bg-green-50 border border-green-100 rounded-2xl animate-in zoom-in-95 duration-500">
            <CheckCircle className="h-5 w-5 text-green-600" />
            <span className="text-xs font-black text-green-700 uppercase tracking-widest">{R('declaration.selfDeclConfirmedTitle')}</span>
          </div>

          {!confirmed && crossValidResult === 'passed' && (
            <div className="flex items-center gap-3 p-4 bg-emerald-50 border-2 border-emerald-100 rounded-2xl animate-in slide-in-from-left-4 duration-700">
              <ShieldCheck className="h-6 w-6 text-emerald-600 flex-shrink-0" />
              <span className="text-[11px] text-emerald-800 font-bold leading-relaxed lowercase first-letter:uppercase">
                {cvMessage || R('declaration.allChecksOut')}
              </span>
            </div>
          )}

          {!confirmed && crossValidResult === 'failed' && (
            <div className="flex items-center gap-3 p-4 bg-red-50 border-2 border-red-100 rounded-2xl animate-in shake duration-500">
              <AlertCircle className="h-6 w-6 text-red-600 flex-shrink-0" />
              <span className="text-[11px] text-red-800 font-bold leading-relaxed lowercase first-letter:uppercase">
                {cvMessage || '⚠️ Cross-validation found issues. Please review details in the sidebar.'}
              </span>
            </div>
          )}

          {/* SESSION REFERENCE NUMBER CARD */}
          {referenceId && (
            <div className="mt-6 bg-indigo-50 border border-indigo-100 rounded-[28px] overflow-hidden shadow-sm animate-in fade-in zoom-in-95 duration-700 delay-300">
              <div className="p-6">
                <div className="flex items-center gap-2 mb-4">
                  <div className="p-2 bg-indigo-600 rounded-xl">
                    <ShieldCheck className="h-4 w-4 text-white" />
                  </div>
                  <h4 className="text-[10px] font-black text-indigo-900 uppercase tracking-[0.2em]">{R('declaration.sessionRef')}</h4>
                </div>

                <p className="text-[10px] font-medium text-slate-500 mb-6 leading-relaxed">
                  {R('declaration.saveRef')}
                </p>

                <div className="relative group">
                  <div className="w-full bg-white border-2 border-white rounded-2xl p-5 flex items-center justify-between shadow-sm group-hover:border-indigo-200 transition-all duration-300">
                    <span className="text-base font-black text-indigo-600 font-mono tracking-wider">{referenceId}</span>
                    <button
                      onClick={copyToClipboard}
                      className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-xl text-[10px] font-black uppercase tracking-widest hover:bg-indigo-700 transition-all active:scale-95 shadow-lg shadow-indigo-100"
                    >
                      <Copy className="h-3 w-3" />
                      {R('declaration.copy')}
                    </button>
                  </div>
                </div>

                <div className="mt-6 flex items-start gap-2 text-slate-400 border-t border-indigo-100/50 pt-4">
                  <Clock className="h-3 w-3 mt-0.5" />
                  <p className="text-[9px] font-bold uppercase tracking-widest opacity-60">{R('declaration.enterInChat')}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// COMPLIANCE HISTORY & ROLE SELECTORS (STUBS IMPLEMENTED)
// ============================================================================

export { SelfDeclarationCard };
