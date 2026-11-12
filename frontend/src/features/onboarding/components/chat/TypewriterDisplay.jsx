import React, { useEffect, useState } from 'react';
import { stripFormatting } from '../../utils/formatters';

const TypewriterDisplay = ({ text, onComplete }) => {
  const cleanText = stripFormatting(text);
  const [displayedText, setDisplayedText] = useState("");
  const [index, setIndex] = useState(0);

  // Reset typewriter if text changes
  useEffect(() => {
    setDisplayedText("");
    setIndex(0);
  }, [cleanText]);

  useEffect(() => {
    if (typeof cleanText !== 'string') return;
    if (index < cleanText.length) {
      const timeout = setTimeout(() => {
        setDisplayedText((prev) => prev + cleanText[index]);
        setIndex((prev) => prev + 1);
      }, 5);
      return () => clearTimeout(timeout);
    } else if (onComplete) {
      onComplete();
    }
  }, [index, cleanText, onComplete]);

  return <div className="whitespace-pre-wrap">{displayedText}</div>;
};

export { TypewriterDisplay };
