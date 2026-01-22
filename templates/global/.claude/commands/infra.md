# /infra — Infrastructure Quick Reference

Show relevant infrastructure details for the current task.

## Instructions

1. **Read infrastructure files**
   - Check for project INFRASTRUCTURE.md
   - Check for global ~/.claude/INFRASTRUCTURE.md
   - Check .mcp.json for configured services

2. **Identify relevant resources**
   - Based on current task, which servers/services are needed?
   - What credentials are required?
   - What access level is appropriate?

3. **Show connection details**
   - Server access commands
   - Required environment variables
   - Any prerequisites (VPN, auth, etc.)

4. **Safety reminders**
   - Is this a production resource?
   - What approval is needed?
   - What could go wrong?

## Output Format

```
## Infrastructure for: [Task/Context]

### Required Resources
| Resource | Type | Access |
|----------|------|--------|
| [name]   | [type] | [how to connect] |

### Connection Commands
```bash
# [resource name]
[connection command]
```

### Environment Variables Needed
- `$VAR_NAME` — [purpose]

### Prerequisites
- [ ] VPN connected
- [ ] Credentials configured
- [ ] Access approved

### Cautions
- [Any warnings about this infrastructure]
```

## When to Use

- Before SSH operations
- Before database queries
- Before container operations
- Before deployments
- When unsure which server to use
