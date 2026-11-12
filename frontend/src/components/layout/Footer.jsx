// frontend/src/components/layout/Footer.jsx

import React from 'react';
import logo from '../../assets/logo-growx.svg';
import { useLanguage } from '../../context/LanguageContext';

const Footer = () => {
  const { t } = useLanguage();
  return (
    <footer className="bg-white border-t border-gray-200 mt-auto">
      <div className="container mx-auto px-4 py-6">
        <div className="text-center">
          <div className="flex justify-center mb-4">
            <img src={logo} alt="GrowX Logo" className="h-8 w-auto opacity-80 hover:opacity-100 transition-opacity" />
          </div>
          <p className="text-sm text-gray-600 mb-2">
            {t('footer.rights', { year: new Date().getFullYear() })}
          </p>
          <p className="text-xs text-gray-500">
            {t('footer.version')}
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;