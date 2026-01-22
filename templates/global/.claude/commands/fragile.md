# /fragile — Review Danger Zones

Before touching sensitive code, review what could break.

## Instructions

1. **Read _FRAGILE.md** if it exists in the project

2. **Identify the fragile zone** being touched:
   - Authentication/Authorization
   - Payment processing
   - Database migrations
   - Security policies (RLS, permissions)
   - Third-party integrations
   - Caching/state management

3. **List potential risks**
   - What could break?
   - What's the blast radius?
   - Are there non-obvious dependencies?

4. **Pre-flight checklist**
   - [ ] I understand the current behavior
   - [ ] I know what tests exist
   - [ ] I have a rollback plan
   - [ ] I've identified who to notify

5. **Recommended approach**
   - Suggest safest way to proceed
   - Identify what to test
   - Note if review is needed

## Output Format

```
## Fragile Zone Analysis: [Area]

### Current Behavior
[How it works now]

### Proposed Change
[What we're changing]

### Risk Assessment
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| [X]  | Low/Med/Hi | Low/Med/Hi | [How to prevent] |

### Pre-Flight Check
- [ ] Tests exist: Yes/No
- [ ] Rollback plan: [Plan]
- [ ] Review needed: Yes/No

### Recommendation
[Proceed with caution / Get review first / Safe to proceed]
```

## When to Use

- Before modifying auth flows
- Before touching payment code
- Before database migrations
- Before changing security policies
- When touching unfamiliar critical code
- When the change feels risky
