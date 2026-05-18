FROM mcr.microsoft.com/azurelinux/base/nodejs:24

# Install global CLI as root first
RUN npm install -g @azure/static-web-apps-cli

# Set up workdir and ownership *before* switching users
WORKDIR /app
RUN chown nonroot:nonroot /app

# Switch to non-root before installing dependencies so they're owned correctly instantly
USER nonroot

# Copy and install (no massive recursive chown later)
COPY --chown=nonroot:nonroot package*.json ./
RUN npm install

# Copy application files
COPY --chown=nonroot:nonroot . .

# Copy the Docker-specific environment file
COPY --chown=nonroot:nonroot .env.docker .env

EXPOSE 4280

CMD ["swa", "start", "--app-devserver-url", "http://localhost:5173", "--config-name", "local", "--run", "npm run dev -- --host"]
