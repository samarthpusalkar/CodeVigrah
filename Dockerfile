# CodeVigrah container image: the web UI plus the Anthropic SDK. Runs as an unprivileged user.
#   docker build -t codevigrah .
#   docker run -p 127.0.0.1:8765:8765 -v codevigrah-data:/data --env-file .env codevigrah
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 codevigrah \
    && mkdir /data && chown codevigrah /data

WORKDIR /app
COPY pyproject.toml README.md LICENSE THIRD_PARTY_NOTICES.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[anthropic]"

USER codevigrah
ENV CODEVIGRAH_HOST=0.0.0.0 \
    CODEVIGRAH_WORKSPACE=/data \
    PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=4)"
CMD ["codevigrah"]
