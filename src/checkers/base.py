"""
Base checker module that defines the interface for all domain availability checkers.

File: domain-monitor/src/checkers/base.py
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional

from src.utils.rate_limiter import domain_rate_limiter


class CheckResult(Enum):
    """Possible results from a domain check."""
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    ERROR = "error"


@dataclass
class CheckData:
    """Data structure to hold check results and metadata."""
    domain: str
    result: CheckResult
    timestamp: float
    checker_type: str
    details: Dict[str, Any]
    duration_ms: int
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert CheckData to a JSON-serializable dictionary."""
        data = {
            "domain": self.domain,
            "result": self.result.value,
            "timestamp": self.timestamp,
            "checker_type": self.checker_type,
            "details": self.details,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            data["error"] = self.error
        return data


class BaseChecker(ABC):
    """Base class for all domain availability checkers."""
    
    def __init__(self, name: str, rate_limit: int) -> None:
        """
        Initialize the base checker.
        
        Args:
            name: Name of the checker
            rate_limit: Maximum number of checks per minute
        """
        self.name = name
        self.rate_limit = rate_limit
        self.last_check_time: Dict[str, float] = {}
    
    @abstractmethod
    async def check_domain(self, domain: str) -> CheckData:
        """
        Check if a domain is available.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData object with check results
        """
        pass
    
    def _rate_limit(self, domain: str) -> None:
        """
        Implement rate limiting for domain checks.
        
        Args:
            domain: Domain being checked
        """
        # Use the global domain rate limiter
        domain_rate_limiter.limit_domain_check(
            domain=domain,
            checker_type=self.name,
            rate_per_minute=self.rate_limit,
            min_interval=60.0 / self.rate_limit  # Ensure minimum interval between checks
        )
    
    def _create_check_data(
        self, 
        domain: str, 
        result: CheckResult, 
        details: Dict[str, Any],
        start_time: float,
        error: Optional[str] = None
    ) -> CheckData:
        """
        Create a CheckData object with check results.
        
        Args:
            domain: Domain name checked
            result: Check result
            details: Additional details about the check
            start_time: When the check started (timestamp)
            error: Optional error message if check failed
            
        Returns:
            CheckData object
        """
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)
        
        return CheckData(
            domain=domain,
            result=result,
            timestamp=end_time,
            checker_type=self.name,
            details=details,
            duration_ms=duration_ms,
            error=error
        )