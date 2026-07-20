FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache \
    TELEMETRY_MAX_CONCURRENCY=2 \
    TELEMETRY_MAX_PLOT_POINTS=1200 \
    TELEMETRY_CACHE_DIR=/data/telemetry-pdfs \
    TELEMETRY_CACHE_MAX_DOCS=100 \
    TELEMETRY_CACHE_MAX_MB=500

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    fontconfig \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

COPY . .

RUN useradd --create-home --shell /usr/sbin/nologin appuser && \
    mkdir -p /data/telemetry-pdfs && \
    chown -R appuser:appuser /app /data

EXPOSE 5050

CMD ["python", "docker_entrypoint.py"]
