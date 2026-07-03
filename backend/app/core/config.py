from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "/data/uploads"
    chroma_persist_dir: str = "/data/chroma"
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    cors_origins: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
