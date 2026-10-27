# 🤝 Contributing

How changes get into HomeLab. The same rules apply in
[homelab-cluster](https://github.com/GreenMachine582/homelab-cluster/blob/main/CONTRIBUTING.md).

**Quick links:** [🔀 Flow](#-flow) · [💻 Where to work](#-where-to-work) · [✍️ Commit messages](#️-commit-messages) ·
[⚙️ Ansible changes](#️-ansible-changes)

---

## 🔀 Flow

```
branch ──► commits (signed) ──► PR to main ──► checks pass ──► merge ──► git pull in WSL ──► run the playbook
```

- 🔒 `main` is protected. Changes go through a PR. Direct pushes, force-pushes and branch deletion are blocked.
- ✍️ Every commit on `main` must be signed.
- 🎯 One change per PR. A playbook change and the docs that describe it go in the same PR.
- ➕ Update an open PR by adding commits, or by merging `main` into the branch. Never rebase and force-push.

**Branch names:** `<area>/<short-description>`, for example `k8s/cloudflared-cli`, `k8s/gateway-check-route`,
`docs/k8s-restructure`.

---

## 💻 Where to work

| Clone                         | Used for |
|-------------------------------|----------|
| 🪟 Windows (OneDrive) `HomeLab/` | Editing, committing (signed) and pushing |
| 🐧 WSL `~/homelab`               | Running Ansible. It holds `vault.yml`, `.vault_pass`, `overrides.yml` and the SSH keys |

> [!IMPORTANT]
> **Commit and push from Windows.** Windows git signs commits with an SSH key. WSL git has no signing key, so its
> commits are rejected on `main`. After merging, `git pull` in WSL and run from there.
>
> `git log --show-signature` reports "No signature" because no allowed-signers file is set. Check a commit with
> `git cat-file -p <sha> | grep "BEGIN SSH SIGNATURE"` instead.

> [!TIP]
> Don't `git stash -u` in the OneDrive clone: OneDrive can block git from removing untracked folders, which leaves
> the stash half-applied. Carry local changes with `git switch -c`, or commit them first.

---

## ✍️ Commit messages

[Conventional Commits](https://www.conventionalcommits.org):

```
type(scope): subject

Why the change was needed: what was broken or missing, and anything a reviewer
wouldn't guess from the diff.

Co-Authored-By: …            (optional trailers)
```

- **scope** (optional): lowercase, naming what the change is about: the role, playbook or area, such as `k8s`,
  `cilium`, `flux`, `cluster_status`, `k8s_prereqs` or `etcd_backup`.
- **subject**: imperative or descriptive, no trailing period. The whole first line is at most **100 characters**.
- **`!`** after the type or scope marks a breaking change, for example a variable that must now be set in
  `overrides.yml`: `feat(k8s)!: require k8s_api_client_ip`.
- **The PR title follows the same format.** GitHub uses it for squash merges.

<details>
<summary><b>Types</b></summary>

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

</details>

<details>
<summary><b>Examples from this repo</b></summary>

```
feat(k8s): etcd snapshots, fetch home, restore rehearsal (M2 part B)
fix(k8s_prereqs): keep k8s-api in the cloud-init hosts template
feat(controller): pinned cloudflared CLI for the M4 tunnel
fix(cluster_status): tell "site route off" from a broken Gateway
```

</details>

<details>
<summary><b>The <code>commit-style</code> check</b></summary>

`.github/workflows/commit-style.yml` runs on every PR to `main`. Its `commit-style` job checks the PR title and each
non-merge commit in the PR, and is a required status check. GitHub's own `Merge pull request …` / `Merge branch …`
commits and `git revert`'s `Revert "…"` are exempt. Commits from before the check aren't re-checked.

To fix a bad message, do it **before pushing**: `git commit --amend` for the last commit. Once a commit is pushed,
don't rewrite it. Instead, cherry-pick the changes onto a new branch with fixed messages, open a new PR, and close
the old one.

</details>

---

## ⚙️ Ansible changes

- [ ] 🎨 Follow the surrounding style: task names `"Area | What it does"`, comments that say why, `changed_when` on
  read-only commands.
- [ ] 🧪 Diagnostics and checks go into playbooks (`cluster_status.yml`), not one-off command lists in docs.
- [ ] 📝 Say in the PR what a changing playbook will do to the nodes and how it was tested (`--check`, which nodes,
  what you saw). Read-only playbooks (`cluster_status.yml`) are safe any time.
- [ ] 📌 Versions are pinned in `group_vars/k8s.yml`, with checksums where the download has them. A version Renovate
  should track gets a `# renovate: datasource=… depName=…` comment on the line above (`.github/renovate.json5`).
  A held version also gets a `packageRules` entry with an `allowedVersions` cap, `dependencyDashboardApproval: true`
  and a description saying why. The cap is the hold: approving an update in the dashboard or the Mend portal can't
  move past it, only a PR that lifts it.
- [ ] 🔐 Never commit `vault.yml`, `.vault_pass`, `overrides.yml`, keys or tokens. They're gitignored. Keep it that
  way.

> [!WARNING]
> A free-form `shell:`/`command:` block can't contain an apostrophe, even in a comment. Ansible's argument splitter
> reads it as an unclosed quote and refuses the whole play.
