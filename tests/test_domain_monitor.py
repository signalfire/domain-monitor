# File: domain-monitor/tests/test_domain_monitor.py

import pytest
from unittest.mock import MagicMock, patch

from src.checkers.base import CheckData, CheckResult
from src.domain_monitor import DomainMonitor


class TestDomainMonitor:
    """Tests for the DomainMonitor class."""

    @pytest.fixture
    def mock_monitor(self):
        """Fixture that provides a configured DomainMonitor instance with mocks."""
        with patch('src.domain_monitor.DNSChecker') as mock_dns_checker, \
             patch('src.domain_monitor.WHOISChecker') as mock_whois_checker, \
             patch('src.domain_monitor.APIClient') as mock_api_client, \
             patch('src.domain_monitor.DomainAPIClient') as mock_domain_api_client, \
             patch('src.domain_monitor.DomainMonitorScheduler') as mock_scheduler:
            
            # Setup mock checkers
            dns_checker_instance = MagicMock()
            whois_checker_instance = MagicMock()
            mock_dns_checker.return_value = dns_checker_instance
            mock_whois_checker.return_value = whois_checker_instance
            
            # Setup mock domain API client
            domain_api_client_instance = MagicMock()
            domain_api_client_instance.fetch_domains.return_value = (
                ["example.com", "example.org"], 
                {"example.com"}
            )
            mock_domain_api_client.return_value = domain_api_client_instance
            
            # Setup mock scheduler
            scheduler_instance = MagicMock()
            mock_scheduler.return_value = scheduler_instance
            
            # Create monitor instance
            monitor = DomainMonitor()
            
            # Initialize domains manually for tests
            monitor.domains = ["example.com", "example.org"]
            monitor.high_priority_domains = {"example.com"}
            
            # Expose mocks for assertions
            monitor.mock_dns_checker = dns_checker_instance
            monitor.mock_whois_checker = whois_checker_instance
            monitor.mock_api_client = monitor.api_client
            monitor.mock_domain_api_client = monitor.domain_api_client
            monitor.mock_scheduler = monitor.scheduler
            
            yield monitor

    @pytest.mark.asyncio
    async def test_update_domains(self, mock_monitor):
        """Test updating domains from API."""
        # Setup mock to return new domain list
        mock_monitor.mock_domain_api_client.fetch_domains.return_value = (
            ["example.com", "example.org", "newdomain.com"],
            {"example.com", "newdomain.com"}
        )
        
        # Update domains
        await mock_monitor._update_domains(force=True)
        
        # Verify domain API client was called
        mock_monitor.mock_domain_api_client.fetch_domains.assert_called_once_with(force=True)
        
        # Verify domains were updated
        assert "newdomain.com" in mock_monitor.domains
        assert "newdomain.com" in mock_monitor.high_priority_domains
        assert len(mock_monitor.domains) == 3
        
        # Verify domain status was initialized for new domain
        assert "newdomain.com" in mock_monitor.domain_status
        assert mock_monitor.domain_status["newdomain.com"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_update_domains_error_handling(self, mock_monitor):
        """Test error handling when updating domains from API."""
        # Setup mock to raise exception
        mock_monitor.mock_domain_api_client.fetch_domains.side_effect = Exception("API error")
        
        # Store original domains
        original_domains = mock_monitor.domains.copy()
        
        # Update domains (should handle error gracefully)
        await mock_monitor._update_domains(force=True)
        
        # Verify domain API client was called
        mock_monitor.mock_domain_api_client.fetch_domains.assert_called_once_with(force=True)
        
        # Verify domains were not changed due to error
        assert mock_monitor.domains == original_domains

    @pytest.mark.asyncio
    async def test_check_domain_layer1(self, mock_monitor):
        """Test Layer 1 domain checking."""
        domain = "example.com"
        
        # Configure mock DNS checker
        check_data = CheckData(
            domain=domain,
            result=CheckResult.AVAILABLE,
            timestamp=1647854321.123,
            checker_type="dns",
            details={"nxdomain": True},
            duration_ms=123,
            error=None
        )
        mock_monitor.mock_dns_checker.check_domain.return_value = check_data
        mock_monitor.checkers["layer1"]["dns"] = mock_monitor.mock_dns_checker
        
        # Run the check
        await mock_monitor.check_domain_layer1(domain)
        
        # Verify DNS checker was called
        mock_monitor.mock_dns_checker.check_domain.assert_called_once_with(domain)
        
        # Verify API client was called
        mock_monitor.mock_api_client.send_check_result.assert_called_once()
        
        # Verify domain status was updated
        assert domain in mock_monitor.domain_status
        assert mock_monitor.domain_status[domain]["status"] == "possibly_available"
        
        # Verify last check time was updated
        assert domain in mock_monitor.last_check_times
        assert "layer1" in mock_monitor.last_check_times[domain]

    @pytest.mark.asyncio
    async def test_check_domain_layer3(self, mock_monitor):
        """Test Layer 3 domain checking."""
        domain = "example.com"
        
        # Configure mock WHOIS checker
        check_data = CheckData(
            domain=domain,
            result=CheckResult.AVAILABLE,
            timestamp=1647854321.123,
            checker_type="whois",
            details={"reason": "available_pattern_match"},
            duration_ms=123,
            error=None
        )
        mock_monitor.mock_whois_checker.check_domain.return_value = check_data
        mock_monitor.checkers["layer3"]["whois"] = mock_monitor.mock_whois_checker
        
        # Setup domain status for testing
        mock_monitor.domain_status[domain] = {
            "status": "likely_available",
            "last_updated": 1647854321.123,
            "checks": {},
        }
        
        # Initialize cache for calculation
        mock_monitor.check_cache[domain] = {
            "dns": CheckData(
                domain=domain,
                result=CheckResult.AVAILABLE,
                timestamp=1647854321.123,
                checker_type="dns",
                details={},
                duration_ms=123,
                error=None
            ),
            "whois": check_data
        }
        
        # Configure API client
        mock_monitor.mock_api_client.send_available_domain_notification.return_value = {"status": "success"}
        
        # Run the check
        await mock_monitor.check_domain_layer3(domain)
        
        # Verify WHOIS checker was called
        mock_monitor.mock_whois_checker.check_domain.assert_called_once_with(domain)
        
        # Verify API client was called twice (check result + available notification)
        assert mock_monitor.mock_api_client.send_check_result.call_count == 1
        assert mock_monitor.mock_api_client.send_available_domain_notification.call_count == 1
        
        # Verify domain status was updated to available
        assert domain in mock_monitor.domain_status
        assert mock_monitor.domain_status[domain]["status"] == "available"
        assert "confidence" in mock_monitor.domain_status[domain]
        
        # Verify last check time was updated
        assert domain in mock_monitor.last_check_times
        assert "layer3" in mock_monitor.last_check_times[domain]

    def test_calculate_availability_score(self, mock_monitor):
        """Test availability score calculation."""
        domain = "example.com"
        
        # Create test check results
        results = [
            ("dns", CheckData(
                domain=domain,
                result=CheckResult.AVAILABLE,
                timestamp=1647854321.123,
                checker_type="dns",
                details={},
                duration_ms=123,
                error=None
            )),
            ("http", CheckData(
                domain=domain,
                result=CheckResult.UNKNOWN,
                timestamp=1647854321.123,
                checker_type="http",
                details={},
                duration_ms=123,
                error=None
            ))
        ]
        
        # Calculate score
        score = mock_monitor._calculate_availability_score(domain, results, "layer1")
        
        # DNS is available (1.0), HTTP is unknown (0.5)
        # With weights DNS=0.3, HTTP=0.2, expected score is:
        # (0.3 * 1.0 + 0.2 * 0.5) / (0.3 + 0.2) = 0.8
        assert score > 0.7
        assert score < 0.9# File: domain-monitor/tests/test_domain_monitor.py

import pytest
from unittest.mock import MagicMock, patch

from src.checkers.base import CheckData, CheckResult
from src.domain_monitor import DomainMonitor


class TestDomainMonitor:
    """Tests for the DomainMonitor class."""

    @pytest.fixture
    def mock_monitor(self):
        """Fixture that provides a configured DomainMonitor instance with mocks."""
        with patch('src.domain_monitor.DNSChecker') as mock_dns_checker, \
             patch('src.domain_monitor.WHOISChecker') as mock_whois_checker, \
             patch('src.domain_monitor.APIClient') as mock_api_client:
            
            # Setup mock checkers
            dns_checker_instance = MagicMock()
            whois_checker_instance = MagicMock()
            mock_dns_checker.return_value = dns_checker_instance
            mock_whois_checker.return_value = whois_checker_instance
            
            # Create monitor instance
            monitor = DomainMonitor()
            
            # Expose mocks for assertions
            monitor.mock_dns_checker = dns_checker_instance
            monitor.mock_whois_checker = whois_checker_instance
            monitor.mock_api_client = monitor.api_client
            
            yield monitor

    @pytest.mark.asyncio
    async def test_check_domain_layer1(self, mock_monitor):
        """Test Layer 1 domain checking."""
        domain = "example.com"
        
        # Configure mock DNS checker
        check_data = CheckData(
            domain=domain,
            result=CheckResult.AVAILABLE,
            timestamp=1647854321.123,
            checker_type="dns",
            details={"nxdomain": True},
            duration_ms=123,
            error=None
        )
        mock_monitor.mock_dns_checker.check_domain.return_value = check_data
        mock_monitor.checkers["layer1"]["dns"] = mock_monitor.mock_dns_checker
        
        # Run the check
        await mock_monitor.check_domain_layer1(domain)
        
        # Verify DNS checker was called
        mock_monitor.mock_dns_checker.check_domain.assert_called_once_with(domain)
        
        # Verify API client was called
        mock_monitor.mock_api_client.send_check_result.assert_called_once()
        
        # Verify domain status was updated
        assert domain in mock_monitor.domain_status
        assert mock_monitor.domain_status[domain]["status"] == "possibly_available"
        
        # Verify last check time was updated
        assert domain in mock_monitor.last_check_times
        assert "layer1" in mock_monitor.last_check_times[domain]

    @pytest.mark.asyncio
    async def test_check_domain_layer3(self, mock_monitor):
        """Test Layer 3 domain checking."""
        domain = "example.com"
        
        # Configure mock WHOIS checker
        check_data = CheckData(
            domain=domain,
            result=CheckResult.AVAILABLE,
            timestamp=1647854321.123,
            checker_type="whois",
            details={"reason": "available_pattern_match"},
            duration_ms=123,
            error=None
        )
        mock_monitor.mock_whois_checker.check_domain.return_value = check_data
        mock_monitor.checkers["layer3"]["whois"] = mock_monitor.mock_whois_checker
        
        # Setup domain status for testing
        mock_monitor.domain_status[domain] = {
            "status": "likely_available",
            "last_updated": 1647854321.123,
            "checks": {},
        }
        
        # Initialize cache for calculation
        mock_monitor.check_cache[domain] = {
            "dns": CheckData(
                domain=domain,
                result=CheckResult.AVAILABLE,
                timestamp=1647854321.123,
                checker_type="dns",
                details={},
                duration_ms=123,
                error=None
            ),
            "whois": check_data
        }
        
        # Configure API client
        mock_monitor.mock_api_client.send_available_domain_notification.return_value = {"status": "success"}
        
        # Run the check
        await mock_monitor.check_domain_layer3(domain)
        
        # Verify WHOIS checker was called
        mock_monitor.mock_whois_checker.check_domain.assert_called_once_with(domain)
        
        # Verify API client was called twice (check result + available notification)
        assert mock_monitor.mock_api_client.send_check_result.call_count == 1
        assert mock_monitor.mock_api_client.send_available_domain_notification.call_count == 1
        
        # Verify domain status was updated to available
        assert domain in mock_monitor.domain_status
        assert mock_monitor.domain_status[domain]["status"] == "available"
        assert "confidence" in mock_monitor.domain_status[domain]
        
        # Verify last check time was updated
        assert domain in mock_monitor.last_check_times
        assert "layer3" in mock_monitor.last_check_times[domain]

    def test_calculate_availability_score(self, mock_monitor):
        """Test availability score calculation."""
        domain = "example.com"
        
        # Create test check results
        results = [
            ("dns", CheckData(
                domain=domain,
                result=CheckResult.AVAILABLE,
                timestamp=1647854321.123,
                checker_type="dns",
                details={},
                duration_ms=123,
                error=None
            )),
            ("http", CheckData(
                domain=domain,
                result=CheckResult.UNKNOWN,
                timestamp=1647854321.123,
                checker_type="http",
                details={},
                duration_ms=123,
                error=None
            ))
        ]
        
        # Calculate score
        score = mock_monitor._calculate_availability_score(domain, results, "layer1")
        
        # DNS is available (1.0), HTTP is unknown (0.5)
        # With weights DNS=0.3, HTTP=0.2, expected score is:
        # (0.3 * 1.0 + 0.2 * 0.5) / (0.3 + 0.2) = 0.8
        assert score > 0.7
        assert score < 0.9