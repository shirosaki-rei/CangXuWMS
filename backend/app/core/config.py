"""集中配置：pydantic-settings 读 .env，全项目只从这里取配置。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_name: str = "WMS"
    env: str = "dev"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    db_url: str = "mysql+pymysql://wms:wms123456@127.0.0.1:3306/wms?charset=utf8mb4"
    # AI 只读连接（架构 8.1）。留空 = 退回 db_url，仅本地开发可接受。
    db_readonly_url: str = ""
    redis_url: str = "redis://127.0.0.1:6379/0"

    jwt_secret: str = "please-change-me-to-at-least-32-characters-long-secret"
    jwt_alg: str = "HS256"
    access_ttl: int = 7200
    refresh_ttl: int = 604800
    idle_ttl: int = 28800  # 8h 无操作作废

    captcha_ttl: int = 300
    login_fail_max: int = 5
    login_lock_minutes: int = 10
    idempotency_ttl: int = 86400

    seed_admin_username: str = "admin"
    seed_admin_password: str = "admin123"

    @property
    def readonly_url(self) -> str:
        return self.db_readonly_url or self.db_url

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
