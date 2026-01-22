# /plan — Two-Phase Planning Workflow

Complex features need planning before implementation. No YOLO commits.

## Phase 1: Planning

### Instructions

1. **Understand the requirement**
   - What's being asked?
   - What's the success criteria?
   - What are the constraints?

2. **Research the codebase**
   - Find related existing code
   - Identify patterns to follow
   - Note dependencies

3. **Design the solution**
   - Architecture decisions
   - Component breakdown
   - Data flow
   - API design (if applicable)

4. **Identify risks & edge cases**
   - What could go wrong?
   - What edge cases exist?
   - What's the testing strategy?

5. **Create implementation plan**
   - Break into discrete tasks
   - Order by dependencies
   - Estimate complexity (S/M/L)

6. **STOP and get approval**
   - Present the plan
   - Wait for user feedback
   - Do NOT proceed until approved

### Phase 1 Output Format

```
## Implementation Plan: [Feature Name]

### Understanding
[What we're building and why]

### Approach
[High-level solution design]

### Architecture
[Components, data flow, key decisions]

### Tasks
| # | Task | Complexity | Dependencies |
|---|------|------------|--------------|
| 1 | [X]  | S/M/L      | None         |
| 2 | [Y]  | S/M/L      | Task 1       |

### Risks & Mitigations
- Risk 1: [Mitigation]
- Risk 2: [Mitigation]

### Testing Strategy
[How we'll verify it works]

### Open Questions
- [ ] [Question needing decision]

---
**Awaiting approval to proceed to Phase 2 (Implementation)**
```

## Phase 2: Implementation

Only begin after explicit approval.

### Instructions

1. **Follow the approved plan**
   - Execute tasks in order
   - Don't deviate without discussion

2. **Incremental commits**
   - Commit after each logical unit
   - Keep commits reviewable

3. **Test as you go**
   - Verify each piece works
   - Run existing tests

4. **Document decisions**
   - Note any deviations from plan
   - Update docs as needed

5. **Final review**
   - Summary of what was built
   - Any remaining work
   - How to test/verify

### Phase 2 Completion Format

```
## Implementation Complete: [Feature Name]

### Delivered
- [x] Task 1: [brief description]
- [x] Task 2: [brief description]

### Commits
- `abc123` — [message]
- `def456` — [message]

### Deviations from Plan
- [Any changes and why]

### How to Test
1. [Step 1]
2. [Step 2]

### Follow-up Items
- [ ] [Any remaining work]
```
