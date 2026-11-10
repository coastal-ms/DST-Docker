FROM python:3.13-slim-bookworm
COPY packaging/docker/observer.py /observer.py
ENTRYPOINT ["python3", "-B", "/observer.py"]
