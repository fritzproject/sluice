FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir ".[web]"

# Stesso utente usato dalla maggior parte delle immagini per server domestici:
# i file scaricati restano leggibili e spostabili dagli altri servizi, invece
# di appartenere a root e bloccare chi deve importarli.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "$GID" sluice 2>/dev/null || true \
    && useradd -u "$UID" -g "$GID" -M sluice 2>/dev/null || true \
    && mkdir -p /downloads /state && chown -R "$UID:$GID" /downloads /state /app
USER $UID:$GID

ENV SLUICE_DOWNLOAD_ROOT=/downloads \
    SLUICE_STATE_DIR=/state

VOLUME ["/downloads", "/state"]
EXPOSE 8420

ENTRYPOINT ["sluice"]
CMD ["serve", "--port", "8420"]
