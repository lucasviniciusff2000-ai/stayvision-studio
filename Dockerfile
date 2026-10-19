FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY preview_server.py /app/preview_server.py
COPY static /app/static
USER 65532:65532
CMD ["python", "preview_server.py"]
