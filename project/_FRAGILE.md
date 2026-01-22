# Fragile Zones — Handle With Care

> These areas break in non-obvious ways. Read before touching. Ask if unsure.

## Authentication & Authorization

<!-- Document auth-sensitive code paths -->
- **Files**:
- **Risk**: Auth state can desync between client/server
- **Testing**: Always test logged-in, logged-out, and expired session states
- **Dependencies**:

## Payment Processing

<!-- If applicable -->
- **Files**:
- **Risk**: Financial transactions, refunds, webhooks
- **Testing**: Use test mode/sandbox. Never test with real payments.
- **Critical**: Webhook signature verification must never be bypassed

## Database Migrations

- **Location**:
- **Risk**: Data loss, downtime, schema conflicts
- **Process**:
  1. Always backup before migrating
  2. Test migration on staging first
  3. Have rollback plan ready
  4. Never modify existing migrations

## Row-Level Security (RLS) Policies

<!-- If using Supabase or similar -->
- **Files**:
- **Risk**: Data leaks, unauthorized access
- **Testing**: Test as multiple user roles
- **Critical**: Never disable RLS in production

## Third-Party Integrations

<!-- List sensitive integrations -->
| Integration | Risk Level | Notes |
|-------------|------------|-------|
| [Service]   | High       | [Why] |

## Environment-Specific Code

- **Production checks**:
- **Risk**: Debug code leaking to prod, prod data in dev
- **Critical paths**:

## State Management

<!-- Document complex state interactions -->
- **Global state location**:
- **Risk**: Race conditions, stale data
- **Patterns to follow**:

## Caching

- **Cache locations**:
- **Invalidation triggers**:
- **Risk**: Stale data served to users

---

## Before Modifying Fragile Code

1. Read the relevant section above
2. Understand current behavior first
3. Write tests before changing
4. Get review from team lead if unsure
5. Deploy to staging before production
