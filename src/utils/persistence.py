"""
State persistence module for the domain monitoring service.
Handles saving and loading state to ensure recovery after crashes.

File: domain-monitor/src/utils/persistence.py
"""
import json
import logging
import os
import time
from typing import Dict, List, Set, Any, Optional

logger = logging.getLogger(__name__)

# State file location
STATE_DIR = os.environ.get("STATE_DIR", "/app/state")
STATE_FILE = os.path.join(STATE_DIR, "monitor_state.json")

# How often to save state (in seconds)
SAVE_INTERVAL = int(os.environ.get("STATE_SAVE_INTERVAL", "300"))  # Default: 5 minutes


class StatePersistence:
    """Handles saving and loading domain monitor state."""
    
    def __init__(self) -> None:
        """Initialize state persistence."""
        self.last_save_time = 0.0
        
        # Create state directory if it doesn't exist
        os.makedirs(STATE_DIR, exist_ok=True)
    
    def save_state(
        self,
        domains: List[str],
        high_priority_domains: Set[str],
        domain_status: Dict[str, Dict[str, Any]],
        last_check_times: Dict[str, Dict[str, float]],
        force: bool = False
    ) -> None:
        """
        Save current monitoring state to disk.
        
        Args:
            domains: List of domains being monitored
            high_priority_domains: Set of high priority domains
            domain_status: Domain status information
            last_check_times: Last check times for domains
            force: Force save regardless of save interval
        """
        current_time = time.time()
        
        # Check if we need to save state
        if not force and current_time - self.last_save_time < SAVE_INTERVAL:
            return
        
        try:
            state = {
                "timestamp": current_time,
                "domains": domains,
                "high_priority_domains": list(high_priority_domains),
                "domain_status": domain_status,
                "last_check_times": last_check_times
            }
            
            # Save to temporary file first, then rename
            temp_file = f"{STATE_FILE}.tmp"
            with open(temp_file, "w") as f:
                json.dump(state, f)
            
            # Atomic rename to avoid corruption
            os.rename(temp_file, STATE_FILE)
            
            self.last_save_time = current_time
            logger.debug(f"State saved to {STATE_FILE}")
            
        except Exception as e:
            logger.error(f"Error saving state: {str(e)}", exc_info=True)
    
    def load_state(self) -> Optional[Dict[str, Any]]:
        """
        Load monitoring state from disk if available.
        
        Returns:
            Dictionary with state data or None if no state available
        """
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r") as f:
                    state = json.load(f)
                
                logger.info(f"Loaded state from {STATE_FILE} (saved at {time.ctime(state.get('timestamp', 0))})")
                
                # Convert high_priority_domains back to a set
                if "high_priority_domains" in state:
                    state["high_priority_domains"] = set(state["high_priority_domains"])
                
                return state
                
        except Exception as e:
            logger.error(f"Error loading state: {str(e)}", exc_info=True)
        
        return None


# Create a global instance
state_persistence = StatePersistence()