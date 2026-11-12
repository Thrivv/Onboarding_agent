import React from 'react';
import { CheckCircle, FileText, ShieldCheck, Upload, User, Users } from 'lucide-react';
import logger from '../../../../utils/logger';
import { useLanguage } from '../../../../context/LanguageContext';
import { translateDocName } from '../../utils/reportI18n';

const NextDocumentCard = ({ msgId, nextDoc, remainingDocs, onUploadTrigger, currentStepId, hasTriggers, membersInfo, verifiedDocType, extractedData }) => {
  const { t } = useLanguage();
  logger.log(`[NEXT-DOC-DEBUG] ID: ${msgId}, verifiedDocType: ${verifiedDocType}, hasExtracted: ${!!extractedData}`);

  // Only show if this is the MOST RECENT progression card

  if (currentStepId && msgId !== currentStepId) return null;

  const nextDocType = nextDoc?.type || (remainingDocs && remainingDocs[0]);
  const allMembersVerified = membersInfo ? (membersInfo.verified >= membersInfo.total) : true;
  const isActuallyFinished = !nextDocType && (!remainingDocs || remainingDocs.length === 0) && !hasTriggers && allMembersVerified;

  // Early exit ONLY if it's not finished and we have no data
  if (!isActuallyFinished && !nextDocType && (!remainingDocs || remainingDocs.length === 0)) return null;

  const formatName = (str) => translateDocName(t, str);

  // Try to find a person's name for identity documents
  const isIdentityDoc = (verifiedDocType || '').toLowerCase().includes('eid') || (verifiedDocType || '').toLowerCase().includes('passport') || (verifiedDocType || '').toLowerCase().includes('identity');
  const personName = isIdentityDoc && (extractedData?.['Full Name'] || extractedData?.['Name'] || extractedData?.['english']?.['Full Name'] || extractedData?.['english']?.['Name']);

  // SUCCESS STATE: ALL DOCUMENTS UPLOADED & MEMBERS VERIFIED
  if (isActuallyFinished) {
    if (!verifiedDocType && !personName) return null;
    return (
      <div className="max-w-md w-full mt-6 mb-2 animate-in fade-in slide-in-from-bottom-4 duration-700">
        <div className="bg-white border-2 border-emerald-50 rounded-[32px] overflow-hidden shadow-2xl shadow-emerald-100/40 translate-z-0">
          <div className="bg-brand-primary px-6 py-5 flex items-center justify-between border-b border-white/10">
            <div className="flex items-center gap-4">
              <div className="p-2 bg-white/10 rounded-xl backdrop-blur-xl border border-white/20 shadow-inner">
                {isIdentityDoc ? <User className="h-5 w-5 text-white" /> : <ShieldCheck className="h-5 w-5 text-white" />}
              </div>
              <div>
                <h2 className="text-[10px] font-black text-white uppercase tracking-[0.25em] opacity-70 mb-0.5">
                  {personName ? t('ui.nameVerified', { name: personName }) : verifiedDocType ? t('ui.nameVerified', { name: formatName(verifiedDocType) }) : t('ui.verifiedMovingForward')}
                </h2>
                <p className="text-white text-[16px] font-black leading-tight tracking-tight">{t('ui.progression')}</p>
              </div>
            </div>
            <div className="flex items-center gap-1.5 bg-white/10 px-3 py-1.5 rounded-full border border-white/10">
              <div className="w-2 h-2 bg-emerald-400 rounded-full shadow-md shadow-emerald-400/50" />
              <span className="text-[10px] font-black text-white uppercase tracking-[0.1em] leading-none">{t('ui.complete')}</span>
            </div>
          </div>

          <div className="p-6">
            <div className="relative flex flex-col items-center text-center p-8 bg-emerald-50/50 rounded-3xl border border-emerald-100 custom-dotted-pattern">
              <div className="h-20 w-20 bg-white rounded-full flex items-center justify-center shadow-lg border-4 border-emerald-100 text-emerald-600 mb-4">
                <CheckCircle className="h-10 w-10 animate-pulse" />
              </div>
              <h3 className="text-[18px] font-black text-slate-800 leading-tight tracking-tight mb-2">
                {personName ? t('ui.nameVerifiedBang', { name: personName }) : verifiedDocType ? t('ui.nameVerifiedBang', { name: formatName(verifiedDocType) }) : t('ui.allDocumentsVerified')}
              </h3>
              <p className="text-[12px] font-bold text-slate-500 leading-relaxed max-w-[240px]">
                {personName
                  ? t('ui.identityCapturedFor', { name: personName })
                  : verifiedDocType
                    ? t('ui.docCaptured', { doc: formatName(verifiedDocType) })
                    : t('ui.allCaptured')}
              </p>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // If triggers are active, we hide the progression card to let the compliance forms take focus
  if (hasTriggers) return null;
  if (!nextDocType) return null;

  const memberName = nextDoc?.member_name;


  return (
    <div className="max-w-md w-full mt-6 mb-2 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="bg-white border-2 border-blue-50 rounded-[32px] overflow-hidden shadow-2xl shadow-blue-100/40 translate-z-0">
        <div className="bg-brand-primary px-6 py-5 flex items-center justify-between border-b border-white/10">
          <div className="flex items-center gap-4">
            <div className="p-2 bg-white/10 rounded-xl backdrop-blur-xl border border-white/20 shadow-inner">
              <Upload className="h-5 w-5 text-white" />
            </div>
            <div>
              <h2 className="text-[10px] font-black text-white uppercase tracking-[0.25em] opacity-70 mb-0.5">{t('ui.captureRequired')}</h2>
              <p className="text-white text-[16px] font-black leading-tight tracking-tight">{t('ui.progression')}</p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 bg-white/10 px-3 py-1.5 rounded-full border border-white/10">
            <div className="w-2 h-2 bg-emerald-400 rounded-full animate-pulse shadow-md shadow-emerald-400/50" />
            {membersInfo && membersInfo.total > 1 ? (
              <span className="text-[10px] font-black text-white uppercase tracking-[0.1em] leading-none">
                {t('ui.idsCount', { count: membersInfo.verified, total: membersInfo.total })}
              </span>
            ) : (
              <span className="text-[10px] font-black text-white uppercase tracking-[0.1em] leading-none">{t('ui.inProgress')}</span>
            )}
          </div>
        </div>

        <div className="p-6 space-y-6">
          <div className="relative">
            <div className="absolute -inset-1 bg-brand-primary rounded-3xl blur opacity-10 transition duration-500"></div>
            <div className="relative flex items-center gap-5 bg-gray-50/80 p-5 rounded-3xl border border-gray-100">
              <div className="h-14 w-14 bg-white rounded-2xl flex items-center justify-center shadow-lg border border-gray-50 text-brand-primary">
                <FileText className="h-7 w-7" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">{t('ui.requiredNextDocument')}</p>
                <h3 className="text-[17px] font-black text-slate-800 leading-tight tracking-tight">
                  {formatName(nextDocType)}
                </h3>
                {memberName && (
                  <div className="mt-2 flex items-center gap-1.5 py-1 px-2.5 bg-blue-50 border border-blue-100 rounded-lg w-fit">
                    <User className="h-3 w-3 text-brand-primary" />
                    <span className="text-[11px] font-black text-brand-secondary uppercase tracking-tight">{t('ui.forMember', { name: memberName })}</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {membersInfo && membersInfo.all_members && membersInfo.all_members.length > 0 && (
            <div className="space-y-4 bg-indigo-50/50 p-5 rounded-[28px] border border-indigo-100">
              <div className="flex items-center justify-between px-1">
                <div className="flex items-center gap-2">
                  <div className="p-1 bg-indigo-600 rounded-lg">
                    <Users className="h-3 w-3 text-white" />
                  </div>
                  <h4 className="text-[10px] font-black text-indigo-900 uppercase tracking-[0.2em]">{t('ui.identityVerification')}</h4>
                </div>
                <span className="text-[10px] font-black text-indigo-400">{t('ui.verifiedCount', { count: membersInfo.verified, total: membersInfo.total })}</span>
              </div>

              <div className="space-y-2.5 relative">
                {/* Vertical Line Connector */}
                <div className="absolute left-[11px] top-4 bottom-4 w-0.5 bg-indigo-100/50" />

                {(membersInfo.all_members || []).map((member, i) => {
                  const isVerified = (membersInfo.verified_members || []).includes(member);
                  const isCurrent = membersInfo.current_member === member;

                  return (
                    <div key={i} className={`relative flex items-center gap-4 pl-0.5 group`}>
                      {/* Status Dot */}
                      <div className={`mt-0.5 z-10 flex items-center justify-center w-5 h-5 rounded-full border-2 transition-all duration-500 ${isVerified ? 'bg-emerald-500 border-emerald-500 shadow-lg shadow-emerald-200' :
                        isCurrent ? 'bg-white border-indigo-500 shadow-lg shadow-indigo-100' :
                          'bg-white border-slate-200'
                        }`}>
                        {isVerified ? (
                          <CheckCircle className="h-3 w-3 text-white" />
                        ) : isCurrent ? (
                          <div className="w-1.5 h-1.5 bg-indigo-500 rounded-full animate-pulse" />
                        ) : (
                          <div className="w-1 h-1 bg-slate-300 rounded-full" />
                        )}
                      </div>

                      {/* Member Info Card */}
                      <div className={`flex-1 flex items-center justify-between py-2.5 px-4 rounded-xl border transition-all duration-300 ${isVerified ? 'bg-emerald-50/50 border-emerald-100/50' :
                        isCurrent ? 'bg-white border-indigo-200 shadow-md ltr:translate-x-1 rtl:-translate-x-1' :
                          'bg-transparent border-transparent opacity-60'
                        }`}>
                        <span className={`text-[12px] font-black tracking-tight ${isVerified ? 'text-emerald-800' :
                          isCurrent ? 'text-slate-800' :
                            'text-slate-400'
                          }`}>
                          {member}
                        </span>
                        {isVerified ? (
                          <span className="text-[8px] font-black text-emerald-600 uppercase tracking-widest bg-white/80 px-2 py-0.5 rounded-full border border-emerald-100 italic">{t('ui.verified')}</span>
                        ) : isCurrent && (
                          <span className="text-[8px] font-black text-indigo-600 uppercase tracking-widest bg-indigo-50 px-2 py-0.5 rounded-full border border-indigo-100">{t('ui.current')}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {remainingDocs && remainingDocs.length > 0 && (
            <div className="space-y-3 bg-slate-50/50 p-4 rounded-[24px] border border-slate-100">
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.15em] pl-1">{t('ui.remainingRequirements')}</h4>
                <span className="text-[10px] font-black text-slate-400">{t('ui.totalCount', { count: remainingDocs.length })}</span>
              </div>
              <div className="flex flex-col gap-2">
                {remainingDocs.map((rd, i) => (
                  <div key={i} className={`px-4 py-2.5 rounded-xl text-[12px] font-bold border transition-all ${i === 0 ? 'bg-white text-slate-800 border-blue-200 shadow-sm' : 'bg-transparent text-slate-400 border-slate-100/50 opacity-60'}`}>
                    <div className="flex items-center gap-3">
                      <div className={`h-2 w-2 rounded-full ${i === 0 ? 'bg-blue-500 shadow-[0_0_8px_rgba(37,99,235,0.5)]' : 'bg-slate-200'}`} />
                      <span className="flex-1">{formatName(rd)}</span>
                      {i === 0 && (
                        <span className="text-[8px] font-black text-brand-primary uppercase tracking-widest bg-blue-50 px-2 py-0.5 rounded-full">{t('ui.comingUp')}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="pt-2 flex flex-col items-center">
            <p className="text-center text-[10px] font-bold text-slate-400 mt-2 uppercase tracking-[0.1em] opacity-60">
              {t('ui.idProcessingActive')}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export { NextDocumentCard };
