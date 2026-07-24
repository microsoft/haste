FROM mcr.microsoft.com/azure-functions/python:4-python3.11

WORKDIR /home/site/wwwroot

# Create non-root user first so COPY --chown can reference it; Secrets dir is empty so chown is fast
RUN groupadd -r appgroup && useradd -r -g appgroup appuser \
    && mkdir -p /azure-functions-host/Secrets \
    && chown appuser:appgroup /azure-functions-host/Secrets

# Copy the hastegeo library so requirements.txt can install it editable:
# `-e ../../hastelib` resolves to /home/hastelib from the /home/site/wwwroot
# WORKDIR. The local/remote install toggle lives in requirements.txt, so this
# stays a plain `pip install -r requirements.txt`.
COPY --chown=appuser:appgroup hastelib/ /home/hastelib/
COPY --chown=appuser:appgroup api/hastefuncqueues/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=appuser:appgroup api/hastefuncqueues/ .

USER appuser

EXPOSE 8080
