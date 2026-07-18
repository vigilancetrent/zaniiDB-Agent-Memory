FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .

# Data lives in a volume; SQLite + scenes + persona + refs under /data
ENV ZANII_DATA_DIR=/data \
    ZANII_GATEWAY_HOST=0.0.0.0 \
    ZANII_GATEWAY_PORT=8520
VOLUME /data
EXPOSE 8520

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8520/health',timeout=4).status==200 else 1)"

CMD ["zanii-memory", "serve"]
