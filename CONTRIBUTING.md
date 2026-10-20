# Contributing

How changes get into HomeLab. The same rules apply in
[homelab-cluster](https://github.com/GreenMachine582/homelab-cluster/blob/main/CONTRIBUTING.md).

## Flow

```
branch ──► commits (signed) ──► PR to main ──► checks pass ──► merge ──► pull in WSL, run the playbook
```

- `main` is protected. Changes go through a PR. Direct pushes, force-pushes and branch deletion are blocked.
- Every commit on `main` must be signed.
- One change per PR. A playbook change and the docs that describe it go in the same PR.

**Branch names:** `<area>/<short-description>`, for example `k8s/cilium-flux-owned`, `docs/status-contributing`,
`m3/flux`.

## Where to work

There are two clones:

| Clone                                   | Used for                                                   |
|-----------------------------------------|------------------------------------------------------------|
| Windows (OneDrive) `HomeLab/`           | Editing, committing (signed) and pushing                   |
| WSL `~/homelab`                         | Running Ansible: it holds `vault.yml`, `.vault_pass`, `overrides.yml` and the SSH keys |

**Commit and push from Windows.** Windows git signs commits with an SSH key. WSL git has no signing key, so its
commits are rejected on `main`. After merging, `git pull` in WSL and run from there.

`git log --show-signature` reports "No signature" because no allowed-signers file is set. Check a commit with
`git cat-file -p <sha> | grep "BEGIN SSH SIGNATURE"` instead.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org):

```
type(scope): subject

Why the change was needed: what was broken or missing, and anything a reviewer
wouldn't guess from the diff.

Co-Authored-By: …            (optional trailers)
```

- **type**: one of
  | type       | for                                                  |
  |------------|------------------------------------------------------|
  | `feat`     | new behaviour: a role, playbook, task or option      |
  | `fix`      | something that was broken                            |
  | `docs`     | documentation only                                   |
  | `chore`    | housekeeping that changes no behaviour (renames, version pins) |
  | `refactor` | restructuring with the same behaviour                |
  | `test`     | rehearsals and checks (restore tests, smoke tests)   |
  | `ci`       | GitHub Actions workflows                             |
  | `build`    | tooling and dependencies (`requirements.yml`, the controller toolchain) |
  | `perf`     | faster or lighter, same behaviour                    |
  | `revert`   | undoing an earlier commit                            |
- **scope** (optional): lowercase, what the change is about. Use the role, playbook or area: `k8s`, `cilium`,
  `flux`, `cluster_status`, `k8s_prereqs`, `etcd_backup`.
- **subject**: imperative or descriptive, no trailing period. The whole first line is at most 100 characters.
- **`!`** after the type or scope marks a breaking change, for example a variable that must now be set in
  `overrides.yml`: `feat(k8s)!: require k8s_api_client_ip`.

Examples from this repo:

```
feat(k8s): etcd snapshots, fetch home, restore rehearsal (M2 part B)
fix(k8s_prereqs): keep k8s-api in the cloud-init hosts template
docs(k8s): rpi-01 and rpi-02 joined; database taint stays off for now
```

**The PR title follows the same format.** GitHub uses it for squash merges.

### The check

`.github/workflows/commit-style.yml` runs on every PR to `main`. Its `commit-style` job checks the PR title and each
non-merge commit in the PR, and is a required status check. GitHub's own `Merge pull request …` / `Merge branch …`
commits and `git revert`'s `Revert "…"` are exempt. Commits from before the check aren't re-checked.

To fix a failing commit: `git commit --amend` (last commit) or `git rebase -i main`, then
`git push --force-with-lease` to the PR branch. Never to `main`.

## Ansible changes

- Follow the surrounding style: task names `"Area | What it does"`, comments that say why, `changed_when` on
  read-only commands.
- Shell blocks in a free-form `shell:`/`command:` can't contain an apostrophe, even in a comment. Ansible's
  argument splitter reads it as an unclosed quote and refuses the whole play.
- Diagnostics and checks go into playbooks (`cluster_status.yml`), not one-off command lists in docs.
- Read-only playbooks (`cluster_status.yml`) are safe any time. Say in the PR what a changing playbook will do to
  the nodes and how it was tested (`--check`, which nodes, what you saw).
- Never commit `vault.yml`, `.vault_pass`, `overrides.yml`, keys or tokens. They're gitignored. Keep it that way.
