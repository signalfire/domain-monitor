# File: domain-monitor/tests/conftest.py

import asyncio
import pytest
from unittest.mock import MagicMock

from src.checkers.base import CheckData, CheckResult
from src.config import Settings


@pytest.fixture
def mock_settings():
    """Fixture that provides test settings."""
    return Settings(
        APP_NAME="domain-monitor-test",
        APP_VERSION="0.1.0-test",
        LOG_LEVEL="DEBUG",
        SENTRY_DSN=None,
        SENTRY_ENVIRONMENT="test",
        API_CALLBACK_URL="https://api.example.com/callback",
        API_AUTH_TOKEN="test-token",
        API_TIMEOUT=1,
        API_MAX_RETRIES=1,
        DOMAINS_TO_MONITOR=["example.com", "example.org"],
        HIGH_PRIORITY_DOMAINS=["example.com"],
        LAYER1_CHECK_INTERVAL=60,
        LAYER2_CHECK_INTERVAL=120,
        LAYER3_CHECK_INTERVAL=240,
        DNS_CHECKS_PER_MINUTE=10,
        HTTP_CHECKS_PER_MINUTE=10,
        REGISTRAR_CHECKS_PER_MINUTE=5,
        RDAP_CHECKS_PER_MINUTE=5,
        WHOIS_CHECKS_PER_MINUTE=2,
    )


@pytest.fixture
def mock_check_data():
    """Fixture that provides sample check data."""
    return CheckData(
        domain="example.com",
        result=CheckResult.AVAILABLE,
        timestamp=1647854321.123,
        checker_type="test_checker",
        details={"test_key": "test_value"},
        duration_ms=123,
        error=None
    )


@pytest.fixture
def mock_httpx_response():
    """Fixture that provides a mock HTTPX response."""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"status": "success"}
    response.raise_for_status.return_value = None
    response.text = '{"status": "success"}'
    return response


@pytest.fixture
def event_loop():
    """Create an instance of the default event loop for each test."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()