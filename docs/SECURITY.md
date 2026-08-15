# Security deployment checklist

- Terminate TLS at a trusted ingress and reject cleartext traffic.
- Enforce OIDC/JWT authentication and workspace-scoped RBAC on every route.
- Back rate limits with Redis; partition by workspace, user and route.
- Encrypt secrets with a KMS-managed data-encryption key and redact all logs.
- Run code tools in ephemeral, unprivileged containers with no host socket, no network by default, read-only root, seccomp/AppArmor, PID limits and hard CPU/memory/time quotas.
- Require human approvals for repository writes, external messages, financial actions and policy changes.
- Export immutable audit events and OpenTelemetry spans to separate storage.
- Rotate dependencies and scan containers before promotion.
