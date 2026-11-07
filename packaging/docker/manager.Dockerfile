FROM python:3.13-slim-bookworm
LABEL io.dst.asset-activator="true"
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir PyYAML==6.0.3
RUN groupadd --gid 10001 dst && mkdir -p /control /projects && chgrp dst /control && chmod 750 /control
COPY packaging/docker/engine.py packaging/docker/manager.py /opt/dst-manager/
COPY packaging/docker/resource_policy.py /opt/dst-manager/resource_policy.py
COPY packaging/docker/migration-job.py /opt/dst-manager/migration-job.py
COPY packaging/docker/backup-job.py /opt/dst-manager/backup-job.py
COPY packaging/docker/restore-job.py /opt/dst-manager/restore-job.py
COPY packaging/docker/world_template.py /opt/dst-manager/world_template.py
COPY packaging/docker/game_plan.py packaging/docker/connection_services.py /opt/dst-manager/
COPY packaging/docker/core_services.py packaging/docker/native-game.sh /opt/dst-manager/
COPY packaging/docker/rmq_commands.py /opt/dst-manager/rmq_commands.py
COPY packaging/docker/scale_protocol.py packaging/docker/scaler.py /opt/dst-manager/
COPY packaging/docker/director_policy.py /opt/dst-manager/director_policy.py
COPY packaging/docker/file_browser.py /opt/dst-manager/file_browser.py
COPY packaging/docker/asset_version.py /opt/dst-manager/asset_version.py
COPY packaging/docker/log_export.py /opt/dst-manager/log_export.py
COPY packaging/docker/assets.py packaging/docker/asset_updates.py /opt/dst-manager/
COPY packaging/docker/asset_activation.py /opt/dst-manager/asset_activation.py
COPY packaging/docker/service_generations.py /opt/dst-manager/service_generations.py
COPY packaging/docker/world_update.py /opt/dst-manager/world_update.py
COPY packaging/docker/settings_service.py packaging/docker/settings_client.py packaging/docker/settings_adapter.py /opt/dst-manager/
WORKDIR /opt/dst-manager
ENTRYPOINT ["python3", "-B", "manager.py"]
