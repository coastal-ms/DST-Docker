FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends bash binutils procps \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dst \
    && mkdir -p /var/lib/dst-atlas/readers \
    && printf '#!/bin/sh\nexec "$@"\n' > /usr/local/bin/sudo \
    && chmod 755 /usr/local/bin/sudo
LABEL io.dst.map-observer="true"
COPY packaging/docker/map-observer.py /opt/dst-map-observer.py
ENTRYPOINT ["python3", "-B", "/opt/dst-map-observer.py"]
