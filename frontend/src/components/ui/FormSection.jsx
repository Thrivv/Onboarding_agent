import React from 'react';

const FormSection = ({ title, icon: Icon, children }) => (
  <div className="mb-6 last:mb-0">
    <div className="flex items-center gap-2 mb-3 px-1">
      <div className="p-1.5 bg-indigo-50 rounded-lg">
        <Icon className="h-3 w-3 text-indigo-600" />
      </div>
      <h4 className="text-[10px] font-black text-slate-400 uppercase tracking-widest">{title}</h4>
    </div>
    <div className="space-y-4">
      {children}
    </div>
  </div>
);

export { FormSection };
