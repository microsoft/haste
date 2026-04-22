#!/bin/bash
set -e

echo "Starting HASTE API container..."

# Run startup initialization
python /home/site/wwwroot/startup.py

# Start Azure Functions host
exec /azure-functions-host/Microsoft.Azure.WebJobs.Script.WebHost
