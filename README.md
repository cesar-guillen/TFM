# TFM — ATT&CK Mapper

Trabajo de Fin de Máster (César Guillén Cuñat). A locally-run, Dockerized tool that ingests security artifacts (incident reports, pentest reports, security policies) and automatically generates a MITRE ATT&CK matrix of observed TTPs, with a chat interface to ask questions about or edit the result.

**Fully local**: everything (parsing, retrieval, LLM) runs on-premise via Docker. No uploaded report data is ever sent to an external/cloud API.

See [CLAUDE.md](CLAUDE.md) for the full architecture/pipeline description and development guidelines.

## Status

This is an early scaffold. What works end-to-end today:

- `POST /api/ingest` — upload a PDF, get back its Markdown conversion (via `pymupdf4llm`).
- Frontend shell with a working upload panel, and placeholder Matrix/Chat panels.

Not implemented yet: chunking, hybrid (BM25 + dense) retrieval, the ATT&CK knowledge base, LLM-based technique mapping, and aggregation — i.e. pipeline stages 3–7 in CLAUDE.md. `/api/chat` and `/api/matrix` are stubs.

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
frontend/
  src/
    App.tsx             3-pane shell
    components/         UploadPanel (real), MatrixView, ChatPanel (placeholders)
    api/client.ts        fetch wrapper
data/
  uploads/              uploaded PDFs (gitignored)
  chroma/                vector store persistence (gitignored)
docker-compose.yml
.env.example
```

## Running it

```
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (`/health`, `/api/ingest`, `/api/chat`, `/api/matrix`)
- Ollama: http://localhost:11434

Pull the models the first time (names configurable in `.env`):

```
docker compose exec ollama ollama pull llama3.1:8b
docker compose exec ollama ollama pull nomic-embed-text
```

Uploaded reports persist under `./data/uploads/`; the vector store persists under `./data/chroma/`.

**Note on `OLLAMA_HOST`**: inside `docker-compose.yml` this is set to `http://ollama:11434` — `ollama` is the Compose service name, resolved by Docker's internal DNS to that container's private IP on the local Compose network. This is still entirely local (no traffic leaves the host); it's just how containers address each other instead of `localhost`, since each container has its own network namespace.

### Host prerequisites

- Docker Engine + the Compose v2 plugin (`docker compose version` should work). On this machine that came from the `docker-compose-v2` apt package.
- Your user must be in the `docker` group (`groups` should list `docker`) to run Docker commands without `sudo`.

## Next steps

Per the pipeline in CLAUDE.md, the next stages to build are chunking (stage 3) and/or the ATT&CK knowledge base builder (stage 5).
