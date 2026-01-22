# Infrastructure Access Rules

## SSH Access Guidelines

When connecting to remote servers:

1. **Always use key-based authentication** — Never ask for or use passwords directly
2. **Prefer environment variables** for usernames: `$DEV_SSH_USER`, `$BUILD_SSH_USER`
3. **Check server purpose** before running commands — See INFRASTRUCTURE.md
4. **Production servers require explicit approval** before any write operations

## Docker / Container Rules

1. **Build containers on build server** — Not local unless specified
2. **Tag images properly** — Use `project:version` format
3. **Push to correct registry** — Check project's target registry
4. **Clean up** — Remove unused images after builds

## Database Rules

1. **Use read-only connections by default** — Request write access explicitly
2. **Never run migrations** without explicit approval
3. **Always backup** before destructive operations
4. **Use connection strings from environment** — Never hardcode credentials

## Kubernetes Rules

1. **Check cluster context** before running kubectl commands
2. **Verify namespace** — Don't operate in wrong namespace
3. **Dry-run first** for any apply/delete operations
4. **Production changes require explicit approval**

## Prohibited Actions (Without Explicit Approval)

- SSH to production servers
- Write operations on production databases
- Deleting Kubernetes resources in staging/production
- Pushing to main/master branches of infrastructure repos
- Modifying cloud IAM/permissions
