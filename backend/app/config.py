import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    owner_api_token: str = os.getenv("OWNER_API_TOKEN", "")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./profitbot.db")
    cors_origins: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost").split(",") if x.strip()
    )

settings = Settings()
