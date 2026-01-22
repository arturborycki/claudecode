# Project Infrastructure

> Project-specific infrastructure details. Inherits from global INFRASTRUCTURE.md.
> **NEVER store actual passwords here.** Use environment variable references.

## Project Servers

### Application Server
- **Host**: `app.project.example.com`
- **IP**: `10.0.1.50`
- **User**: `$PROJECT_SSH_USER`
- **Key**: `~/.ssh/id_project`
- **Purpose**: Running this application
- **Services**: nginx, node, pm2
- **Logs**: `/var/log/app/`

### Database Server
- **Host**: `db.project.example.com`
- **Type**: PostgreSQL 15
- **Port**: `5432`
- **Database**: `projectdb`
- **User**: `$PROJECT_DB_USER`
- **Connection**: See `.env.example` for format

## Container Infrastructure

### Build & Deploy
- **Registry**: `registry.example.com/project`
- **Build Server**: Use global build server
- **Dockerfile**: `./Dockerfile`
- **Compose**: `./docker-compose.yml`

### Running Containers
```bash
# Local development
docker-compose up -d

# Build for production
docker build -t registry.example.com/project:latest .
docker push registry.example.com/project:latest
```

## Kubernetes (If Applicable)

- **Namespace**: `project-namespace`
- **Manifests**: `./k8s/`
- **Helm Chart**: `./helm/project/`

```bash
# Deploy to dev
kubectl apply -f k8s/ -n project-namespace

# Check status
kubectl get pods -n project-namespace
```

## Third-Party Services

| Service | Purpose | Dashboard | Credentials |
|---------|---------|-----------|-------------|
| Stripe | Payments | stripe.com/dashboard | `$STRIPE_SECRET_KEY` |
| SendGrid | Email | app.sendgrid.com | `$SENDGRID_API_KEY` |
| Sentry | Error tracking | sentry.io | `$SENTRY_DSN` |
| Redis | Caching | N/A | `$REDIS_URL` |

## Environment Files

- `.env.example` — Template with all required variables (committed)
- `.env` — Local development values (git-ignored)
- `.env.production` — Production values (git-ignored, stored in secrets manager)

## Deployment Pipeline

1. **CI/CD**: GitHub Actions / GitLab CI / etc.
2. **Stages**: `test → build → deploy-staging → deploy-production`
3. **Config**: `.github/workflows/` or `.gitlab-ci.yml`

## Monitoring & Logs

- **Application Logs**: `ssh app-server 'tail -f /var/log/app/app.log'`
- **Container Logs**: `docker logs -f container-name`
- **K8s Logs**: `kubectl logs -f deployment/app -n project-namespace`
- **Metrics**: Grafana at `metrics.example.com`
- **Alerts**: PagerDuty / Opsgenie

## Runbooks

### Restart Application
```bash
ssh $PROJECT_SSH_USER@app.project.example.com 'pm2 restart all'
# or
kubectl rollout restart deployment/app -n project-namespace
```

### Database Backup
```bash
ssh $PROJECT_SSH_USER@db.project.example.com 'pg_dump projectdb > backup.sql'
```

### Scale Up
```bash
kubectl scale deployment/app --replicas=5 -n project-namespace
```

---

## Required Environment Variables

```bash
# Server Access
export PROJECT_SSH_USER="deploy"

# Database
export PROJECT_DB_USER="app"
export PROJECT_DB_PASS=""  # From secrets manager

# Third-Party
export STRIPE_SECRET_KEY=""
export SENDGRID_API_KEY=""
export SENTRY_DSN=""
export REDIS_URL=""
```
