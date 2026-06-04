---
applyTo: "**"
excludeAgent: "code-review"
---

# Security Instructions (Cloud Agent Only)

- Never commit secrets, API keys, tokens, or passwords.
- Validate and sanitize all user inputs.
- Use parameterized queries — never construct SQL from user input.
- Escape output to prevent XSS when rendering HTML.
- Follow OWASP Top 10 guidelines.
- Use HTTPS for all external requests.
- Apply the principle of least privilege for file permissions, API scopes, and IAM roles.
- Review dependencies for known vulnerabilities before adding them.
