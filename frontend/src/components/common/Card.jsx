// frontend/src/components/common/Card.jsx

import React from 'react';

const Card = ({
  children,
  title,
  subtitle,
  footer,
  className = '',
  padding = 'md',
  hover = false,
  gradient = false,
}) => {
  const paddingClasses = {
    sm: 'p-4',
    md: 'p-6',
    lg: 'p-8',
    none: '',
  };

  const baseClasses = `
    bg-white rounded-xl shadow-lg
    ${hover ? 'card-hover' : ''}
    ${gradient ? 'bg-gradient-to-br from-primary to-primary-dark text-white' : ''}
    ${paddingClasses[padding]}
    ${className}
  `.trim();

  return (
    <div className={baseClasses}>
      {(title || subtitle) && (
        <div className="mb-4">
          {title && (
            <h3 className={`text-xl font-bold ${gradient ? 'text-white' : 'text-gray-800'}`}>
              {title}
            </h3>
          )}
          {subtitle && (
            <p className={`text-sm mt-1 ${gradient ? 'text-blue-100' : 'text-gray-600'}`}>
              {subtitle}
            </p>
          )}
        </div>
      )}

      <div>{children}</div>

      {footer && (
        <div className="mt-4 pt-4 border-t border-gray-200">
          {footer}
        </div>
      )}
    </div>
  );
};

export default Card;