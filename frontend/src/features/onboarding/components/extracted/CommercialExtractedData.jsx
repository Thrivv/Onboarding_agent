import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Building, Calendar, CheckCircle, ChevronDown, ChevronUp, Clock, FileText, Globe, Home, ShieldCheck } from 'lucide-react';
import { InfoRow } from '../../../../components/ui/InfoRow';

const CommercialExtractedData = ({ data }) => {
  const [showMore, setShowMore] = useState(false);
  const englishData = data.english || {};
  const partners = data.partners || [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <InfoRow label="Company Name" value={englishData.company_name_english || englishData['Company Name']} fullWidth icon={Building} />
        <InfoRow label="License Number" value={englishData.license_number || englishData['License Number']} icon={ShieldCheck} />
        <InfoRow label="Legal Type" value={englishData.legal_type || englishData['Legal Type']} icon={Building} />
        <InfoRow label="Mobile" value={englishData.mobile || 'N/A'} icon={CheckCircle} />
        <InfoRow label="Issue Date" value={englishData.issue_date || englishData['Issue Date']} icon={Calendar} />
        <InfoRow label="Expiry Date" value={englishData.expiry_date || englishData['Expiry Date']} icon={Clock} />
      </div>

      <div className="flex justify-center -mt-2">
        <button
          onClick={() => setShowMore(!showMore)}
          className="px-5 py-1.5 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-full text-[9px] font-black text-indigo-600 uppercase tracking-widest transition-all flex items-center gap-1.5 shadow-sm"
        >
          {showMore ? (
            <><ChevronUp className="h-3 w-3" /> Show Less</>
          ) : (
            <><ChevronDown className="h-3 w-3" /> View All Details</>
          )}
        </button>
      </div>

      {showMore && (
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="space-y-6"
        >
          <div className="grid grid-cols-2 gap-4">
            <InfoRow label="Register Number" value={englishData.commercial_register_number} icon={ShieldCheck} />
            <InfoRow label="Main License" value={englishData.main_license_number} icon={FileText} />
            <InfoRow label="Receipt Number" value={englishData.receipt_number} icon={FileText} />
            <InfoRow label="DCCI Number" value={englishData.dcci_number} icon={Building} />
            <InfoRow label="Parcel ID" value={englishData.parcel_id} icon={Home} />
            <InfoRow label="Address" value={englishData.license_address} fullWidth icon={Home} />
          </div>



          <div className="grid grid-cols-2 gap-4">
            <InfoRow label="Nominated Capital" value={englishData.nominated_capital} icon={Building} />
            <InfoRow label="Paid Capital" value={englishData.paid_capital} icon={Building} />
            <InfoRow label="Currency" value={englishData.currency} icon={Globe} />
            <InfoRow label="Value Per Share" value={englishData.value_per_share} icon={ShieldCheck} />
          </div>

          <div className="rounded-2xl border border-slate-200 overflow-hidden">
            <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50 border-b border-amber-100">
              <div className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <p className="text-[9px] font-black text-amber-600 uppercase tracking-[0.18em]">Payment Information</p>
            </div>
            <div className="p-4 bg-white grid grid-cols-2 gap-4">
              <InfoRow label="Voucher No" value={englishData.payment_voucher_number} icon={FileText} />
              <InfoRow label="Payment Mode" value={englishData.payment_mode} icon={ShieldCheck} />
              <InfoRow label="Payment Amount" value={englishData.payment_amount} fullWidth icon={CheckCircle} />
            </div>
          </div>

          {partners.length > 0 && (
            <div className="rounded-2xl border border-slate-200 overflow-hidden">
              <div className="flex items-center gap-2 px-4 py-2.5 bg-indigo-50 border-b border-indigo-100">
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-400" />
                <p className="text-[9px] font-black text-indigo-500 uppercase tracking-[0.18em]">Ownership Structure</p>
              </div>
              <div className="p-4 space-y-2 bg-white">
                {partners.map((partner, idx) => (
                  <div key={idx} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100 group hover:border-indigo-200 transition-all">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-black text-[10px]">
                        {String(partner.name_english || partner['Name (EN)']).charAt(0)}
                      </div>
                      <div>
                        <p className="text-[12px] font-black text-slate-800 leading-none mb-1">
                          {partner.name_english || partner['Name (EN)']}
                        </p>
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tighter">{partner.role || 'Verified Member'}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className="text-[12px] font-black text-indigo-600">
                        {partner.share_percentage || partner['Share Percentage']}
                        {(partner.share_percentage || partner['Share Percentage']) && !String(partner.share_percentage || partner['Share Percentage']).endsWith('%') ? '%' : ''}
                      </p>
                      <p className="text-[9px] font-bold text-slate-300 uppercase tracking-widest">Share</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      )}
    </div>
  );
};

export { CommercialExtractedData };
