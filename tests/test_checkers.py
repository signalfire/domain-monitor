# File: domain-monitor/tests/test_checkers.py

import pytest
from unittest.mock import MagicMock, patch

import dns.resolver
import httpx

from src.checkers.base import CheckResult
from src.checkers.dns_checker import DNSChecker
from src.checkers.http_checker import HTTPChecker
from src.checkers.whois_checker import WHOISChecker


class TestDNSChecker:
    """Tests for the DNSChecker class."""

    @pytest.mark.asyncio
    async def test_available_domain(self):
        """Test checking an available domain via DNS."""
        with patch('dns.resolver.Resolver.resolve') as mock_resolve:
            # Simulate NXDOMAIN exception
            mock_resolve.side_effect = dns.resolver.NXDOMAIN()
            
            checker = DNSChecker()
            result = await checker.check_domain("available-domain.com")
            
            assert result.result == CheckResult.AVAILABLE
            assert result.domain == "available-domain.com"
            assert result.checker_type == "dns"
            assert "nxdomain" in result.details
            assert result.details["nxdomain"] is True

    @pytest.mark.asyncio
    async def test_unavailable_domain(self):
        """Test checking an unavailable domain via DNS."""
        with patch('dns.resolver.Resolver.resolve') as mock_resolve:
            # Simulate successful resolution
            mock_resolve.return_value = MagicMock()
            
            checker = DNSChecker()
            result = await checker.check_domain("unavailable-domain.com")
            
            assert result.result == CheckResult.UNAVAILABLE
            assert result.domain == "unavailable-domain.com"
            assert result.checker_type == "dns"

    @pytest.mark.asyncio
    async def test_dns_error(self):
        """Test handling DNS resolution errors."""
        with patch('dns.resolver.Resolver.resolve') as mock_resolve:
            # Simulate timeout
            mock_resolve.side_effect = dns.exception.Timeout()
            
            checker = DNSChecker()
            result = await checker.check_domain("error-domain.com")
            
            assert result.result == CheckResult.UNKNOWN
            assert result.domain == "error-domain.com"
            assert result.checker_type == "dns"
            assert "error_type" in result.details
            assert result.details["error_type"] == "timeout"


class TestHTTPChecker:
    """Tests for the HTTPChecker class."""

    @pytest.mark.asyncio
    async def test_available_domain(self):
        """Test checking an available domain via HTTP."""
        with patch('httpx.AsyncClient.head') as mock_head:
            # Simulate connection error for all requests
            mock_head.side_effect = httpx.ConnectError("Failed to connect")
            
            checker = HTTPChecker()
            result = await checker.check_domain("available-domain.com")
            
            assert result.result == CheckResult.AVAILABLE
            assert result.domain == "available-domain.com"
            assert result.checker_type == "http"
            assert "protocols_checked" in result.details
            assert "responses" in result.details

    @pytest.mark.asyncio
    async def test_unavailable_domain(self):
        """Test checking an unavailable domain via HTTP."""
        with patch('httpx.AsyncClient.head') as mock_head:
            # Simulate successful response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.url = "https://unavailable-domain.com"
            mock_response.headers = {"server": "nginx"}
            mock_head.return_value = mock_response
            
            checker = HTTPChecker()
            result = await checker.check_domain("unavailable-domain.com")
            
            assert result.result == CheckResult.UNAVAILABLE
            assert result.domain == "unavailable-domain.com"
            assert result.checker_type == "http"
            assert "responses" in result.details


class TestWHOISChecker:
    """Tests for the WHOISChecker class."""

    @pytest.mark.asyncio
    async def test_available_domain(self):
        """Test checking an available domain via WHOIS."""
        with patch('whois.whois') as mock_whois:
            # Simulate domain not found
            whois_response = MagicMock()
            whois_response.status = None
            whois_response.registrar = None
            whois_response.text = "No match for domain example.com"
            mock_whois.return_value = whois_response
            
            checker = WHOISChecker()
            result = await checker.check_domain("available-domain.com")
            
            assert result.result == CheckResult.AVAILABLE
            assert result.domain == "available-domain.com"
            assert result.checker_type == "whois"
            assert "reason" in result.details

    @pytest.mark.asyncio
    async def test_unavailable_domain(self):
        """Test checking an unavailable domain via WHOIS."""
        with patch('whois.whois') as mock_whois:
            # Simulate domain exists
            whois_response = MagicMock()
            whois_response.status = ["clientTransferProhibited"]
            whois_response.registrar = "Example Registrar"
            whois_response.text = "Domain Name: example.com"
            mock_whois.return_value = whois_response
            
            checker = WHOISChecker()
            result = await checker.check_domain("unavailable-domain.com")
            
            assert result.result == CheckResult.UNAVAILABLE
            assert result.domain == "unavailable-domain.com"
            assert result.checker_type == "whois"
            assert "reason" in result.details
            assert result.details["reason"] == "has_status"

    @pytest.mark.asyncio
    async def test_whois_error(self):
        """Test handling WHOIS lookup errors."""
        with patch('whois.whois') as mock_whois:
            # Simulate PywhoisError indicating domain not found
            from whois.parser import PywhoisError
            mock_whois.side_effect = PywhoisError("No match for domain")
            
            checker = WHOISChecker()
            result = await checker.check_domain("error-domain.com")
            
            assert result.result == CheckResult.AVAILABLE
            assert result.domain == "error-domain.com"
            assert result.checker_type == "whois"
            assert "reason" in result.details
            assert result.details["reason"] == "whois_error_available"