"""
Main domain monitoring service that implements the hybrid checking approach.

File: domain-monitor/src/domain_monitor.py
"""
import asyncio
import logging
import time
from typing import Dict, List, Any, Set, Tuple

from src.checkers.base import CheckResult, CheckData
from src.checkers.dns_checker import DNSChecker
from src.checkers.http_checker import HTTPChecker
from src.checkers.whois_checker import WHOISChecker
# Import other checkers as needed
from src.api.client import APIClient
from src.api.domain_api_client import DomainAPIClient
from src.scheduler.jobs import DomainMonitorScheduler
from src.utils.persistence import state_persistence
from src.utils.metrics import metrics_collector
from src.config import settings

# Set up logging
logger = logging.getLogger(__name__)


class DomainMonitor:
    """
    Domain monitoring service that implements a hybrid checking approach.
    
    The service follows a 3-layer approach:
    - Layer 1: Fast preliminary checks (DNS, HTTP)
    - Layer 2: Intermediate verification (RDAP, Registrar API)
    - Layer 3: Deep verification (WHOIS)
    """
    
    def __init__(self) -> None:
        """Initialize the domain monitoring service."""
        # Initialize all checkers
        self.checkers = {
            "layer1": {
                "dns": DNSChecker(),
                "http": HTTPChecker(),  # Include HTTP checker
            },
            "layer2": {
                # Add RDAP and Registrar checkers
            },
            "layer3": {
                "whois": WHOISChecker(),
            }
        }
        
        # Initialize API clients
        self.api_client = APIClient()
        self.domain_api_client = DomainAPIClient()
        
        # Initialize scheduler
        self.scheduler = DomainMonitorScheduler()
        
        # Domain tracking
        self.domains: List[str] = []
        self.high_priority_domains: Set[str] = set()
        self.domain_status: Dict[str, Dict[str, Any]] = {}
        self.availability_scores: Dict[str, float] = {}
        self.last_check_times: Dict[str, Dict[str, float]] = {}
        
        # Track domains that are currently being checked
        self.in_progress: Set[str] = set()
        
        # Cache of check results
        self.check_cache: Dict[str, Dict[str, CheckData]] = {}
        
        # Load previous state if available
        self._load_persisted_state()
        
        # Initialize timing settings
        self.layer1_interval = settings.LAYER1_CHECK_INTERVAL
        self.layer2_interval = settings.LAYER2_CHECK_INTERVAL
        self.layer3_interval = settings.LAYER3_CHECK_INTERVAL
        
        # We'll set up the state persistence task in the start method
        self._state_persistence_task = None
        
        # Initialize metrics
        metrics_collector.set_counter("domains_total", len(self.domains))
        metrics_collector.set_counter("domains_high_priority", len(self.high_priority_domains))
    
    def _load_persisted_state(self) -> None:
        """Load previously saved state if available."""
        state = state_persistence.load_state()
        if state:
            self.domains = state.get("domains", [])
            self.high_priority_domains = state.get("high_priority_domains", set())
            self.domain_status = state.get("domain_status", {})
            self.last_check_times = state.get("last_check_times", {})
            logger.info(f"Restored {len(self.domains)} domains from saved state")
    
    async def _periodic_state_saving(self) -> None:
        """Periodically save state."""
        try:
            while True:
                await asyncio.sleep(300)  # Save every 5 minutes
                self._save_state()
                logger.debug("Periodic state save completed")
        except asyncio.CancelledError:
            logger.info("State persistence task cancelled")
            # Save state one last time before exiting
            self._save_state(force=True)
            raise
        except Exception as e:
            logger.error(f"Error in periodic state saving: {str(e)}", exc_info=True)
    
    def _save_state(self, force: bool = False) -> None:
        """Save current state."""
        state_persistence.save_state(
            domains=self.domains,
            high_priority_domains=self.high_priority_domains,
            domain_status=self.domain_status,
            last_check_times=self.last_check_times,
            force=force
        )
    
    async def start(self) -> None:
        """Start the domain monitoring service."""
        logger.info("Starting domain monitoring service")
        metrics_collector.increment("service_starts")
        
        # Start the state persistence task
        self._state_persistence_task = asyncio.create_task(self._periodic_state_saving())
        
        # Initial fetch of domains from API
        await self.update_domains(force=True)
        
        if not self.domains:
            logger.warning("No domains to monitor. Will try again in next cycle.")
            metrics_collector.increment("empty_domain_list")
        
        try:
            # Start the scheduler with appropriate callbacks
            await self.scheduler.start(
                refresh_domains_callback=lambda: self.update_domains(force=False),
                check_domain_callbacks={
                    "layer1": self.check_domain_layer1,
                    "layer2": self.check_domain_layer2,
                    "layer3": self.check_domain_layer3,
                },
                get_domains_callback=lambda: self.domains,
                get_high_priority_callback=lambda: self.high_priority_domains,
                get_domain_status_callback=lambda domain: self.domain_status.get(domain, {}).get("status", "unknown"),
            )
        except asyncio.CancelledError:
            logger.info("Domain monitor cancelled")
            
            # Save state before exiting
            self._save_state(force=True)
            
            # Cancel state persistence task
            if self._state_persistence_task:
                self._state_persistence_task.cancel()
                try:
                    await self._state_persistence_task
                except asyncio.CancelledError:
                    pass
            
            raise
    
    async def update_domains(self, force: bool = False) -> None:
        """
        Update domains to monitor from API.
        
        Args:
            force: Force update even if refresh interval hasn't elapsed
        """
        timer_id = metrics_collector.start_timer("domain_api_fetch")
        try:
            # Fetch domains from API
            new_domains, new_high_priority = await self.domain_api_client.fetch_domains(force=force)
            
            metrics_collector.stop_timer("domain_api_fetch", timer_id)
            
            if not new_domains:
                # If we couldn't get new domains but have existing ones, keep using them
                if self.domains:
                    logger.warning("Failed to fetch new domains, continuing with existing domains")
                    metrics_collector.increment("domain_api_empty_response")
                    return
                logger.error("Failed to fetch domains from API and no existing domains")
                metrics_collector.increment("domain_api_no_domains")
                return
            
            # Check for new domains that weren't being monitored before
            new_added = [d for d in new_domains if d not in self.domains]
            removed = [d for d in self.domains if d not in new_domains]
            
            if new_added:
                logger.info(f"Adding {len(new_added)} new domains to monitor: {', '.join(new_added)}")
                metrics_collector.increment("domains_added", len(new_added))
                
                # Initialize tracking for new domains
                for domain in new_added:
                    self.domain_status[domain] = {
                        "status": "unknown",
                        "last_updated": time.time(),
                        "checks": {},
                    }
            
            if removed:
                logger.info(f"Removing {len(removed)} domains from monitoring: {', '.join(removed)}")
                metrics_collector.increment("domains_removed", len(removed))
            
            # Update domain lists
            self.domains = new_domains
            self.high_priority_domains = new_high_priority
            
            # Update metrics
            metrics_collector.set_counter("domains_total", len(self.domains))
            metrics_collector.set_counter("domains_high_priority", len(self.high_priority_domains))
            
            available_domains = [d for d in self.domains 
                               if self.domain_status.get(d, {}).get("status") == "available"]
            metrics_collector.update_domain_stats(
                domains=self.domains,
                high_priority=self.high_priority_domains,
                available=available_domains
            )
            
            logger.info(f"Now monitoring {len(self.domains)} domains ({len(self.high_priority_domains)} high priority)")
            
        except Exception as e:
            metrics_collector.increment("domain_api_errors")
            logger.error(f"Error updating domains: {str(e)}", exc_info=True)
    
    async def check_domain_layer1(self, domain: str) -> None:
        """
        Perform Layer 1 (fast) checks for a domain.
        
        Args:
            domain: Domain to check
        """
        if domain in self.in_progress:
            metrics_collector.increment("check_skipped_in_progress")
            return
        
        metrics_collector.increment("check_layer1")
        self.in_progress.add(domain)
        timer_id = metrics_collector.start_timer("check_layer1_total")
        
        try:
            logger.debug(f"Running Layer 1 checks for {domain}")
            
            # Update last check time
            self.last_check_times.setdefault(domain, {})["layer1"] = time.time()
            
            # Run all Layer 1 checkers concurrently
            check_tasks = []
            for checker_name, checker in self.checkers["layer1"].items():
                check_tasks.append(self._run_checker(domain, checker, "layer1", checker_name))
            
            results = await asyncio.gather(*check_tasks)
            
            # Calculate availability score for Layer 1
            score = self._calculate_availability_score(domain, results, "layer1")
            
            # Update domain status based on Layer 1 score
            old_status = self.domain_status.get(domain, {}).get("status", "unknown")
            
            if score >= 0.7:  # High confidence from Layer 1
                self.domain_status[domain]["status"] = "possibly_available"
                logger.info(f"Domain {domain} possibly available (Layer 1 score: {score:.2f})")
                metrics_collector.increment("possibly_available_domains")
                
                if old_status != "possibly_available":
                    metrics_collector.increment("status_changes")
                
                # Trigger Layer 2 check immediately for high confidence
                if score >= 0.9:
                    metrics_collector.increment("high_confidence_layer1")
                    await self.check_domain_layer2(domain)
            else:
                self.domain_status[domain]["status"] = "likely_unavailable"
                
                if old_status != "likely_unavailable":
                    metrics_collector.increment("status_changes")
            
        except Exception as e:
            metrics_collector.increment("check_layer1_errors")
            logger.error(f"Error in Layer 1 check for {domain}: {str(e)}", exc_info=True)
        finally:
            metrics_collector.stop_timer("check_layer1_total", timer_id)
            self.in_progress.remove(domain)
    
    async def check_domain_layer2(self, domain: str) -> None:
        """
        Perform Layer 2 (intermediate) checks for a domain.
        
        Args:
            domain: Domain to check
        """
        if domain in self.in_progress:
            metrics_collector.increment("check_skipped_in_progress")
            return
            
        metrics_collector.increment("check_layer2")
        self.in_progress.add(domain)
        timer_id = metrics_collector.start_timer("check_layer2_total")
        
        try:
            logger.debug(f"Running Layer 2 checks for {domain}")
            
            # Update last check time
            self.last_check_times.setdefault(domain, {})["layer2"] = time.time()
            
            # Run all Layer 2 checkers concurrently
            check_tasks = []
            for checker_name, checker in self.checkers["layer2"].items():
                check_tasks.append(self._run_checker(domain, checker, "layer2", checker_name))
            
            results = await asyncio.gather(*check_tasks)
            
            # If no Layer 2 checkers are implemented yet, we'll skip to Layer 3
            if not results:
                metrics_collector.increment("no_layer2_checkers")
                self.domain_status[domain]["status"] = "likely_available"
                await self.check_domain_layer3(domain)
                return
            
            # Calculate availability score for Layer 2
            score = self._calculate_availability_score(domain, results, "layer2")
            
            # Update domain status based on Layer 2 score
            old_status = self.domain_status.get(domain, {}).get("status", "unknown")
            
            if score >= 0.6:  # Decent confidence from Layer 2
                self.domain_status[domain]["status"] = "likely_available"
                logger.info(f"Domain {domain} likely available (Layer 2 score: {score:.2f})")
                metrics_collector.increment("likely_available_domains")
                
                if old_status != "likely_available":
                    metrics_collector.increment("status_changes")
                
                # Trigger Layer 3 check immediately for high confidence
                if score >= 0.8:
                    metrics_collector.increment("high_confidence_layer2")
                    await self.check_domain_layer3(domain)
            else:
                self.domain_status[domain]["status"] = "likely_unavailable"
                
                if old_status != "likely_unavailable":
                    metrics_collector.increment("status_changes")
            
        except Exception as e:
            metrics_collector.increment("check_layer2_errors")
            logger.error(f"Error in Layer 2 check for {domain}: {str(e)}", exc_info=True)
        finally:
            metrics_collector.stop_timer("check_layer2_total", timer_id)
            self.in_progress.remove(domain)
    
    async def check_domain_layer3(self, domain: str) -> None:
        """
        Perform Layer 3 (deep) checks for a domain.
        
        Args:
            domain: Domain to check
        """
        if domain in self.in_progress:
            metrics_collector.increment("check_skipped_in_progress")
            return
            
        metrics_collector.increment("check_layer3")
        self.in_progress.add(domain)
        timer_id = metrics_collector.start_timer("check_layer3_total")
        
        try:
            logger.debug(f"Running Layer 3 checks for {domain}")
            
            # Update last check time
            self.last_check_times.setdefault(domain, {})["layer3"] = time.time()
            
            # Run all Layer 3 checkers concurrently
            check_tasks = []
            for checker_name, checker in self.checkers["layer3"].items():
                check_tasks.append(self._run_checker(domain, checker, "layer3", checker_name))
            
            results = await asyncio.gather(*check_tasks)
            
            # Calculate availability score for Layer 3
            score = self._calculate_availability_score(domain, results, "layer3")
            
            # Calculate final combined score across all layers
            final_score = self._calculate_final_score(domain)
            metrics_collector.increment("final_score_calculations")
            
            # Update domain status based on final score
            old_status = self.domain_status.get(domain, {}).get("status", "unknown")
            
            if final_score >= settings.AVAILABILITY_THRESHOLD:
                self.domain_status[domain]["status"] = "available"
                self.domain_status[domain]["confidence"] = final_score
                
                metrics_collector.increment("available_domains")
                
                if old_status != "available":
                    metrics_collector.increment("status_changes")
                    metrics_collector.increment("newly_available_domains")
                    logger.info(f"Domain {domain} AVAILABLE with confidence {final_score:.2f}")
                    
                    # Notify API about availability
                    all_checks = self._get_all_check_results(domain)
                    
                    api_timer_id = metrics_collector.start_timer("api_available_notification")
                    try:
                        await self.api_client.send_available_domain_notification(
                            domain, final_score, all_checks
                        )
                        metrics_collector.record_api_call("send_available_notification", True, 
                                                      metrics_collector.stop_timer("api_available_notification", api_timer_id))
                        metrics_collector.increment("available_notifications_sent")
                    except Exception as e:
                        metrics_collector.record_api_call("send_available_notification", False, 
                                                      metrics_collector.stop_timer("api_available_notification", api_timer_id))
                        metrics_collector.increment("available_notification_errors")
                        logger.error(f"Failed to notify API about available domain {domain}: {str(e)}")
            else:
                self.domain_status[domain]["status"] = "unavailable"
                self.domain_status[domain]["confidence"] = 1.0 - final_score
                
                if old_status != "unavailable":
                    metrics_collector.increment("status_changes")
            
            # Update available domains metric
            available_domains = [d for d in self.domains 
                               if self.domain_status.get(d, {}).get("status") == "available"]
            metrics_collector.update_domain_stats(
                domains=self.domains,
                high_priority=self.high_priority_domains,
                available=available_domains
            )
            metrics_collector.set_counter("domains_available", len(available_domains))
            
        except Exception as e:
            metrics_collector.increment("check_layer3_errors")
            logger.error(f"Error in Layer 3 check for {domain}: {str(e)}", exc_info=True)
        finally:
            metrics_collector.stop_timer("check_layer3_total", timer_id)
            self.in_progress.remove(domain)
    
    async def _run_checker(
        self, 
        domain: str, 
        checker: Any, 
        layer: str, 
        checker_name: str
    ) -> Tuple[str, CheckData]:
        """
        Run a specific checker and handle the result.
        
        Args:
            domain: Domain to check
            checker: Checker instance
            layer: Layer name
            checker_name: Checker name
            
        Returns:
            Tuple of checker name and check data
        """
        timer_id = metrics_collector.start_timer(f"check_{checker_name}")
        try:
            # Run the check
            check_data = await checker.check_domain(domain)
            
            # Record timing and result
            metrics_collector.stop_timer(f"check_{checker_name}", timer_id)
            metrics_collector.record_check_result(domain, checker_name, check_data.result.value)
            metrics_collector.increment(f"checks_{checker_name}")
            
            # Store in cache
            self.check_cache.setdefault(domain, {})[checker_name] = check_data
            
            # Send result to API
            api_timer_id = metrics_collector.start_timer("api_callback")
            try:
                await self.api_client.send_check_result(check_data)
                metrics_collector.record_api_call("send_check_result", True, 
                                               metrics_collector.stop_timer("api_callback", api_timer_id))
            except Exception as api_err:
                metrics_collector.record_api_call("send_check_result", False, 
                                               metrics_collector.stop_timer("api_callback", api_timer_id))
                logger.error(f"Failed to send {checker_name} check result to API: {str(api_err)}")
            
            return checker_name, check_data
            
        except Exception as e:
            metrics_collector.stop_timer(f"check_{checker_name}", timer_id)
            metrics_collector.increment(f"check_errors_{checker_name}")
            logger.error(f"Error running {checker_name} check for {domain}: {str(e)}", exc_info=True)
            
            # Create error check data
            error_data = CheckData(
                domain=domain,
                result=CheckResult.ERROR,
                timestamp=time.time(),
                checker_type=checker_name,
                details={},
                duration_ms=0,
                error=str(e)
            )
            
            metrics_collector.record_check_result(domain, checker_name, "error")
            
            return checker_name, error_data
    
    def _calculate_availability_score(
        self, 
        domain: str, 
        results: List[Tuple[str, CheckData]],
        layer: str
    ) -> float:
        """
        Calculate availability score based on check results for a specific layer.
        
        Args:
            domain: Domain name
            results: List of check results
            layer: Layer name
            
        Returns:
            Availability score (0-1)
        """
        if not results:
            return 0.0
        
        # Get weights for each checker
        checker_weights = settings.get_checker_weights()
        
        # Calculate weighted score
        total_weight = 0.0
        weighted_score = 0.0
        
        for checker_name, check_data in results:
            weight = checker_weights.get(checker_name, 1.0 / len(results))
            
            if check_data.result == CheckResult.AVAILABLE:
                weighted_score += weight * 1.0
            elif check_data.result == CheckResult.UNAVAILABLE:
                weighted_score += weight * 0.0
            elif check_data.result == CheckResult.UNKNOWN:
                weighted_score += weight * 0.5
            else:  # ERROR
                weighted_score += weight * 0.3  # Conservative approach for errors
            
            total_weight += weight
        
        # Normalize score
        if total_weight > 0:
            score = weighted_score / total_weight
            
            # Update metrics
            metrics_collector.increment(f"scores_calculated_{layer}")
            
            # Log score in different ranges
            if score >= 0.9:
                metrics_collector.increment(f"scores_{layer}_90plus")
            elif score >= 0.7:
                metrics_collector.increment(f"scores_{layer}_70plus")
            elif score >= 0.5:
                metrics_collector.increment(f"scores_{layer}_50plus")
            else:
                metrics_collector.increment(f"scores_{layer}_below50")
                
            return score
            
        return 0.0
    
    def _calculate_final_score(self, domain: str) -> float:
        """
        Calculate final availability score considering all layers.
        
        Args:
            domain: Domain name
            
        Returns:
            Final availability score (0-1)
        """
        # Layer weights (Layer 3 has highest weight)
        layer_weights = {
            "layer1": 0.2,
            "layer2": 0.3,
            "layer3": 0.5,
        }
        
        # Get all check results for domain
        all_checks = self._get_all_check_results(domain)
        
        # Calculate layer scores
        layer_scores = {}
        
        for layer, checkers in self.checkers.items():
            layer_results = []
            
            for checker_name in checkers.keys():
                if checker_name in all_checks["checks"]:
                    layer_results.append((checker_name, all_checks["checks"][checker_name]))
            
            if layer_results:
                layer_scores[layer] = self._calculate_availability_score(domain, layer_results, layer)
        
        # Calculate weighted final score
        total_weight = 0.0
        weighted_score = 0.0
        
        for layer, score in layer_scores.items():
            weight = layer_weights.get(layer, 0.0)
            weighted_score += weight * score
            total_weight += weight
        
        # Normalize score
        if total_weight > 0:
            final_score = weighted_score / total_weight
            
            # Update metrics based on final score
            if final_score >= settings.AVAILABILITY_THRESHOLD:
                metrics_collector.increment("final_scores_above_threshold")
            else:
                metrics_collector.increment("final_scores_below_threshold")
                
            return final_score
        
        return 0.0
    
    def _get_all_check_results(self, domain: str) -> Dict[str, Any]:
        """
        Get all check results for a domain.
        
        Args:
            domain: Domain name
            
        Returns:
            Dictionary of check results
        """
        domain_cache = self.check_cache.get(domain, {})
        
        # Convert to dict with additional timestamp
        result = {
            "timestamp": time.time(),
            "checks": domain_cache
        }
        
        return result
