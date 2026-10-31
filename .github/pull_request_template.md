> **Note to contributors:**
> This template is part of our review process. A pull request that does not meaningfully complete the sections below, or does not show understanding of the change, may be closed without detailed review.

### Description & Design

<!--
Start with what changes for the user: "Deduparr now X, instead of Y."

When a user can see the change, show it, with what stays the same as its own row:

| First start, `./config` missing | Before | After |
| --- | --- | --- |
| Default settings | exits with a database error | starts |
| `./config` already there | starts | unchanged |

Then, as far as a reader needs it:
- What caused it, and since when
- Why this approach, and how it works at a high level
- Trade-offs, edge cases and limitations
- Anything breaking, under a "### Breaking" heading
-->

### Related issue

<!-- Fixes #123 -->

### Verified

<!--
What you did, against which real services and versions, and what you saw: the files on
disk, what each service holds, the logs, the screen. Numbers where you can measure, and
one screenshot per flow you touched. Say what you could not verify. No credentials or
account names. The stand-ins in frontend/e2e do not count.
-->

### Checklist

- [ ] I understand the code I am submitting and can explain how it works
- [ ] I have reviewed my own change
- [ ] `bash scripts/test.sh` passes, with tests for what earns one
- [ ] The title follows Conventional Commits and says what changes: it appears as written in the release notes
- [ ] Model changes come with a migration from `scripts/new-migration.sh`
- [ ] Documentation updated, ARCHITECTURE.md too if a boundary moved
