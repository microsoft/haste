---
applyTo: "**/*.yml,**/*.yaml,.github/workflows/**"
---

# CI/CD & YAML Instructions

- Use proper YAML indentation (2 spaces, never tabs).
- Pin action versions to full SHA hashes for security (e.g., `uses: actions/checkout@abcdef1234567890`).
- Use environment variables and secrets — never hardcode credentials.
- Add comments explaining non-obvious workflow steps.
- Keep workflow files focused — one workflow per concern (CI, deploy, release).
- Use `permissions` blocks to follow the principle of least privilege.
