from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "/data/uploads"
    layers_dir: str = "/data/layers"
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
    # Retrieval candidates offered to the model per chunk, and how many chars
    # of each candidate's description survive into the prompt. Prefill (prompt
    # reading) is ~60-70% of a chunk's cost on CPU, so the CPU compose
    # profiles set leaner values (6 / 170) than these full-quality defaults.
    map_candidates: int = 8
    map_desc_chars: int = 250
    # llama.cpp thread count passed per request: 0 = let Ollama decide
    # (physical cores), >0 = explicit, -1 = auto: min(physical cores,
    # cpu_count - 2) — matches the CPU profiles' taskset pinning so threads
    # never outnumber the cores they're allowed to run on (oversubscribed
    # spin-wait barriers are a cliff, e.g. 8 threads on a 6-CPU cpuset in a
    # VM). On unpinned/GPU setups auto resolves to Ollama's own default.
    map_num_thread: int = 0
    # Skip embedding/mapping of chunks from remediation-style and boilerplate
    # sections (see app.ingest.chunking.classify_heading_path). Set
    # SECTION_FILTER=false to index every chunk, e.g. for an ablation run.
    section_filter: bool = True
    cors_origins: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
