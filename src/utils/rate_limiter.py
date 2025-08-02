"""
Rate limiter implementation for domain checkers.
Provides token bucket and distributed rate limiting.

File: domain-monitor/src/utils/rate_limiter.py
"""
import logging
import time
from typing import Dict, Optional
import threading
import random

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter.
    
    Implements the token bucket algorithm for rate limiting:
    - Tokens refill at a constant rate up to a maximum capacity
    - Each operation consumes one or more tokens
    - If insufficient tokens are available, the operation is delayed
    """
    
    def __init__(self, rate: float, capacity: int = None, name: str = "default"):
        """
        Initialize the rate limiter.
        
        Args:
            rate: Maximum operations per second
            capacity: Maximum number of tokens in the bucket (defaults to rate)
            name: Name for this rate limiter (for logging)
        """
        self.rate = rate
        self.capacity = capacity if capacity is not None else max(1, int(rate))
        self.tokens = self.capacity  # Start with a full bucket
        self.last_refill = time.time()
        self.name = name
        self.lock = threading.RLock()
        
        logger.debug(f"Rate limiter '{name}' initialized: {rate} ops/sec, capacity: {self.capacity}")
    
    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill
        
        # Calculate new tokens based on elapsed time and rate
        new_tokens = elapsed * self.rate
        
        # Update token count and last refill time
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill = now
    
    def acquire(self, tokens: int = 1, wait: bool = True) -> bool:
        """
        Acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to acquire
            wait: Whether to wait for tokens to become available
            
        Returns:
            True if tokens were acquired, False if not and wait is False
        """
        if tokens > self.capacity:
            logger.warning(f"Requested tokens ({tokens}) > capacity ({self.capacity})")
            tokens = self.capacity
        
        with self.lock:
            self._refill()
            
            # Check if we have enough tokens
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            if not wait:
                return False
            
            # Calculate wait time
            needed = tokens - self.tokens
            wait_time = needed / self.rate
            
            logger.debug(f"Rate limiter '{self.name}' waiting {wait_time:.2f}s for {needed:.2f} tokens")
            
            # Add a small random factor to avoid thundering herd problems
            jitter = random.uniform(0, 0.1)  # Up to 100ms jitter
            time.sleep(wait_time + jitter)
            
            # After waiting, tokens should be available
            self._refill()
            self.tokens -= tokens
            return True


class DomainRateLimiter:
    """
    Rate limiter for domain checking operations.
    
    Manages rate limits per domain and per checker type, ensuring:
    - Overall rate limits are respected
    - Checkers don't exceed their individual rate limits
    - Domains are checked at appropriate frequencies
    """
    
    def __init__(self):
        """Initialize domain rate limiter."""
        self.limiters: Dict[str, TokenBucketRateLimiter] = {}
        self.domain_last_check: Dict[str, Dict[str, float]] = {}
        self.lock = threading.RLock()
    
    def get_limiter(self, name: str, rate: float) -> TokenBucketRateLimiter:
        """
        Get or create a rate limiter for a specific check type.
        
        Args:
            name: Name of the limiter (usually checker type)
            rate: Maximum operations per second
            
        Returns:
            TokenBucketRateLimiter instance
        """
        with self.lock:
            if name not in self.limiters:
                self.limiters[name] = TokenBucketRateLimiter(rate, name=name)
            return self.limiters[name]
    
    def limit_domain_check(
        self, 
        domain: str, 
        checker_type: str, 
        rate_per_minute: float,
        min_interval: Optional[float] = None
    ) -> None:
        """
        Apply rate limiting for a domain check.
        
        Args:
            domain: Domain being checked
            checker_type: Type of checker
            rate_per_minute: Maximum checks per minute
            min_interval: Minimum interval between checks for this domain (seconds)
        """
        # Convert rate to per-second for the token bucket
        rate_per_second = rate_per_minute / 60.0
        
        # Get or create limiter for this checker type
        limiter = self.get_limiter(checker_type, rate_per_second)
        
        # Apply token bucket rate limiting
        limiter.acquire(1, wait=True)
        
        # Apply per-domain minimum interval if specified
        if min_interval is not None:
            # Get last check time for this domain and checker
            with self.lock:
                last_times = self.domain_last_check.setdefault(domain, {})
                last_time = last_times.get(checker_type, 0)
                
                now = time.time()
                elapsed = now - last_time
                
                # If we haven't waited long enough, sleep for the remaining time
                if elapsed < min_interval:
                    wait_time = min_interval - elapsed
                    logger.debug(f"Domain {domain} checked too recently, waiting {wait_time:.2f}s")
                    time.sleep(wait_time)
                
                # Update last check time
                last_times[checker_type] = time.time()


# Global rate limiter instance
domain_rate_limiter = DomainRateLimiter()