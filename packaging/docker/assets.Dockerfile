FROM ubuntu:24.04
LABEL io.dst.asset-installer="true"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates python3 lib32gcc-s1 lib32stdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 dst && useradd --uid 10001 --gid dst --create-home dst \
    && mkdir -p /srv/dst && chown dst:dst /srv/dst
COPY packaging/docker/assets.py /assets.py
COPY packaging/docker/asset_version.py /asset_version.py
USER 10001:10001
ENV HOME=/home/dst
ENTRYPOINT ["python3", "-B", "/assets.py"]
