"""
Scheduler jobs for domain monitoring.

File: domain-monitor/src/scheduler/jobs.py
"""
import asyncio
import logging
import time
from typing import Dict, List, Set, Callable, Awaitable

from src.config import settings

logger = logging.getLogger(__name__)


class DomainMonitorScheduler:
    """
    Scheduler for domain monitoring jobs.
    Manages the timing of domain checks based on priority and intervals.
    """
    
    def __init__(self) -> None:
        """Initialize the scheduler."""
        # Timing settings
        self.layer1_interval = settings.LAYER1_CHECK_INTERVAL
        self.layer2_interval = settings.LAYER2_CHECK_INTERVAL
        self.layer3_interval = settings.LAYER3_CHECK_INTERVAL
        self.domain_refresh_interval = settings.DOMAIN_API_REFRESH_INTERVAL
        
        # Tracking of last check times
        self.last_check_times: Dict[str, Dict[str, float]] = {}
        self.last_domain_refresh_time: float = 0.0
        
        # Keep track of in-progress domains
        self.in_progress: Set[str] = set()
    
    async def start(
        self,
        refresh_domains_callback: Callable[[], Awaitable[None]],
        check_domain_callbacks: Dict[str, Callable[[str], Awaitable[None]]],
        get_domains_callback: Callable[[], List[str]],
        get_high_priority_callback: Callable[[], Set[str]],
        get_domain_status_callback: Callable[[str], str],
    ) -> None:
        """
        Start the scheduler main loop.
        
        Args:
            refresh_domains_callback: Callback to refresh domain list
            check_domain_callbacks: Dict of callbacks for checking domains {'layer1': callback, ...}
            get_domains_callback: Callback to get current domain list
            get_high_priority_callback: Callback to get high priority domains
            get_domain_status_callback: Callback to get domain status
        """
        logger.info("Starting domain monitor scheduler")
        
        # Initial domain refresh
        await refresh_domains_callback()
        self.last_domain_refresh_time = time.time()
        
        # Main scheduling loop
        while True:
            try:
                current_time = time.time()
                tasks = []
                
                # Check if we need to refresh domains
                if current_time - self.last_domain_refresh_time >= self.domain_refresh_interval:
                    tasks.append(refresh_domains_callback())
                    self.last_domain_refresh_time = current_time
                
                # Schedule domain checks based on priority and intervals
                domains = get_domains_callback()
                high_priority_domains = get_high_priority_callback()
                
                for domain in domains:
                    # Skip domains currently being checked
                    if domain in self.in_progress:
                        continue
                    
                    # Get last check times
                    last_times = self.last_check_times.get(domain, {})
                    last_layer1 = last_times.get("layer1", 0)
                    last_layer2 = last_times.get("layer2", 0)
                    last_layer3 = last_times.get("layer3", 0)
                    
                    # Determine if domain should be checked based on priority and intervals
                    is_high_priority = domain in high_priority_domains
                    
                    # Layer 1 checks (most frequent)
                    if current_time - last_layer1 >= (self.layer1_interval / 2 if is_high_priority else self.layer1_interval):
                        tasks.append(self._run_check(domain, "layer1", check_domain_callbacks["layer1"]))
                    
                    # Layer 2 checks (less frequent, only if Layer 1 suggests availability)
                    domain_status = get_domain_status_callback(domain)
                    if (current_time - last_layer2 >= self.layer2_interval and 
                        domain_status == "possibly_available"):
                        tasks.append(self._run_check(domain, "layer2", check_domain_callbacks["layer2"]))
                    
                    # Layer 3 checks (least frequent, only if Layer 2 confirms potential availability)
                    if (current_time - last_layer3 >= self.layer3_interval and 
                        domain_status == "likely_available"):
                        tasks.append(self._run_check(domain, "layer3", check_domain_callbacks["layer3"]))
                
                if tasks:
                    # Run checks concurrently
                    await asyncio.gather(*tasks)
                
                # Sleep a short time before next iteration
                await asyncio.sleep(10)
                
            except Exception as e:
                logger.error(f"Error in scheduler cycle: {str(e)}", exc_info=True)
                await asyncio.sleep(30)  # Wait a bit longer on errors
    
    async def _run_check(
        self, 
        domain: str, 
        layer: str, 
        check_callback: Callable[[str], Awaitable[None]]
    ) -> None:
        """
        Run a domain check and update timing information.
        
        Args:
            domain: Domain to check
            layer: Layer name ('layer1', 'layer2', 'layer3')
            check_callback: Callback function to perform the check
        """
        if domain in self.in_progress:
            return
            
        self.in_progress.add(domain)
        try:
            # Update last check time
            self.last_check_times.setdefault(domain, {})[layer] = time.time()
            
            # Run the check
            await check_callback(domain)
            
        except Exception as e:
            logger.error(f"Error in {layer} check for {domain}: {str(e)}", exc_info=True)
        finally:
            self.in_progress.remove(domain)