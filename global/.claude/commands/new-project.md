# /new-project — Initialize Project with Claude Code Templates

Set up a new project with all standard Claude Code configuration files.

## Instructions

1. **Confirm the target directory**
   - Ask user for project path if not obvious
   - Verify directory exists or should be created

2. **Copy template files to project root**
   - `CLAUDE.md` — Project context
   - `INFRASTRUCTURE.md` — Project servers/services
   - `_FRAGILE.md` — Danger zones
   - `_NEXT_SESSION_MEMO.md` — Session handoff
   - `_VOCABULARY.md` — Canonical terms

3. **Set up .claude folder**
   - Create `.claude/` directory
   - Create `.claude/commands/` for project commands
   - Create `.claude/rules/` for project rules
   - Copy `rules/infrastructure.md`

4. **Create .mcp.json if needed**
   - Ask if MCP servers are needed
   - Copy template if yes

5. **Update .gitignore**
   - Add Claude local files to .gitignore:
     ```
     CLAUDE.local.md
     .claude/settings.local.json
     _NEXT_SESSION_MEMO.md
     ```

6. **Customize CLAUDE.md**
   - Ask for project name
   - Ask for brief description
   - Ask for tech stack
   - Fill in the template

## Output

```
## Project Initialized: [project-name]

### Files Created
- [x] CLAUDE.md
- [x] INFRASTRUCTURE.md
- [x] _FRAGILE.md
- [x] _NEXT_SESSION_MEMO.md
- [x] _VOCABULARY.md
- [x] .claude/rules/infrastructure.md
- [x] .gitignore updated

### Next Steps
1. Edit CLAUDE.md with project details
2. Edit INFRASTRUCTURE.md with server info
3. Edit _VOCABULARY.md with domain terms
4. Review _FRAGILE.md for sensitive areas

### Quick Start
Read CLAUDE.md. Working on [first task].
```

## Template Location

Templates are stored at: `~/Workfiles/claudecode/templates/project/`

If templates aren't found, create minimal versions inline.
