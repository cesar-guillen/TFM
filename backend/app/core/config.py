from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upload_dir: str = "/data/uploads"
    layers_dir: str = "/data/layers"
    chroma_persist_dir: str = "/data/chroma"
    attack_stix_dir: str = "/data/attack"
    attack_collection: str = "attack_techniques"
    attack_examples_collection: str = "attack_examples"
    # Merge ATT&CK procedure-example vectors into the dense retrieval halves
    # (see app.attack.build_examples). EXPERIMENTAL, off by default: the
    # examples demonstrably close the vocabulary gap (systematically
    # unretrievable techniques like T1489 reach window-rank 4-8 once report
    # phrasing can match "Babuk can stop specific services related to
    # backups"), but under the current 8-candidate verdict menu the coverage
    # A/B measured a net LOSS — added example hits displace
    # previously-reachable techniques from the fused top-8 (Meridian Health
    # core reachable 18→15; T1059.001/T1547.001/T1570 lost their window
    # seats), and the two failed variants (concatenating examples into
    # technique documents; deeper window-seat quotas) are documented in
    # CLAUDE.md. Kept for the per-candidate-verdicts redesign, where
    # candidates don't compete for menu slots and this collection plugs
    # straight in. Retrieval degrades gracefully to KB-only if the collection
    # was never built.
    example_retrieval: bool = False
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
    # Cross-encoder reranking of the fused candidate pool (app.retrieval.rerank).
    # EXPERIMENTAL, off by default — measured 2026-08-24 (cycle 12) and it is
    # the cleanest demonstration yet that *coverage is a veto, not a predictor*:
    # it improved exact-reachable coverage on 2 of 3 labelled reports and
    # regressed none (20/16/24 -> 22/17/24, the best selection profile of the
    # whole tuning series), and then LOST exact F1 on 3 of 3 (0.596->0.577,
    # 0.597->0.568, 0.734->0.650; mean 0.642 -> 0.598). Mechanism, per-report:
    # on openslop and health it did exactly what it was built to do — recall up
    # (16.8->18.8, 11.5->12.0) — but roughly doubled false positives
    # (5.5->12.2, 3.0->6.2), because the candidates it promotes are plausible
    # cousins the 8b then accepts; on grove, where coverage was unchanged, exact
    # recall still collapsed 21.0->16.8 purely because the *identity* of the 8
    # candidates changed (menu-composition sensitivity, the same effect that
    # killed cycles 6-9). Kept behind this flag for the per-candidate-verdicts
    # redesign (VERDICT_MODE=independent), where menu composition cannot exist
    # and a recall-raising selector should convert — the same reasoning that
    # keeps EXAMPLE_RETRIEVAL around. Runs locally on CPU via onnxruntime +
    # tokenizers (already dependencies via chromadb); degrades to a no-op when
    # the model files are absent, so enabling it on a checkout that never
    # fetched them is safe.
    rerank: bool = False
    rerank_model_dir: str = "/data/reranker"
    # int8-quantized ms-marco-MiniLM-L-6-v2: measured identical coverage to the
    # 87MB fp32 model (63, improving 2 of 3 reports and regressing none) at
    # 2.7s/chunk vs 10.6s, from a 22MB file.
    rerank_model_file: str = "model_int8.onnx"
    rerank_threads: int = 4
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
    # Default flipped "off" → "drop" 2026-08-22 after the grouped-mode A/B
    # (harness, --runs 4 --top-k 8 --verdict menu, all three labelled incident
    # reports): exact F1 openslop 0.481→0.558, health 0.472→0.551 (0.456 on a
    # same-session off re-run), grove 0.700→0.736; unexpected/run 10.2→3.5,
    # 19.8→9.5, 10.0→6.5; exact recall flat (14→14.5, 13→12.8, 21.5→21.2) at
    # ~+27% wall time. `demote` scores like `off` on this harness by
    # construction (it removes nothing and the harness ignores confidence).
    # Known cost: the judge's named-mechanism blind spot deterministically
    # rejects T1490 Inhibit System Recovery on shadow-copy/backup-catalog
    # phrasing (3/3 in a direct probe), so that core technique goes 4/4 → 0/4
    # on both ransomware reports. See docs/grouped-tuning-log.md cycle 2.
    # Default changed "drop" → "demote" 2026-08-28 at the user's explicit
    # request: dropping silently risks losing a real technique with no way to
    # notice, whereas demote keeps everything visible — a flagged mapping now
    # renders with a yellow-outlined cell in the matrix (see ChunkMapping.flagged
    # / aggregate_mappings' metadata below and AttackMatrix.tsx) instead of the
    # old "[flagged by verification]" text prefix, so the reviewer sees exactly
    # which cells to double-check without losing any of them outright.
    verify_mode: str = "demote"
    # Verdict architecture (EXPERIMENTAL): "menu" = one LLM call per chunk
    # with all retrieval candidates offered at once (the original design);
    # "independent" = one small call per candidate ("does the excerpt
    # evidence THIS technique?"), chunk-first prompts so Ollama's prefix
    # cache absorbs the repeated chunk text. Rationale: three retrieval
    # experiments (family expansion, procedure examples, seat tuning) all
    # died on the same wall — candidates compete for 8 menu slots, and the
    # 8b's menu verdicts are composition-sensitive (techniques at unchanged
    # candidate ranks flip 8/8→0/8 when the menu merely grows). Independent
    # verdicts remove slot competition and menu sensitivity by construction;
    # the open risk is over-acceptance, gated by the same evidence-quote
    # validation. More decode per chunk (~1.5-2.5× wall on GPU) — keep
    # "menu" on CPU-only hosts.
    verdict_mode: str = "menu"
    # Default prompt family for the mapping stage: "incident" (post-incident /
    # IR write-ups — the intruder is the adversary, defender/victim activity
    # is not evidence) or "pentest" (penetration-test / red-team reports —
    # the testers play the adversary, usually narrating in the first person,
    # and findings merely identified but not exploited are not evidence).
    # Chosen per run in the upload dialog and sent as `report_type` on
    # POST /reports/{id}/map, which overrides this default.
    report_type: str = "incident"
    cors_origins: list[str] = ["http://localhost:5173"]

    class Config:
        env_file = ".env"


settings = Settings()
