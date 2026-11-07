# Build tools only. The owner's Funcom content is never part of this image.
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:212fe4cb74627d5adf9817a4088906ae3edff1bd853bb27565d4b46731efe61e AS build
RUN mkdir -p /thirdparty/UAssetAPI /out/licenses /out/native \
    && curl -fsSL https://codeload.github.com/atenfyr/UAssetAPI/tar.gz/bee2f9b630ac679012c00dde0306eadcc8f21e2b -o /tmp/uassetapi.tar.gz \
    && echo 'c96c8429d8fd890bcb7b96cd9a6b7506dba99c2b3ed1a367e221c541bdfa2fd9  /tmp/uassetapi.tar.gz' | sha256sum -c - \
    && tar xzf /tmp/uassetapi.tar.gz --strip-components=1 -C /thirdparty/UAssetAPI \
    && cp /thirdparty/UAssetAPI/LICENSE /out/licenses/UAssetAPI-LICENSE.txt
WORKDIR /codec
COPY app/tools/DuneRegisAssetCodec/ ./
RUN dotnet publish DuneRegisAssetCodec.csproj -c Release -o /out/codec
WORKDIR /generator
COPY app/tools/DuneRegisTanks/Program.cs app/tools/DuneRegisTanks/DuneRegisTanks.Linux.csproj ./
RUN dotnet publish DuneRegisTanks.Linux.csproj -c Release -o /out/generator
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://github.com/trumank/retoc/releases/download/v0.1.5/retoc_cli-x86_64-unknown-linux-gnu.tar.xz -o /tmp/retoc.tar.xz \
    && echo '3c309a4aea0c6d0a5c6ee31b1d1b32768eb86ac67e3a1890d677eabe6ce26b36  /tmp/retoc.tar.xz' | sha256sum -c - \
    && mkdir /tmp/retoc && tar xJf /tmp/retoc.tar.xz -C /tmp/retoc \
    && find /tmp/retoc -type f -name retoc -exec cp '{}' /out/native/retoc ';' \
    && echo 'aa649cd8751a212ee946fa9c27f883770a9d67ca8d5f0b0c76ad856f44cf5eab  /out/native/retoc' | sha256sum -c -
RUN curl -fsSL https://raw.githubusercontent.com/WorkingRobot/OodleUE/refs/heads/main/Engine/Source/Programs/Shared/EpicGames.Oodle/Sdk/2.9.10/linux/lib/liboo2corelinux64.so.9 -o /out/native/liboo2corelinux64.so.9 \
    && echo 'ed7e98f70be1254a80644efd3ae442ff61f854a2fe9debb0b978b95289884e9c  /out/native/liboo2corelinux64.so.9' | sha256sum -c -
RUN cp /root/.nuget/packages/newtonsoft.json/13.0.3/LICENSE.md /out/licenses/Newtonsoft.Json-LICENSE.txt \
    && cp /root/.nuget/packages/microsoft.netcore.app.runtime.linux-x64/10.0.14/LICENSE.TXT /out/licenses/DotNET-LICENSE.txt \
    && cp /root/.nuget/packages/microsoft.netcore.app.runtime.linux-x64/10.0.14/THIRD-PARTY-NOTICES.TXT /out/licenses/DotNET-THIRD-PARTY-NOTICES.txt \
    && curl -fsSL https://raw.githubusercontent.com/trumank/retoc/v0.1.5/LICENSE -o /out/licenses/retoc-LICENSE.txt \
    && curl -fsSL https://raw.githubusercontent.com/oleg-st/ZstdSharp/f8ec37192fa4037b6580a80ce83c5a7664a322f7/LICENSE -o /out/licenses/ZstdSharp-LICENSE.txt
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
LABEL io.dst.regis-tools="true" io.dst.regis-serializer="bee2f9b630ac679012c00dde0306eadcc8f21e2b"
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 libstdc++6 libssl3t64 \
    && rm -rf /var/lib/apt/lists/* && mkdir /work && chown 1000:1000 /work
COPY --from=build /out/ /tools/
COPY app/resources/regis-tanks/ /tools/recipes/
COPY LICENSE /tools/licenses/DST-LICENSE.txt
COPY packaging/docker/regis_job.py /tools/regis_job.py
ENV LD_LIBRARY_PATH=/tools/native DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 HOME=/work
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["python3", "-B", "/tools/regis_job.py"]
