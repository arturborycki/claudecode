# Claude Code Configuration Templates

Based on production patterns from running multi-agent Claude Code deployments.

## Quick Start

```bash
# Clone the repo
git clone https://github.com/arturborycki/claudecode.git
cd claudecode

# One-time global setup
./setup-global.sh

# Set up a new project
./setup-project.sh /path/to/my-project
```

## Folder Structure

```
├── setup-global.sh                  # Script to install global config
├── setup-project.sh                 # Script to initialize new projects
├── global/                          # Copy to ~/.claude/
│   └── .claude/
│       ├── MEMORY.md                # System-wide standards (all projects)
│       ├── INFRASTRUCTURE.md        # Global server/service reference
│       ├── settings.json            # Global permissions & env vars
│       ├── skill-library/           # Menu of skills to pick from per-project (NEW)
│       ├── bin/
│       │   └── claude-skills-init   # Interactive skill picker (NEW)
│       ├── commands/                # Global custom commands
│       │   ├── wrap.md              # /wrap — End session, commit
│       │   ├── sup.md               # /sup — Quick status check
│       │   ├── fragile.md           # /fragile — Review danger zones
│       │   ├── plan.md              # /plan — Two-phase planning
│       │   ├── research.md          # /research — Deep exploration
│       │   ├── infra.md             # /infra — Infrastructure reference
│       │   ├── new-project.md       # /new-project — Initialize project
│       │   └── skills.md            # /skills — Add library skills to a project (NEW)
│       └── rules/
│           └── infrastructure-access.md  # Global infra access rules
│
└── project/                         # Copy to your project root
    ├── CLAUDE.md                    # Project context (read first)
    ├── INFRASTRUCTURE.md            # Project-specific servers/services
    ├── _FRAGILE.md                  # Danger zones documentation
    ├── _NEXT_SESSION_MEMO.md        # Session handoff notes
    ├── _VOCABULARY.md               # Canonical terminology
    ├── .mcp.json.example            # MCP server config template
    └── .claude/
        ├── commands/                # Project-specific commands
        └── rules/
            └── infrastructure.md    # Project infra access rules
```

## Installation

### Using Setup Scripts (Recommended)

```bash
# Global setup (one time)
./setup-global.sh

# Per-project setup
./setup-project.sh /path/to/my-project
```

### Manual Installation

<details>
<summary>Click to expand manual steps</summary>

#### Global Setup (One Time)

```bash
# Copy all global files
cp global/.claude/MEMORY.md ~/.claude/
cp global/.claude/INFRASTRUCTURE.md ~/.claude/
cp global/.claude/settings.json ~/.claude/

# Copy global commands
cp -r global/.claude/commands ~/.claude/

# Copy global rules
mkdir -p ~/.claude/rules
cp -r global/.claude/rules/* ~/.claude/rules/
```

#### Per-Project Setup

```bash
# From your project root:
cp /path/to/claudecode/project/CLAUDE.md ./
cp /path/to/claudecode/project/INFRASTRUCTURE.md ./
cp /path/to/claudecode/project/_FRAGILE.md ./
cp /path/to/claudecode/project/_NEXT_SESSION_MEMO.md ./
cp /path/to/claudecode/project/_VOCABULARY.md ./

# Copy project .claude folder
cp -r /path/to/claudecode/project/.claude ./

# Optional: Set up MCP servers
cp /path/to/claudecode/project/.mcp.json.example ./.mcp.json
# Then edit .mcp.json with your actual values
```

</details>

## Commands Usage

After installing the global commands, use them in any Claude Code session:

| Command | Purpose | When to Use |
|---------|---------|-------------|
| `/wrap` | End session properly | End of work session |
| `/sup` | Quick status check | Anytime, fast overview |
| `/fragile` | Review danger zones | Before touching sensitive code |
| `/plan` | Two-phase planning | Complex features, no YOLO |
| `/research` | Deep exploration | Investigation tasks |
| `/infra` | Infrastructure reference | Before server/DB operations |
| `/new-project` | Initialize new project | Starting a new codebase |
| `/skills` | Add skills from the library | Project needs domain skills |

## Skills & Agents

Skills are reusable playbooks Claude loads on demand; agents are specialized
workers. This repo ships a **skill library** (a menu) plus a picker so each
project gets only the skills it needs — global skills would clutter every
unrelated project with descriptions they don't use.

```
~/.claude/skill-library/   # installed by setup-global.sh — the menu
~/.claude/bin/claude-skills-init   # the interactive picker
```

### Add skills to a project

`setup-project.sh` offers to run the picker at the end. To add skills later,
from the project root:

```bash
claude-skills-init            # interactive multi-select (gum > fzf > plain)
claude-skills-init --list     # just list what's available
claude-skills-init --link     # symlink instead of copy (single source of truth)
```

Selected skills land in `.claude/skills/`. The picker also offers the bundled
agent (`engine-dev`) into `.claude/agents/` and rules into `.claude/rules/`.
Inside a session you can use `/skills` instead of dropping to the shell.

### What's in the library

A database / query-engine internals set (14 skills) for C/C++/Rust work —
query plan design, SQL front end, optimizer, joins, columnar/Arrow layout,
storage & indexing, page/file formats, LSM storage, transactions & recovery,
parallel execution, replication & consistency, consensus, distributed
transactions, and testing — plus an `engine-dev` agent. See
`global/.claude/skill-library/README.md`. Drop your own skill folders into the
library to extend the menu.

### A note on hooks

A hook can't present the picker — Claude Code hooks are non-interactive
scripts (their stdin is JSON event context, not your keyboard). The live
checkbox menu only works in your terminal, so the picker is a standalone
script; `/skills` and `setup-project.sh` are the integration points.

## Startup Prompt Template

Use this pattern when starting a session:

```
Read CLAUDE.md. Read _FRAGILE.md. Read _NEXT_SESSION_MEMO.md.
Working on [TASK/RFD]. Your role: [ROLE]. Write permission: [SCOPE].
```

### Role Examples

- **Review agent**: Read-only code review
- **Testing agent**: Write only to test files
- **Security agent**: Output to SECURITY_REPORT.md only
- **Coding agent**: Full implementation access

## File Reference

### CLAUDE.md
Project-specific context. What you're building, tech stack, architecture decisions, conventions. Every agent reads this first.

### _FRAGILE.md
Document code that breaks in non-obvious ways: auth flows, payments, RLS policies, migrations. Agents must check before modifying.

### _NEXT_SESSION_MEMO.md
Handoff documentation. Updated at session end via `/wrap`. Contains completed work, in-progress items, blockers, and next steps.

### _VOCABULARY.md
Canonical terminology. Prevents confusion from inconsistent naming (e.g., "user" vs "member" vs "account").

### MEMORY.md (Global)
System-wide standards that apply to all projects. Code quality rules, git practices, security defaults.

### INFRASTRUCTURE.md (Global & Project)
Server details, connection info, credentials references. **Never store actual passwords** — use environment variable references like `$SSH_USER`.

### settings.json
Permissions and environment variables. Controls what Claude can access (allow/ask/deny rules).

### .mcp.json
MCP (Model Context Protocol) server configurations. Enables Claude to interact with external services like GitHub, databases, Docker, Kubernetes.

### rules/*.md
Modular rules files. Split large instruction sets by topic (infrastructure, security, testing, etc.).

## Infrastructure Configuration

### Security: Never Store Secrets Directly

```markdown
# WRONG - Never do this
- **Password**: `mysecretpassword123`

# CORRECT - Use environment variable references
- **Password**: `$DB_PASSWORD` (set in environment)
```

### Environment Variables

Set credentials in your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
# SSH
export DEV_SSH_USER="your-username"
export PROD_SSH_USER="your-prod-username"

# Database
export DB_USER="dbuser"
export DB_PASSWORD="from-secrets-manager"

# Cloud
export AWS_PROFILE="default"
```

### MCP Servers for Infrastructure

Enable Claude to interact with external services by configuring `.mcp.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
    },
    "postgres": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-postgres"],
      "env": { "DATABASE_URL": "${DATABASE_URL}" }
    }
  }
}
```

### Permission Levels in settings.json

```json
{
  "permissions": {
    "allow": ["Bash(ssh:*dev*)"],       // Auto-approved
    "ask": ["Bash(ssh:*prod*)"],         // Requires confirmation
    "deny": ["Read(.env)", "Read(~/.ssh/*)"]  // Blocked entirely
  }
}
```

## Best Practices

1. **Short prompts + comprehensive docs** beats elaborate role definitions
2. **Update _NEXT_SESSION_MEMO.md** religiously via `/wrap`
3. **Use `/fragile`** before touching auth, payments, or security code
4. **Use `/plan`** for any feature that spans multiple files
5. **Keep files under 300 lines** for reviewable diffs
6. **Single source of truth** for env vars, formatters, query keys

## Customization

Edit the template files to match your:
- Tech stack and frameworks
- Coding conventions
- Project structure
- Domain vocabulary
- Team processes
