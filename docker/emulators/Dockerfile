# Use the official Azurite image from Microsoft
FROM mcr.microsoft.com/azure-storage/azurite:latest

# Expose the necessary ports
EXPOSE 10000 10001 10002

# Command to run Azurite with --skipApiVersionCheck to handle newer SDK versions
CMD ["azurite", "-l", "/data", "--blobHost", "0.0.0.0", "--queueHost", "0.0.0.0", "--tableHost", "0.0.0.0", "--skipApiVersionCheck"]