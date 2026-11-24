from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CredResolve SmartDialer"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/smartdialer"
    max_provider_failure_rate: float = 0.30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
