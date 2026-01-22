# Project Context — CLAUDE.md

> Read this file first. Then read _FRAGILE.md and _NEXT_SESSION_MEMO.md.

## What We're Building

<!-- Describe your project here -->
[PROJECT_NAME] — A [brief description of what this project does]

## Current Focus

<!-- Update this section regularly -->
- [ ] Current sprint/milestone goal
- [ ] Key features in progress
- [ ] Immediate priorities

## Tech Stack

<!-- List your technologies -->
- **Frontend**:
- **Backend**:
- **Database**:
- **Infrastructure**:

## Key Architecture Decisions

<!-- Document important choices and their rationale -->
1. **[Decision]**: [Rationale]
2. **[Decision]**: [Rationale]

## Project Structure

```
/src
  /components    # UI components
  /lib           # Data layer, utilities
  /hooks         # Custom React hooks (if applicable)
  /pages         # Routes/pages
  /types         # Type definitions
```

## Development Commands

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Run tests
npm test

# Build for production
npm run build
```

## Environment Variables

Required variables (see .env.example):
- `DATABASE_URL` — Database connection string
- `API_KEY` — External API key

## Conventions

- Use [coding style] for [language]
- Component naming: PascalCase
- File naming: kebab-case
- Branch naming: `feature/`, `fix/`, `chore/`

## Related Documentation

- [Link to design docs]
- [Link to API docs]
- [Link to architecture diagrams]
