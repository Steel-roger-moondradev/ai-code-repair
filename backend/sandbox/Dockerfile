FROM python:3.12-slim

RUN useradd --create-home --uid 10001 sandbox
WORKDIR /workspace
RUN pip install --no-cache-dir pytest
USER sandbox

ENTRYPOINT ["python"]
