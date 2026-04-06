---
name: Feature / Task
about: New functionality, improvement, or Week N task from the step-by-step guide
title: "feat(COMPONENT): short description"
labels: ["enhancement"]
assignees: []
---

## Week / Task Reference

<!-- Which week and task from docs/step-by-step.md does this relate to? -->
Week: ___  Task: ___  (e.g. Week 2, Task 2.3 — Kinesis Producer)

---

## Description

<!-- What needs to be built and why? -->

---

## Acceptance Criteria

A PR for this issue is complete when:

- [ ] Feature is implemented in `src/`
- [ ] Unit tests added in `tests/unit/`
- [ ] Tests pass: `make test`
- [ ] Linting passes: `make lint`
- [ ] Terraform updated if new AWS resources are needed
- [ ] CLAUDE.md updated if architecture changed
- [ ] Manual verification in dev workspace documented below

---

## Implementation Notes

<!-- Design decisions, edge cases to handle, references -->

**Edge cases to handle:**
-
-

**Key design decision:**
<!-- What tradeoff are you making? Why? -->

---

## Skill Unlocked

<!-- From the project spec — which skill does this contribute to? -->
- [ ] Kinesis producer/consumer patterns
- [ ] Lambda event processing
- [ ] Spark sessionization
- [ ] DynamoDB single-table design
- [ ] Terraform modules + workspaces
- [ ] Lambda Architecture tradeoffs

---

## Estimated Effort

- [ ] Small — <2 hours (single function, clear spec)
- [ ] Medium — 2–4 hours (new module with tests)
- [ ] Large — 4–8 hours (new component: simulator, Spark job, Terraform module)
