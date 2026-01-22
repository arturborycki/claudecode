# Project Infrastructure Rules

## Server Access

1. **Read INFRASTRUCTURE.md** before connecting to any server
2. **Use project SSH key**: `~/.ssh/id_project`
3. **Default user**: `$PROJECT_SSH_USER`

## Database Operations

1. **Development DB** — Free to query and modify
2. **Staging DB** — Query freely, ask before modifying schema
3. **Production DB** — Read-only unless explicitly authorized

### Safe Operations (No Approval Needed)
- SELECT queries
- EXPLAIN ANALYZE
- Reading schema information

### Requires Approval
- INSERT/UPDATE/DELETE on production
- Schema migrations
- Index creation on large tables
- Backup/restore operations

## Container Operations

### Local Development
- Free to build, run, stop containers
- Use `docker-compose` for standard operations

### Registry Push
- Always tag with version: `project:v1.2.3`
- Verify tests pass before pushing
- Update deployment manifests after push

### Production Containers
- Never `docker exec` into production without approval
- Use kubectl for Kubernetes operations
- Check logs before restarting

## Deployment Rules

1. **Never deploy directly** — Use CI/CD pipeline
2. **Staging first** — All changes go to staging before production
3. **Verify in staging** — Manual verification required
4. **Production deploys** — Require explicit approval

## Secrets Handling

1. **Never echo secrets** in terminal output
2. **Never commit secrets** to git
3. **Use environment variables** — Referenced as `$VAR_NAME`
4. **Secrets source**: Team secrets manager (1Password, Vault, etc.)
