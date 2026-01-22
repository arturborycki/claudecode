# Global Infrastructure Reference

> Personal infrastructure details available across all projects.
> **NEVER store actual passwords here.** Use environment variable references.

## SSH Servers

### Development Server
- **Host**: `dev.example.com`
- **IP**: `192.168.1.100`
- **User**: `$DEV_SSH_USER` (set in environment)
- **Key**: `~/.ssh/id_dev`
- **Purpose**: General development, testing
- **Access**: `ssh -i ~/.ssh/id_dev $DEV_SSH_USER@dev.example.com`

### Build Server
- **Host**: `build.example.com`
- **IP**: `192.168.1.101`
- **User**: `$BUILD_SSH_USER`
- **Key**: `~/.ssh/id_build`
- **Purpose**: CI/CD, container builds
- **Docker**: Available at `/var/run/docker.sock`
- **Access**: `ssh -i ~/.ssh/id_build $BUILD_SSH_USER@build.example.com`

### Production Bastion
- **Host**: `bastion.example.com`
- **User**: `$PROD_SSH_USER`
- **Key**: `~/.ssh/id_prod`
- **Purpose**: Jump host for production access
- **Access**: Requires VPN connection first
- **Warning**: Read-only access unless explicitly authorized

## Container Registries

### Private Registry
- **URL**: `registry.example.com`
- **User**: `$REGISTRY_USER`
- **Auth**: `docker login registry.example.com`

### Cloud Registry
- **URL**: `gcr.io/my-project` | `123456789.dkr.ecr.us-east-1.amazonaws.com`
- **Auth**: Via cloud CLI (`gcloud auth configure-docker` | `aws ecr get-login-password`)

## Kubernetes Clusters

### Development Cluster
- **Context**: `dev-cluster`
- **Namespace**: `development`
- **Access**: `kubectl config use-context dev-cluster`

### Staging Cluster
- **Context**: `staging-cluster`
- **Namespace**: `staging`
- **Access**: Requires VPN

## Databases

### Development DB
- **Type**: PostgreSQL
- **Host**: `db.dev.example.com`
- **Port**: `5432`
- **Database**: `devdb`
- **User**: `$DEV_DB_USER`
- **Connection**: `postgresql://$DEV_DB_USER:$DEV_DB_PASS@db.dev.example.com:5432/devdb`

## Cloud Accounts

### AWS
- **Profile**: `default` | `production`
- **Region**: `us-east-1`
- **Auth**: `~/.aws/credentials` (configured via `aws configure`)

### GCP
- **Project**: `my-gcp-project`
- **Auth**: `gcloud auth login`

### Azure
- **Subscription**: `my-subscription`
- **Auth**: `az login`

## VPN / Network

- **VPN**: OpenVPN config at `~/.vpn/company.ovpn`
- **Internal DNS**: `*.internal.example.com`

---

## Environment Variables Required

Set these in your shell profile (`~/.zshrc`, `~/.bashrc`):

```bash
# SSH Users
export DEV_SSH_USER="your-dev-username"
export BUILD_SSH_USER="your-build-username"
export PROD_SSH_USER="your-prod-username"

# Database
export DEV_DB_USER="your-db-user"
export DEV_DB_PASS="your-db-password"  # Or use a secrets manager

# Registry
export REGISTRY_USER="your-registry-user"
```

## Security Notes

- Production servers require explicit approval before any write operations
- Database credentials should use read-only accounts by default
- All SSH access is logged
- Never expose credentials in command output or commit history
