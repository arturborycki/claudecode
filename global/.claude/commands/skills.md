# /skills — Add skills from the global library to this project

Interactively pick skills (and optionally the bundled agent/rules) from the
global skill library and install them into the current project's
`.claude/skills/`. The library is a *menu*, not active config — installing
per-project keeps unrelated projects free of skills they don't need.

## Instructions

1. **Find the library.** Default `~/.claude/skill-library/`, or the path in
   `$CLAUDE_SKILL_LIBRARY` if set. If it's missing, tell the user to run
   `setup-global.sh` rather than guessing.

2. **List what's available.** Read each subdirectory's `SKILL.md` frontmatter
   (`name`, `description`) and present a numbered list with one-line
   summaries. Group them if helpful (query pipeline / storage / transactions
   / distributed / testing).

3. **Ask which to add.** Accept numbers or names. Mention they can also run
   `claude-skills-init` in their terminal for a checkbox UI.

4. **Install.** Copy each selected skill folder into `./.claude/skills/`
   (create it if needed). Skip ones already present unless told to overwrite.
   Offer the bundled `agents/engine-dev.md` and `rules/engine-internals.md`
   too if the project is a database/query-engine codebase.

5. **Confirm.** List exactly what was installed. Remind the user that Claude
   Code will prompt to trust the workspace the first time, and that skill
   changes take effect live.

## Note

The terminal picker (`claude-skills-init`) is the canonical, fully
interactive path. This command is the in-session equivalent for when the user
is already in a Claude session and doesn't want to drop to the shell.

$ARGUMENTS
