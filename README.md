# Domain Monitor

A production-grade domain monitoring service that checks for domain availability using a hybrid approach. The system continuously monitors domains and notifies an external API when domains become available for registration.

## Features

- **Hybrid Checking Approach**: Uses three layers of domain availability checking:
  - **Layer 1 (Fast Checks)**: DNS lookups and HTTP requests for fast, preliminary checks
  - **Layer 2 (Intermediate Checks)**: RDAP queries and registrar API calls for more reliable verification
  - **Layer 3 (Deep Checks)**: WHOIS lookups for thorough verification
  
- **Dynamic Domain Management**: 
  - Fetches domains to monitor from an API endpoint
  - Updates domain list automatically at configurable intervals
  - Supports priority flagging for more frequent checking
  
- **Production Ready**:
  - Dockerized for easy deployment
  - Horizontal scaling support
  - Sentry.io integration for error tracking
  - Comprehensive logging
  - Health check endpoints
  
- **Intelligent Rate Limiting**: Built-in token bucket rate limiting to avoid being blocked
  
- **Robust Error Handling**: Retries, fallbacks, and error reporting
  
- **Comprehensive Metrics**: Performance and operational metrics collection and reporting
  
- **State Persistence**: Maintains state across restarts and crashes

## Architecture

The domain monitoring system is built with a layered approach:

1. **Domain Monitor Service**: Coordinates the different checking layers and makes final availability decisions
2. **Domain Checkers**: Specialized checkers for different availability checking methods
3. **API Client**: Handles communication with the external API
4. **Scheduler**: Manages check schedules based on domain priority and previous results
5. **Rate Limiter**: Controls request rates to avoid being blocked
6. **Metrics Collector**: Tracks performance and operational metrics
7. **State Persistence**: Manages saving and loading state

## Getting Started

### Prerequisites

- Docker and Docker Compose
- An external API endpoint to receive domain status updates
- An API endpoint that provides domains to monitor

### Configuration

Configure the system using environment variables:

```shell
# Create a .env file
cp .env.example .env
# Edit the .env file with your configuration
```

Required environment variables:

- `API_CALLBACK_URL`: URL for the API to receive domain check results
- `API_AUTH_TOKEN`: Bearer token for API authentication
- `DOMAIN_API_URL`: URL for the API that provides domains to monitor
- `SENTRY_DSN`: Sentry DSN for error tracking (optional but recommended)

See `docker-compose.yml` for a complete list of available configuration options.

### Running the Service

```shell
# Build the Docker image
docker-compose build

# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Check service status
curl http://localhost:8000/health

# View monitoring status
curl http://localhost:8000/status
```

### Horizontal Scaling

To run multiple instances for horizontal scaling:

```shell
# Scale to 3 instances
docker-compose up -d --scale domain-monitor=3
```

Each instance should have a unique `INSTANCE_ID` environment variable.

## Domain API Integration

The system periodically fetches the list of domains to monitor from an API endpoint. The API should return a JSON response in the following format:

```json
{
  "domains": [
    {
      "domain": "example.com",
      "priority": true
    },
    {
      "domain": "example.org",
      "priority": false
    },
    "another-example.com"
  ]
}
```

Notes:
- Domains can be specified as objects with `domain` and `priority` fields, or as simple strings
- Domains with `priority: true` will be checked more frequently
- The system will check for new domains at each refresh interval
- New domains will be added to the monitoring list automatically
- Domains that are removed from the API response will be removed from monitoring

The refresh interval can be configured using the `DOMAIN_API_REFRESH_INTERVAL` environment variable (default: 300 seconds).

## API Callback Integration

The system sends domain check results to your API in the following format:

```json
{
  "domain": "example.com",
  "check_type": "whois",
  "result": "available",
  "timestamp": 1647854321.123,
  "details": {
    "registrar": null,
    "creation_date": null,
    "expiration_date": null
  },
  "duration_ms": 1250
}
```

When a domain is determined to be available, it sends a special notification:

```json
{
  "domain": "example.com",
  "status": "available",
  "confidence": 0.95,
  "timestamp": 1647854321.123,
  "checks": {
    "timestamp": 1647854321.123,
    "checks": {
      "dns": { ... },
      "whois": { ... }
    }
  }
}
```

## Monitoring and Maintenance

The service provides several API endpoints for monitoring and control:

- Health check endpoint: `GET /health`
- Status overview: `GET /status`
- List all monitored domains: `GET /domains`
- Specific domain status: `GET /domain/{domain}`
- Manually refresh domain list: `POST /refresh`
- View metrics: `GET /metrics`
- Reset metrics: `GET /metrics/reset`

These endpoints allow you to monitor the system's operation and manage the domains being checked.

## Performance Metrics

The system collects and exposes detailed performance metrics through the `/metrics` endpoint. These metrics include:

- **Operational Statistics**:
  - Uptime
  - Domain counts (total, high priority, available)
  - Counter values for various operations

- **Performance Timers**:
  - API call durations (average, min, max)
  - Check durations by checker type
  - Domain refresh operation times

- **Check Results**:
  - Success/failure counts by checker type
  - Error counts and types
  - Availability statistics

- **API Statistics**:
  - Call counts by endpoint
  - Error rates
  - Response times

You can filter the metrics by using query parameters:
```
GET /metrics?include_timers=true&include_counters=true&include_api=true&include_check_results=true
```

## Crash Recovery and Resilience

The domain monitoring system is designed to be fault-tolerant with multiple layers of crash recovery:

### 1. State Persistence

- Domain state is automatically saved to disk every 5 minutes
- State is also saved on graceful shutdown or application crash
- When the service restarts, it loads the previous state to continue monitoring
- Domains being monitored, their status, and timing information are preserved

### 2. Application-Level Restart Loop

- The main process includes a restart loop that catches unhandled exceptions
- If a critical error occurs, the application:
  1. Attempts to save state
  2. Logs the error with full traceback
  3. Waits a short period (with exponential backoff)
  4. Automatically restarts itself

### 3. Container-Level Recovery

- Docker is configured to restart the container if the process exits unexpectedly
- The `restart: unless-stopped` policy ensures the container restarts until manually stopped
- A custom restart policy limits restart attempts to prevent rapid-cycling restarts

### 4. Process Supervision

- Supervisord monitors the application process inside the container
- If the Python process crashes, Supervisord restarts it automatically
- Separate processes monitor health and ensure clean restarts

### State Directory

The state is stored in the `/app/state` directory, which is mounted as a volume to persist data across container restarts. This ensures no monitoring progress is lost even if the container is completely restarted.

You can find crash dumps and debug information in the state directory if there were critical failures.

## Testing

The domain monitoring system includes a comprehensive test suite to ensure all components function correctly.

### Running Tests

```bash
# Install development dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage report
pytest --cov=src

# Run specific test file
pytest tests/test_checkers.py

# Run tests with detailed output
pytest -v

# Run only tests related to the API client
pytest tests/test_api_client.py
```

### Test Structure

- **Unit Tests**: Test individual components in isolation
  - `test_checkers.py`: Tests for DNS, HTTP, and WHOIS checkers
  - `test_api_client.py`: Tests for the API client
  - `test_domain_api_client.py`: Tests for domain API client
  - `test_domain_monitor.py`: Tests for the main monitoring service
  - `test_scheduler.py`: Tests for the scheduler component

### Mock Data

The tests use mock data and fixtures to avoid making actual external API calls or domain lookups during testing:

- Mock DNS responses
- Mock HTTP responses
- Mock WHOIS data
- Mock API client responses

### CI/CD Integration

You can integrate these tests into your CI/CD pipeline with:

```yaml
# Example GitHub Actions workflow
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v3
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.12'
    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        pip install -r requirements-dev.txt
    - name: Run tests
      run: |
        pytest --cov=src --cov-report=xml
    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

## Project Structure

```
domain-monitor/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
├── supervisord.conf
├── .env.example
├── README.md
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config.py               # Configuration management
│   ├── domain_monitor.py       # Main monitoring service
│   ├── checkers/               # Domain checking implementations
│   │   ├── __init__.py
│   │   ├── base.py             # Base checker class
│   │   ├── dns_checker.py      # Layer 1: DNS checks
│   │   ├── http_checker.py     # Layer 1: HTTP HEAD requests
│   │   └── whois_checker.py    # Layer 3: WHOIS checks
│   ├── api/                    # API clients
│   │   ├── __init__.py
│   │   ├── client.py           # API callback client
│   │   └── domain_api_client.py # Domain list fetching client
│   ├── scheduler/              # Job scheduling
│   │   ├── __init__.py
│   │   └── jobs.py             # Scheduler implementation
│   └── utils/                  # Utility modules
│       ├── __init__.py
│       ├── persistence.py      # State persistence
│       ├── rate_limiter.py     # Rate limiting
│       └── metrics.py          # Metrics collection
└── tests/                      # Test suite
    ├── __init__.py
    ├── conftest.py
    ├── test_checkers.py
    ├── test_api_client.py
    ├── test_domain_api_client.py
    ├── test_domain_monitor.py
    └── test_scheduler.py
```

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.

This is free software: you are free to change and redistribute it under the terms of the GPL v3. There is NO WARRANTY, to the extent permitted by law.