// frontend/src/components/layout/Sidebar.jsx

import React, { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import logoWhite from '../../assets/logo-growx.svg';
import {
  LayoutDashboard,
  MessageSquare,
  LogOut,
  ChevronRight,
  ChevronDown,
  Building,
  Home,
  User,
  CheckCircle,
  FileText,
  ShieldCheck,
} from 'lucide-react';
import { getConversationLogs } from '../../api/onboarding';
import { getFatcaStatus, getPepStatus, getSelfDeclarationStatus } from '../../api/compliance';
import { getPackageStatus } from '../../api/products';
import { getDocumentRequirements, getDocumentStatus } from '../../api/documents';
import { logout } from '../../api/auth';
import { useAuth } from '../../context/AuthContext';
import { useLanguage } from '../../context/LanguageContext';
import { translateDocName } from '../../features/onboarding/utils/reportI18n';
import logger from '../../utils/logger';
import { canonicalKeywords } from '../../features/onboarding/utils/i18nText';

const SIDEBAR_SHORT_KEYS = {
  fatca_declaration: 'report.docs.fatcaShort',
  pep_declaration: 'report.docs.pepShort',
  product_package: 'report.docs.productPackage',
  summary_declaration: 'report.docs.final',
};



const navigationItems = [
  { name: 'AI Assistant', path: '/ai-assistant', icon: MessageSquare },
];

const profileDropdownItems = [
  {
    name: 'Admin Dashboard',
    path: '/dashboard',
    icon: LayoutDashboard,
  },
];

const Sidebar = ({ onSectionClick, activeSection }) => {
  const location = useLocation();
  const { user, logout } = useAuth();
  const { t } = useLanguage();
  const [showUserDetails, setShowUserDetails] = useState(false);
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
  const [expandedCategory, setExpandedCategory] = useState(activeSection || 'corporate'); // Default expanded category
  const [docItems, setDocItems] = useState([]);
  const [docStatus, setDocStatus] = useState({});
  const [globalProgress, setGlobalProgress] = useState({
    totalMembers: 1,
    verifiedMembers: 0,
    allMembers: [],
    verifiedMembersList: [],
    pendingMembersList: []
  });
  const [loadingDocs, setLoadingDocs] = useState(true);
  const [ownershipType, setOwnershipType] = useState('');

  const [, setSelectedGroup] = useState('corporate');
  const [isPostIdentity, setIsPostIdentity] = useState(false);

  // Sync expandedCategory with activeSection prop
  React.useEffect(() => {
    if (activeSection) {
      setExpandedCategory(activeSection);
    }
  }, [activeSection]);

  // Fetch document status and requirements
  React.useEffect(() => {
    const fetchData = async () => {
      if (!user?.email) return;

      try {

        // Fetch requirements and logs in parallel
        const [reqRes, logsRes] = await Promise.all([
          getDocumentRequirements({ email: user.email }),
          getConversationLogs(user.email, { limit: 100 })
        ]);

        // 1. Determine Required Documents
        const fetchedOwnershipType = reqRes.data?.ownership_type || '';
        setOwnershipType(fetchedOwnershipType);
        let required = reqRes.data?.required_documents || [];
        const logs = (logsRes.data?.logs || []).map(log => ({
          ...log,
          role: (log.role === 'agent' || log.role === 'bot') ? 'assistant' : log.role,
          content: log.message || log.content || '',
          // English rendering when known + EN aliases for AR/ES keywords, so
          // the phrase checks below work in every language (utils/i18nText.js).
          logicContent: canonicalKeywords(
            ((typeof log.metadata === 'string' ? (() => { try { return JSON.parse(log.metadata); } catch (e) { return {}; } })() : log.metadata) || {}).i18n?.english
            || log.message || log.content || ''
          ),
        }));

        // PRIORITY: Trust the chat instructions
        const welcomeMsgs = logs.filter(l =>
          l.role === 'assistant' &&
          (l.content?.includes('Prepare these') || l.logicContent?.includes('required documents') || (l.metadata && (typeof l.metadata === 'string' ? JSON.parse(l.metadata).is_welcome : l.metadata.is_welcome)))
        );

        if (welcomeMsgs.length > 0) {
          let longestChatList = [];
          welcomeMsgs.forEach(msg => {
            const lines = msg.content.split('\n');
            const chatDocs = [];
            lines.forEach(line => {
              const trimmed = line.trim();
              const isBullet = /^[•\-*]/.test(trimmed) || /^\d+[.)]/.test(trimmed) || /^\(\d+\)/.test(trimmed);
              if (isBullet) chatDocs.push(trimmed.replace(/^[•\-*]|\d+[.)]|\(\d+\)/, '').trim());
            });
            if (chatDocs.length > longestChatList.length) longestChatList = chatDocs;
          });
          if (longestChatList.length >= required.length && longestChatList.length > 0) required = longestChatList;
        }

        if (required.length === 0) {
          try {
            const statusRes = await getDocumentStatus(user.email);
            if (statusRes.data?.remaining_documents?.length > 0 || statusRes.data?.approved_documents?.length > 0) {
              required = [...(statusRes.data.approved_documents || []), ...(statusRes.data.remaining_documents || [])];
            }
          } catch (e) { }
        }
        // Also dynamically add COI if asked in chat or submitted
        logs.forEach(m => {
          if (m.role === 'assistant' && m.content) {
            const txt = m.content.toLowerCase();
            if (txt.includes('coi') || txt.includes('certificate of incorporation')) {
              if (!required.includes('coi')) required.push('coi');
            }
          }
          let meta = {};
          try { meta = typeof m.metadata === 'string' ? JSON.parse(m.metadata) : (m.metadata || {}); } catch (e) { }
          const dt = (meta.document_type || m.document_type || '').toLowerCase();
          if (dt.includes('coi') || dt.includes('incorporation')) {
            if (!required.includes('coi')) required.push('coi');
          }
        });

        if (required.length === 0) required = ['commercial_license', 'identity', 'ejari'];

        // Deduplicate required documents using normalization
        const normalizedRequired = [];
        const seen = new Set();
        required.forEach(id => {
          const type = (typeof id === 'string' ? id : (id.document_type || 'document')).toLowerCase();
          let norm = type;
          if (type.includes('commercial') || type.includes('license')) norm = 'commercial_license';
          else if (type.includes('moa') || type.includes('memorandum')) norm = 'moa';
          else if (type.includes('eid') || type.includes('passport') || type.includes('identity')) norm = 'identity';
          else if (type.includes('ejari') || type.includes('tenancy')) norm = 'ejari';
          else if (type.includes('coi') || type.includes('incorporation')) norm = 'coi';

          if (!seen.has(norm)) {
            seen.add(norm);
            normalizedRequired.push(id);
          }
        });
        required = normalizedRequired;

        const items = required.map(id => {
          const rawId = typeof id === 'string' ? id : (id.document_type || 'document');
          const type = rawId.toLowerCase();
          let label = rawId.replace(/_/g, ' ');
          if (label.length < 5) label = label.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
          let icon = Building;
          if (type.includes('commercial') || type.includes('license')) { label = 'Commercial License'; icon = Building; }
          else if (type.includes('moa') || type.includes('memorandum')) { label = 'Memorandum of Association'; icon = FileText; }
          else if (type.includes('eid') || type.includes('passport') || type.includes('identity')) { label = 'Emirates ID or Passport'; icon = User; }
          else if (type.includes('ejari') || type.includes('tenancy')) { label = 'Ejari (Address Proof)'; icon = Home; }
          else if (type.includes('coi') || type.includes('incorporation')) { label = 'Certificate of Inc.'; icon = ShieldCheck; }
          else { icon = FileText; }
          return { key: rawId, label, icon };
        });
        setDocItems(items);

        let statusData = {};
        let approvedDocs = [];
        let submittedDocsRaw = reqRes.data?.submitted_documents || [];

        try {
          const statusRes = await getDocumentStatus(user.email);
          statusData = statusRes.data || {};
          approvedDocs = statusData.approved_documents || [];
        } catch (e) {
          logger.warn('[Sidebar] Failed to fetch status pass 1', e);
        }

        // 3. Determine Status from Logs & Backend Sync
        const statusMap = {};

        const checkMatch = (backendType, item) => {
          if (!backendType || !item) return false;
          const bt = backendType.toLowerCase();
          const ik = (item.key || '').toLowerCase();
          const il = (item.label || '').toLowerCase();

          return bt === ik ||
            (bt && ik.includes(bt)) ||
            (ik && bt.includes(ik)) ||
            (bt.includes('commercial') && il.includes('commercial')) ||
            (bt.includes('moa') && (il.includes('memorandum') || il.includes('moa'))) ||
            (bt.includes('ejari') && (il.includes('ejari') || il.includes('address'))) ||
            (bt.includes('tenancy') && il.includes('ejari')) ||
            ((bt.includes('coi') || bt.includes('incorporation')) && (il.includes('certificate') || ik.includes('coi'))) ||
            ((bt.includes('eid') || bt.includes('passport') || bt.includes('identity')) &&
              (il.includes('emirates id') || il.includes('passport') || il.includes('identity')));
        };

        const rd = reqRes.data;
        let apiMembersList = statusData.members_info?.all_members || rd.moa_members || rd.members || rd.members_list || rd.shareholders || rd.ubo_names || [];

        // FALLBACK: If apiMembersList is empty, scan logs for the member list
        if (apiMembersList.length === 0) {
          for (const l of logs) {
            let meta = {};
            try { meta = typeof l.metadata === 'string' ? JSON.parse(l.metadata) : (l.metadata || {}); } catch (e) { }

            // Check standard list fields
            const members = l.moaMembers || l.membersList || meta.moa_members || meta.members || meta.membersList || meta.extracted_members || meta.shareholders || meta.ubo_names || [];
            if (Array.isArray(members) && members.length > 0) {
              apiMembersList = members;
              break;
            }

            // Check single owner field
            const extracted = meta.extracted_fields || l.extractedData;
            if (extracted?.owner?.name_english) {
              apiMembersList = [extracted.owner.name_english];
              break;
            }
          }
        }

        const postIdentity = logs.some(l => {
          let m = {};
          try { m = typeof l.metadata === 'string' ? JSON.parse(l.metadata) : (l.metadata || {}); } catch (e) { }
          return m.fatca_trigger || m.pep_trigger || m.self_declaration_trigger || l.fatcaTrigger || l.pepTrigger || l.selfDeclTrigger;
        });
        setIsPostIdentity(postIdentity);

        let initialMemberCount = 1;
        if (Array.isArray(apiMembersList) && apiMembersList.length > 0) {
          initialMemberCount = apiMembersList.length;
        } else {
          for (const l of logs) {
            let meta = {};
            try { meta = typeof l.metadata === 'string' ? JSON.parse(l.metadata) : (l.metadata || {}); } catch (e) { }

            // Check standard list fields
            const members = l.moaMembers || l.membersList || meta.moa_members || meta.members || meta.membersList || meta.extracted_members || meta.shareholders || meta.ubo_names || [];
            if (Array.isArray(members) && members.length > 0) {
              initialMemberCount = members.length;
              break;
            }

            // Check single owner field
            const extracted = meta.extracted_fields || l.extractedData;
            if (extracted?.owner?.name_english) {
              initialMemberCount = 1;
              apiMembersList = [extracted.owner.name_english];
              break;
            }
          }
        }

        // 1. Determine base counts from logs/requirements
        const idDocs = approvedDocs.filter(a => {
          const type = (typeof a === 'string' ? a : (a.document_type || '')).toLowerCase();
          return type.includes('eid') || type.includes('passport') || type.includes('identity');
        });

        const uniqueNames = new Set();
        idDocs.forEach(d => {
          if (typeof d !== 'string') {
            const name = d.extracted_data?.['Full Name'] || d.extracted_data?.['Name'] || d.extracted_data?.['customer_name'] || d.filename;
            if (name) uniqueNames.add(name);
            else uniqueNames.add(Math.random());
          } else {
            uniqueNames.add(d);
          }
        });

        // 2. GROUND TRUTH OVERRIDE: Prioritize statusData (The User's Ground Truth)
        let initialVerifiedCount = uniqueNames.size || idDocs.length;

        if (statusData.members_info) {
          initialMemberCount = statusData.members_info.total || initialMemberCount;
          initialVerifiedCount = statusData.members_info.verified || initialVerifiedCount;
        } else if (statusData.member_eid_status) {
          initialMemberCount = statusData.member_eid_status.total_members || initialMemberCount;
          initialVerifiedCount = statusData.member_eid_status.submitted_eids || initialVerifiedCount;
        }

        if (initialVerifiedCount > initialMemberCount) initialMemberCount = initialVerifiedCount;

        // Initialize statusMap from backend ground truth
        items.forEach(item => {
          const isIdentity = (item.key || '').toLowerCase().includes('eid') || (item.key || '').toLowerCase().includes('passport');

          const isActuallyApproved = approvedDocs.some(a => {
            const at = (typeof a === 'string' ? a : (a.document_type || '')).toLowerCase();
            const ik = item.key.toLowerCase();
            return at === ik || at.includes(ik) || ik.includes(at);
          });

          const isSubmittedAndValid = submittedDocsRaw.some(d =>
            checkMatch(d.document_type, item) && d.is_valid !== false
          );

          if (isActuallyApproved || isSubmittedAndValid) {
            // For identity, only success if all members are done OR it's already compliance phase
            if (isIdentity && initialMemberCount > 1 && initialVerifiedCount < initialMemberCount && !postIdentity) {
              statusMap[item.key] = 'in_progress';
            } else {
              statusMap[item.key] = 'success';
            }
          } else {
            statusMap[item.key] = 'pending';
          }
        });

        const chronLogs = [...logs].reverse();
        chronLogs.forEach(log => {
          let metadata = {};
          try { metadata = typeof log.metadata === 'string' ? JSON.parse(log.metadata) : (log.metadata || {}); } catch (e) { }
          const content = log.logicContent || (log.content || '').toLowerCase();
          const logType = (metadata.document_type || log.document_type || '').toLowerCase();

          const isAccepted = metadata.decision === 'ACCEPT' ||
            log.tampering_status === 'ACCEPT' ||
            metadata.is_complete === true ||
            metadata.is_valid === true ||
            content.includes('successfully validated and accepted') ||
            content.includes('document has been accepted') ||
            metadata.message_type === 'ki_loop_finalized';

          const isProcessing = metadata.message_type === 'extraction_result' || log.role === 'user' || content.includes('authenticating document');

          if (isAccepted || isProcessing) {
            items.forEach(item => {
              if (checkMatch(logType, item)) {
                const isIdentity = (item.key || '').toLowerCase().includes('eid') || (item.key || '').toLowerCase().includes('passport');
                if (isAccepted || (isIdentity && postIdentity)) {
                  if (isIdentity && initialMemberCount > 1 && initialVerifiedCount < initialMemberCount && !postIdentity) {
                    statusMap[item.key] = 'in_progress';
                  } else {
                    statusMap[item.key] = 'success';
                  }
                } else if (statusMap[item.key] !== 'success') {
                  statusMap[item.key] = 'in_progress';
                }
              }
            });
          }
        });

        setDocItems(items);
        setDocStatus(statusMap);
        setGlobalProgress(prev => {
          const newTotal = initialMemberCount;
          const newVerified = (postIdentity && initialMemberCount > 0) ? initialMemberCount : initialVerifiedCount;
          const newAll = apiMembersList.length > 0 ? apiMembersList : prev.allMembers;

          // CRITICAL: Preserve the verified list names if the backend stops sending them
          let newVerifiedList = statusData.members_info?.verified_members || [];
          if (newVerifiedList.length === 0 && prev.verifiedMembersList.length > 0) {
            newVerifiedList = prev.verifiedMembersList;
          }
          // If we are in post-identity, we should treat all known members as verified if the list is empty
          if (postIdentity && newVerifiedList.length === 0) {
            newVerifiedList = newAll;
          }

          return {
            totalMembers: newTotal,
            verifiedMembers: newVerified,
            allMembers: newAll,
            verifiedMembersList: newVerifiedList,
            pendingMembersList: postIdentity ? [] : (statusData.members_info?.pending_members || (statusData.members_info ? [] : prev.pendingMembersList) || [])
          };
        });

        // 4. Also fetch FATCA / PEP / Self-Decl status / Product Package
        try {
          const [fatcaRes, pepRes, sdRes, ppRes] = await Promise.all([
            getFatcaStatus(user.email).catch(() => ({ data: {} })),
            getPepStatus(user.email).catch(() => ({ data: {} })),
            getSelfDeclarationStatus(user.email).catch(() => ({ data: {} })),
            getPackageStatus(user.email).catch(() => ({ data: {} }))
          ]);
          // FATCA/PEP are now required for every Corporate account, Single
          // Owner included, so show the real pending/success status for both.
          setDocStatus(prev => ({
            ...prev,
            product_package: ppRes.data?.status === 'completed' ? 'success' : 'pending',
            fatca_declaration: fatcaRes.data?.status === 'completed' ? 'success' : 'pending',
            pep_declaration: pepRes.data?.status === 'completed' ? 'success' : 'pending',
            summary_declaration: (sdRes.data?.status === 'completed' || sdRes.data?.confirmed === true) ? 'success' : 'pending',
          }));
        } catch (e) { }
      } catch (err) {
        logger.error('[Sidebar] Component error:', err);
      } finally { setLoadingDocs(false); }
    };
    fetchData();
    const interval = setInterval(fetchData, 60000);
    window.addEventListener('compliance-updated', fetchData);
    return () => {
      clearInterval(interval);
      window.removeEventListener('compliance-updated', fetchData);
    };
  }, [user]);

  // Auto-scroll logic
  React.useEffect(() => {
    if (!loadingDocs && docItems.length > 0) {
      const allKeys = [...docItems.map(i => i.key), 'product_package', 'fatca_declaration', 'pep_declaration', 'summary_declaration'];
      const activeKey = allKeys.find(k => docStatus[k] === 'in_progress' || docStatus[k] === 'pending');
      if (activeKey) {
        const categorizer = (key) => {
          if (key.includes('commercial') || key.includes('license') || key.includes('ejari') || key.includes('moa') || key.includes('coi') || key.includes('tenancy')) return 'corporate';
          if (key.includes('eid') || key.includes('passport') || key.includes('identity')) return 'user';
          if (key.includes('fatca') || key.includes('pep') || key.includes('product_package')) return 'additional';
          if (key.includes('summary') || key.includes('declaration')) return 'declaration';
          return 'corporate';
        };
        setSelectedGroup(categorizer(activeKey));
      }
    }
  }, [docStatus, loadingDocs, docItems]);

  const handleLogout = () => { logout(); };

  const getDisplayName = (u) => {
    if (!u) return 'User';
    if (u.name && u.name !== 'undefined' && u.name.trim()) return u.name.trim();
    return (u.email || 'User').split('@')[0];
  };

  const getUserInitials = (u) => {
    const name = getDisplayName(u);
    if (!name || name === 'User') return '?';
    const parts = name.split(' ').filter(Boolean);
    if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
    return name[0].toUpperCase();
  };

  return (
    <div className="h-screen w-64 bg-[#3E5C9A] text-white flex flex-col fixed left-0 rtl:left-auto rtl:right-0 top-0 border-r rtl:border-r-0 rtl:border-l border-[#304B82] z-50 font-sans">
      <style>{`
        .custom-sidebar-scroll {
          scrollbar-width: none; /* Firefox */
          -ms-overflow-style: none; /* IE/Edge */
        }
        .custom-sidebar-scroll::-webkit-scrollbar {
          display: none; /* Chrome, Safari, Edge */
        }
        @media (min-width: 1024px) {
          .right-sidebar-open .logout-modal-wrapper {
            padding-right: clamp(300px, 50%, 50vw);
          }
        }
      `}</style>


      {/* Header Logo */}
      <div className="px-4 py-3 flex justify-start items-center h-[92px] bg-white mb-2">
        <img src={logoWhite} alt="Logo" className="h-14 w-auto max-w-full object-contain" />
      </div>

      {/* Main Content Area - Scrollable */}
      <div className="flex-1 overflow-y-auto custom-sidebar-scroll px-4 space-y-4 pb-4">
        {/* Navigation Section - Tighter spacing */}
        <nav className="space-y-0.5">
          <p className="text-[9px] font-black text-white/40 uppercase tracking-[0.2em] mb-1.5 px-1">{t('nav.mainMenu')}</p>
          {navigationItems.map((item) => {
            const isActive = location.pathname === item.path;
            const Icon = item.icon;
            return (
              <Link key={item.path} to={item.path} className={`flex items-center justify-between px-3 py-2.5 rounded-xl transition-all ${isActive ? 'text-brand-primary text-white shadow-lg' : 'hover:bg-white/5 text-blue-100 opacity-80 hover:opacity-100'}`}>
                <div className="flex items-center gap-3">
                  <Icon className={`h-4 w-4 ${isActive ? 'text-white' : 'text-blue-300'}`} />
                  <span className="text-[11.5px] font-black tracking-tight">{item.path === '/ai-assistant' ? t('nav.aiAssistant') : item.name}</span>
                </div>
                {isActive && <ChevronRight className="h-3 w-3 opacity-70" />}
              </Link>
            );
          })}
        </nav>

        {/* Refined Expandable Verification Hub */}
        <div className="px-1 mt-6">
          <div className="bg-[#2D4A85] rounded-3xl p-4 border border-white/5 shadow-inner">
            <div className="flex items-center justify-between mb-4 px-1">
              <h3 className="text-[10px] font-black text-white/50 uppercase tracking-[0.2em]">{t('sidebar.verificationHub')}</h3>
            </div>

            <div className="relative space-y-3">
              {/* Persistent Vertical Stepper Line for Categories */}
              <div className="absolute left-[20px] top-6 bottom-6 w-0.5 bg-white/5" />

              {(() => {
                const categorizer = (doc) => {
                  const type = (doc.key || '').toLowerCase();
                  if (type.includes('commercial') || type.includes('license') || type.includes('ejari') || type.includes('moa') || type.includes('coi') || type.includes('tenancy')) return 'corporate';
                  if (type.includes('eid') || type.includes('passport') || type.includes('identity')) return 'user';
                  if (type.includes('fatca') || type.includes('pep') || type.includes('product_package')) return 'additional';
                  if (type.includes('summary') || type.includes('declaration')) return 'declaration';
                  return 'corporate';
                };

                const allItems = [...docItems,
                // FATCA and PEP are always shown in the ADDITIONAL category
                ...(!docItems.some(d => d.key === 'fatca_declaration') ? [{ key: 'fatca_declaration', label: 'FATCA' }] : []),
                ...(!docItems.some(d => d.key === 'pep_declaration') ? [{ key: 'pep_declaration', label: 'PEP' }] : []),
                ...(!docItems.some(d => d.key === 'product_package') ? [{ key: 'product_package', label: 'Product Package' }] : []),
                ...(!docItems.some(d => d.key === 'summary_declaration') ? [{ key: 'summary_declaration', label: 'Final' }] : [])
                ];

                const categories = [
                  { id: 'corporate', label: t('sidebar.corporate').toUpperCase(), icon: Building, items: allItems.filter(i => categorizer(i) === 'corporate') },
                  { id: 'user', label: t('sidebar.identity').toUpperCase(), icon: User, items: allItems.filter(i => categorizer(i) === 'user') },
                  { id: 'additional', label: t('sidebar.additional').toUpperCase(), icon: ShieldCheck, items: allItems.filter(i => categorizer(i) === 'additional') },
                  { id: 'declaration', label: t('sidebar.declaration').toUpperCase(), icon: CheckCircle, items: allItems.filter(i => categorizer(i) === 'declaration') }
                ];

                return categories.map((cat, idx) => {
                  const isExpanded = expandedCategory === cat.id;
                  const isUser = cat.id === 'user';
                  const doneCount = isUser ? globalProgress.verifiedMembers : cat.items.filter(i => docStatus[i.key] === 'success' || docStatus[i.key] === 'skipped').length;
                  const total = isUser ? globalProgress.totalMembers : cat.items.length;
                  const isFullyDone = isUser
                    ? (globalProgress.verifiedMembers >= globalProgress.totalMembers || isPostIdentity)
                    : total > 0 && doneCount === total;

                  const Icon = cat.icon;

                  return (
                    <div key={cat.id} className="overflow-hidden">
                      <button
                        onClick={() => {
                          const next = isExpanded ? null : cat.id;
                          setExpandedCategory(next);
                          if (onSectionClick) onSectionClick(next);
                        }}
                        className={`w-full flex items-center justify-between p-3 rounded-2xl transition-all ${isExpanded ? 'bg-white/10 ring-1 ring-white/10' : 'hover:bg-white/5 opacity-80 hover:opacity-100'
                          }`}
                      >
                        <div className="flex items-center gap-3">
                          <div className={`h-8 w-8 rounded-xl flex items-center justify-center transition-all ${isFullyDone ? 'bg-emerald-500 text-white' : isExpanded ? 'text-brand-primary text-white' : 'bg-brand-secondary-dark/40 text-blue-300'
                            }`}>
                            <Icon className="h-4 w-4" />
                          </div>
                          <div className="text-left">
                            <p className={`text-[10px] font-black tracking-widest ${isFullyDone ? 'text-white' : 'text-blue-100'}`}>{cat.label}</p>
                            <p className="text-[8px] font-bold text-blue-400/60 uppercase">{t('ui.verifiedCount', { count: doneCount, total })}</p>
                          </div>
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="mt-2 ml-4 pl-4 border-white/5 space-y-3 animate-in slide-in-from-top-2 duration-300 pb-2">
                          {cat.id === 'user' ? (
                            // ✅ Special handling for IDENTITY: List actual members or placeholders
                            (() => {
                              const members = globalProgress?.allMembers || [];
                              const totalNeeded = globalProgress?.totalMembers || 1;
                              const verifiedList = globalProgress?.verifiedMembersList || [];

                              // If we have names, use them. If not, show "Member 1", "Member 2", etc.
                              const displayList = (members.length > 0)
                                ? members
                                : Array.from({ length: totalNeeded }, (_, i) => `Member ${i + 1}`);

                              return displayList.map((member, mIdx) => {
                                // Check verification status. If no names, use verifiedMembers count.
                                const isVerified = isPostIdentity ||
                                  (globalProgress.verifiedMembers >= globalProgress.totalMembers && globalProgress.totalMembers > 0) ||
                                  (members.length > 0
                                    ? (verifiedList.some(v => String(v).toLowerCase().trim() === String(member).toLowerCase().trim()) || (mIdx < globalProgress?.verifiedMembers))
                                    : (mIdx < globalProgress?.verifiedMembers));

                                const isCurrent = members.length > 0
                                  ? (verifiedList.length === mIdx)
                                  : (mIdx === globalProgress?.verifiedMembers);


                                return (
                                  <div key={`member-${mIdx}`} className="flex items-center justify-between group">
                                    <div className="flex items-center gap-2.5">
                                      <div className={`h-1.5 w-1.5 rounded-full ${isVerified ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.4)]' : isCurrent ? 'text-brand-primary animate-pulse shadow-[0_0_8px_rgba(238,167,59,0.4)]' : 'bg-brand-primary'}`} />
                                      <span className={`text-[10px] font-black tracking-tight ${isVerified ? 'text-white' : 'text-blue-300/80 group-hover:text-white transition-colors'}`}>
                                        {member}
                                      </span>
                                    </div>
                                    {isVerified && <CheckCircle className="h-3 w-3 text-emerald-400 ml-auto opacity-60" />}
                                  </div>
                                );
                              });
                            })()
                          ) : (
                            // Default handling for other categories
                            (cat.items || []).map((item, iidx) => {
                              const status = docStatus[item.key] || 'pending';
                              const isDone = status === 'success';
                              const isSkipped = status === 'skipped';
                              const isInProgress = status === 'in_progress';
                              return (
                                <div key={iidx} className="flex items-center justify-between group">
                                  <div className="flex items-center gap-2.5">
                                    <div className={`h-1.5 w-1.5 rounded-full ${isDone ? 'bg-emerald-400' : isSkipped ? 'bg-blue-300/40' : isInProgress ? 'text-brand-primary animate-pulse' : 'bg-brand-primary'}`} />
                                    <span className={`text-[10px] font-black tracking-tight ${isDone ? 'text-white' : isSkipped ? 'text-blue-300/60' : 'text-blue-300/80 group-hover:text-white transition-colors'}`}>
                                      {SIDEBAR_SHORT_KEYS[item.key] ? t(SIDEBAR_SHORT_KEYS[item.key]) : translateDocName(t, item.label)}{isSkipped ? ` · ${t('ui.skipped')}` : ''}
                                    </span>
                                  </div>
                                  {isDone && <CheckCircle className="h-3 w-3 text-emerald-400 ml-auto opacity-60" />}
                                </div>
                              );
                            })
                          )}
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        </div>
      </div>

      {/* User Area - Bottom Fixed */}
      <div className="px-4 py-1 border-t border-brand-secondary-dark/50 bg-brand-secondary-dark/10">

        {/* Profile Dropdown Panel — expands above the user button */}
        {showUserDetails && (
          <div className="mb-2 bg-brand-secondary-dark/50 rounded-xl border border-brand-primary/40 overflow-hidden animate-in fade-in slide-in-from-bottom-2 duration-200">
            <p className="text-[8px] font-black text-blue-300 uppercase tracking-[0.2em] px-3 pt-2.5 pb-1 opacity-60">{t('ui.navigation')}</p>
            {profileDropdownItems.map((item) => {
              const Icon = item.icon;
              const isActive = location.pathname === item.path;
              return (
                <Link
                  key={item.path}
                  to={item.path}
                  onClick={() => setShowUserDetails(false)}
                  className={`flex items-center gap-3 px-3 py-2.5 transition-all outline-none focus:outline-none ${isActive
                    ? 'text-brand-primary/20 text-brand-primary'
                    : 'hover:bg-white/5 hover:shadow-lg hover:shadow-brand-primary/30 text-blue-100'
                    }`}
                >
                  <Icon className={`h-3.5 w-3.5 flex-shrink-0 ${isActive ? 'text-brand-primary' : 'text-blue-300'}`} />
                  <span className="text-[11px] font-black tracking-tight">{item.path === '/dashboard' ? t('nav.adminDashboard') : item.name}</span>
                  {isActive && <ChevronRight className="h-3 w-3 ml-auto opacity-60" />}
                </Link>
              );
            })}
          </div>
        )}

        {/* User Profile + Logout Rows */}
        <div className="flex flex-col gap-2 mt-auto pb-4">
          <button
            onClick={() => setShowUserDetails(!showUserDetails)}
            className="w-full bg-brand-secondary-dark/40 hover:bg-brand-secondary-dark/60 rounded-xl p-2.5 transition-all duration-300 border border-brand-primary/50 flex items-center gap-3 overflow-hidden shadow-lg shadow-blue-950/20 outline-none focus:outline-none hover:shadow-brand-primary/40"
          >
            <div className="text-brand-primary w-8 h-8 rounded-lg flex-shrink-0 flex items-center justify-center font-black text-xs text-white shadow-lg shadow-brand-primary/40">
              {getUserInitials(user)}
            </div>
            <div className="flex-1 text-left overflow-hidden hidden lg:block">
              <p className="font-black text-white text-[11px] truncate uppercase tracking-tighter">{getDisplayName(user)}</p>
              <p className="text-[9px] font-bold text-blue-300 truncate opacity-60">{user?.email}</p>
            </div>
            <ChevronDown className={`h-3.5 w-3.5 text-blue-400 transition-transform duration-200 ${showUserDetails ? 'rotate-180' : ''}`} />
          </button>

          <button
            onClick={() => setShowLogoutConfirm(true)}
            className="px-5 h-10 ml-0.5 bg-red-500/10 hover:bg-red-500/20 text-red-400 hover:text-red-300 rounded-xl flex items-center gap-2 transition-all border border-red-500/20 shadow-lg shadow-red-950/20 flex-shrink-0 font-black text-[10px] uppercase tracking-widest group"
          >
            <LogOut className="h-3.5 w-3.5 group-hover:-translate-x-0.5 transition-transform" />
            <span className="">{t('nav.logout')}</span>
          </button>
        </div>

        {/* Version tag */}
      </div>

      {/* Logout Confirmation Modal Overlay */}
      {showLogoutConfirm && (
        <div className="logout-modal-wrapper fixed inset-0 z-[1001] flex items-center justify-center lg:pl-64 p-4 bg-gray-900/60 backdrop-blur-[2px] transition-all duration-300">
          <div className="bg-white rounded-2xl w-full max-w-[320px] shadow-2xl border border-gray-100 animate-in fade-in zoom-in duration-200">
            <div className="p-6 text-center">
              <h3 className="text-lg font-black text-gray-900 mb-2 tracking-tight">{t('sidebar.logoutTitle')}</h3>
              <p className="text-[12px] font-bold text-slate-500 leading-relaxed px-2">
                {t('sidebar.logoutBody')}
              </p>
            </div>

            <div className="p-4 bg-gray-50 flex flex-col gap-2 rounded-b-2xl">
              <button
                onClick={handleLogout}
                className="w-full py-3 bg-red-600 hover:bg-red-700 text-white rounded-xl font-black text-xs transition-all shadow-lg shadow-red-100"
              >
                {t('sidebar.logoutConfirm')}
              </button>
              <button
                onClick={() => setShowLogoutConfirm(false)}
                className="w-full py-3 bg-white hover:bg-gray-100 text-gray-600 rounded-xl font-black text-xs transition-all border border-gray-200"
              >
                {t('sidebar.logoutCancel')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default Sidebar;
