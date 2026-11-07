# Standalone qualification image for the console's packaged Linux cache helper.
FROM mcr.microsoft.com/dotnet/sdk:10.0@sha256:212fe4cb74627d5adf9817a4088906ae3edff1bd853bb27565d4b46731efe61e AS build
WORKDIR /source
COPY app/tools/DunePlatformStore/ ./
COPY LICENSE /source/DST-LICENSE.txt
RUN dotnet publish DunePlatformStore.Linux.csproj -c Release -o /out
RUN mkdir -p /out/licenses \
    && cp DST-LICENSE.txt Linux/THIRD-PARTY-NOTICES.txt /out/licenses/ \
    && cp /root/.nuget/packages/microsoft.netcore.app.runtime.linux-x64/10.0.14/LICENSE.TXT /out/licenses/DotNET-LICENSE.txt \
    && cp /root/.nuget/packages/microsoft.netcore.app.runtime.linux-x64/10.0.14/THIRD-PARTY-NOTICES.TXT /out/licenses/DotNET-THIRD-PARTY-NOTICES.txt \
    && cp /usr/share/common-licenses/Apache-2.0 /out/licenses/Apache-2.0.txt \
    && cp /root/.nuget/packages/microsoft.data.sqlite*/10.0.10/*.nuspec /root/.nuget/packages/sqlitepclraw.*/2.1.13/*.nuspec /out/licenses/
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 libssl3t64 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/ /tools/
USER 10001:10001
ENTRYPOINT ["/tools/DunePlatformStore"]
