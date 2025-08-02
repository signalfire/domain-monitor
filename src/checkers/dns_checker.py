"""
DNS-based domain availability checker (Layer 1).
Performs fast DNS lookups to check domain availability.

File: domain-monitor/src/checkers/dns_checker.py
"""
import time
from typing import Dict, Any, List

import dns.resolver
import dns.exception
from dns.resolver import NoAnswer, NXDOMAIN, NoNameservers

from src.checkers.base import BaseChecker, CheckData, CheckResult
from src.config import settings


class DNSChecker(BaseChecker):
    """DNS-based domain availability checker."""
    
    def __init__(self) -> None:
        """Initialize the DNS checker with rate limit from settings."""
        super().__init__(name="dns", rate_limit=settings.DNS_CHECKS_PER_MINUTE)
        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = 2.0  # Short timeout for fast checks
        self.resolver.lifetime = 4.0  # Maximum time to spend on a query
        
        # Use Google and Cloudflare public DNS servers for reliability
        self.resolver.nameservers = ['8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1']
    
    async def check_domain(self, domain: str) -> CheckData:
        """
        Check domain availability using DNS lookup.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData with check results
        """
        self._rate_limit(domain)
        start_time = time.time()
        
        details: Dict[str, Any] = {
            "query_type": "A",
            "nameservers": self.resolver.nameservers,
        }
        
        try:
            # Try to resolve A record
            self.resolver.resolve(domain, 'A')
            
            # If we get here, the domain has DNS records
            return self._create_check_data(
                domain=domain,
                result=CheckResult.UNAVAILABLE,
                details=details,
                start_time=start_time
            )
            
        except NXDOMAIN:
            # NXDOMAIN means the domain doesn't exist in DNS
            details["nxdomain"] = True
            return self._create_check_data(
                domain=domain,
                result=CheckResult.AVAILABLE,
                details=details,
                start_time=start_time
            )
            
        except (NoAnswer, NoNameservers):
            # These could indicate either an unavailable domain or misconfiguration
            details["error_type"] = "no_answer_or_nameservers"
            return self._create_check_data(
                domain=domain,
                result=CheckResult.UNKNOWN,
                details=details,
                start_time=start_time
            )
            
        except dns.exception.Timeout:
            # Timeout might mean the domain is poorly configured but exists
            details["error_type"] = "timeout"
            return self._create_check_data(
                domain=domain,
                result=CheckResult.UNKNOWN,
                details=details,
                start_time=start_time
            )
            
        except Exception as e:
            # Any other error
            return self._create_check_data(
                domain=domain,
                result=CheckResult.ERROR,
                details=details,
                start_time=start_time,
                error=str(e)
            )

    async def check_domain_multiple_records(self, domain: str) -> CheckData:
        """
        More thorough DNS check that looks for multiple record types.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData with check results
        """
        self._rate_limit(domain)
        start_time = time.time()
        
        # Try multiple DNS record types
        record_types = ['A', 'AAAA', 'MX', 'NS', 'SOA', 'TXT']
        found_records: List[str] = []
        
        details: Dict[str, Any] = {
            "query_types": record_types,
            "nameservers": self.resolver.nameservers,
            "found_records": found_records
        }
        
        try:
            for record_type in record_types:
                try:
                    answers = self.resolver.resolve(domain, record_type)
                    if answers:
                        found_records.append(record_type)
                except (NXDOMAIN, NoAnswer, NoNameservers, dns.exception.Timeout):
                    continue
            
            if found_records:
                # If any records found, domain is unavailable
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.UNAVAILABLE,
                    details=details,
                    start_time=start_time
                )
            else:
                # No records found, potentially available
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.AVAILABLE,
                    details=details,
                    start_time=start_time
                )
                
        except Exception as e:
            return self._create_check_data(
                domain=domain,
                result=CheckResult.ERROR,
                details=details,
                start_time=start_time,
                error=str(e)
            )