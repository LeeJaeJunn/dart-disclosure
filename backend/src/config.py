from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    openai_api_key: str
    openai_model: str = "gpt-6-luna"
    embedding_model: str = "text-embedding-3-small"
    opendart_api_key: str


settings = Settings()
