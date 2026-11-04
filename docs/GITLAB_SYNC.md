# One-way GitHub → GitLab mirror

GitHub stays canonical. The workflow `.github/workflows/sync-gitlab.yml` copies **all Git branches and tags** to GitLab, including commit history reachable from those refs. It never deletes or force-updates GitLab refs. A divergence produces a visible failure instead of destroying history.

## Destinations

| GitHub source | GitLab destination | Current state on 2026-11-04 |
|---|---|---|
| `RamiConstruct/X402` (public) | Create `RamiConstruct/X402` in GitLab | Not yet created; choose **empty project, without README** |
| `RamiConstruct/MaryDream` (private) | `https://gitlab.com/marydream-group/marydream-project.git` | Existing, private, empty repository |

For X402 a *private* GitLab mirror is a sensible default. No secrets or private data should be added to GitHub because the X402 source remains public.

## One-time setup on GitLab (requires account owner)

1. Create an empty GitLab project for X402: **New project > Create blank project**, name `X402`, namespace `RamiConstruct`, private visibility, and **do not initialize a README**. If the desired namespace is not available, use a group you own and change the URL accordingly.
2. Keep `marydream-group/marydream-project` private and empty, because GitHub MaryDream has its own existing Git history.
3. Create a short-lived **GitLab personal access token** with only `write_repository`, or a narrower project access token if supported by your GitLab plan. Token owner must be allowed to push to destination branches.
4. Enable **2FA** on GitLab, keep the token outside any repo, and rotate/revoke it if exposed.

## One-time setup on each GitHub source repository

Under **Settings > Secrets and variables > Actions**:

- Repository **variable** `GITLAB_REPO_URL`:
  - For X402: `https://gitlab.com/RamiConstruct/X402.git` (adjust if destination differs)
  - For MaryDream: `https://gitlab.com/marydream-group/marydream-project.git`
- Repository **secret** `GITLAB_MIRROR_TOKEN`: the GitLab token (never paste it in issue descriptions, files, or PRs).

Then merge the matching GitHub workflow PR into the GitHub default branch. From **Actions > Sync GitHub to GitLab > Run workflow**, start the initial transfer. Check GitLab for the full set of branches, tags and commit SHA values, and confirm privacy. Afterwards, it runs after pushes to `main` / X402's current default branch and every three hours (GitHub scheduled jobs can be delayed). On MaryDream, the workflow is in its `main` branch.

## Limits and safeguards

- Git **content and history** only. GitHub issues, PRs, comments, collaborators, secrets, Actions logs, artifacts, releases, and branch protection are **not** mirrored by this workflow.
- No GitLab → GitHub sync; no bidirectional edits. Don't commit directly on GitLab mirror branches.
- No deploys or payments.
- Never use `--mirror`, `--force` or `--delete` blindly on a downstream repository.
- If GitLab denies a protected branch push, repair access settings rather than force-writing history.
- A GitLab personal token may access other repos owned by its user; prefer least privilege and short expiration.

## GitHub default branch issue in X402

As of 2026-11-04 the GitHub default is `claude/x402-service-discovery-workshop-xjjmjt`, not `main`. The workflow intentionally includes both branch names and transfers **all** branches (including `main`). Decide separately which is the stable release branch; do not change the default automatically.
