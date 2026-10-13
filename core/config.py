from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://notif:notif@localhost:5432/notificaciones"
    amqp_url: str = "amqp://guest:guest@localhost:5672/"
    amqp_exchange: str = "notificaciones"

    mail_backend: str = "smtp"  # brevo | smtp
    mail_from: str = "notificaciones@example.com"
    mail_from_name: str = "Notificaciones"
    brevo_api_key: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 1025

    worker_enabled: bool = True
    webhook_timeout: float = 10.0
    max_intentos: int = 3
    reintento_minutos: int = 5

    render_health_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
