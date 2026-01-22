# /research — Deep Exploration Mode

Investigate without polluting the main conversation. Use for complex exploration.

## Instructions

This command signals a research/exploration task that should:
- Be thorough and comprehensive
- Explore multiple angles
- Document findings clearly
- NOT make changes to code (read-only exploration)

## Research Protocol

1. **Define the question**
   - What exactly are we trying to learn?
   - What would a good answer look like?

2. **Search strategy**
   - Codebase search (grep, file exploration)
   - Documentation review
   - External research if needed

3. **Explore systematically**
   - Start broad, then narrow
   - Follow the dependency chain
   - Note patterns and conventions

4. **Document findings**
   - Key discoveries
   - How things work
   - Where things are located
   - Patterns identified

5. **Synthesize**
   - Answer the original question
   - Provide actionable recommendations
   - Note any gaps or uncertainties

## Output Format

```
## Research: [Topic]

### Question
[What we're investigating]

### Methodology
[How we searched/explored]

### Findings

#### [Finding 1]
- Location: `path/to/file.ts`
- How it works: [explanation]
- Relevant code: [snippet if helpful]

#### [Finding 2]
...

### Architecture/Pattern Summary
[High-level understanding gained]

### Recommendations
1. [Actionable recommendation]
2. [Actionable recommendation]

### Gaps / Uncertainties
- [Things we couldn't determine]
- [Areas needing more investigation]

### Key Files Reference
| File | Purpose |
|------|---------|
| `path/file.ts` | [What it does] |
```

## When to Use

- Understanding unfamiliar code
- Investigating bugs
- Learning existing patterns
- Architecture discovery
- Before major refactors
- Evaluating technical approaches
