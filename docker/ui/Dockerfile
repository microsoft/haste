# Use the official Node.js image as the base image
FROM mcr.microsoft.com/azurelinux/base/nodejs:24.17

# Set the working directory
WORKDIR /app

# Copy the package.json and package-lock.json files
COPY ../../UI/package*.json ./

# Install the dependencies
RUN npm install

# Copy the rest of the application code
COPY ../../UI .

# Build the Vite application
RUN npm run build

# Install serve to serve the build
RUN npm install -g serve

# Expose the necessary port
EXPOSE 5000

# Command to run the application
CMD ["serve", "-s", "dist", "-l", "5000"]