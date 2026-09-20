# ---------- NetPulse ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# iputils-ping gives the `ping` fallback; libpq not needed for SQLite.
RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts

# Non-root user. Grant CAP_NET_RAW at runtime for ICMP (see docker-compose).
RUN useradd -m -u 10001 netpulse && chown -R netpulse:netpulse /app
USER netpulse

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
