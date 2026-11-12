import React from 'react';

const WelcomeOnboardingCard = ({ content }) => {
  // Plain rendering: the welcome message is just text like any other message
  // bubble — no colored callout box, no icon, no "Next step" label. Only the
  // greeting (first paragraph) is bolded; everything after it (intro copy,
  // if any, and the next-step line) renders as regular text, separated by
  // blank lines the same way the message was authored.
  const stripBold = (s) => s.replace(/\*\*(.*?)\*\*/g, '$1');

  const paragraphs = content
    .split(/\n\s*\n/)
    .map(p => p.replace(/\s*\n\s*/g, ' ').trim())
    .filter(Boolean);

  const greeting = paragraphs[0] || '';
  const rest = paragraphs.slice(1);

  return (
    <div className="max-w-md space-y-2 text-[15px] leading-relaxed">
      <p className="font-medium">{stripBold(greeting)}</p>
      {rest.map((line, i) => (
        <p key={i}>{stripBold(line)}</p>
      ))}
    </div>
  );
};

export { WelcomeOnboardingCard };
