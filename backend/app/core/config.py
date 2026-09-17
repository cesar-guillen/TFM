from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, overridable per environment variable (see
    .env.example). CLAUDE.md documents what each knob was measured to do."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage (paths inside the container)
    upload_dir: str = "/data/uploads"
    layers_dir: str = "/data/layers"
    chroma_persist_dir: str = "/data/chroma"
    attack_stix_dir: str = "/data/attack"

    # Chroma collections
    attack_collection: str = "attack_techniques"
    attack_examples_collection: str = "attack_examples"
    report_chunks_collection: str = "report_chunks"
    report_windows_collection: str = "report_windows"

    # Ollama
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"

    # Concurrent per-chunk LLM calls. Keep in sync with the ollama service's
    # OLLAMA_NUM_PARALLEL — extra workers just queue server-side. -1 = size
    # automatically from machine RAM (see llm.resolve_map_workers).
    map_workers: int = 4

    # Retrieval candidates offered per chunk, and how many chars of each
    # candidate's description reach the prompt. Prompt reading dominates CPU
    # cost, so these are the main latency/quality trade-off.
    map_candidates: int = 8
    map_desc_chars: int = 250

    # llama.cpp threads per request: 0 = Ollama's default, >0 = explicit,
    # -1 = match the CPU profiles' core pinning (see llm.resolve_num_thread).
    map_num_thread: int = 0

    # Skip remediation-style and boilerplate sections at indexing time; false
    # indexes everything (ablation runs).
    section_filter: bool = True

    # Inject ATT&CK ids cited literally in a chunk ("[T1573]") as candidates —
    # retrieval cannot surface them, since KB documents carry no ids.
    explicit_ids: bool = True

    # Sub-chunk retrieval halves (sentence-window dense + per-sentence BM25)
    # alongside the chunk-level dense half.
    sentence_retrieval: bool = True

    # Merge ATT&CK procedure-example vectors into the dense halves. Off: it
    # closes the vocabulary gap but loses more candidates than it gains under
    # the current menu width. Degrades to a no-op if never built.
    example_retrieval: bool = False

    # Cross-encoder reranking of the fused candidate pool. Off: it is the best
    # candidate *selector* measured but loses exact F1 in menu mode. Runs
    # locally on CPU; a no-op when the model files are absent.
    rerank: bool = False
    rerank_model_dir: str = "/data/reranker"
    rerank_model_file: str = "model_int8.onnx"
    rerank_threads: int = 4

    # Per-window priority seats in fusion: each sentence window's top-N dense
    # hits are seated ahead of fused-score ordering, so a minority sentence's
    # best hit is not buried by the chunk's dominant topic. 0 disables.
    window_seat_depth: int = 1

    # What the verification pass does with a mapping it cannot confirm:
    # "off" (no judging), "demote" (kept, capped near the score floor and
    # flagged for review), "drop" (removed). Overridable per run.
    verify_mode: str = "demote"

    # Verdict architecture: "menu" (one call per chunk, all candidates at once)
    # or "independent" (one small call per candidate). Overridable per run.
    # independent scores better on exact F1 and precision on real DFIR
    # reports; menu lets stronger evidence in the same chunk crowd out
    # weaker-but-real techniques (e.g. AD/Discovery enumeration losing to
    # LSASS dumping).
    verdict_mode: str = "independent"

    # Prompt family: "incident" (the intruder is the adversary) or "pentest"
    # (the testers are). Overridable per run.
    report_type: str = "incident"

    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
