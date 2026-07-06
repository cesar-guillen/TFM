# TFM — ATT&CK Mapper

Trabajo de Fin de Máster (César Guillén Cuñat). A locally-run, Dockerized tool that ingests security artifacts (incident reports, pentest reports, security policies) and automatically generates a MITRE ATT&CK matrix of observed TTPs, with a chat interface to ask questions about or edit the result.

**Fully local**: everything (parsing, retrieval, LLM) runs on-premise via Docker. No uploaded report data is ever sent to an external/cloud API.

See [CLAUDE.md](CLAUDE.md) for the full architecture/pipeline description and development guidelines.

## Status

This is an early scaffold. What works end-to-end today:

- `POST /api/ingest` — upload a PDF, get back its Markdown conversion (via `pymupdf4llm`).
- `app.attack.build_kb` — one-time offline builder that downloads the Enterprise ATT&CK STIX bundle, extracts the ~700 active techniques, embeds them via Ollama, and indexes them into a Chroma collection. See CLAUDE.md for the command.
- Frontend shell with a working upload panel, and placeholder Matrix/Chat panels.

Not implemented yet: chunking and hybrid (BM25 + dense) retrieval against the report, LLM-based technique mapping, and aggregation — i.e. pipeline stages 3, 4, 6, 7 in CLAUDE.md. `/api/chat` and `/api/matrix` are stubs.

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

```
docker compose up --build
```

(Every setting has a working default baked into `docker-compose.yml`; create a `.env` only to override them — ports, model names, `MAP_WORKERS`/`OLLAMA_NUM_PARALLEL` parallelism.)

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
