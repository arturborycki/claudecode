# /wrap — End of Session

End this session properly. Complete handoff documentation for the next agent or future session.

## Instructions

1. **Summarize completed work**
   - List all tasks completed this session
   - Note any files created or modified
   - Document any important decisions made

2. **Document in-progress work**
   - What's partially done?
   - What's the current state?
   - What remains to finish?

3. **Update _NEXT_SESSION_MEMO.md**
   - Fill in all sections
   - Be specific about next steps
   - Note any blockers or open questions

4. **Stage and commit all changes**
   ```bash
   git add -A
   git status
   ```
   - Review what's being committed
   - Write a clear commit message summarizing the session's work
   - Commit with descriptive message

5. **Final status report**
   - Confirm everything is committed
   - Summarize what the next session should pick up

## Output Format

```
## Session Wrap-Up

### Completed
- [x] Task 1
- [x] Task 2

### In Progress
- [ ] Task 3 (80% done — needs X)

### Files Changed
- `path/to/file.ts` — description
- `path/to/other.ts` — description

### Commit
[commit hash] — [commit message]

### Next Session Should
1. First priority
2. Second priority
3. Third priority

### Blockers
- [Any blocking issues]
```
