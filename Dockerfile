# Multi-stage, rootless, distroless container image for Platform Resilience Tools
# Hardened against DoD Platform One / Chainguard Python baseline

# Build stage
FROM cgr.dev/chainguard/python:latest-dev AS builder
WORKDIR /app

COPY scripts/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final hardened production runtime (Distroless / Non-root 65532)
FROM cgr.dev/chainguard/python:latest
WORKDIR /app

COPY --from=builder /home/nonroot/.local /home/nonroot/.local
COPY scripts/ /app/scripts/

USER 65532:65532
ENV PATH="/home/nonroot/.local/bin:$PATH"
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "/app/scripts/lease_pruner.py"]
CMD ["--check-only"]
