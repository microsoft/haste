FROM mcr.microsoft.com/azure-functions/python:4-nightly-python3.11-slim

RUN apt-get update && apt-get install -y \
    vim \
    curl \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

USER root

# Create non-root user before COPY so --chown can reference it
RUN groupadd -r appgroup && useradd -r -g appgroup -m -s /bin/bash appuser

# Copy files with correct ownership at copy time (avoids chown -R after the fact)
COPY --chown=appuser:appgroup hastelib/src/hastegeo /app/hastegeo
COPY --chown=appuser:appgroup docker/imageryprep/scripts /app/scripts/
COPY --chown=appuser:appgroup docker/imageryprep/requirements.txt /app/

# Install dependencies (no need to install haste package since we copy source directly)
RUN pip install -r /app/requirements.txt

# Provide CLI entrypoints expected by the workflows without requiring a separate package install
RUN printf '#!/bin/bash\nexec python -m haste.workflows.prepare_imagery "$@"\n' > /usr/local/bin/prepare-imagery \
    && printf '#!/bin/bash\nexec python -m haste.workflows.zip_artifacts "$@"\n' > /usr/local/bin/zip-artifacts \
    && chmod +x /usr/local/bin/prepare-imagery \
    && chmod +x /usr/local/bin/zip-artifacts

# Set PYTHONPATH so haste modules can be found at runtime
ENV PYTHONPATH=/app

# Convert line endings and make entrypoint script executable
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/entrypoint.sh

USER appuser

# Use the custom entrypoint script
ENTRYPOINT ["/app/scripts/entrypoint.sh"]