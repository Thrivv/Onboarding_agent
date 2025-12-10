// frontend/src/components/common/Button.jsx

import React from 'react';

const Button = ({
  children,
  type = 'button',
  variant = 'primary',
  size = 'md',
  disabled = false,
  loading = false,
  icon: Icon,
  onClick,
  className = '',
  fullWidth = false,
}) => {
  const baseClasses = 'font-medium rounded-lg transition-all duration-200 flex items-center justify-center';
  
  const variantClasses = {
    primary: 'gradient-btn text-white hover:opacity-90',
    secondary: 'bg-gray-200 text-gray-800 hover:bg-gray-300',
    outline: 'border-2 border-primary text-primary hover:bg-primary hover:text-white',
    danger: 'bg-red-600 text-white hover:bg-red-700',
    success: 'bg-green-600 text-white hover:bg-green-700',
  };

  const sizeClasses = {
    sm: 'px-3 py-1.5 text-sm',
    md: 'px-4 py-2 text-base',
    lg: 'px-6 py-3 text-lg',
  };

  const widthClass = fullWidth ? 'w-full' : '';

  const disabledClasses = disabled || loading ? 'opacity-50 cursor-not-allowed' : '';

  const classes = `
    ${baseClasses}
    ${variantClasses[variant]}
    ${sizeClasses[size]}
    ${widthClass}
    ${disabledClasses}
    ${className}
  `.trim();

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={classes}
    >
      {loading && (
        <div
          className="spinner mr-2"
          style={{ width: '16px', height: '16px', borderWidth: '2px' }}
        ></div>
      )}
      {!loading && Icon && <Icon className="h-5 w-5 mr-2" />}
      {children}
    </button>
  );
};

export default Button;