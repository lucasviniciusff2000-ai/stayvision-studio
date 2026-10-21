FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
# Free/local image processing and offline MP4 production; no external AI account needed.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt
COPY server_online.py /app/server_online.py
COPY ai_engine.py /app/ai_engine.py
COPY photo_engine_v2.py /app/photo_engine_v2.py
COPY payments_readiness.py /app/payments_readiness.py
COPY payment_reconciliation.py /app/payment_reconciliation.py
COPY checkout_production.py /app/checkout_production.py
COPY seller_identity.py /app/seller_identity.py
COPY static /app/static
# Railway volume mounts as /data, never put tokens or clients' photos in Docker.
CMD ["sh", "-c", "exec python server_online.py --host 0.0.0.0 --port ${PORT:-8787}"]
