import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./rcaa.db")
    cors_origins: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()
    )
    razorpay_key_id: str = os.getenv("RAZORPAY_KEY_ID", "")
    razorpay_key_secret: str = os.getenv("RAZORPAY_KEY_SECRET", "")
    razorpay_webhook_secret: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    billing_provider: str = os.getenv("BILLING_PROVIDER", "manual").strip().lower()
    razorpay_plan_starter: str = os.getenv("RAZORPAY_PLAN_STARTER", "")
    razorpay_plan_growth: str = os.getenv("RAZORPAY_PLAN_GROWTH", "")
    razorpay_plan_business: str = os.getenv("RAZORPAY_PLAN_BUSINESS", "")
    settlement_window_days: int = int(os.getenv("SETTLEMENT_WINDOW_DAYS", "3"))
    redis_url: str = os.getenv("REDIS_URL", "")
    ai_provider: str = os.getenv("AI_PROVIDER", "mock").strip().lower()
    ai_api_key: str = os.getenv("AI_API_KEY", "")
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://api.openai.com/v1")
    ai_model: str = os.getenv("AI_MODEL", "gpt-4o-mini")
    ai_timeout_seconds: float = float(os.getenv("AI_TIMEOUT_SECONDS", "20"))
    auth_secret: str = os.getenv("AUTH_SECRET", "")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    auth_bootstrap_token: str = os.getenv("AUTH_BOOTSTRAP_TOKEN", "")
    testing: bool = os.getenv("TESTING", "0") == "1"
    reconciliation_timestamp_tolerance_minutes: int = int(os.getenv("RECONCILIATION_TIMESTAMP_TOLERANCE_MINUTES", "30"))
    reconciliation_amount_tolerance: str = os.getenv("RECONCILIATION_AMOUNT_TOLERANCE", "0.00")
    reconciliation_timezone: str = os.getenv("RECONCILIATION_TIMEZONE", "UTC")
    db_pool_size: int = int(os.getenv("DB_POOL_SIZE", "10"))
    db_max_overflow: int = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    db_pool_timeout_seconds: int = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "30"))
    db_pool_recycle_seconds: int = int(os.getenv("DB_POOL_RECYCLE_SECONDS", "1800"))
    db_pool_pre_ping: bool = _env_bool("DB_POOL_PRE_PING", True)
    rcaa_version: str = os.getenv("RCAA_VERSION", "0.15.0")
    build_id: str = os.getenv("BUILD_ID", "local")
    git_commit_sha: str = os.getenv("GIT_COMMIT_SHA", "unknown")
    max_request_body_bytes: int = int(os.getenv("MAX_REQUEST_BODY_BYTES", str(10 * 1024 * 1024)))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
    trust_proxy_headers: bool = _env_bool("TRUST_PROXY_HEADERS", False)
    metrics_auth_token: str = os.getenv("METRICS_AUTH_TOKEN", "")
    mfa_encryption_key: str = os.getenv("MFA_ENCRYPTION_KEY", "")
    mfa_issuer: str = os.getenv("MFA_ISSUER", "RCAA")
    mfa_required_roles: tuple[str, ...] = tuple(x.strip().upper() for x in os.getenv("MFA_REQUIRED_ROLES", "").split(",") if x.strip())
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    refresh_cookie_name: str = os.getenv("REFRESH_COOKIE_NAME", "rcaa_refresh")
    refresh_cookie_secure: bool = _env_bool("REFRESH_COOKIE_SECURE", False)
    refresh_cookie_samesite: str = os.getenv("REFRESH_COOKIE_SAMESITE", "lax").strip().lower()
    refresh_cookie_domain: str = os.getenv("REFRESH_COOKIE_DOMAIN", "").strip() or None
    raw_data_retention_days: int = int(os.getenv("RAW_DATA_RETENTION_DAYS", "90"))
    upload_retention_days: int = int(os.getenv("UPLOAD_RETENTION_DAYS", "30"))
    razorpay_webhook_allowed_ips: tuple[str, ...] = tuple(x.strip() for x in os.getenv("RAZORPAY_WEBHOOK_ALLOWED_IPS", "").split(",") if x.strip())
    rate_limit_enabled: bool = _env_bool("RATE_LIMIT_ENABLED", True)
    rate_limit_login_ip: int = int(os.getenv("RATE_LIMIT_LOGIN_IP", "60"))
    rate_limit_login_email: int = int(os.getenv("RATE_LIMIT_LOGIN_EMAIL", "10"))
    rate_limit_login_window_seconds: int = int(os.getenv("RATE_LIMIT_LOGIN_WINDOW_SECONDS", "300"))
    rate_limit_signup_ip: int = int(os.getenv("RATE_LIMIT_SIGNUP_IP", "20"))
    rate_limit_signup_email: int = int(os.getenv("RATE_LIMIT_SIGNUP_EMAIL", "5"))
    rate_limit_signup_window_seconds: int = int(os.getenv("RATE_LIMIT_SIGNUP_WINDOW_SECONDS", "3600"))
    rate_limit_demo_ip: int = int(os.getenv("RATE_LIMIT_DEMO_IP", "20"))
    rate_limit_demo_email: int = int(os.getenv("RATE_LIMIT_DEMO_EMAIL", "5"))
    rate_limit_demo_window_seconds: int = int(os.getenv("RATE_LIMIT_DEMO_WINDOW_SECONDS", "3600"))
    rate_limit_mfa_user: int = int(os.getenv("RATE_LIMIT_MFA_USER", "10"))
    rate_limit_mfa_window_seconds: int = int(os.getenv("RATE_LIMIT_MFA_WINDOW_SECONDS", "600"))
    password_reset_expire_minutes: int = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "30"))
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_starttls: bool = _env_bool("SMTP_STARTTLS", True)
    password_reset_public_base_url: str = os.getenv("PASSWORD_RESET_PUBLIC_BASE_URL", "")
    connector_sync_default_interval_minutes: int = int(os.getenv("CONNECTOR_SYNC_DEFAULT_INTERVAL_MINUTES", "360"))
    sso_enabled: bool = _env_bool("SSO_ENABLED", False)
    sso_callback_url: str = os.getenv("SSO_CALLBACK_URL", "")
    sso_frontend_url: str = os.getenv("SSO_FRONTEND_URL", "")
    sso_allowed_issuers: tuple[str, ...] = tuple(x.strip().rstrip("/") for x in os.getenv("SSO_ALLOWED_ISSUERS", "").split(",") if x.strip())
    sso_state_expire_minutes: int = int(os.getenv("SSO_STATE_EXPIRE_MINUTES", "10"))
    sla_critical_hours: int = int(os.getenv("SLA_CRITICAL_HOURS", "4"))
    sla_high_hours: int = int(os.getenv("SLA_HIGH_HOURS", "24"))
    sla_medium_hours: int = int(os.getenv("SLA_MEDIUM_HOURS", "72"))
    sla_low_hours: int = int(os.getenv("SLA_LOW_HOURS", "120"))


settings = Settings()


def validate_startup_config() -> None:
    """Validate deployment-sensitive configuration without exposing secret values."""
    if settings.testing or settings.app_env not in {"production", "prod"}:
        return

    errors: list[str] = []
    if not settings.database_url or settings.database_url.startswith("sqlite"):
        errors.append("DATABASE_URL must point to PostgreSQL in production")
    if len(settings.auth_secret) < 32:
        errors.append("AUTH_SECRET must contain at least 32 characters in production")
    if settings.max_request_body_bytes < 1024 or settings.max_upload_bytes < 1024 or settings.max_upload_bytes > settings.max_request_body_bytes:
        errors.append("Request/upload size limits are invalid")
    if settings.metrics_auth_token == "":
        errors.append("METRICS_AUTH_TOKEN must be configured in production")
    if not settings.mfa_encryption_key:
        errors.append("MFA_ENCRYPTION_KEY must be configured in production")
    if settings.refresh_token_expire_days < 1 or settings.refresh_token_expire_days > 30:
        errors.append("REFRESH_TOKEN_EXPIRE_DAYS must be between 1 and 30")
    if settings.refresh_cookie_samesite not in {"lax", "strict", "none"}:
        errors.append("REFRESH_COOKIE_SAMESITE must be lax, strict, or none")
    if settings.refresh_cookie_samesite == "none" and not settings.refresh_cookie_secure:
        errors.append("REFRESH_COOKIE_SECURE must be enabled when SameSite=None is used")
    if settings.rate_limit_mfa_user < 1 or settings.rate_limit_mfa_window_seconds < 60:
        errors.append("MFA rate-limit settings are invalid")
    if settings.raw_data_retention_days < 7 or settings.upload_retention_days < 1:
        errors.append("Data retention periods are invalid")
    if settings.password_reset_expire_minutes < 5 or settings.password_reset_expire_minutes > 120:
        errors.append("PASSWORD_RESET_EXPIRE_MINUTES must be between 5 and 120")
    if settings.smtp_host and not settings.smtp_from:
        errors.append("SMTP_FROM is required when SMTP_HOST is configured")
    if not settings.trust_proxy_headers:
        errors.append("TRUST_PROXY_HEADERS must be enabled when production runs behind the configured reverse proxy")
    if not settings.cors_origins:
        errors.append("CORS_ORIGINS must contain at least one allowed origin")
    if settings.ai_provider in {"openai", "openai_compatible"} and not settings.ai_api_key:
        errors.append("AI_API_KEY is required when an external AI provider is enabled")
    if settings.ai_provider not in {"mock", "deterministic", "openai", "openai_compatible"}:
        errors.append("AI_PROVIDER is not supported")
    if settings.razorpay_key_id and not settings.razorpay_key_secret:
        errors.append("RAZORPAY_KEY_SECRET is required when RAZORPAY_KEY_ID is configured")
    if settings.razorpay_key_secret and not settings.razorpay_key_id:
        errors.append("RAZORPAY_KEY_ID is required when RAZORPAY_KEY_SECRET is configured")
    if settings.razorpay_key_id and not settings.razorpay_webhook_secret:
        errors.append("RAZORPAY_WEBHOOK_SECRET is required when Razorpay credentials are configured")
    if settings.billing_provider not in {"manual", "razorpay"}:
        errors.append("BILLING_PROVIDER must be manual or razorpay")
    if settings.billing_provider == "razorpay":
        if not settings.razorpay_key_id or not settings.razorpay_key_secret or not settings.razorpay_webhook_secret:
            errors.append("Razorpay billing requires key id, key secret, and webhook secret")
        for name, value in (("STARTER", settings.razorpay_plan_starter), ("GROWTH", settings.razorpay_plan_growth), ("BUSINESS", settings.razorpay_plan_business)):
            if not value:
                errors.append(f"RAZORPAY_PLAN_{name} is required when BILLING_PROVIDER=razorpay")
    if settings.db_pool_size < 1 or settings.db_max_overflow < 0 or settings.db_pool_timeout_seconds < 1 or settings.db_pool_recycle_seconds < 0:
        errors.append("Database pool settings are invalid")
    if errors:
        raise RuntimeError("Production configuration validation failed: " + "; ".join(errors))
