# /sup — Quick Status Check

Five-second status overview. What's the current state of things?

## Instructions

Give a rapid status check covering:

1. **Current branch & git state**
   - Which branch?
   - Clean or dirty working tree?
   - Ahead/behind remote?

2. **What's in progress**
   - Current task being worked on
   - Estimated completion (near/far)

3. **Any blockers?**
   - Yes/No + one-liner if yes

4. **Last completed item**
   - Most recent accomplishment

## Output Format

Keep it SHORT. Max 10 lines.

```
## Status

Branch: `feature/xyz` (3 uncommitted files)
Working on: [current task]
Progress: [emoji indicator] [brief status]
Blocked: No | Yes — [reason]
Last done: [most recent completion]
```

## Progress Indicators

- `[=====>    ]` — Making progress
- `[=========>]` — Almost done
- `[??????????]` — Stuck/investigating
- `[==========]` — Complete, needs review
