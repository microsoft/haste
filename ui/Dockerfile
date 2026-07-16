FROM mcr.microsoft.com/azurelinux/base/nodejs:24

# Install global CLI as root first
RUN npm install -g @azure/static-web-apps-cli

# Prefill the administrator role in the Docker-only SWA mock-login portal.
RUN node -e "const fs=require('node:fs');const path=require('node:path');const {execFileSync}=require('node:child_process');const root=execFileSync('npm',['root','-g'],{encoding:'utf8'}).trim();const p=path.join(root,'@azure','static-web-apps-cli','dist','public','auth.html');let s=fs.readFileSync(p,'utf8');const defaults='const defaultRoles = [\"anonymous\", \"authenticated\"];';const cached='input.val(userRoles.join(\"\\\\n\"));';if(!s.includes(defaults)||!s.includes(cached))throw new Error('Unexpected SWA auth portal');s=s.replace(defaults,'const defaultRoles = [\"anonymous\", \"authenticated\", \"administrators\"];').replace(cached,'input.val([...new Set([...userRoles, ...settings.defaultRoles])].join(\"\\\\n\"));\\n                input.saveToLocalStorage();');fs.writeFileSync(p,s);"

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
