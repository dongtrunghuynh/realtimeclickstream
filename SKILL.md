# SKILL.md — Git, PR & Code Review Workflow

> Your engineering workflow guide for this project. Follow this every time you touch code.
> These are the habits that separate junior engineers from senior ones on real teams.

---

## Table of Contents

1. [Branch Strategy](#1-branch-strategy)
2. [Commit Standards](#2-commit-standards)
3. [Pushing Code](#3-pushing-code)
4. [Pulling & Syncing](#4-pulling--syncing)
5. [Opening a Pull Request](#5-opening-a-pull-request)
6. [PR Review — As Author](#6-pr-review--as-author)
7. [PR Review — As Reviewer](#7-pr-review--as-reviewer)
8. [PR Comments — Writing & Responding](#8-pr-comments--writing--responding)
9. [Code Refactor Workflow](#9-code-refactor-workflow)
10. [Merging & Cleanup](#10-merging--cleanup)
11. [Emergency Hotfix Workflow](#11-emergency-hotfix-workflow)
12. [Daily Workflow Checklist](#12-daily-workflow-checklist)

---

## 1. Branch Strategy

This project follows **GitHub Flow** (simple, effective for small teams):

```
main          ← always deployable, protected
  └── feature/simulator-kinesis-producer
  └── feature/lambda-sessionizer
  └── feature/spark-batch-reconciler
  └── feature/terraform-dynamodb-module
  └── fix/late-arrival-timestamp-bug
  └── refactor/session-state-extraction
  └── docs/architecture-diagram
```

### Branch Naming Convention

| Type | Pattern | Example |
|------|---------|---------|
| New feature | `feature/<short-description>` | `feature/kinesis-producer` |
| Bug fix | `fix/<what-is-broken>` | `fix/session-boundary-off-by-one` |
| Refactor | `refactor/<what-changed>` | `refactor/dynamodb-client-abstraction` |
| Documentation | `docs/<topic>` | `docs/emr-spark-setup` |
| Terraform | `infra/<resource>` | `infra/emr-serverless-module` |
| Chore | `chore/<task>` | `chore/update-requirements` |

### Commands

```bash
# Create a new branch from an up-to-date main
git checkout main
git pull origin main
git checkout -b feature/your-feature-name

# List branches
git branch -a

# Delete a merged local branch
git branch -d feature/your-feature-name

# Delete a remote branch after merge
git push origin --delete feature/your-feature-name
```

---

## 2. Commit Standards

Follow **Conventional Commits** — this makes your git history readable and enables
automated changelogs.

### Format

```
<type>(<scope>): <short summary>

[optional body — explain WHY, not WHAT]

[optional footer — refs, breaking changes]
```

### Types

| Type | When to Use |
|------|------------|
| `feat` | New functionality (simulator, Lambda handler, Spark job) |
| `fix` | Bug fix |
| `refactor` | Code restructure without behaviour change |
| `test` | Adding or updating tests |
| `docs` | Documentation only |
| `infra` | Terraform changes |
| `chore` | Build scripts, dependencies, tooling |
| `perf` | Performance improvement |

### Scopes (this project)

`simulator`, `lambda`, `spark`, `dynamodb`, `kinesis`, `terraform`, `athena`, `dashboard`, `tests`, `scripts`

### Examples

```bash
# Good commits
git commit -m "feat(simulator): add configurable event replay rate to KinesisProducer"
git commit -m "fix(lambda): correct 30-min session boundary when events arrive out-of-order"
git commit -m "infra(dynamodb): add TTL attribute and GSI for session lookups"
git commit -m "refactor(spark): extract late-arrival detection into standalone function"
git commit -m "test(sessionizer): add unit tests for cart total calculation edge cases"
git commit -m "docs(architecture): add Lambda Architecture tradeoff diagram"

# Bad commits (never do these)
git commit -m "fix stuff"
git commit -m "WIP"
git commit -m "asdfgh"
git commit -m "final final v2"
```

### Commit Body (use for non-obvious changes)

```bash
git commit -m "fix(lambda): handle duplicate Kinesis records via idempotency key

Kinesis 'at-least-once' delivery means Lambda can receive the same
record twice during shard re-balancing. Added event_id deduplication
using a DynamoDB conditional write to prevent double-counting sessions.

Fixes: #23
See also: https://docs.aws.amazon.com/lambda/latest/dg/with-kinesis.html"
```

---

## 3. Pushing Code

```bash
# Push a new branch for the first time
git push -u origin feature/your-feature-name

# Push subsequent commits
git push

# Force push (only on YOUR branch, NEVER on main — use with caution after rebase)
git push --force-with-lease

# Push and immediately open a PR (GitHub CLI)
gh pr create --fill

# Check what you're about to push
git log origin/main..HEAD --oneline
git diff origin/main..HEAD --stat
```

### Pre-Push Checklist

```bash
# Run before every push
cd realtimeclickstream

# 1. Lint Python
pip install ruff
ruff check src/ tests/

# 2. Run unit tests
pytest tests/unit/ -v

# 3. Validate Terraform (if you changed .tf files)
cd terraform && terraform validate && terraform fmt -check

# 4. Check for secrets/credentials accidentally staged
git diff --cached | grep -i "aws_secret\|password\|api_key\|token"
```

---

## 4. Pulling & Syncing

```bash
# Sync your branch with latest main (preferred over merge)
git fetch origin
git rebase origin/main

# If rebase has conflicts
git status                          # See conflicted files
# Edit the conflicted files, then:
git add <resolved-file>
git rebase --continue

# Abort a messy rebase and start over
git rebase --abort

# Pull with rebase as default (set once)
git config --global pull.rebase true

# Fetch all remote branches
git fetch --all --prune
```

### Keeping Long-Running Branches Fresh

If your branch lives more than 2 days, rebase daily:

```bash
git fetch origin
git rebase origin/main
git push --force-with-lease   # update remote branch after rebase
```

---

## 5. Opening a Pull Request

### Before Opening

- [ ] Branch is rebased on latest `main`
- [ ] All tests pass locally (`pytest tests/unit/`)
- [ ] Terraform validates (`terraform validate`)
- [ ] No hardcoded credentials or `.env` files staged
- [ ] Self-reviewed your own diff in GitHub before requesting review

### PR Title Format

Same as commit format: `type(scope): description`

```
feat(lambda): implement sessionizer with 30-min inactivity window
fix(kinesis): handle shard iterator expiry in event simulator
infra(emr): add EMR Serverless Spark application Terraform module
refactor(spark): extract session stitching logic into SessionStitcher class
```

### PR Description Template (`.github/PULL_REQUEST_TEMPLATE.md`)

Already set up in this repo — fill it out every time. Don't leave sections blank.

### PR Size Guidelines

| Size | Lines Changed | Guidance |
|------|--------------|---------|
| Small | <100 | Ideal — fast to review |
| Medium | 100–400 | Acceptable — add extra context in description |
| Large | 400–800 | Break it up if possible |
| Too Large | >800 | Must be split — reviewer will ask you to |

### Draft PRs

Open a **Draft PR** early when:
- You want early feedback on direction
- You're blocked and need a second opinion
- The feature is large and spans multiple commits

```bash
gh pr create --draft --title "feat(spark): batch reconciler WIP" --body "Early look — not ready for review yet"
```

---

## 6. PR Review — As Author

Your responsibilities don't end when you open the PR:

### After Opening

1. **Self-review first** — read your own diff in GitHub. You'll catch 30% of issues.
2. **Add inline comments** on non-obvious code in your own PR to guide the reviewer.
3. **Respond within 24 hours** to all review comments.
4. **Never resolve a reviewer's comment yourself** — let the reviewer resolve after you address it.
5. **Don't push new features** while a review is in progress — only push fixes to review comments.

### Responding to Comments

```markdown
# Good response to a review comment
> Why are you using a 5-second window here?

Good catch — I chose 5s to match the Kinesis `GetRecords` polling interval so each
Lambda invocation processes one batch before the next arrives. Updated the inline
comment to explain this. Let me know if you'd like me to make it configurable.

# Another good response — disagreeing respectfully
> I'd extract this into a separate class

I considered that, but since `late_arrival_injector.py` is already <80 lines
and only used in one place, I think the added abstraction layer hurts readability here.
Happy to revisit if the file grows. What do you think?
```

---

## 7. PR Review — As Reviewer

### Review SLA

- **Acknowledge** the PR within 4 hours: leave a comment like "On my list, will review by EOD"
- **Complete** the review within 1 business day for small/medium PRs

### What to Check

#### Correctness
- [ ] Does the logic match the stated intent?
- [ ] Are edge cases handled? (empty Kinesis batch, session expiry, duplicate events)
- [ ] Are error paths handled? (DynamoDB write failure, Kinesis shard error)

#### Data Engineering Specifics
- [ ] Is event ordering assumed anywhere it shouldn't be?
- [ ] Is late-arrival logic correct? (timestamp used: event time vs arrival time?)
- [ ] Are Kinesis shard limits respected? (1MB/s write, 2MB/s read per shard)
- [ ] Are DynamoDB writes idempotent?
- [ ] Does the Spark job partition output correctly?
- [ ] Are Terraform resources tagged with `env` and `project`?

#### Code Quality
- [ ] Functions are single-purpose (<30 lines ideally)
- [ ] No hardcoded values — use config/env vars
- [ ] Logging is meaningful (include session_id, event_id in log lines)
- [ ] Tests cover the new code

#### Security
- [ ] No credentials in code
- [ ] IAM roles follow least-privilege
- [ ] No overly permissive S3 bucket policies

### Review Comment Types (label them)

```markdown
# Blocking — must be fixed before merge
**[BLOCKING]** This will cause Lambda to silently swallow exceptions. 
The except block needs to re-raise or the error will never surface.

# Non-blocking suggestion
**[SUGGESTION]** Consider extracting this into a helper function — 
it's duplicated in `session_state.py` line 47.

# Question — not blocking, just curious
**[QUESTION]** Why are we using `batch_write_item` here instead of 
`transact_write_items`? Is atomicity not needed?

# Positive reinforcement — do this!
**[NICE]** Clean handling of the TTL calculation — exactly right.

# Nitpick — trivially optional
**[NIT]** `session_id` → `session_id` for consistency with the rest of the file.
```

### Approving

Only approve when ALL blocking issues are resolved. Use the GitHub "Approve" button —
don't just comment "LGTM" and leave it as "Comment" state.

---

## 8. PR Comments — Writing & Responding

### Writing Effective Comments

```markdown
# Bad comment (unhelpful)
This is wrong.

# Good comment (explains what, why, and how to fix)
**[BLOCKING]** `event_time` can be None if the Kinesis record was 
injected by the late-arrival simulator without a timestamp. 
This will cause a KeyError in `calculate_session_duration()`.

Suggested fix:
```python
event_time = record.get("event_time") or record["kinesis_arrival_time"]
```
See the event schema in `data/schemas/event_schema.json` for nullable fields.
```

### Inline Code in Comments

Always use backticks for inline code and triple-backtick blocks for multi-line code.
Specify the language for syntax highlighting: ` ```python `.

### Linking to References

```markdown
Related to the Kinesis ordering guarantee — per AWS docs, ordering is
only guaranteed within a shard, not across shards. Worth commenting this
in the code. [AWS Kinesis Data Ordering](https://docs.aws.amazon.com/streams/latest/dev/key-concepts.html)
```

---

## 9. Code Refactor Workflow

Refactors that don't change behaviour deserve their own PR — never mix
refactor + feature in the same PR.

### Refactor Process

```bash
# 1. Open a refactor branch
git checkout -b refactor/extract-session-state-class

# 2. Write/update tests FIRST (they define expected behaviour)
# Tests must pass before AND after the refactor

# 3. Make the smallest change that passes tests
# 4. Run tests after each logical chunk of changes
pytest tests/unit/ -v -x   # -x stops on first failure

# 5. Commit with clear scope
git commit -m "refactor(lambda): extract SessionState into dedicated class

No behaviour change. Extracted session accumulation logic from handler.py
into session_state.py to enable unit testing in isolation and reduce
handler.py from 180 to 90 lines."
```

### Refactor PR Description Must Include

- What changed structurally
- What did NOT change (behaviour, API contracts)
- Before/after line count or complexity metric
- Link to tests confirming no regression

### Common Refactors in This Project

| Smell | Refactor |
|-------|---------|
| Lambda handler >100 lines | Extract business logic to separate modules |
| Repeated DynamoDB client init | Move to `shared/dynamodb_client.py` singleton |
| Hardcoded stream names in tests | Use `pytest` fixtures with config injection |
| Spark job doing too much | Split into `session_stitcher.py` + `late_arrival_handler.py` |
| Terraform resource repeated 3x | Extract to module in `terraform/modules/` |

---

## 10. Merging & Cleanup

### Merge Strategy

This project uses **Squash and Merge** for feature branches:
- Keeps `main` history clean (one commit per feature)
- Makes `git log --oneline` on `main` readable

**Exception:** Use **Merge Commit** for large features with meaningful intermediate
commits that tell a story reviewers should see.

```bash
# After PR is approved — merge via GitHub UI (preferred)
# Or via CLI:
gh pr merge <PR-number> --squash --delete-branch
```

### Post-Merge Cleanup

```bash
# After your PR is merged
git checkout main
git pull origin main
git branch -d feature/your-feature-name   # delete local branch
```

---

## 11. Emergency Hotfix Workflow

```bash
# Cut directly from main
git checkout main
git pull origin main
git checkout -b fix/kinesis-shard-exhaustion

# Make the minimal fix
# Test it
pytest tests/unit/test_simulator.py -v

# Open PR with [HOTFIX] in title — marks it for expedited review
gh pr create --title "[HOTFIX] fix(kinesis): cap retry backoff to prevent shard exhaustion"

# After merge — tag the release
git tag -a v1.0.1 -m "Hotfix: Kinesis retry backoff cap"
git push origin v1.0.1
```

---

## 12. Daily Workflow Checklist

```
Morning:
  [ ] git pull origin main (or git fetch + rebase)
  [ ] Check open PR comments — respond to anything from yesterday
  [ ] Check GitHub Issues for new assignments

During Development:
  [ ] Commit small and often — at least every 2 hours of work
  [ ] Run tests before each push
  [ ] No TODOs in committed code — open a GitHub Issue instead

End of Day:
  [ ] Push WIP to your branch (so it's backed up)
  [ ] If it's not ready for review: push as Draft PR
  [ ] terraform workspace select dev && terraform destroy (cost control!)
  [ ] Log off CloudWatch / stop any active EMR jobs
```

---

## Quick Reference Card

```bash
# Start a feature
git checkout main && git pull && git checkout -b feature/name

# Save work
git add -p                          # Stage interactively (review each hunk)
git commit -m "feat(scope): message"

# Push
git push -u origin feature/name     # First push
git push                            # Subsequent pushes

# Sync with main
git fetch origin && git rebase origin/main

# Open PR
gh pr create --fill

# Check PR status
gh pr status

# Tear down dev infra (do this every day)
cd terraform && terraform workspace select dev && terraform destroy -var-file=environments/dev.tfvars
```
