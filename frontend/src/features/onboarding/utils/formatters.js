import { User } from 'lucide-react';

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

const calculateAge = (dobString) => {
  if (!dobString) return "";
  try {
    const today = new Date();
    const birthDate = new Date(dobString);
    let age = today.getFullYear() - birthDate.getFullYear();
    const m = today.getMonth() - birthDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) age--;
    return `${age}Y`;
  } catch (e) { return ""; }
};

const formatLabel = (key) => {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const stripFormatting = (text) => {
  if (typeof text !== 'string') return text;

  // 1. Clean structured lists and headers line-by-line
  // This is more robust than complex regex lookaheads
  let lines = text.split('\n');
  let cleanedLines = lines.filter(line => {
    const trimmed = line.trim().replace(/\*/g, ''); // strip asterisks for check
    if (!trimmed) return true;

    // Skip headers (more robust regex)
    if (/^(Final Members? List|Registered Individuals|Verification is required for the following (beneficial owners|members)):?\.?$/i.test(trimmed)) {
      return false;
    }

    // Skip member rows (e.g. "1. Name - Member | Share...")
    // Using a more inclusive regex for the start "1. " or "- "
    if (/^(\d+\.|-)\s+/.test(trimmed) && (
      trimmed.includes('|') ||
      trimmed.includes('Share:') ||
      trimmed.includes('Verified') ||
      trimmed.includes('Member') ||
      trimmed.includes('effective ownership') ||
      trimmed.includes('✅') ||
      trimmed.includes('Pending')
    )) {
      return false;
    }


    return true;
  });

  let cleaned = cleanedLines.join('\n').trim();

  // 2. MOA Specific Prompt Cleanup
  if (text.toLowerCase().includes('verification is required for the following beneficial owners:')) {
    cleaned = cleaned.replace(/verification is required for the members listed below:/gi, ''); // prevent double
    cleaned = 'Verification is required for the members listed below:\n' + cleaned;
  }

  // 3. Strip Markdown and Emojis
  return cleaned
    .replace(/\*\*(.+?)\*\*/gs, '$1')
    .replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/gs, '$1')
    .replace(/__(.+?)__/gs, '$1')
    .replace(/[\u{1F000}-\u{1FFFF}]/gu, '')
    .replace(/[\u{2600}-\u{26FF}]/gu, '')
    .replace(/[\u{2700}-\u{27BF}]/gu, '')
    .replace(/[\u{FE00}-\u{FE0F}]/gu, '')
    .replace(/[\u{200D}]/gu, '')
    .replace(/\n{3,}/g, '\n\n')
    .split('\n').map(line => line.trimEnd()).join('\n')
    .trim();
};

export { getDisplayName, getUserInitials, calculateAge, formatLabel, stripFormatting };
