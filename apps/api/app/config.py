from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://workflow:workflow@postgres:5432/workflow"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "change-me-before-deploying"
    credential_encryption_key: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_sender: str = ""
    frontend_url: str = "http://localhost:5173"
    execution_timeout_seconds: int = 300


settings = Settings()
