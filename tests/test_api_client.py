# File: domain-monitor/tests/test_api_client.py

import json
import pytest
from unittest.mock import patch, MagicMock

import httpx

from src.api.client import APIClient
from src.config import settings


class TestAPIClient:
    """Tests for the APIClient class."""

    @pytest.mark.asyncio
    async def test_send_check_result_success(self, mock_check_data, mock_httpx_response):
        """Test successful API call to send check result."""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value = mock_httpx_response
            
            client = APIClient()
            # Disable retries for test
            client.max_retries = 1
            
            response = await client.send_check_result(mock_check_data)
            
            assert response == {"status": "success"}
            mock_post.assert_called_once()
            
            # Verify the call arguments
            args, kwargs = mock_post.call_args
            assert kwargs['headers']['Authorization'] == f"Bearer {client.auth_token}"
            assert kwargs['headers']['Content-Type'] == "application/json"
            
            # Verify payload
            payload = json.loads(kwargs['json'])
            assert payload['domain'] == mock_check_data.domain
            assert payload['check_type'] == mock_check_data.checker_type
            assert payload['result'] == mock_check_data.result.value

    @pytest.mark.asyncio
    async def test_send_check_result_retry(self, mock_check_data):
        """Test retry mechanism when API call fails."""
        with patch('httpx.AsyncClient.post') as mock_post, \
             patch('src.api.client.retry') as mock_retry:
            
            # Make retry execute immediately without waiting
            mock_retry.return_value = lambda f: f
            
            # First call fails, second succeeds
            mock_post.side_effect = [
                httpx.ConnectError("Connection error"),
                MagicMock(
                    status_code=200,
                    json=lambda: {"status": "success after retry"},
                    raise_for_status=lambda: None,
                    text="Success"
                )
            ]
            
            client = APIClient()
            response = await client.send_check_result(mock_check_data)
            
            assert mock_post.call_count == 2
            assert response == {"status": "success after retry"}

    @pytest.mark.asyncio
    async def test_send_available_domain_notification(self, mock_httpx_response):
        """Test sending notification for available domain."""
        with patch('httpx.AsyncClient.post') as mock_post:
            mock_post.return_value = mock_httpx_response
            
            client = APIClient()
            # Disable retries for test
            client.max_retries = 1
            
            domain = "available-domain.com"
            confidence = 0.95
            checks = {
                "timestamp": 1647854321.123,
                "checks": {
                    "dns": {
                        "result": "available",
                        "details": {}
                    },
                    "whois": {
                        "result": "available",
                        "details": {}
                    }
                }
            }
            
            response = await client.send_available_domain_notification(domain, confidence, checks)
            
            assert response == {"status": "success"}
            mock_post.assert_called_once()
            
            # Verify the call arguments
            args, kwargs = mock_post.call_args
            assert args[0] == settings.API_AVAILABLE_CALLBACK_URL
            assert kwargs['headers']['Authorization'] == f"Bearer {client.auth_token}"
            
            # Verify payload
            payload = json.loads(kwargs['json'])
            assert payload['domain'] == domain
            assert payload['status'] == "available"
            assert payload['confidence'] == confidence
            assert 'checks' in payload

    @pytest.mark.asyncio
    async def test_handle_json_decode_error(self, mock_check_data):
        """Test handling invalid JSON response."""
        with patch('httpx.AsyncClient.post') as mock_post:
            # Return non-JSON response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "Not a JSON response"
            mock_response.raise_for_status.return_value = None
            mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "Not a JSON response", 0)
            mock_post.return_value = mock_response
            
            client = APIClient()
            # Disable retries for test
            client.max_retries = 1
            
            response = await client.send_check_result(mock_check_data)
            
            assert response["status"] == "success"
            assert response["raw_response"] == "Not a JSON response"