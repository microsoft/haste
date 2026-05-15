FROM node:22-slim

# Install global CLI as root first
RUN npm install -g @azure/static-web-apps-cli

# Set up workdir; the upstream image has a "node" non-root user
WORKDIR /app
RUN chown node:node /app

# Switch to non-root before installing dependencies so they're owned correctly instantly
USER node

# Copy and install (no massive recursive chown later)
COPY --chown=node:node package*.json ./
RUN npm install

# Copy application files
COPY --chown=node:node . .

# Copy the Docker-specific environment file
COPY --chown=node:node .env.docker .env

EXPOSE 4280

CMD ["swa", "start", "--app-devserver-url", "http://localhost:5173", "--config-name", "local", "--run", "npm run dev -- --host"]
