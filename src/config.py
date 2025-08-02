"""
Configuration module for domain monitoring service.
Handles loading and validating configuration from environment variables.

File: domain-monitor/src/config.py
"""
from typing import Dict, Optional
from pydantic import validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Application settings
    APP_NAME: str = "domain-monitor"
    APP_VERSION: str = "0.1.0"
    LOG_LEVEL: str = "INFO"
    
    # Sentry configuration
    SENTRY_DSN: Optional[str] = None
    SENTRY_ENVIRONMENT: str = "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    
    # API callback configuration
    API_CALLBACK_URL: str
    API_AVAILABLE_CALLBACK_URL: str
    API_AUTH_TOKEN: str
    API_TIMEOUT: int = 30
    API_MAX_RETRIES: int = 3
    API_RETRY_BACKOFF: float = 1.0
    
    # Domain API configuration
    DOMAIN_API_URL: str
    DOMAIN_API_REFRESH_INTERVAL: int = 300  # 5 minutes
    
    # Checking intervals (in seconds)
    LAYER1_CHECK_INTERVAL: int = 300  # 5 minutes
    LAYER2_CHECK_INTERVAL: int = 1800  # 30 minutes
    LAYER3_CHECK_INTERVAL: int = 10800  # 3 hours
    
    # Rate limiting configuration
    DNS_CHECKS_PER_MINUTE: int = 100
    HTTP_CHECKS_PER_MINUTE: int = 60
    REGISTRAR_CHECKS_PER_MINUTE: int = 30
    RDAP_CHECKS_PER_MINUTE: int = 20
    WHOIS_CHECKS_PER_MINUTE: int = 10
    
    # Availability scoring configuration
    AVAILABILITY_THRESHOLD: float = 0.75
    DNS_WEIGHT: float = 0.3
    HTTP_WEIGHT: float = 0.2
    REGISTRAR_WEIGHT: float = 0.2
    RDAP_WEIGHT: float = 0.15
    WHOIS_WEIGHT: float = 0.15
    
    # Horizontal scaling
    INSTANCE_ID: str = "default"
    ENABLE_DISTRIBUTED_LOCKING: bool = False
    
    
    @validator("DNS_WEIGHT", "HTTP_WEIGHT", "REGISTRAR_WEIGHT", "RDAP_WEIGHT", "WHOIS_WEIGHT")
    def validate_weights(cls, v: float) -> float:
        """Validate weights are between 0 and 1."""
        if not 0 <= v <= 1:
            raise ValueError("Weight values must be between 0 and 1")
        return v
    
    def get_checker_weights(self) -> Dict[str, float]:
        """Return a dictionary of checker weights."""
        return {
            "dns": self.DNS_WEIGHT,
            "http": self.HTTP_WEIGHT,
            "registrar": self.REGISTRAR_WEIGHT,
            "rdap": self.RDAP_WEIGHT,
            "whois": self.WHOIS_WEIGHT,
        }
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Create global settings instance
settings = Settings()