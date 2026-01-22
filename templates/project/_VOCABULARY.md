# Project Vocabulary — Canonical Terms

> Use these exact terms to prevent confusion. Consistency matters for token prediction.

## Domain Terms

<!-- Define your domain-specific vocabulary -->

| Term | Definition | NOT |
|------|------------|-----|
| `user` | An authenticated account holder | `member`, `account`, `profile` |
| `workspace` | A container for projects | `org`, `team`, `space` |
| `project` | A single work item | `task`, `item`, `job` |

## Technical Terms

| Term | Definition | Context |
|------|------------|---------|
| `query` | Database read operation | Not API request |
| `mutation` | Database write operation | Not state change |
| `handler` | Request processor | Not controller |

## UI Terms

| Term | Where Used | NOT |
|------|------------|-----|
| `Modal` | Overlay dialogs | `Dialog`, `Popup` |
| `Button` | Clickable actions | `Btn`, `Action` |
| `Card` | Content containers | `Box`, `Panel` |

## State Terms

| State | Meaning | Triggers |
|-------|---------|----------|
| `loading` | Async operation in progress | Data fetch, submit |
| `error` | Operation failed | API error, validation |
| `idle` | Ready for interaction | Initial, after complete |

## File Naming

| Pattern | Use For | Example |
|---------|---------|---------|
| `use-*.ts` | React hooks | `use-auth.ts` |
| `*.types.ts` | Type definitions | `user.types.ts` |
| `*.test.ts` | Test files | `auth.test.ts` |
| `*.utils.ts` | Utility functions | `date.utils.ts` |

## API Conventions

| Pattern | Method | Example |
|---------|--------|---------|
| `GET /resources` | List | `GET /users` |
| `GET /resources/:id` | Read | `GET /users/123` |
| `POST /resources` | Create | `POST /users` |
| `PATCH /resources/:id` | Update | `PATCH /users/123` |
| `DELETE /resources/:id` | Delete | `DELETE /users/123` |

## Abbreviations

| Abbreviation | Full Term | When to Use |
|--------------|-----------|-------------|
| `auth` | authentication | Always OK |
| `config` | configuration | Always OK |
| `env` | environment | In variable names |
| `props` | properties | React components |

---

## Adding New Terms

When adding a new concept:
1. Check this file first for existing terms
2. Choose one canonical name
3. Add to appropriate section above
4. Update existing code to match
