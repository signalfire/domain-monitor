# File: domain-monitor/tests/test_domain_api_client.py

import json
import pytest
import time
from unittest.mock import patch, MagicMock


from src.api.domain_api_client import DomainAPIClient


class TestDomainAPIClient:
    """Tests for the DomainAPIClient class."""

    @pytest.mark.asyncio
    async def test_fetch_domains_success(self, mock_httpx_response):
        """Test successful API call to fetch domains."""
        # Configure mock response
        mock_httpx_response.json.return_value = {
            "domains": [
                {"domain": "example.com", "priority": True},
                {"domain": "example.org", "priority": False},
                "example.net"
            ]
        }
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.return_value = mock_httpx_response
            
            client = DomainAPIClient()
            # Force refresh regardless of time
            client.last_fetch_time = 0
            
            domains, priority_domains = await client.fetch_domains()
            
            # Verify the correct domains were parsed
            assert len(domains) == 3
            assert "example.com" in domains
            assert "example.org" in domains
            assert "example.net" in domains
            
            # Verify priority domains
            assert len(priority_domains) == 1
            assert "example.com" in priority_domains
            
            # Verify the API was called with correct parameters
            mock_get.assert_called_once()
            args, kwargs = mock_get.call_args
            assert kwargs['headers']['Authorization'].startswith("Bearer ")
            assert kwargs['headers']['Content-Type'] == "application/json"

    @pytest.mark.asyncio
    async def test_fetch_domains_empty_response(self, mock_httpx_response):
        """Test handling of empty API response."""
        # Configure mock response
        mock_httpx_response.json.return_value = {"domains": []}
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.return_value = mock_httpx_response
            
            client = DomainAPIClient()
            client.last_fetch_time = 0
            
            domains, priority_domains = await client.fetch_domains()
            
            # Verify empty results
            assert len(domains) == 0
            assert len(priority_domains) == 0

    @pytest.mark.asyncio
    async def test_fetch_domains_invalid_json(self, mock_httpx_response):
        """Test handling of invalid JSON response."""
        # Configure mock response to raise JSONDecodeError
        mock_httpx_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "not json", 0)
        mock_httpx_response.text = "not json"
        
        with patch('httpx.AsyncClient.get') as mock_get:
            mock_get.return_value = mock_httpx_response
            
            client = DomainAPIClient()
            client.last_fetch_time = 0
            
            domains, priority_domains = await client.fetch_domains()
            
            # Verify empty results on error
            assert len(domains) == 0
            assert len(priority_domains) == 0

    @pytest.mark.asyncio
    async def test_fetch_domains_respects_refresh_interval(self):
        """Test that fetch_domains respects the refresh interval."""
        with patch('httpx.AsyncClient.get') as mock_get:
            client = DomainAPIClient()
            
            # Set last fetch time to now
            client.last_fetch_time = time.time()
            # Set a long refresh interval
            client.refresh_interval = 3600  # 1 hour
            
            # Should skip API call due to refresh interval
            domains, priority_domains = await client.fetch_domains(force=False)
            
            # Verify API was not called
            mock_get.assert_not_called()
            assert len(domains) == 0
            
            # Now force refresh
            mock_get.return_value = MagicMock(
                json=lambda: {"domains": ["example.com"]},
                raise_for_status=lambda: None
            )
            
            domains, priority_domains = await client.fetch_domains(force=True)
            
            # Verify API was called
            mock_get.assert_called_once()
            assert len(domains) == 1

    @pytest.mark.asyncio
    async def test_parse_domains_different_formats(self):
        """Test parsing different domain formats in the response."""
        client = DomainAPIClient()
        
        # Test with mixed formats
        data = {
            "domains": [
                {"domain": "example.com", "priority": True},
                {"domain": "example.org"},  # No priority specified
                "example.net",              # String format
                {"domain": "  spaced.com  ", "priority": True}  # With whitespace
            ]
        }
        
        domains, priority_domains = client._parse_domains_response(data)
        
        # Verify correct parsing
        assert len(domains) == 4
        assert "example.com" in domains
        assert "example.org" in domains
        assert "example.net" in domains
        assert "spaced.com" in domains  # Should be trimmed
        
        # Verify priority domains
        assert len(priority_domains) == 2
        assert "example.com" in priority_domains
        assert "spaced.com" in priority_domains
        assert "example.org" not in priority_domains
        assert "example.net" not in priority_domains