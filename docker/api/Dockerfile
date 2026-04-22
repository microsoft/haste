# Use the official Azure Functions Python 3.11 image as a base image
FROM mcr.microsoft.com/azure-functions/python:4-nightly-python3.11-slim

# Set the working directory
WORKDIR /home/site/wwwroot

# Copy the Azure Functions API code from the specified directory
COPY ../../api/hastefuncapi/ .
#COPY ../../api/hastefuncapi/ /home/site/wwwroot/ --chown=www-data:www-data --exclude .venv

# Install dependencies
#COPY ../../api/hastefuncapi/requirements.txt .
RUN pip install -r requirements.txt

# Expose the necessary ports
# EXPOSE 80
# EXPOSE 443
EXPOSE 7071
# Start the Azure Functions host
CMD ["func", "host", "start", "--verbose"]