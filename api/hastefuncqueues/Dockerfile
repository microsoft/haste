FROM mcr.microsoft.com/azure-functions/python:4-python3.11

WORKDIR /home/site/wwwroot

# Create non-root user first so COPY --chown can reference it; Secrets dir is empty so chown is fast
RUN groupadd -r appgroup && useradd -r -g appgroup appuser \
    && mkdir -p /azure-functions-host/Secrets \
    && chown appuser:appgroup /azure-functions-host/Secrets

# Copy files with correct ownership at copy time (avoids chown -R after the fact)
COPY --chown=appuser:appgroup hasteutils/src/haste /home/site/wwwroot/haste
COPY --chown=appuser:appgroup hasteutils/ /tmp/hasteutils/
COPY --chown=appuser:appgroup api/hastefuncqueues/requirements.txt ./
# Install requirements (includes published haste wheel), then override with local source
# so that local code changes are reflected without publishing a new wheel.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir /tmp/hasteutils/ \
    && rm -rf /tmp/hasteutils
COPY --chown=appuser:appgroup api/hastefuncqueues/ .

USER appuser

EXPOSE 8080
