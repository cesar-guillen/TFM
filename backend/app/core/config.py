from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "/data/uploads"
    chroma_persist_dir: str = "/data/chroma"
    attack_stix_dir: str = "/data/attack"
    attack_collection: str = "attack_techniques"
    report_chunks_collection: str = "report_chunks"
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"
    # Concurrent per-chunk LLM calls in the mapping stage. Keep in sync with
    # the ollama service's OLLAMA_NUM_PARALLEL (docker-compose.yml) — extra
    # workers beyond that just queue server-side.
    map_workers: int = 4
    # Skip embedding/mapping of chunks from remediation-style and boilerplate
    # sections (see app.ingest.chunking.classify_heading_path). Set
    # SECTION_FILTER=false to index every chunk, e.g. for an ablation run.
    section_filter: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
