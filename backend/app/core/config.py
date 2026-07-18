from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "/data/uploads"
    layers_dir: str = "/data/layers"
    chroma_persist_dir: str = "/data/chroma"
    attack_stix_dir: str = "/data/attack"
    attack_collection: str = "attack_techniques"
    report_chunks_collection: str = "report_chunks"
    report_windows_collection: str = "report_windows"
    ollama_host: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_embed_model: str = "nomic-embed-text"
    # Concurrent per-chunk LLM calls in the mapping stage. Keep in sync with
    # the ollama service's OLLAMA_NUM_PARALLEL (docker-compose.yml) — extra
    # workers beyond that just queue server-side. -1 = auto by machine RAM,
    # matching the CPU profile's slot auto-sizing (see resolve_map_workers
    # in app.core.llm and the docker-compose.cpu.yml ollama entrypoint).
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
    # Inject ATT&CK ids cited literally in a chunk's text (e.g. "[T1573]" in
    # CISA advisories) into that chunk's candidate list ahead of retrieval —
    # dense/BM25 can't surface them (KB documents carry names + descriptions,
    # not ids). Set EXPLICIT_IDS=false to score pure retrieval in an ablation.
    explicit_ids: bool = True
    # Sub-chunk retrieval halves: sentence-window dense queries (embedded at
    # ingest into report_windows) and per-sentence rank-pooled BM25, fused
    # alongside the chunk-level dense half. Recovers techniques evidenced by a
    # single sentence inside a chunk about something else. Set
    # SENTENCE_RETRIEVAL=false for a chunk-granularity-only ablation run
    # (windows are still embedded at ingest, so the flag flips without
    # re-ingesting).
    sentence_retrieval: bool = True
    # Per-window priority seats in fusion: every sentence window's top-N dense
    # hits are seated in the fused top_k AHEAD of fused-score ordering (deduped
    # across windows; ordered by per-window rank tier, then fused score, if
    # they alone would overflow top_k). Without this, rank-pooling ties all
    # windows' #1 hits at pooled rank 1 and a minority sentence's #1 sorts
    # behind the majority cluster's tie-break, misses the pooled half's
    # RESERVE_PER_HALF prefix, and RRF buries it (measured on the Meridian
    # Health report: 8 of 11 missed core techniques ranked ≤6 in the right
    # chunk's windows — T1059.001 at window rank 1 — yet never became
    # candidates; merely *reserving* them measured no better, because
    # fused-score selection among a large reserved set re-buries them).
    # Set WINDOW_SEAT_DEPTH=0 to disable for an ablation run.
    window_seat_depth: int = 1
    # Default mode for the mapping verification pass: each accepted mapping
    # gets one small yes/no judge call (technique description + evidence quote
    # + the ±220-char passage around it). Measured N=8 on both eval reports:
    # judge-rejected mappings are FPs about twice as often as not (Health
    # unexpected 19.9→10.1/run when removed) but include some solid techniques
    # (T1490, T1021.002 went to 0/8) — so what to DO with a rejection is the
    # user's per-run choice, exposed in the upload UI and as `verify_mode` on
    # POST /reports/{id}/map (which overrides this default):
    #   "off"    — no judging (fastest; every verdict kept as-is)
    #   "demote" — flagged mappings are kept but capped at a near-floor score
    #              and their comment marked, so they fall to the faint end of
    #              the matrix instead of vanishing (the balanced middle)
    #   "drop"   — flagged mappings are removed (max precision)
    # Verification errors always fail open (mapping kept unchanged).
    verify_mode: str = "off"
    cors_origins: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
