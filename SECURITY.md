# Security Policy

The OpenMarker project takes security seriously.

Although the application runs locally, security issues can still affect users through malformed files or vulnerabilities in dependencies.

---

# Supported Versions

Security fixes will be applied to the latest stable version of the project.

Older versions may not receive security updates.

---

# Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

Do NOT open a public GitHub issue for security vulnerabilities.

Instead:

1. Contact the maintainers privately
2. Provide a detailed description
3. Include steps to reproduce if possible

Information that helps:

• Description of the vulnerability  
• Example DXF file if relevant  
• Steps to reproduce  
• Potential impact

---

# Responsible Disclosure

We ask that researchers allow maintainers reasonable time to investigate and resolve vulnerabilities before publicly disclosing them.

---

# Common Security Concerns

Since OpenMarker processes external DXF files, common risks include:

• Malformed DXF files  
• Large file denial-of-service  
• Geometry processing crashes

Mitigations include:

• Input validation  
• Size limits  
• Safe geometry operations

---

# Dependency Security

Dependencies will be monitored for known vulnerabilities.

Contributors should avoid introducing unnecessary dependencies.

---

# Security Updates

When security issues are resolved:

• A patch release will be created  
• Release notes will describe the fix  
