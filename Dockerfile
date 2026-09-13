FROM python:3.12-slim

# util-linux provides setpriv, used by the entrypoint to drop privileges.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates util-linux \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p /downloads /state

# PUID/PGID are read at startup, so one image works for everyone: set them to
# whatever user the programs sharing the download folder run as.
ENV SLUICEBOX_DOWNLOAD_ROOT=/downloads \
    SLUICEBOX_STATE_DIR=/state \
    PUID=1000 \
    PGID=1000

VOLUME ["/downloads", "/state"]
EXPOSE 8420

ENTRYPOINT ["docker-entrypoint.sh", "sluicebox"]
CMD ["serve", "--port", "8420"]
