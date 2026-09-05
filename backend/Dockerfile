FROM python:3.12-slim

# Unbuffered stdout so startup prints (KB build/restore progress) reach
# `docker compose up` logs as they happen instead of on process exit.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# tesseract-ocr: OCR for embedded screenshots (app/ingest/ocr.py) — the text
# layer can't see console output, dashboards, or sandbox logs shown only as
# images (see CLAUDE.md's Known limitations). Build stages run with full
# privileges regardless of the runtime cap_drop in docker-compose.yml, so a
# plain install here needs none of that container's privilege-drop workarounds.
RUN apt-get update -qq \
    && apt-get install -y -qq --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
