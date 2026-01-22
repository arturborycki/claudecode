# Example Project-Specific Command

This file demonstrates how to add project-specific commands.

Place `.md` files in your project's `.claude/commands/` folder for commands that only apply to that project.

## Example: /deploy

```markdown
# /deploy — Deploy to Staging

Deploy current branch to staging environment.

## Pre-flight Checks

1. All tests passing?
2. No uncommitted changes?
3. Branch up to date with main?

## Steps

1. Run build
2. Run tests
3. Push to staging branch
4. Monitor deployment
5. Verify health checks

## Output

Deployment status and URL.
```

## Creating Your Own Commands

1. Create a `.md` file in `.claude/commands/`
2. Name it after your command (e.g., `deploy.md` for `/deploy`)
3. Include:
   - Clear instructions
   - Expected output format
   - When to use it

Delete this example file when setting up your project.
