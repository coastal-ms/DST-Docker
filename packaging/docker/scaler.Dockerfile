FROM python:3.13-slim-bookworm
RUN groupadd --gid 10001 dst && useradd --uid 10002 --gid 10001 --no-create-home scaler
LABEL io.dst.scaler="true"
COPY packaging/docker/scaler.py /opt/dst-scaler.py
USER 10002:10001
ENTRYPOINT ["python3", "-B", "/opt/dst-scaler.py"]
