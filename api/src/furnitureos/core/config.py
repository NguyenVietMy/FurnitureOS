"""Runtime configuration.

The database lives in Docker on host port 5433, not the conventional 5432 — a local
Postgres install already occupies 5432 on the development machine. See
docker-compose.yml.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FURNITUREOS_", env_file=".env")

    database_url: str = "postgresql+psycopg://furnitureos:furnitureos@localhost:5433/furnitureos"
    test_database_url: str = (
        "postgresql+psycopg://furnitureos:furnitureos@localhost:5433/furnitureos_test"
    )


settings = Settings()
