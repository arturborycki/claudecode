# Global Memory — System-Wide Standards

These standards apply to ALL projects. Project-specific overrides go in each project's CLAUDE.md.

## Code Quality Standards

- **File size limit**: Keep files under 300 lines for reviewable diffs
- **No hardcoded IDs**: Always use context-based identifiers
- **Single source of truth**: Environment variables, query keys, formatters should have one canonical location
- **Responsive from day one**: Never retrofit responsive design

## Data Flow Architecture

Follow this strict hierarchy:
```
Database → Queries → Models → Hooks → UI Components
```

Components should never import database code directly.

## Security Defaults

- Never commit secrets or API keys
- Use environment variables for all credentials
- Validate all user input at system boundaries
- Follow principle of least privilege

## Git Practices

- Write clear, descriptive commit messages
- One logical change per commit
- Never force push to shared branches
- Always pull before pushing

## Documentation

- Update relevant docs when changing functionality
- Keep README current with setup instructions
- Document non-obvious decisions in code comments

## Testing

- Write tests for new functionality
- Run existing tests before committing
- Don't merge with failing tests
