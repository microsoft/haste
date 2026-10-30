FROM mcr.microsoft.com/azureml/curated/minimal-py311-inference:59@sha256:89a46a46b71b4692731654d0523f53c8d14929e41ea8129293dc4e39fcabb14c

USER root

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

# Keep worker dependencies separate from the base image's inference server.
RUN python -m venv /opt/haste-venv
ENV VIRTUAL_ENV=/opt/haste-venv
ENV PATH="/opt/haste-venv/bin:${PATH}"

# Set the working directory
WORKDIR /app

# Create non-root user before COPY so --chown can reference it
RUN groupadd -r appgroup && useradd -r -g appgroup -m -s /bin/bash appuser

# Copy files with correct ownership at copy time (avoids chown -R after the fact)
COPY --chown=appuser:appgroup hastelib/src/hastegeo /app/hastegeo
COPY --chown=appuser:appgroup docker/imageryprep/scripts /app/scripts/
COPY --chown=appuser:appgroup docker/imageryprep/requirements.txt /app/

# Install dependencies (no need to install haste package since we copy source directly)
# Optional unauthenticated index override for managed developer machines.
# Build arguments are visible in build metadata; never pass credentials here.
ARG PIP_INDEX_URL
RUN python -m pip install --no-cache-dir -r /app/requirements.txt \
    && python -m pip check

# Provide CLI entrypoints expected by the workflows without requiring a separate package install
RUN printf '#!/bin/bash\nexec python -m hastegeo.workflows.prepare_imagery "$@"\n' > /usr/local/bin/prepare-imagery \
    && printf '#!/bin/bash\nexec python -m hastegeo.workflows.zip_artifacts "$@"\n' > /usr/local/bin/zip-artifacts \
    && chmod +x /usr/local/bin/prepare-imagery \
    && chmod +x /usr/local/bin/zip-artifacts

# Set PYTHONPATH so hastegeo modules can be found at runtime
ENV PYTHONPATH=/app

# Refuse the unused GDAL drivers at the GDAL level. In-process code also
# verifies the shared runtime and enforces its driver/VSI policy.
ENV GDAL_SKIP="HDF4 HDF4Image HDF5 HDF5Image netCDF"
ENV HASTE_GDAL_RUNTIME_REQUIRED=true
ENV GDAL_VRT_ENABLE_RAWRASTERBAND=NO
ENV GDAL_VRT_ENABLE_PYTHON=NO
ENV GDAL_DRIVER_PATH=disable
ENV GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR
ENV CPL_VSIL_CURL_HEADER_FILE_KVP_ENABLED=NO

# Fail the build unless every GDAL binding runs on the one shared runtime.
RUN python -c "from hastegeo.core.utils.gdal_security import harden_gdal; harden_gdal(); \
    from osgeo import gdal; import fiona, pyogrio, rasterio; \
    v = gdal.VersionInfo('RELEASE_NAME'); \
    assert v.startswith('3.13.'), v; \
    assert {rasterio.__gdal_version__, fiona.__gdal_version__, pyogrio.__gdal_version_string__} == {v}, v"

# Ensure /app itself is writable by appuser (for runtime-created dirs like ./logs)
RUN chown appuser:appgroup /app

# Convert line endings and make entrypoint script executable
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/entrypoint.sh

USER appuser

# Use the custom entrypoint script
ENTRYPOINT ["/app/scripts/entrypoint.sh"]