"""
Main entry point for the domain monitoring service.
Sets up logging, initializes Sentry, and starts the monitoring service.

File: domain-monitor/src/main.py
"""
import asyncio
import logging
import os
import signal
import sys
import time
import traceback
from contextlib import asynccontextmanager

import sentry_sdk
import uvicorn
from fastapi import FastAPI, HTTPException, Query

from src.config import settings
from src.domain_monitor import DomainMonitor
from src.utils.metrics import metrics_collector

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Initialize Sentry if DSN is provided
if settings.SENTRY_DSN:
    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.SENTRY_ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        ignore_errors=[KeyboardInterrupt],
    )
    logger.info("Sentry initialized")
else:
    logger.warning("Sentry DSN not provided, error tracking disabled")

# Create global monitor instance
monitor = DomainMonitor()


def handle_exit(signum, frame):
    """Handle exit signals and save state before exiting."""
    logger.info(f"Received signal {signum}, saving state and shutting down...")
    
    # Save state before exit if monitor is initialized
    if 'monitor' in globals():
        monitor._save_state(force=True)
        
    sys.exit(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan event handler.
    Starts the monitoring service and handles graceful shutdown.
    """
    # Start monitoring task
    monitoring_task = asyncio.create_task(monitor.start())
    logger.info("Domain monitoring service started")
    
    yield
    
    # Clean shutdown
    logger.info("Shutting down domain monitoring service")
    monitoring_task.cancel()
    try:
        await monitoring_task
    except asyncio.CancelledError:
        logger.info("Monitoring task cancelled")
    
    # Save state on shutdown
    monitor._save_state(force=True)
    logger.info("State saved, shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "domains_count": len(monitor.domains),
        "uptime": f"{int(time.time() - metrics_collector.start_time)} seconds",
    }


@app.get("/status")
async def monitor_status():
    """Get monitoring service status."""
    return {
        "domains": len(monitor.domains),
        "high_priority": len(monitor.high_priority_domains),
        "status": {
            domain: status for domain, status in monitor.domain_status.items()
            if status.get("status") != "unavailable"  # Only show interesting domains
        }
    }


@app.get("/domains")
async def list_domains():
    """Get the list of domains being monitored."""
    return {
        "total": len(monitor.domains),
        "high_priority": len(monitor.high_priority_domains),
        "domains": [
            {
                "domain": domain,
                "priority": domain in monitor.high_priority_domains,
                "status": monitor.domain_status.get(domain, {}).get("status", "unknown")
            }
            for domain in monitor.domains
        ]
    }


@app.get("/domain/{domain}")
async def domain_status(domain: str):
    """Get status for a specific domain."""
    if domain not in monitor.domain_status:
        raise HTTPException(status_code=404, detail="Domain not monitored")
    
    return {
        "domain": domain,
        "status": monitor.domain_status.get(domain, {"status": "unknown"}),
        "checks": monitor.check_cache.get(domain, {})
    }


@app.post("/refresh")
async def refresh_domains():
    """Manually trigger a refresh of the domain list from the API."""
    try:
        await monitor.update_domains(force=True)
        return {
            "status": "success",
            "domains_count": len(monitor.domains),
            "message": "Domain list refreshed successfully"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to refresh domains: {str(e)}")


@app.get("/metrics")
async def get_metrics(
    include_timers: bool = Query(True, description="Include timer metrics"),
    include_counters: bool = Query(True, description="Include counter metrics"),
    include_api: bool = Query(True, description="Include API call metrics"),
    include_check_results: bool = Query(True, description="Include check result metrics")
):
    """Get metrics for the monitoring service."""
    metrics = metrics_collector.get_metrics()
    
    # Filter metrics based on query parameters
    if not include_timers and "timers" in metrics:
        del metrics["timers"]
    
    if not include_counters and "counters" in metrics:
        del metrics["counters"]
    
    if not include_api and "api_stats" in metrics:
        del metrics["api_stats"]
    
    if not include_check_results and "check_results" in metrics:
        del metrics["check_results"]
    
    return metrics


@app.get("/metrics/reset", response_model=dict)
async def reset_metrics():
    """Reset metrics counters (timers and stats will be preserved)."""
    # Create a new metrics collector
    global metrics_collector
    from src.utils.metrics import MetricsCollector
    metrics_collector = MetricsCollector()
    
    return {"status": "success", "message": "Metrics reset successfully"}


"""
This code adds a test endpoint to verify Sentry integration.
Add this to your main.py file, after the other endpoints.

File: domain-monitor/src/main.py (addition)
"""

@app.get("/test-sentry")
async def test_sentry_integration():
    """
    Test Sentry integration by deliberately raising an exception.
    
    This endpoint will:
    1. Check if Sentry is configured
    2. Capture a test message
    3. Raise a test exception
    
    Returns:
        Success message if Sentry is not configured (to avoid real errors)
        Raises a test exception if Sentry is configured (which should be captured)
    """
    if not settings.SENTRY_DSN:
        return {
            "status": "skipped",
            "message": "Sentry DSN not configured. Set SENTRY_DSN in your environment variables to enable Sentry integration."
        }
    
    # Import sentry_sdk here to ensure it's been initialized
    import sentry_sdk
    
    # Capture a message (this will appear in Sentry as an "info" level event)
    sentry_sdk.capture_message("This is a test message from the domain-monitor service", level="info")
    
    try:
        # Create a custom exception with context
        sentry_sdk.set_context("test_data", {
            "purpose": "Testing Sentry integration",
            "initiated_by": "Test endpoint",
            "timestamp": time.time()
        })
        
        # Raise a deliberate exception
        logger.warning("About to raise a test exception for Sentry")
        raise ValueError("This is a deliberate test exception to verify Sentry integration")
    
    except Exception as e:
        # Capture the exception explicitly (though Sentry should catch it automatically)
        sentry_sdk.capture_exception(e)
        
        # Re-raise to trigger a 500 response and ensure Sentry catches the full stack trace
        raise HTTPException(
            status_code=500, 
            detail="Test exception raised successfully. Check your Sentry dashboard for this error."
        )

if __name__ == "__main__":
    # Setup crash recovery loop
    retry_count = 0
    max_retries = 10
    
    while True:
        try:
            # Register signal handlers
            signal.signal(signal.SIGINT, handle_exit)
            signal.signal(signal.SIGTERM, handle_exit)
            
            # Start the API server
            logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
            uvicorn.run(
                "src.main:app",
                host="0.0.0.0",
                port=8000,
                reload=False,
                log_level=settings.LOG_LEVEL.lower(),
            )
            # If we get here, uvicorn was stopped cleanly
            break
            
        except Exception as e:
            retry_count += 1
            logger.critical(f"Critical error occurred: {str(e)}", exc_info=True)
            
            # Save state if monitor is initialized
            if 'monitor' in globals():
                try:
                    monitor._save_state(force=True)
                    logger.info("Saved state before restart")
                except Exception as save_error:
                    logger.error(f"Failed to save state: {str(save_error)}")
            
            # Check if we should try again
            if retry_count <= max_retries:
                wait_time = min(30, 5 * retry_count)  # Exponential backoff (up to 30 seconds)
                logger.info(f"Restarting application in {wait_time} seconds (attempt {retry_count}/{max_retries})...")
                time.sleep(wait_time)
            else:
                logger.critical(f"Too many restart attempts ({retry_count}), giving up")
                
                # Attempt to write crash dump
                try:
                    crash_file = os.path.join(os.environ.get("STATE_DIR", "/app/state"), "crashdump.txt")
                    with open(crash_file, "w") as f:
                        f.write(f"Crash at {time.ctime()}\n")
                        f.write(f"Error: {str(e)}\n")
                        f.write(traceback.format_exc())
                        f.write("\n\nSystem giving up after too many restart attempts.\n")
                except Exception:
                    pass
                    
                sys.exit(1)
