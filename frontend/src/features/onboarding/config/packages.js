import { Plus } from 'lucide-react';

const PACKAGE_DEFINITIONS = {
  Essential: [
    'CASA Accounts', 'Deposit Accounts', 'Loan Accounts', 'Cards', 'Beneficiary',
    'Own Account Transfers', 'Within Bank Transfers', 'Domestic Transfers',
    'Instant Transfers', 'International Transfers', 'Bill Payments', 'Card Payments',
    'Loan Payments', 'Bulk Payments', 'Payroll', 'Non WPS',
  ],
  Plus: [
    'CASA Accounts', 'Deposit Accounts', 'Loan Accounts', 'Cards', 'Beneficiary',
    'Own Account Transfers', 'Within Bank Transfers', 'Domestic Transfers',
    'Instant Transfers', 'International Transfers', 'Bill Payments', 'Card Payments',
    'Loan Payments', 'Bulk Payments', 'Payroll', 'Non WPS',
    'Request To Pay', 'EIPP', 'Checkbook Request', 'Balance Confirmation', 'Payer',
  ],
  Advanced: [
    'CASA Accounts', 'Deposit Accounts', 'Loan Accounts', 'Cards', 'Beneficiary',
    'Own Account Transfers', 'Within Bank Transfers', 'Domestic Transfers',
    'Instant Transfers', 'International Transfers', 'Bill Payments', 'Card Payments',
    'Loan Payments', 'Bulk Payments', 'Payroll', 'Non WPS',
    'Request To Pay', 'EIPP', 'Checkbook Request', 'Balance Confirmation', 'Payer',
    'Tally', 'Zoho', 'RFM Loyalty', 'Stripe', 'RewardX', 'HRMS',
  ],
};

const OFFERED_PRODUCTS = [
  'CASA Accounts', 'Deposit Accounts', 'Loan Accounts', 'Cards', 'Beneficiary',
  'Own Account Transfers', 'Within Bank Transfers', 'Domestic Transfers',
  'Instant Transfers', 'International Transfers', 'Bill Payments', 'Card Payments',
  'Loan Payments', 'Bulk Payments', 'Payroll', 'Non WPS',
  'Request To Pay', 'EIPP', 'Checkbook Request', 'Balance Confirmation', 'Payer',
  'Tally', 'Zoho', 'RFM Loyalty', 'Stripe', 'RewardX', 'HRMS',
];

const PACKAGE_ICONS = { Essential: '⭐', Plus: '🚀', Advanced: '💎' };

const CONFIDENCE_STYLES = {
  high: { label: 'High Confidence', bg: 'bg-emerald-100', text: 'text-emerald-700' },
  medium: { label: 'Good Match', bg: 'bg-sky-100', text: 'text-sky-700' },
  low: { label: 'Suggested Match', bg: 'bg-amber-100', text: 'text-amber-700' },
};

export { PACKAGE_DEFINITIONS, OFFERED_PRODUCTS, PACKAGE_ICONS, CONFIDENCE_STYLES };
