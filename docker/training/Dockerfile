# ---------- Stage 1: Build Conda Environment ----------
FROM mcr.microsoft.com/azureml/curated/minimal-py312-cuda12.4-inference AS conda-env

USER root

# Install micromamba and conda-pack (micromamba avoids Python version conflicts)
RUN for i in 1 2 3 4 5; do \
		apt-get update && apt-get install -y --no-install-recommends libgl1-mesa-glx curl && break || sleep 15; \
	done \
	&& rm -rf /var/lib/apt/lists/* \
	&& curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj -C /usr/local bin/micromamba \
	&& conda install -n base -c conda-forge conda-pack --yes \
	&& conda clean -afy

# Copy only env.yml first (maximize build cache)
COPY docker/training/env/env.yml /tmp/env.yml

# Create environment using micromamba and pack it for reuse
# Force-reinstall setuptools after pip to restore conda-managed files pip may clobber
RUN micromamba create -f /tmp/env.yml -y \
	&& micromamba install -n bda -c conda-forge setuptools --force-reinstall -y \
	&& micromamba clean -afy \
	&& conda-pack -n bda -o /tmp/bda.tar.gz


# ---------- Stage 2: Final Runtime Image ----------
FROM mcr.microsoft.com/azureml/curated/minimal-py312-cuda12.4-inference

USER root

# Install runtime system dependencies and CA certificates (with retry for flaky network)
RUN for i in 1 2 3 4 5; do \
		apt-get update && apt-get install -y --no-install-recommends libgl1-mesa-glx ca-certificates && break || sleep 15; \
	done \
	&& update-ca-certificates \
	&& rm -rf /var/lib/apt/lists/*

# Prepare conda env directory owned by the target user, then extract the packed env
# as that user — non-root tar uses the running user's UID/GID, so no chown -R needed.
RUN mkdir -p /opt/conda/envs/bda && chown dockeruser:dockeruser /opt/conda/envs/bda
COPY --chown=dockeruser:dockeruser --from=conda-env /tmp/bda.tar.gz /tmp/bda.tar.gz
USER dockeruser
RUN tar -xzf /tmp/bda.tar.gz -C /opt/conda/envs/bda \
	&& rm /tmp/bda.tar.gz \
	&& /opt/conda/envs/bda/bin/conda-unpack

# Set working directory (created as dockeruser since USER is already set)
WORKDIR /app

# Copy application code and scripts with correct ownership at copy time
COPY --chown=dockeruser:dockeruser docker/training/code /app
COPY --chown=dockeruser:dockeruser docker/training/scripts/ /app/scripts/

# Copy haste source so training can import the package just like imagery prep
COPY --chown=dockeruser:dockeruser hastelib/src/hastegeo /app/hastegeo

# Convert line endings and ensure scripts are executable inside the container
RUN sed -i 's/\r$//' /app/scripts/*.sh && chmod +x /app/scripts/*.sh

# Activate the environment by default and expose shared data directories
ENV PATH="/opt/conda/envs/bda/bin:${PATH}"
ENV PROJ_LIB=/opt/conda/envs/bda/share/proj
ENV GDAL_DATA=/opt/conda/envs/bda/share/gdal
ENV PYTHONPATH=/app
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Use training-specific entrypoint wrapper to mirror imagery prep behavior
ENTRYPOINT ["/app/scripts/entrypoint.sh"]