"""
Client for fetching domains to monitor from API endpoint.

File: domain-monitor/src/api/domain_api_client.py
"""
import json
import logging
import time
from typing import Dict, List, Set, Tuple, Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.config import settings

# Set up logger
logger = logging.getLogger(__name__)


class DomainAPIClient:
    """Client for fetching domains to monitor from API."""
    
    def __init__(self) -> None:
        """Initialize the domain API client with configuration from settings."""
        self.api_url = settings.DOMAIN_API_URL
        self.auth_token = settings.API_AUTH_TOKEN
        self.timeout = settings.API_TIMEOUT
        self.max_retries = settings.API_MAX_RETRIES
        self.retry_backoff = settings.API_RETRY_BACKOFF
        self.last_fetch_time = 0.0
        self.refresh_interval = settings.DOMAIN_API_REFRESH_INTERVAL
        
        # Default testing domains in case API is unreachable
        self.default_domains = [
            {"domain": "example.com", "priority": True},
            {"domain": "example.org", "priority": False},
            "example.net"
        ]
    
    def _ensure_url_has_protocol(self, url: str) -> str:
        """
        Ensure the URL has a protocol prefix (http:// or https://).
        
        Args:
            url: URL to check
            
        Returns:
            URL with protocol
        """
        if not url:
            return "http://localhost:8001/domains"  # Fallback to local test endpoint
            
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            # Default to https if no protocol specified
            return f"https://{url}"
        return url
    
    @retry(
        stop=stop_after_attempt(settings.API_MAX_RETRIES),
        wait=wait_exponential(multiplier=settings.API_RETRY_BACKOFF, min=1, max=60),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)),
    )
    async def fetch_domains(self, force: bool = False) -> Tuple[List[str], Set[str]]:
        """
        Fetch domains to monitor from API.
        
        Args:
            force: Force fetch even if refresh interval hasn't elapsed
            
        Returns:
            Tuple of (all domains, high priority domains)
            
        Raises:
            httpx.HTTPStatusError: If API returns a 4xx or 5xx status code
            httpx.ConnectError: If connection to API fails
            httpx.TimeoutException: If API request times out
        """
        current_time = time.time()
        
        # Check if we need to fetch new domains
        if not force and current_time - self.last_fetch_time < self.refresh_interval:
            logger.debug("Skipping domain fetch, refresh interval not elapsed")
            return [], set()
        
        # Ensure URL has protocol
        api_url = self._ensure_url_has_protocol(self.api_url)
        
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{settings.APP_NAME}/{settings.APP_VERSION}",
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                logger.info(f"Fetching domains to monitor from API: {api_url}")
                response = await client.get(
                    api_url,
                    headers=headers
                )
                
                # Raise exception for 4xx and 5xx responses (will trigger retry)
                response.raise_for_status()
                
                # Update last fetch time
                self.last_fetch_time = current_time
                
                # Parse and return domains
                try:
                    data = response.json()
                    return self._parse_domains_response(data)
                except json.JSONDecodeError:
                    logger.error(f"API response is not valid JSON: {response.text}")
                    return self._use_default_domains()
        except Exception as e:
            logger.warning(f"Failed to fetch domains from API: {str(e)}")
            return self._use_default_domains()
    
    def _use_default_domains(self) -> Tuple[List[str], Set[str]]:
        """
        Use default domains when API is unreachable.
        
        Returns:
            Tuple of (all domains, high priority domains)
        """
        logger.warning("Using default domains for testing")
        return self._parse_domains_response({"domains": self.default_domains})
    
    def _parse_domains_response(self, data: Dict[str, Any]) -> Tuple[List[str], Set[str]]:
        """
        Parse domains response from API.
        
        Args:
            data: API response data
            
        Returns:
            Tuple of (all domains, high priority domains)
        """
        all_domains = []
        high_priority_domains = set()
        
        # Handle different possible response formats
        
        # 1. Look for 'domains' array (primary format)
        domains_list = data.get("domains", [])
        
        # 2. Alternative format: domains directly at root level as array
        if not domains_list and isinstance(data.get("data"), list):
            domains_list = data.get("data", [])
            
        # 3. Another alternative: domain objects with a 'results' key
        if not domains_list and isinstance(data.get("results"), list):
            domains_list = data.get("results", [])
            
        if not domains_list:
            logger.warning("No domains found in API response")
            return [], set()
        
        for domain_info in domains_list:
            # Handle both object and string formats
            if isinstance(domain_info, dict):
                domain = domain_info.get("domain", "").strip()
                is_priority = domain_info.get("priority", False)
                # Alternative field names
                if not domain:
                    domain = domain_info.get("name", "").strip()
                if not domain:
                    domain = domain_info.get("domainName", "").strip()
            else:
                domain = str(domain_info).strip()
                is_priority = False
            
            if domain:
                all_domains.append(domain)
                if is_priority:
                    high_priority_domains.add(domain)
        
        logger.info(f"Fetched {len(all_domains)} domains from API ({len(high_priority_domains)} high priority)")
        return all_domains, high_priority_domains