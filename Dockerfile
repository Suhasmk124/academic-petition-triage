FROM python:3.11-slim@sha256:b7a9e5f6a93d6d4a31f129bbd4bdee69efccb6ded0fb230d78aafaf37af98377
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src HF_HOME=/models TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-ops.txt ./
RUN pip install --no-cache-dir torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements.txt -r requirements-ops.txt
COPY src ./src
COPY scripts ./scripts
COPY load ./load
COPY prompts ./prompts
COPY data/raw ./data/raw
COPY data/processed ./data/processed
COPY evaluations/scenarios.json evaluations/safety_scenarios.json ./evaluations/
COPY tests ./tests
RUN mkdir -p /app/data/runtime /app/data/chroma_db /app/work /app/logs /models && useradd --uid 10001 --create-home triage && chown -R triage:triage /app /models
USER triage
EXPOSE 8000
CMD ["python","-m","uvicorn","api:app","--app-dir","src","--host","0.0.0.0","--port","8000"]
