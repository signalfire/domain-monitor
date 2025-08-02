"""
HTTP-based domain availability checker (Layer 1).
Performs fast HTTP HEAD requests to check domain availability.

File: domain-monitor/src/checkers/http_checker.py
"""
import time
from typing import Dict, Any

import httpx

from src.checkers.base import BaseChecker, CheckData, CheckResult
from src.config import settings


class HTTPChecker(BaseChecker):
    """HTTP-based domain availability checker."""
    
    def __init__(self) -> None:
        """Initialize the HTTP checker with rate limit from settings."""
        super().__init__(name="http", rate_limit=settings.HTTP_CHECKS_PER_MINUTE)
        self.timeout = 5.0  # Short timeout for fast checks
        self.protocols = ["https", "http"]
        
    async def check_domain(self, domain: str) -> CheckData:
        """
        Check domain availability using HTTP HEAD requests.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData with check results
        """
        self._rate_limit(domain)
        start_time = time.time()
        
        details: Dict[str, Any] = {
            "protocols_checked": self.protocols,
            "responses": {}
        }
        
        try:
            # Try HEAD requests with both https and http
            for protocol in self.protocols:
                url = f"{protocol}://{domain}"
                try:
                    # Use limited redirects and more security settings
                    async with httpx.AsyncClient(
                        timeout=self.timeout,
                        follow_redirects=True,
                        max_redirects=3,
                        verify=True,
                        http2=True  # Changed to False to avoid http2 dependency
                    ) as client:
                        # Set custom headers to avoid appearing as a bot
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
                            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                            "Accept-Language": "en-US,en;q=0.5",
                            "Accept-Encoding": "gzip, deflate, br",
                            "DNT": "1",
                            "Connection": "keep-alive",
                            "Upgrade-Insecure-Requests": "1",
                            "Sec-Fetch-Dest": "document",
                            "Sec-Fetch-Mode": "navigate",
                            "Sec-Fetch-Site": "cross-site",
                        }
                        
                        # Make the request
                        response = await client.head(url, headers=headers)
                        
                        # Store response details
                        details["responses"][protocol] = {
                            "status_code": response.status_code,
                            "url": str(response.url),
                            "headers": dict(response.headers),
                            "redirected": str(response.url) != url,
                        }
                        
                        # A successful response means the domain is in use
                        if response.status_code < 500:
                            return self._create_check_data(
                                domain=domain,
                                result=CheckResult.UNAVAILABLE,
                                details=details,
                                start_time=start_time
                            )
                except httpx.TooManyRedirects:
                    # Too many redirects usually means the domain exists but has a redirect loop
                    details["responses"][protocol] = {
                        "error": "too_many_redirects",
                        "error_type": "TooManyRedirects",
                    }
                    # Domain exists if it's redirecting
                    return self._create_check_data(
                        domain=domain,
                        result=CheckResult.UNAVAILABLE,
                        details=details,
                        start_time=start_time
                    )
                except httpx.RequestError as e:
                    # Store error details
                    details["responses"][protocol] = {
                        "error": str(e),
                        "error_type": type(e).__name__,
                    }
            
            # If all requests failed, domain might be available
            # But this is a weak signal, so we'll just return a positive result
            # with lower confidence (which is handled by weighted scoring)
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
        
    async def check_common_subdomains(self, domain: str) -> CheckData:
        """
        Check common subdomains to increase confidence.
        
        Args:
            domain: Domain name to check
            
        Returns:
            CheckData with check results
        """
        self._rate_limit(domain)
        start_time = time.time()
        
        # Common subdomains to check
        subdomains = ["www", "mail", "webmail", "admin", "blog"]
        
        details: Dict[str, Any] = {
            "subdomains_checked": subdomains,
            "responses": {}
        }
        
        responsive_subdomains = []
        
        try:
            # Try HEAD requests for common subdomains
            for subdomain in subdomains:
                full_domain = f"{subdomain}.{domain}"
                url = f"https://{full_domain}"
                
                try:
                    async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                        response = await client.head(url)
                        
                        # Store response details
                        details["responses"][subdomain] = {
                            "status_code": response.status_code,
                            "url": str(response.url),
                        }
                        
                        # A successful response means this subdomain exists
                        if response.status_code < 500:
                            responsive_subdomains.append(subdomain)
                            
                except httpx.RequestError:
                    # Ignore errors for subdomains
                    pass
            
            # If any subdomain responds, the domain is likely in use
            details["responsive_subdomains"] = responsive_subdomains
            
            if responsive_subdomains:
                return self._create_check_data(
                    domain=domain,
                    result=CheckResult.UNAVAILABLE,
                    details=details,
                    start_time=start_time
                )
            else:
                # No subdomains responded, which strengthens the available signal
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