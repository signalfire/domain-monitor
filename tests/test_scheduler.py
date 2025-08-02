# File: domain-monitor/tests/test_scheduler.py

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from src.scheduler.jobs import DomainMonitorScheduler


class TestDomainMonitorScheduler:
    """Tests for the DomainMonitorScheduler class."""

    @pytest.fixture
    def scheduler(self):
        """Create a scheduler instance for testing."""
        scheduler = DomainMonitorScheduler()
        # Set shorter intervals for testing
        scheduler.layer1_interval = 10
        scheduler.layer2_interval = 20
        scheduler.layer3_interval = 30
        scheduler.domain_refresh_interval = 15
        return scheduler
    
    @pytest.mark.asyncio
    async def test_run_check(self, scheduler):
        """Test the _run_check method."""
        # Setup test domain and mocks
        domain = "example.com"
        layer = "layer1"
        mock_callback = AsyncMock()
        
        # Run the check
        await scheduler._run_check(domain, layer, mock_callback)
        
        # Verify callback was called
        mock_callback.assert_called_once_with(domain)
        
        # Verify last check time was updated
        assert domain in scheduler.last_check_times
        assert layer in scheduler.last_check_times[domain]
        
        # Verify domain was added and removed from in_progress
        assert domain not in scheduler.in_progress
    
    @pytest.mark.asyncio
    async def test_run_check_error_handling(self, scheduler):
        """Test error handling in _run_check method."""
        # Setup test domain and failing callback
        domain = "example.com"
        layer = "layer1"
        mock_callback = AsyncMock(side_effect=Exception("Test exception"))
        
        # Run the check (should not raise exception)
        await scheduler._run_check(domain, layer, mock_callback)
        
        # Verify callback was called
        mock_callback.assert_called_once_with(domain)
        
        # Verify last check time was still updated
        assert domain in scheduler.last_check_times
        assert layer in scheduler.last_check_times[domain]
        
        # Verify domain was removed from in_progress despite error
        assert domain not in scheduler.in_progress
    
    @pytest.mark.asyncio
    async def test_start_scheduling_logic(self, scheduler):
        """Test the scheduling logic in start method."""
        # Mock callbacks
        refresh_domains = AsyncMock()
        check_callbacks = {
            "layer1": AsyncMock(),
            "layer2": AsyncMock(),
            "layer3": AsyncMock(),
        }
        
        # Mock domain management functions
        domains = ["example.com", "example.org"]
        high_priority = {"example.com"}
        
        get_domains = MagicMock(return_value=domains)
        get_high_priority = MagicMock(return_value=high_priority)
        
        # Configure domain statuses
        domain_statuses = {
            "example.com": "possibly_available",
            "example.org": "likely_available"
        }
        get_domain_status = MagicMock(side_effect=lambda d: domain_statuses.get(d, "unknown"))
        
        # Patch asyncio.sleep to avoid actual waiting and exit after one iteration
        with patch('asyncio.sleep', new=AsyncMock()) as mock_sleep:
            # Make sleep exit the loop after first call
            mock_sleep.side_effect = [None, asyncio.CancelledError]
            
            try:
                # Start the scheduler - should run one iteration and then raise CancelledError
                await scheduler.start(
                    refresh_domains_callback=refresh_domains,
                    check_domain_callbacks=check_callbacks,
                    get_domains_callback=get_domains,
                    get_high_priority_callback=get_high_priority,
                    get_domain_status_callback=get_domain_status
                )
            except asyncio.CancelledError:
                pass
            
            # Verify refresh_domains was called
            refresh_domains.assert_called_once()
            
            # Check if appropriate layer checks were scheduled based on domain status
            check_callbacks["layer1"].assert_called()  # Should be called for all domains
            check_callbacks["layer2"].assert_called_with("example.com")  # Should be called for "possibly_available"
            check_callbacks["layer3"].assert_called_with("example.org")  # Should be called for "likely_available"