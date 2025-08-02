"""
WHOIS-based domain availability checker (Layer 3).
Performs thorough WHOIS lookups to confirm domain availability.

File: domain-monitor/src/checkers/whois_checker.py
"""
import time
from typing import Dict, Any, List

import whois
from whois.parser import PywhoisError

from src.checkers.base import BaseChecker, CheckData, CheckResult
from src.config import settings


class WHOISChecker(BaseChecker):
    """WHOIS-based domain availability checker."""
    
    def __init__(self) -> None:
        """Initialize the WHOIS checker with rate limit from settings."""
        super().__init__(name="whois", rate_limit=settings.WHOIS_CHECKS_PER_MINUTE)
        
        # Common patterns indicating domain availability in WHOIS responses
        self.available_patterns: List[str] = [
            "no match for",
            "not found",
            "no data found",
            "no entries found",
            "domain not found",
            "domain available",
            "status: free",
            "status: available",
            "no object found",
        ]
    
    async def check_domain(self, domain: str) -> CheckData:
        """
        Check domain availability using WHOIS lookup.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData with check results
        """
        self._rate_limit(domain)
        start_time = time.time()
        
        details: Dict[str, Any] = {}
        
        try:
            # Perform WHOIS lookup
            domain_info = whois.whois(domain)
            
            # Check if domain_info indicates domain not found
            if domain_info.status is None:
                # Check raw text for availability patterns
                if domain_info.text and any(pattern.lower() in domain_info.text.lower() 
                                           for pattern in self.available_patterns):
                    details["reason"] = "available_pattern_match"
                    return self._create_check_data(
                        domain=domain,
                        result=CheckResult.AVAILABLE,
                        details=details,
                        start_time=start_time
                    )
            
            # Extract useful information from WHOIS response
            details.update(self._extract_whois_details(domain_info))
            
            # Check expiration date
            if self._is_expired(domain_info):
                details["reason"] = "expired"
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.AVAILABLE,
                    details=details,
                    start_time=start_time
                )
            
            # If we have status fields and domain_info.status is not None, domain exists
            if domain_info.status is not None:
                details["reason"] = "has_status"
                details["status"] = domain_info.status
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.UNAVAILABLE,
                    details=details,
                    start_time=start_time
                )
            
            # Fallback: if we have registrar information, domain likely exists
            if domain_info.registrar is not None:
                details["reason"] = "has_registrar"
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.UNAVAILABLE,
                    details=details,
                    start_time=start_time
                )
            
            # If we reach here with no definitive result, mark as unknown
            return self._create_check_data(
                domain=domain,
                result=CheckResult.UNKNOWN,
                details=details,
                start_time=start_time
            )
            
        except PywhoisError as e:
            # PywhoisError often means the domain doesn't exist
            error_str = str(e).lower()
            
            # Check if error message indicates domain is available
            if any(pattern.lower() in error_str for pattern in self.available_patterns):
                details["error_message"] = str(e)
                details["reason"] = "whois_error_available"
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.AVAILABLE,
                    details=details,
                    start_time=start_time
                )
            
            # Otherwise it's an actual error
            return self._create_check_data(
                domain=domain,
                result=CheckResult.ERROR,
                details=details,
                start_time=start_time,
                error=str(e)
            )
            
        except Exception as e:
            return self._create_check_data(
                domain=domain,
                result=CheckResult.ERROR,
                details=details,
                start_time=start_time,
                error=str(e)
            )
    
    def _extract_whois_details(self, domain_info: Any) -> Dict[str, Any]:
        """
        Extract relevant details from WHOIS response.
        
        Args:
            domain_info: WHOIS information object
            
        Returns:
            Dictionary of extracted details
        """
        details: Dict[str, Any] = {}
        
        # Extract common WHOIS fields if present
        for field in ["registrar", "creation_date", "expiration_date", "updated_date"]:
            value = getattr(domain_info, field, None)
            if value is not None:
                details[field] = value
        
        return details
    
    def _is_expired(self, domain_info: Any) -> bool:
        """
        Check if domain is expired based on WHOIS information.
        
        Args:
            domain_info: WHOIS information object
            
        Returns:
            True if domain is expired, False otherwise
        """
        expiration_date = getattr(domain_info, "expiration_date", None)
        
        if expiration_date is None:
            return False
        
        current_time = time.time()
        
        # Handle both list and single date formats
        if isinstance(expiration_date, list):
            # Use the latest expiration date
            latest_date = max(date.timestamp() for date in expiration_date 
                             if hasattr(date, "timestamp"))
            return latest_date < current_time
        elif hasattr(expiration_date, "timestamp"):
            return expiration_date.timestamp() < current_time
        
        return False