import React from 'react';
import { motion } from 'framer-motion';
import { CheckCircle } from 'lucide-react';

const SuccessDisplay = ({ message }) => (
  <div className="bg-green-50 border border-green-200 p-4 rounded-xl flex items-center gap-3">
    <CheckCircle className="h-5 w-5 text-green-600" />
    <p className="text-sm font-medium text-green-800 tracking-tight">{message}</p>
  </div>
);

const SuccessConfetti = () => {
  const emojis = ['💳', '💰', '✨', '💎', '🚀', '⭐', '🏦', '🎉'];
  return (
    <div className="fixed inset-0 pointer-events-none z-[100] overflow-hidden">
      {[...Array(12)].map((_, i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: window.innerHeight + 50, x: (window.innerWidth / 4) + (Math.random() * (window.innerWidth / 2)), rotate: 0, scale: 0.5 }}
          animate={{ opacity: [0, 1, 1, 0], y: -50, x: (i % 2 === 0 ? '-=100' : '+=100'), rotate: Math.random() * 360, scale: [0.5, 1.2, 1, 0.8] }}
          transition={{ duration: 5 + Math.random() * 3, repeat: 0, delay: Math.random() * 1.5, ease: "easeOut" }}
          className="absolute text-2xl filter drop-shadow-lg"
        >
          {emojis[i % emojis.length]}
        </motion.div>
      ))}
    </div>
  );
};

export { SuccessDisplay, SuccessConfetti };
