FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server_online.py /app/server_online.py
COPY static /app/static
# Os Volumes da Railway sao montados pelo usuario root; arquivos persistem em /data.
# Nunca inclua tokens, .env, banco ou fotos reais na imagem.
CMD ["sh", "-c", "exec python server_online.py --host 0.0.0.0 --port ${PORT:-8787}"]
