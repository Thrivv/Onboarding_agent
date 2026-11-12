# backend/app/services/message_monitor.py

import logging
from datetime import datetime
from typing import Dict
from collections import defaultdict

logger = logging.getLogger(__name__)

class MessageMonitor:
    """
    Monitor LLM message generation
    Track success rates, failures, and performance
    """
    
    stats = defaultdict(lambda: {"success": 0, "failure": 0, "total_time": 0})
    
    @classmethod
    def log_generation(
        cls,
        message_type: str,
        success: bool,
        duration_ms: float,
        fallback_used: bool = False
    ):
        """Log message generation attempt"""
        
        key = message_type
        cls.stats[key]["success" if success else "failure"] += 1
        cls.stats[key]["total_time"] += duration_ms
        
        if fallback_used:
            logger.warning(f"Fallback used for {message_type}")
        
        if not success:
            logger.error(f"Generation failed: {message_type}")
    
    @classmethod
    def get_stats(cls) -> Dict:
        """Get generation statistics"""
        return dict(cls.stats)
    
    @classmethod
    def log_summary(cls):
        """Log summary of all message generation"""
        logger.info("=" * 80)
        logger.info("MESSAGE GENERATION SUMMARY")
        logger.info("=" * 80)
        
        for msg_type, stats in cls.stats.items():
            total = stats["success"] + stats["failure"]
            success_rate = (stats["success"] / total * 100) if total > 0 else 0
            avg_time = (stats["total_time"] / total) if total > 0 else 0
            
            logger.info(
                f"{msg_type}: {stats['success']}/{total} "
                f"({success_rate:.1f}%) | Avg: {avg_time:.0f}ms"
            )