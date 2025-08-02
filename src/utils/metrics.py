"""
Metrics collection for domain monitoring service.
Tracks performance and operational metrics.

File: domain-monitor/src/utils/metrics.py
"""
import time
import threading
from typing import Dict, List, Any
from collections import defaultdict, deque


class MetricsCollector:
    """
    Metrics collector for the domain monitoring service.
    Tracks performance and operational metrics.
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Initialize metrics collector.
        
        Args:
            max_history: Maximum number of historical data points to store
        """
        self.lock = threading.RLock()
        self.max_history = max_history
        
        # Counters
        self.counters = defaultdict(int)
        
        # Timers for performance tracking
        self.timers = defaultdict(list)
        self.timer_history = defaultdict(lambda: deque(maxlen=max_history))
        
        # Domain check results
        self.check_results = defaultdict(lambda: defaultdict(int))
        self.check_result_history = defaultdict(lambda: deque(maxlen=max_history))
        
        # API call tracking
        self.api_calls = defaultdict(int)
        self.api_errors = defaultdict(int)
        self.api_timing = defaultdict(list)
        
        # Domain stats
        self.domain_count = 0
        self.high_priority_count = 0
        self.available_domains = []
        
        # Start time for uptime tracking
        self.start_time = time.time()
    
    def increment(self, name: str, value: int = 1) -> None:
        """
        Increment a counter.
        
        Args:
            name: Counter name
            value: Value to increment by
        """
        with self.lock:
            self.counters[name] += value
    
    def set_counter(self, name: str, value: int) -> None:
        """
        Set a counter to a specific value.
        
        Args:
            name: Counter name
            value: Value to set
        """
        with self.lock:
            self.counters[name] = value
    
    def start_timer(self, name: str) -> int:
        """
        Start a timer.
        
        Args:
            name: Timer name
            
        Returns:
            Timer ID for stopping
        """
        timer_id = int(time.time() * 1000000)  # Microsecond precision ID
        with self.lock:
            self.timers[name].append((timer_id, time.time()))
        return timer_id
    
    def stop_timer(self, name: str, timer_id: int) -> float:
        """
        Stop a timer and record duration.
        
        Args:
            name: Timer name
            timer_id: Timer ID from start_timer
            
        Returns:
            Duration in seconds
        """
        now = time.time()
        with self.lock:
            # Find and remove the timer
            for i, (tid, start_time) in enumerate(self.timers[name]):
                if tid == timer_id:
                    self.timers[name].pop(i)
                    duration = now - start_time
                    self.timer_history[name].append(duration)
                    return duration
        return 0.0
    
    def record_check_result(self, domain: str, checker_type: str, result: str) -> None:
        """
        Record a domain check result.
        
        Args:
            domain: Domain name
            checker_type: Checker type
            result: Check result
        """
        with self.lock:
            self.check_results[checker_type][result] += 1
            self.check_result_history[domain].append((time.time(), checker_type, result))
    
    def record_api_call(self, endpoint: str, success: bool, duration: float) -> None:
        """
        Record an API call.
        
        Args:
            endpoint: API endpoint
            success: Whether the call succeeded
            duration: Call duration in seconds
        """
        with self.lock:
            self.api_calls[endpoint] += 1
            if not success:
                self.api_errors[endpoint] += 1
            self.api_timing[endpoint].append(duration)
    
    def update_domain_stats(self, domains: List[str], high_priority: set, available: List[str]) -> None:
        """
        Update domain statistics.
        
        Args:
            domains: All domains being monitored
            high_priority: Set of high priority domains
            available: List of available domains
        """
        with self.lock:
            self.domain_count = len(domains)
            self.high_priority_count = len(high_priority)
            self.available_domains = available.copy()
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current metrics.
        
        Returns:
            Dictionary of metrics
        """
        with self.lock:
            # Calculate timer statistics
            timer_stats = {}
            for name, durations in self.timer_history.items():
                if durations:
                    timer_stats[name] = {
                        "count": len(durations),
                        "avg_ms": sum(durations) * 1000 / len(durations),
                        "min_ms": min(durations) * 1000,
                        "max_ms": max(durations) * 1000,
                    }
            
            # Calculate uptime
            uptime_seconds = time.time() - self.start_time
            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            metrics = {
                "uptime": {
                    "seconds": uptime_seconds,
                    "formatted": f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s",
                },
                "counters": dict(self.counters),
                "timers": timer_stats,
                "domain_stats": {
                    "total": self.domain_count,
                    "high_priority": self.high_priority_count,
                    "available": len(self.available_domains),
                },
                "api_stats": {
                    "calls": dict(self.api_calls),
                    "errors": dict(self.api_errors),
                },
                "check_results": {
                    checker: dict(results) 
                    for checker, results in self.check_results.items()
                },
            }
            
            return metrics


# Global metrics collector
metrics_collector = MetricsCollector()