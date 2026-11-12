import React, { useEffect, useState } from 'react';
import { confirmSelfDeclaration, getSelfDeclarationStatus, getSelfDeclarationSummary } from '../../../../api/compliance';
import { Building, CheckCircle, ChevronDown, Clock, Copy, FileText, Globe, History, Home, Loader, Package, Phone, Plus, ShieldCheck, User } from 'lucide-react';
import toast from 'react-hot-toast';
import { InfoRow } from '../../../../components/ui/InfoRow';
import logger from '../../../../utils/logger';
import { useReportI18n } from '../../utils/reportI18n';

const FATCAReportBlock = ({ data }) => {
  const { L, R } = useReportI18n();
  if (!data) return null;
  const bool = (v) => v == null ? 'N/A' : (v === true || v === 'yes' || v === 'true') ? 'Yes' : 'No';
  return (
    <div className="space-y-6">
      {data.tampering && (
        <div className="rounded-2xl border border-indigo-200 overflow-hidden shadow-sm">
          <div className="flex items-center justify-between px-4 py-3 bg-brand-primary border-b border-indigo-100">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-indigo-600" />
              <p className="text-[10px] font-black text-indigo-800 uppercase tracking-widest">{R('headings.documentForensics')}</p>
            </div>
            <div className={`px-2.5 py-1 rounded-full text-[9px] font-black uppercase tracking-tighter ${data.tampering.status === 'AUTHENTIC' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
              }`}>
              {data.tampering.status}
            </div>
          </div>
          <div className="p-4 bg-white grid grid-cols-2 gap-x-6 gap-y-3">
            <div className="flex justify-between items-center text-[11px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">{R('headings.forensicScore')}</span>
              <span className="font-black text-slate-700">{data.tampering.score}</span>
            </div>
            <div className="flex justify-between items-center text-[11px]">
              <span className="text-slate-400 font-bold uppercase tracking-tighter">{R('headings.decision')}</span>
              <span className="font-black text-slate-700">{data.tampering.decision}</span>
            </div>
            <div className="col-span-2 text-[10px] py-1 px-3 bg-slate-50 rounded-lg text-slate-500 border border-slate-100">
              {R('idPrefix', { id: data.tampering.case_id })}
            </div>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-4">
        <InfoRow label={L('Entity Type')} value={data.entity_type} icon={Building} />
        <InfoRow label={L('Tax Residence')} value={data.country_of_tax_residence} icon={Globe} />
        <InfoRow label={L('US Incorporated')} value={bool(data.entity_incorporated_in_usa)} icon={ShieldCheck} />
        <InfoRow label={L('US Ownership')} value={bool(data.entity_has_us_ownership)} icon={User} />
        <InfoRow label={L('Passive NFFE')} value={data.passive_nffe_us_ownership} icon={ShieldCheck} />
        <InfoRow label={L('US Address/Phone')} value={bool(data.address_or_phone_in_usa)} icon={Home} />
        <InfoRow label={L('US Payment Inst')} value={bool(data.payment_instruction_to_usa)} icon={Clock} />
        <InfoRow label={L('US Income')} value={bool(data.income_from_us_sources)} icon={CheckCircle} />
        <InfoRow label={L('IRS Form Obtained')} value={bool(data.irs_form_obtained)} icon={FileText} />
        <InfoRow label={L('US Tax ID')} value={data.us_tax_id} icon={ShieldCheck} />
      </div>
    </div>
  );
};

const PEPReportBlock = ({ data }) => {
  const { L } = useReportI18n();
  if (!data) return null;

  const getStatus = (pepVal) => {
    if (pepVal === null || pepVal === undefined || pepVal === '') return null;
    const boolVal = typeof pepVal === 'object' ? pepVal.status : pepVal;
    if (boolVal === true || String(boolVal).toLowerCase() === 'true' || String(boolVal).toLowerCase() === 'yes') return 'Identified';
    if (boolVal === false || String(boolVal).toLowerCase() === 'false' || String(boolVal).toLowerCase() === 'no') return 'False';
    return String(boolVal);
  };

  const domesticStatus = getStatus(data.domestic_pep);
  const domesticName = data.domestic_pep?.name || data.domestic_pep_name;
  const domesticPosition = data.domestic_pep?.position || data.domestic_pep_position;

  const foreignStatus = getStatus(data.foreign_pep);
  const foreignCountry = data.foreign_pep?.country || data.foreign_pep_country;
  const foreignName = data.foreign_pep?.name || data.foreign_pep_name;
  const foreignPosition = data.foreign_pep?.position || data.foreign_pep_position;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <InfoRow label={L('Domestic PEP Status')} value={domesticStatus} icon={ShieldCheck} />
        {domesticStatus === 'Identified' && <InfoRow label={L('Domestic Name')} value={domesticName} icon={User} />}
        {domesticStatus === 'Identified' && <InfoRow label={L('Domestic Role')} value={domesticPosition} icon={ShieldCheck} />}

        <InfoRow label={L('Foreign PEP Status')} value={foreignStatus} icon={Globe} />
        {foreignStatus === 'Identified' && <InfoRow label={L('PEP Jurisdiction')} value={foreignCountry} icon={Globe} />}
        {foreignStatus === 'Identified' && <InfoRow label={L('Foreign Name')} value={foreignName} icon={User} />}
        {foreignStatus === 'Identified' && <InfoRow label={L('Foreign Role')} value={foreignPosition} icon={ShieldCheck} />}
      </div>
    </div>
  );
};

const ProductPackageReportBlock = ({ data }) => {
  const { R } = useReportI18n();
  if (!data) return null;
  const pkg = data.selected_package || '—';
  const products = data.availed_products || [];
  const ICONS = { Essential: '⭐', Plus: '🚀', Advanced: '💎' };
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <span className="text-lg">{ICONS[pkg] || '📦'}</span>
        <span className="text-sm font-black text-slate-800">{R('packageName', { name: pkg })}</span>
      </div>
      {products.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {products.map(p => (
            <span key={p} className="px-2 py-0.5 text-[10px] font-bold bg-blue-50 text-brand-secondary border border-blue-100 rounded-lg">
              {p}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

// ============================================================================
// MOA (MEMORANDUM OF ASSOCIATION) DISPLAY
// ============================================================================

const RegisteredIndividualsReportBlock = ({ data, roleVault }) => {
  const { R, role: roleLabel } = useReportI18n();
  if (!data || !data.all_members) return null;

  logger.log('[SIDEBAR-DEBUG-DATA] OwnershipMap:', data.ownershipMap, 'MemberRoles:', data.member_roles || data.member_role_map, 'RoleVault:', roleVault);

  return (

    <div className="space-y-3">
      {data.all_members.map((member, i) => {
        const name = typeof member === 'string' ? member : (member.display_name || member.name || 'Individual');
        const isVerified = (data.verified_members || []).some(m =>
          (typeof m === 'string' ? m : (m.display_name || m.name)) === name
        );
        const normalizedName = name.replace(/\(UBO\)/gi, '').trim().toUpperCase();

        // 🛡️ Robust ownership lookup: check normalized, trimmed, and raw variations
        const oMap = data.ownershipMap || {};
        const ownership = oMap[normalizedName] || oMap[name.trim().toUpperCase()] || oMap[name] || '—';

        const isUbo = (data.ubo_names || []).some(n => n.trim().toUpperCase() === normalizedName);

        // ✅ NEW: Look up contact details (email + phone) from kiContactMap
        const cMap = data.kiContactMap || {};
        // eslint-disable-next-line no-unused-vars
        const contactInfo = cMap[normalizedName] || cMap[name.trim().toUpperCase()] || cMap[name] || null;

        // Derive role: check vault first, then roles map, then fallback
        let role = 'Authorised Signatory';

        if (roleVault && roleVault[normalizedName]) {
          role = roleVault[normalizedName];
        } else {
          const rolesMap = data.member_roles || data.member_role_map;
          if (rolesMap) {
            // Case-insensitive lookup
            const rolesLower = {};
            Object.entries(rolesMap).forEach(([k, v]) => {
              rolesLower[k.trim().toUpperCase()] = v;
            });
            if (rolesLower[normalizedName]) {
              role = rolesLower[normalizedName];
            }
          } else if (typeof member !== 'string' && member.role) {
            role = member.role;
          }
        }

        // Format role for display (e.g., AS -> Authorised Signatory)
        const roleNorm = String(role || '').toUpperCase().replace(/_/g, ' ');
        const displayRole = (roleNorm === 'AS' || roleNorm === 'AUTHORISED SIGNATORY') ? 'Authorised Signatory' : (roleNorm === 'MEMBER' ? 'Member' : role);
        // Colour by role CODE, not by the (now translated) display text.
        const isMemberRole = roleNorm === 'MEMBER' || roleNorm.includes('MEMBER');

        logger.log(`[SIDEBAR-DEBUG] Member: ${name} | Normalized: ${normalizedName} | Role: ${role} | Display: ${displayRole} | Share: ${ownership}`);


        return (
          <div key={i} className="flex items-start gap-3 p-3 bg-white rounded-xl border border-slate-100 shadow-sm transition-all hover:border-blue-200">
            <div className={`mt-1 flex-shrink-0 h-5 w-5 rounded-full flex items-center justify-center ${isVerified ? 'bg-emerald-500 text-white shadow-sm' : 'bg-slate-100 text-slate-300'}`}>
              <CheckCircle className="h-3 w-3" />
            </div>
            <div className="flex-1 min-w-0">
              {/* Name row + badges */}
              <div className="flex items-center justify-between gap-2">
                <p className="text-[12px] font-black text-slate-800 uppercase truncate tracking-tight">{name}</p>
                <div className="flex items-center gap-1.5">
                  {isUbo && (
                    <span className="text-[7px] font-black uppercase tracking-tight bg-amber-50 text-brand-primary px-1.5 py-0.5 rounded border border-amber-100">UBO</span>
                  )}
                  {/* ✅ Share % pill — shown next to verified badge when available */}
                  {ownership !== '—' && (
                    <span className="bg-blue-50 text-brand-secondary border border-blue-100 px-1.5 py-0.5 rounded-lg text-[9px] font-black">
                      {ownership}
                    </span>
                  )}
                  <span className={`text-[8px] font-black uppercase tracking-[0.1em] px-2 py-0.5 rounded-full ${isVerified ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-50 text-slate-400'}`}>
                    {isVerified ? R('verified') : R('pending')}
                  </span>
                </div>
              </div>
              {/* Role row */}
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-1 flex items-center gap-2">
                <span className={isMemberRole ? 'text-indigo-400' : 'text-purple-400'}>
                  {roleLabel(displayRole)}
                </span>
                {ownership === '—' && (
                  <>
                    <span className="text-slate-200">|</span>
                    <span className="text-slate-300 text-[9px]">{R('shareNone')}</span>
                  </>
                )}
              </p>
            </div>
          </div>
        );
      })}
    </div>
  );
};


const SummaryDeclarationReportBlock = ({ userEmail, onConfirmed }) => {
  const { R } = useReportI18n();
  const [isChecked, setIsChecked] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [, setSummary] = useState(null);
  const [isAlreadyConfirmed, setIsAlreadyConfirmed] = useState(false);
  const [referenceId, setReferenceId] = useState(() => sessionStorage.getItem('final_ref_number') || '');
  const [justConfirmed, setJustConfirmed] = useState(false);
  const [redirectCountdown, setRedirectCountdown] = useState(null);

  useEffect(() => {
    if (!userEmail) return;

    // Fetch summary text
    getSelfDeclarationSummary(userEmail)
      .then(res => setSummary(res.data))
      .catch(e => logger.error(e));

    // Fetch actual confirmation status
    getSelfDeclarationStatus(userEmail)
      .then(res => {
        if (res.data?.confirmed) {
          setIsChecked(true);
          setIsAlreadyConfirmed(true);
          const ref = res.data.reference_number || sessionStorage.getItem('final_ref_number') || '';
          setReferenceId(ref);
          if (ref) sessionStorage.setItem('final_ref_number', ref);
          // Auto-redirect since declaration is already confirmed
          setRedirectCountdown(3);
        }
      })
      .catch(e => logger.error(e));
  }, [userEmail]);

  // Auto-redirect countdown after fresh confirmation
  useEffect(() => {
    if (redirectCountdown === null) return;
    if (redirectCountdown === 0) {
      // window.location.href = REDIRECT_URL;
      return;
    }
    const timer = setTimeout(() => setRedirectCountdown(c => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [redirectCountdown]);

  const copyToClipboard = () => {
    if (referenceId) {
      navigator.clipboard.writeText(referenceId);
      toast.success(R('declaration.refCopied'));
    }
  };

  const handleCheckboxChange = async (e) => {
    if (isAlreadyConfirmed) return;
    if (e.target.checked) {
      setIsChecked(true);
      setIsSubmitting(true);
      try {
        const res = await confirmSelfDeclaration({ email: userEmail });
        toast.success(R('declaration.submitted'));
        const ref = res.data?.reference_number || sessionStorage.getItem('final_ref_number') || '';
        setReferenceId(ref);
        if (ref) sessionStorage.setItem('final_ref_number', ref);
        setJustConfirmed(true);
        setRedirectCountdown(3);
        if (onConfirmed) onConfirmed(res.data);
        // Direct redirect after 3 seconds — fires regardless of React state
        setTimeout(() => {
          // window.location.href = REDIRECT_URL;
        }, 3000);
      } catch (err) {
        logger.error(err);
        toast.error(R('declaration.submitFailed'));
        setIsChecked(false);
      } finally {
        setIsSubmitting(false);
      }
    } else {
      setIsChecked(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="p-8 bg-amber-50/50 border border-amber-100 rounded-[40px] relative overflow-hidden group">
        <div className="absolute top-0 right-0 p-4 opacity-5 group-hover:opacity-10 transition-opacity">
          <ShieldCheck className="h-20 w-20 text-amber-600" />
        </div>
        <p className="text-[13px] text-slate-700 italic leading-relaxed font-semibold relative z-10">
          {R('declaration.text')}
        </p>
      </div>

      <div className={`flex items-center gap-5 p-8 rounded-[40px] border-2 transition-all duration-500 ${isChecked ? 'bg-emerald-50 border-emerald-500 shadow-xl shadow-emerald-100' : 'bg-slate-50 border-slate-100 hover:bg-white hover:border-slate-200'} ${isAlreadyConfirmed ? 'opacity-80' : ''}`}>
        <div className="relative flex items-center justify-center flex-shrink-0">
          <input
            type="checkbox"
            id="declaration-check"
            checked={isChecked}
            onChange={handleCheckboxChange}
            disabled={isSubmitting || isAlreadyConfirmed}
            className={`w-10 h-10 rounded-2xl border-2 transition-all appearance-none bg-white relative flex items-center justify-center after:content-['\\2713'] after:text-white after:text-xl after:hidden checked:after:block ${isAlreadyConfirmed ? 'cursor-default border-emerald-500 bg-emerald-600' : 'cursor-pointer border-slate-300 text-emerald-600 focus:ring-emerald-500 checked:bg-emerald-600 checked:border-emerald-600'}`}
          />
          {isSubmitting && (
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <Loader className="h-5 w-5 animate-spin text-white" />
            </div>
          )}
        </div>
        <label htmlFor="declaration-check" className={`text-[15px] font-black uppercase tracking-tight select-none ${isAlreadyConfirmed ? 'text-emerald-700 cursor-default' : 'text-slate-800 cursor-pointer'}`}>
          {isAlreadyConfirmed ? R('declaration.confirmed') : isSubmitting ? R('declaration.submitting') : R('declaration.agree')}
        </label>
      </div>

      {(isAlreadyConfirmed || justConfirmed) && referenceId && (
        <div className="mt-8 p-6 bg-slate-50 border border-slate-100 rounded-3xl shadow-sm animate-in zoom-in-95 duration-500 text-left">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-black text-slate-400 uppercase tracking-widest">{R('declaration.referenceNumber')}</p>
            <button
              onClick={copyToClipboard}
              className="p-1 hover:bg-slate-200 rounded-lg transition-colors text-slate-400 hover:text-slate-600"
              title={R('declaration.copyReference')}
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
          </div>
          <p className="text-2xl font-black text-slate-900 tracking-tight font-mono break-all">{referenceId}</p>
          <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mt-2 italic">
            {R('declaration.referenceNote')}
          </p>
          {justConfirmed && redirectCountdown !== null && (
            <div className="mt-4 pt-4 border-t border-slate-200 flex items-center justify-between">
              <p className="text-[11px] text-slate-400">
                {R('declaration.redirectingIn')} <span className="font-black text-slate-600">{redirectCountdown}s</span>…
              </p>
              <button
                onClick={() => setRedirectCountdown(null)}
                className="text-[11px] text-slate-400 underline hover:text-slate-600 transition-colors"
              >
                {R('declaration.cancel')}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
};


// ============================================================================
// PRODUCT PACKAGE CARD  (AI-enhanced)
// On mount: fetches AI recommendation from /product-package/recommend
// Displays loading → AI recommendation banner → package grid (pre-selected)
// ============================================================================

const ComplianceHistoryToggle = ({ history, userEmail }) => {
  const { R } = useReportI18n();
  const [open, setOpen] = useState(false);
  return (
    <div className="bg-white border border-slate-100 rounded-2xl overflow-hidden shadow-sm transition-all hover:border-indigo-100">
      <button
        onClick={() => setOpen(!open)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-slate-50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 bg-blue-50 rounded-lg">
            <History className="h-4 w-4 text-brand-primary" />
          </div>
          <span className="text-[11px] font-black text-slate-700 uppercase tracking-widest">{R('declaration.historyLogs')}</span>
        </div>
        <ChevronDown className={`h-4 w-4 text-slate-400 transition-transform duration-300 ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="p-4 bg-slate-50/50 border-t border-slate-50 space-y-3 animate-in slide-in-from-top-2 duration-300">
          {(!history || history.length === 0) ? (
            <div className="py-8 text-center">
              <History className="h-8 w-8 text-slate-200 mx-auto mb-2 opacity-40" />
              <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest">{R('declaration.noLogs')}</p>
            </div>
          ) : (
            <div className="space-y-2">
              {history.map((h, i) => (
                <div key={i} className="bg-white p-3 rounded-xl border border-slate-100 shadow-sm flex items-start gap-3">
                  <div className="mt-1 h-1.5 w-1.5 rounded-full bg-blue-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-black text-slate-800 uppercase leading-none mb-1">{h.action || R('declaration.configUpdated')}</p>
                    <div className="flex items-center gap-2">
                      <Clock className="h-3 w-3 text-slate-300" />
                      <p className="text-[9px] font-bold text-slate-400">{h.timestamp || new Date().toLocaleString()}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export { FATCAReportBlock, PEPReportBlock, ProductPackageReportBlock, RegisteredIndividualsReportBlock, SummaryDeclarationReportBlock, ComplianceHistoryToggle };
