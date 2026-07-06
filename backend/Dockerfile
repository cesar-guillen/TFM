FROM python:3.12-slim

# Unbuffered stdout so startup prints (KB build/restore progress) reach
# `docker compose up` logs as they happen instead of on process exit.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
