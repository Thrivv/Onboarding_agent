// frontend/src/components/layout/Footer.jsx

import React from 'react';

const Footer = () => {
  return (
    <footer className="bg-white border-t border-gray-200 mt-auto">
      <div className="container mx-auto px-4 py-6">
        <div className="text-center">
          <p className="text-2xl font-bold gradient-text mb-2">🏦 Thrivv.Ai</p>
          <p className="text-sm text-gray-600 mb-2">
            © {new Date().getFullYear()} Thrivv.Ai. All rights reserved.
          </p>
          <p className="text-xs text-gray-500">
            Version 2.0
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;