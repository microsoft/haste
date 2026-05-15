FROM mcr.microsoft.com/azure-functions/python:4-python3.11

WORKDIR /home/site/wwwroot

# Create non-root user first so COPY --chown can reference it; Secrets dir is empty so chown is fast
RUN groupadd -r appgroup && useradd -r -g appgroup appuser \
    && mkdir -p /azure-functions-host/Secrets \
    && chown appuser:appgroup /azure-functions-host/Secrets

# Copy files with correct ownership at copy time (avoids chown -R after the fact)
COPY --chown=appuser:appgroup hastelib/src/hastegeo /home/site/wwwroot/hastegeo
COPY --chown=appuser:appgroup hastelib/ /tmp/hastelib/
COPY --chown=appuser:appgroup api/hastefuncqueues/requirements.txt ./
# Install requirements (includes published hastegeo wheel), then override with local source
# so that local code changes are reflected without publishing a new wheel.
# HASTE_SKIP_VERSION_BUMP avoids the haste_build.py hook bumping __about__.py and
# attempting an Azure blob upload during the image build.
RUN pip install --no-cache-dir -r requirements.txt \
    && HASTE_SKIP_VERSION_BUMP=1 pip install --no-cache-dir /tmp/hastelib/ \
    && rm -rf /tmp/hastelib
COPY --chown=appuser:appgroup api/hastefuncqueues/ .

USER appuser

EXPOSE 8080
