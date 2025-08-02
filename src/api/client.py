"""
API client for sending domain check results to external API.
Includes robust retry logic and error handling.

File: domain-monitor/src/api/client.py
"""
import json
import logging
from typing import Dict, Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from src.config import settings
from src.checkers.base import CheckData

# Set up logger
logger = logging.getLogger(__name__)


class APIClient:
    """Client for sending domain check results to external API."""
    
    def __init__(self) -> None:
        """Initialize the API client with configuration from settings."""
        self.callback_url = settings.API_CALLBACK_URL
        self.auth_token = settings.API_AUTH_TOKEN
        self.timeout = settings.API_TIMEOUT
        self.max_retries = settings.API_MAX_RETRIES
        self.retry_backoff = settings.API_RETRY_BACKOFF
    
    @retry(
        stop=stop_after_attempt(settings.API_MAX_RETRIES),
        wait=wait_exponential(multiplier=settings.API_RETRY_BACKOFF, min=1, max=60),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    async def send_check_result(self, check_data: CheckData) -> Dict[str, Any]:
        """
        Send domain check result to API.
        
        Args:
            check_data: Check result data
            
        Returns:
            API response as dictionary
            
        Raises:
            httpx.HTTPStatusError: If API returns a 4xx or 5xx status code
            httpx.ConnectError: If connection to API fails
            httpx.TimeoutException: If API request times out
        """
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{settings.APP_NAME}/{settings.APP_VERSION}",
        }
        
        # Prepare payload
        payload = {
            "domain": check_data.domain,
            "check_type": check_data.checker_type,
            "result": check_data.result.value,
            "timestamp": check_data.timestamp,
            "details": check_data.details,
            "duration_ms": check_data.duration_ms,
        }
        
        if check_data.error:
            payload["error"] = check_data.error
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.debug(f"Sending check result to API for domain {check_data.domain}")
            response = await client.post(
                self.callback_url,
                headers=headers,
                json=payload
            )
            
            # Raise exception for 4xx and 5xx responses (will trigger retry)
            response.raise_for_status()
            
            # Parse and return response
            try:
                return response.json()
            except json.JSONDecodeError:
                logger.warning(f"API response is not valid JSON: {response.text}")
                return {"status": "success", "raw_response": response.text}
    
    async def send_available_domain_notification(self, domain: str, confidence: float, checks: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send notification about an available domain.
        
        Args:
            domain: Available domain name
            confidence: Confidence score (0-1)
            checks: Dictionary of check results
            
        Returns:
            API response as dictionary
        """
        headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"{settings.APP_NAME}/{settings.APP_VERSION}",
        }
        
        # Serialize CheckData objects to dictionaries
        serialized_checks = checks.copy()
        if "checks" in serialized_checks:
            serialized_checks["checks"] = {
                checker_name: check_data.to_dict() if hasattr(check_data, 'to_dict') else check_data
                for checker_name, check_data in serialized_checks["checks"].items()
            }
        
        payload = {
            "domain": domain,
            "status": "available",
            "confidence": confidence,
            "timestamp": checks.get("timestamp", 0),
            "checks": serialized_checks,
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"Notifying API about available domain: {domain} (confidence: {confidence:.2f})")
            response = await client.post(
                settings.API_AVAILABLE_CALLBACK_URL,
                headers=headers,
                json=payload
            )
            
            # Raise exception for 4xx and 5xx responses (will trigger retry)
            response.raise_for_status()
            
            # Parse and return response
            try:
                return response.json()
            except json.JSONDecodeError:
                logger.warning(f"API response is not valid JSON: {response.text}")
                return {"status": "success", "raw_response": response.text}