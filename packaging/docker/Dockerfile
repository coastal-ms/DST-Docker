FROM node:24-bookworm-slim AS web
WORKDIR /src/webui
COPY webui/package.json webui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY webui/ ./
COPY tools/assets/ /src/tools/assets/
COPY app/tools/DuneAtlas/ /src/app/tools/DuneAtlas/
COPY app/resources/solo-mods/dst-solo-live-map/Companion/ /src/app/resources/solo-mods/dst-solo-live-map/Companion/
ENV VITE_DST_EDITION=docker
RUN npm run build

FROM mcr.microsoft.com/powershell:7.5-ubuntu-24.04
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client curl ca-certificates python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dst && useradd --uid 10001 --gid dst --create-home dst \
    && mkdir -p /data/config/DuneServer /data/state/DuneServer /data/cache \
    && chown -R dst:dst /data
RUN python3 -m venv /opt/dst-python && /opt/dst-python/bin/pip install --no-cache-dir 'psycopg[binary]==3.3.8'
WORKDIR /opt/dst
COPY app/ ./app/
COPY dune-server.ps1 dune-server.config.example LICENSE NOTICE ./
COPY --from=web /src/webui/dist/ ./webui/dist/
COPY packaging/docker/healthcheck.ps1 /opt/dst/healthcheck.ps1
COPY packaging/docker/database.py /opt/dst/packaging/docker/database.py
COPY packaging/docker/manager-client.py /opt/dst/packaging/docker/manager-client.py
COPY packaging/docker/settings_client.py /opt/dst/packaging/docker/settings_client.py
COPY packaging/docker/atlas-service.py /opt/dst/packaging/docker/atlas-service.py
COPY packaging/docker/map-observer-client.py /opt/dst/packaging/docker/map-observer-client.py
ENV HOME=/home/dst XDG_CONFIG_HOME=/data/config XDG_STATE_HOME=/data/state XDG_CACHE_HOME=/data/cache \
    POWERSHELL_TELEMETRY_OPTOUT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DST_HOSTING_BACKEND=docker
USER 10001:10001
HEALTHCHECK --interval=20s --timeout=10s --start-period=60s --retries=3 CMD ["pwsh", "-NoLogo", "-NoProfile", "-File", "/opt/dst/healthcheck.ps1"]
ENTRYPOINT ["pwsh", "-NoLogo", "-NoProfile", "-File", "/opt/dst/app/DuneServer-Linux.ps1"]
CMD ["--headless", "--port", "18765"]
