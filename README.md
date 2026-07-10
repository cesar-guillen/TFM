# TFM — ATT&CK Mapper

Trabajo de Fin de Máster (César Guillén Cuñat). A locally-run, Dockerized tool that ingests security artifacts (incident reports, pentest reports, security policies) and automatically generates a MITRE ATT&CK matrix of observed TTPs, with a chat interface to ask questions about or edit the result.

**Fully local**: everything (parsing, retrieval, LLM) runs on-premise via Docker. No uploaded report data is ever sent to an external/cloud API.

See [CLAUDE.md](CLAUDE.md) for the full architecture/pipeline description and development guidelines.

## Status

The whole pipeline works end-to-end:

- **Ingest**: upload a PDF → Markdown conversion (`pymupdf4llm`) → section-aware chunking with role filtering (remediation/boilerplate sections excluded) → embedding into a local Chroma store, with live progress in the UI.
- **Retrieval**: hybrid dense + BM25 search over the bundled ATT&CK v19.1 knowledge base (~700 techniques, pre-embedded seed ships in the repo), fused by reciprocal rank fusion.
- **Mapping**: a local LLM (via Ollama) judges which candidate techniques each chunk actually evidences — schema-constrained output, verbatim evidence quotes checked against the source text — then results are aggregated into a Navigator-style layer with per-technique evidence comments.
- **UI**: a matrix library dashboard (open/edit/delete previously computed matrices, upload new reports), a live-updating matrix preview during runs, and a full Navigator-style editor with scoring, sorting, JSON/SVG export, and save-to-library.

Not implemented yet: the chat interface (`/api/chat` is a stub) and a reranker over the fused retrieval candidates.

## Stack

- **Backend**: FastAPI (Python 3.12)
- **Frontend**: React + TypeScript + Vite
- **LLM / embeddings**: [Ollama](https://ollama.com), run as its own container
- **Retrieval**: Chroma (embedded, in-process) + `rank_bm25` for hybrid search
- **Docker Compose services**: `backend`, `frontend`, `ollama`

## Project layout

```
backend/
  app/
    main.py            FastAPI app, CORS, router mounting, /health
    core/config.py     Settings (env vars)
    api/routes/         ingest.py (real), chat.py (stub), matrix.py (stub)
    ingest/             pdf_to_markdown.py — pymupdf4llm wrapper
    attack/             ATT&CK knowledge base builder (stix_source.py, techniques.py, embeddings.py, build_kb.py)
frontend/
  src/
    App.tsx             3-pane shell
    components/         UploadPanel (real), MatrixView, ChatPanel (placeholders)
    api/client.ts        fetch wrapper
data/
  uploads/              uploaded PDFs (gitignored)
  chroma/                vector store persistence (gitignored)
  attack/                cached ATT&CK STIX bundle (gitignored)
docker-compose.yml
.env.example
```

## Running it

Pick the profile that matches your machine — one command, nothing else to configure:

| Your machine | Command |
|---|---|
| NVIDIA GPU, >8 GB RAM | `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build` |
| No GPU, >8 GB RAM | `docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build` |
| No GPU, ≤8 GB RAM | `docker compose -f docker-compose.yml -f docker-compose.basic.yml up -d --build` |

- **GPU** runs the full-power configuration: `llama3.1:8b`, 4 parallel workers, models pinned in memory. Requires the NVIDIA Container Toolkit (see below). Mapping a report takes ~30-60 s.
- **CPU** keeps the same `llama3.1:8b` quality and parallelism, with idle memory release (~8.5 GB footprint). Mapping takes minutes instead of seconds. (If the machine swaps during runs, set `OLLAMA_NUM_PARALLEL=2` and `MAP_WORKERS=2` in `.env`.)
- **Basic** swaps to the small `llama3.2:3b` model (~2 GB download, ~4 GB footprint) — noticeably worse mappings, but it runs on modest laptops.

Both CPU profiles automatically pin inference to **all CPU threads except two** (computed at container start, whatever the core count), so the machine stays responsive while a report is being mapped.

Tip: to make your profile stick so plain `docker compose up` / `docker compose down` uses it, add a line to `.env`, e.g. `COMPOSE_FILE=docker-compose.yml:docker-compose.cpu.yml`.

(Every other setting has a working default baked into `docker-compose.yml`; create a `.env` only to override them — ports, model names, `MAP_WORKERS`/`OLLAMA_NUM_PARALLEL` parallelism. Values set in `.env` win over profile defaults.)

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (`/health`, `/api/ingest`, `/api/chat`, `/api/matrix`)
- Ollama: http://localhost:11434

That's the only command needed. On first boot the `ollama-init` service pulls the two Ollama models (names configurable in `.env`; the chat model is a ~4.7 GB download, so the backend waits a few minutes before starting), and the backend restores the pre-embedded ATT&CK knowledge base into Chroma on startup. Both steps are near-instant no-ops on every boot after that.

Uploaded reports persist under `./data/uploads/`; the vector store persists under `./data/chroma/`; Ollama models persist in the `ollama_models` volume.

To rebuild the ATT&CK knowledge base from a newer MITRE release (re-embeds via Ollama and rewrites the bundled seed — see CLAUDE.md):

```
docker compose exec backend python -m app.attack.build_kb --refresh
```

**Note on `OLLAMA_HOST`**: inside `docker-compose.yml` this is set to `http://ollama:11434` — `ollama` is the Compose service name, resolved by Docker's internal DNS to that container's private IP on the local Compose network. This is still entirely local (no traffic leaves the host); it's just how containers address each other instead of `localhost`, since each container has its own network namespace.

### Host prerequisites

- Docker Engine + the Compose v2 plugin (`docker compose version` should work). On this machine that came from the `docker-compose-v2` apt package.
- Your user must be in the `docker` group (`groups` should list `docker`) to run Docker commands without `sudo`.

### GPU acceleration (optional, ~10x faster mapping)

With an NVIDIA GPU and the [NVIDIA container toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed:

```
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker   # WSL2 without systemd: sudo service docker restart

docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
```

Plain `docker compose up` keeps working on CPU-only machines.

## Next steps

Per the pipeline in CLAUDE.md, the next stage to build is chunking (stage 3) and hybrid retrieval (stage 4) against the report, now that the ATT&CK knowledge base (stage 5) is in place.
