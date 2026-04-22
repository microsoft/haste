# Use Microsoft-hosted Python image to avoid Docker Hub authentication issues
FROM mcr.microsoft.com/devcontainers/python:3.11

# Install Azure Storage Blob SDK
RUN pip install azure-storage-blob azure-storage-queue

# Copy the data files from setup folder to the container
COPY ./setup/config_admin_settings.json /data/config_admin_settings.json

# Create placeholder files for users_acl and project_stats if they don't exist in your repo
# users_acl.json should be an array of user objects - empty array, users auto-created in dev mode
RUN echo '[]' > /data/users_acl.json
RUN echo '{"projects": [], "project_count": 0, "layer_count": 0, "model_count": 0}' > /data/project_stats.json

# Copy the upload script
COPY ./docker/data-init/upload_data.py /upload_data.py

# Make the script executable
RUN chmod +x /upload_data.py

# Run the upload script
CMD ["python", "/upload_data.py"]
