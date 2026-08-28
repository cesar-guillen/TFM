# TFM — ATT&CK Mapper

Trabajo de Fin de Máster (César Guillén Cuñat). A locally-run, Dockerized tool that ingests security artifacts (incident reports, pentest reports, security policies) and automatically generates a MITRE ATT&CK matrix of observed TTPs, with a chat interface to ask questions about or edit the result.

**Fully local**: everything (parsing, retrieval, LLM) runs on-premise via Docker. No uploaded report data is ever sent to an external/cloud API.

See [CLAUDE.md](CLAUDE.md) for the full architecture/pipeline description and development guidelines.

## Status

The whole pipeline works end-to-end:

- **Ingest**: upload a PDF → Markdown conversion (`pymupdf4llm`) → section-aware chunking with role filtering (remediation/boilerplate sections excluded) → embedding into a local Chroma store, with live progress in the UI.
- **Retrieval**: hybrid dense + BM25 search over the bundled ATT&CK v19.1 knowledge base (~700 techniques, pre-embedded seed ships in the repo), fused by reciprocal rank fusion.
- **Mapping**: a local LLM (via Ollama) judges which candidate techniques each chunk actually evidences — schema-constrained output, verbatim evidence quotes checked against the source text — then results are aggregated into a Navigator-style layer with per-technique evidence comments (strongest evidence first). Supports both **incident reports** (maps the attacker's observed actions) and **pentest / red-team reports** (maps the testers' performed actions; findings merely noted but not exploited are excluded) — chosen per upload in the options dialog, along with false-positive filtering and the technique-judging mode.
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
- **CPU** keeps the same `llama3.1:8b` quality, with idle memory release. Parallelism is auto-sized from RAM at startup: 4 concurrent decodes on ≥10 GiB machines (~6 GB footprint), 2 below that (~5.5 GB) — so it also fits the ~7 GiB VM that WSL2 gives a 16 GB Windows machine by default (see the WSL2 note below). Mapping takes minutes instead of seconds.
- **Basic** swaps to the small `llama3.2:3b` model (~2 GB download, ~4 GB footprint) — noticeably worse mappings, but it runs on modest laptops.

**WSL2 / Docker Desktop note**: by default WSL2 gives the Linux VM only **half the host's RAM** — a 16 GB Windows machine runs everything inside a ~7.2 GiB VM, and that VM total (not the host's 16 GB) is what the auto-sizing sees. The CPU profile fits, but with little headroom; for comfort (or to get the 4-worker tier back) give the VM more memory: create `C:\Users\<you>\.wslconfig` with

```ini
[wsl2]
memory=12GB
```

then run `wsl --shutdown` from Windows and restart Docker.

Both CPU profiles automatically pin inference to **all CPU threads except two** (computed at container start, whatever the core count), so the machine stays responsive while a report is being mapped.

**Apple Silicon (M-series) Macs / ARM64**: the whole stack runs natively on `linux/arm64` — the frontend lockfile ships every platform's native binaries (esbuild/Rollup), and every backend dependency and the `ollama/ollama` image have arm64 builds, so no source compilation is needed. Use the **No GPU** profile (`docker-compose.cpu.yml`, or `docker-compose.basic.yml` on ≤8 GB): the GPU override is NVIDIA-only, and a Mac's Metal GPU isn't reachable from inside a Docker container anyway, so inference runs on CPU. (Docker Desktop on a Mac builds and runs arm64 containers by default — don't force `platform: linux/amd64`, which would run everything under slow x86 emulation.)

Tip: to make your profile stick so plain `docker compose up` / `docker compose down` uses it, add a line to `.env`, e.g. `COMPOSE_FILE=docker-compose.yml:docker-compose.cpu.yml`.

(Every other setting has a working default baked into `docker-compose.yml`; create a `.env` only to override them — ports, model names, `MAP_WORKERS`/`OLLAMA_NUM_PARALLEL` parallelism. Values set in `.env` win over profile defaults.)

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (`/health`, `/api/ingest`, `/api/chat`, `/api/matrix`)
- Ollama: http://localhost:11434

That's the only command needed. On first boot the `ollama-init` service pulls the two Ollama models (names configurable in `.env`; the chat model is a ~4.7 GB download, so the backend waits a few minutes before starting), and the backend restores the pre-embedded ATT&CK knowledge base into Chroma on startup. Both steps are near-instant no-ops on every boot after that.

> **First start looks stuck?** It isn't — it's the model download. With `up -d` the only visible sign is the backend sitting in "Waiting". Watch the download live (progress heartbeat every 20 s) with:
>
> ```
> docker compose logs -f ollama-init
> ```

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

## AWS EC2 deployment (single-user, HTTPS + Basic Auth)

`docker-compose.aws.yml` is a **standalone** production compose file (not
merged with the files above) for hosting the app on an internet-facing EC2
GPU instance, gated by a single hardcoded username/password. It puts
[Caddy](https://caddyserver.com/) in front of everything: Caddy terminates
TLS (an automatic, auto-renewing Let's Encrypt certificate for your domain),
enforces HTTP Basic Auth for the one account, serves the frontend's static
production build, and reverse-proxies `/api/*` to the backend. `backend` and
`ollama` are not published to the host at all in this file — Caddy's 80/443
are the only ports exposed, so nothing else is reachable even if the AWS
security group were misconfigured.

No application code changes are involved — auth and TLS live entirely at the
proxy layer, and since the frontend and API end up same-origin behind Caddy,
the frontend's existing relative `/api/...` fetches work unmodified.

### 1. Buy/point a domain

Any domain works, even a cheap one — Caddy just needs a real DNS name to
request a certificate for. Don't point the A record yet; do that after step 4
once you have a stable IP.

### 2. Launch the EC2 instance

- Type: a GPU instance, e.g. `g4dn.xlarge` (matches this project's tested
  GPU profile).
- AMI: Ubuntu 22.04 LTS (or an NVIDIA-driver-preinstalled "Deep Learning
  Base" AMI if available in your region, to skip the driver install below).
- Storage: **≥120GB gp3** root volume (model weights + Docker images +
  Chroma + uploaded reports add up fast), EBS encryption on.

### 3. Security group

- `22/tcp` — inbound from **your IP only** (not `0.0.0.0/0`).
- `80/tcp` and `443/tcp` — inbound from `0.0.0.0/0` (80 is needed for the
  Let's Encrypt ACME challenge and the HTTP→HTTPS redirect).
- Nothing else. `8000`/`5173`/`11434` are never opened here, matching
  `docker-compose.aws.yml` never publishing them in the first place —
  defense in depth.

### 4. Elastic IP

Allocate and associate an Elastic IP with the instance so the public IP (and
therefore the DNS record and the issued certificate) survives a stop/start.
Then point your domain's A record at this IP.

### 5. Install Docker + NVIDIA support on the instance

```
sudo apt-get update && sudo apt-get install -y ca-certificates curl gnupg

# Docker Engine + Compose v2 plugin
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # log out/in (or `newgrp docker`) to pick this up

# NVIDIA driver (skip if using a Deep-Learning AMI that already has it)
sudo ubuntu-drivers autoinstall
sudo reboot   # then reconnect

# NVIDIA Container Toolkit
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify:
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 6. Clone the repo and check out this branch

```
git clone <your-repo-url>
cd TFM
git checkout aws-ec2-deploy
```

### 7. Configure `.env`

```
cp .env.example .env
```

Edit `.env` and set:
- `OLLAMA_MODEL=llama3.1:8b` (the GPU-profile model — full quality).
- `DOMAIN=yourdomain.com`
- `BASIC_AUTH_USER=` your chosen username.
- `BASIC_AUTH_HASH=` — generate with (use a long random password, e.g.
  `openssl rand -base64 24`):
  ```
  docker run --rm caddy:2-alpine caddy hash-password --plaintext 'your-password-here'
  ```
  Note this stores a **bcrypt hash**, never the plaintext password.

Then `chmod 600 .env` and never commit it (it's already gitignored).

### 8. Bring the stack up

```
docker compose -f docker-compose.aws.yml up -d --build
docker compose -f docker-compose.aws.yml exec backend python -m app.attack.build_kb
```

Watch first-run progress:
```
docker compose -f docker-compose.aws.yml logs -f ollama-init   # model download (first run only)
docker compose -f docker-compose.aws.yml logs -f caddy         # certificate issuance
```

### 9. Verify

Visit `https://yourdomain.com`, log in with the configured credentials, and
run a real report through the pipeline end to end to confirm GPU mapping
works.

### 10. Ongoing hygiene

- `sudo apt update && sudo apt upgrade -y` periodically, or enable
  `unattended-upgrades`.
- `.env` holds the auth hash and domain — keep it `chmod 600` and never
  commit it.

### 11. Tearing it down (e.g. once grading is finished)

```
docker compose -f docker-compose.aws.yml down
```
Then, in the AWS console: terminate the instance, release the Elastic IP,
delete the security group, and remove/let lapse the DNS record and domain if
you no longer need them — this stops all associated billing.

## Next steps

Per the pipeline in CLAUDE.md, the next stage to build is chunking (stage 3) and hybrid retrieval (stage 4) against the report, now that the ATT&CK knowledge base (stage 5) is in place.

1. Base packages
```
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
```
2. Install Docker Engine + Compose v2 (official Docker repo)
```
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
3. Run Docker without sudo + start the daemon

sudo usermod -aG docker $USER
sudo systemctl enable --now docker
```
Log out and back in (or reboot) so the group change applies, then verify:

```
docker run --rm hello-world
docker compose version        # must say v2.x
```
4. Get the project
```
git clone <your-repo-url> TFM
cd TFM
```
5. Launch — pick ONE profile for the machine

# No GPU, more than 8 GB RAM (the usual case):
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build

# No GPU, 8 GB RAM or less:
docker compose -f docker-compose.yml -f docker-compose.basic.yml up -d --build

# NVIDIA GPU (needs step 7 first):
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

