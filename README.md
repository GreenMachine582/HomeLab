# Homelab

![Ansible](https://img.shields.io/badge/Ansible-EE0000?logo=ansible&logoColor=white)
![Kubernetes](https://img.shields.io/badge/Kubernetes-326CE5?logo=kubernetes&logoColor=white)
![Cilium](https://img.shields.io/badge/Cilium-F8C517?logo=cilium&logoColor=black)
![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi-C51A4A?logo=raspberrypi&logoColor=white)
![Tailscale](https://img.shields.io/badge/Tailscale-579DFF?logo=tailscale&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-homelab-4A90D9)
![Status](https://img.shields.io/badge/status-M4_Platform-yellow)

Ansible for the homelab's machines. This repo builds the nodes and the bare Kubernetes cluster: hardening,
Tailscale, containerd, `kubeadm`, the first Cilium install, etcd backups, Flux bootstrap. It also sets up the
controller toolchain. Everything inside the cluster lives in
[homelab-cluster](https://github.com/GreenMachine582/homelab-cluster) and is applied by Flux.

> [!NOTE]
> **Status: M4, Platform.**
> - **M0–M3 done:** four nodes at the remote site, Cilium, daily etcd snapshots with a tested restore, and Flux
>   owning everything in the cluster, Cilium included.
> - **M4:** the Gateway, TLS, LB IPs, storage, the Cloudflare tunnel and Discord deploy notifications are live. The
>   backup target (a drive on a Pi, NFS) is left.
>
> See [homelab-cluster › M4](https://github.com/GreenMachine582/homelab-cluster/blob/main/docs/M4_PLATFORM.md).

**Quick links:** [🏗️ Architecture](#️-architecture) · [🚀 Getting started](#-getting-started) ·
[📚 Docs](#-docs) · [🗂️ Repo structure](#️-repo-structure) · [🔒 Security](#-security) ·
[💾 Backups](#-backups) · [🗺️ Roadmap](#️-roadmap) · [🗄️ Legacy stack](#️-legacy-compose-stack-removed-at-m8)

---

## 🏗️ Architecture

The nodes sit on one switch at a remote site, with static LAN IPs on `192.168.50.0/24`. Everything is run from **WSL
on the main PC at home** (the only Ansible controller) over **Tailscale**, using MagicDNS names.

| Node        | Role                                         | Hardware                              | Envoy |
|-------------|----------------------------------------------|---------------------------------------|-------|
| `laptop-01` | Control plane, Tailscale subnet router       | Old laptop (amd64), Debian 13, wired  | ✅ |
| `rpi-03`    | Worker, database node (local NVMe)           | Raspberry Pi 5 8 GB + NVMe, Argon V3  | ✅ |
| `rpi-01`    | Worker                                       | Raspberry Pi 4 2 GB, no case          | ❌ |
| `rpi-02`    | Worker                                       | Raspberry Pi 4 8 GB, Argon ONE V2     | ❌ |

```
WSL (home) ──Tailscale──► nodes        Ansible (bootstrap.yml, cluster.yml), kubectl → k8s-api
GitHub main ──────────────► Flux        everything inside the cluster (homelab-cluster)
```

<details>
<summary>🌐 <b>Access paths</b></summary>

| Situation                   | How you get in |
|-----------------------------|----------------|
| Normal                      | Tailscale MagicDNS: Ansible to `<node>.<tailnet>.ts.net`, kubectl via `k8s-api` → laptop-01's Tailscale IP |
| A device not on the tailnet | laptop-01's subnet route to the site LAN. Approve it in the Tailscale console when you need it, then disable it |
| Tailscale down on a node    | Break-glass: RDP to the site PC, SSH over the LAN with a one-hour certificate |
| laptop-01 off               | `playbooks/wake.yml` (Wake-on-LAN from a Pi). The Pis also wake it after every boot |

Details: [docs/K8S_SITE.md](./docs/K8S_SITE.md).

</details>

---

## 🚀 Getting started

Everything runs from the WSL clone `~/homelab`. Edit and commit in the Windows clone (see
[CONTRIBUTING.md](./CONTRIBUTING.md)).

```bash
ansible-playbook playbooks/controller.yml -K          # 🧰 controller: kubectl, cilium-cli, flux, sops, age, cloudflared
ansible-playbook playbooks/bootstrap.yml              # 🛡️ nodes: hardening, users, Tailscale, firewall (M1)
ansible-playbook playbooks/cluster.yml                # ☸️ kubeadm + Cilium + etcd backups (M2)
ansible-playbook playbooks/flux_bootstrap.yml         # 🔄 Flux + sops-age (M3); repairs Flux too
ansible-playbook playbooks/cluster_status.yml         # 🩺 read-only health report, safe any time
```

<details>
<summary>🧰 <b>All Kubernetes-era playbooks</b></summary>

| Playbook | What it does |
|---|---|
| `controller.yml` | Controller toolchain at pinned versions, `k8s-api` hosts entry, `KUBECONFIG`. `--tags ssh_ca` makes the break-glass CA; `--tags dev_wsl` sets up key + TOTP SSH into WSL ([REMOTE_ACCESS.md](./docs/REMOTE_ACCESS.md)) |
| `bootstrap.yml` | Fresh or hardened node → hardened, key-only, on the tailnet. Probes how to reach each node |
| `cluster.yml` | kubeadm cluster, Cilium (fresh installs only, since Flux owns it), labels/taints, etcd snapshot timer |
| `cluster_status.yml` | Read-only report: nodes, kubelet, Cilium, Gateway API, Gateway reachability from the controller. `-e connectivity_test=true` |
| `cluster_reset.yml` | Tears the cluster down (asks you to type `reset`) |
| `flux_bootstrap.yml` | Installs or repairs Flux from homelab-cluster's committed manifests, with the `sops-age` secret |
| `etcd_fetch.yml` | Newest etcd snapshot + PKI → `~/homelab-backups/etcd` |
| `etcd_restore_test.yml` | Restore rehearsal into a throwaway etcd |
| `identify_nodes.yml` | Finds and identifies freshly imaged nodes on the site LAN |
| `tailscale_admin.yml` | Tailscale policy (dry run by default; `-e confirm=true` applies) |
| `wake.yml` | Wake-on-LAN for laptop-01, then waits for SSH |

</details>

---

## 📚 Docs

| | Doc | For |
|---|---|---|
| 🛡️ | [K8S_BOOTSTRAP.md](./docs/K8S_BOOTSTRAP.md) | Preparing nodes, adding a fresh node at the site |
| ☸️ | [K8S_CLUSTER.md](./docs/K8S_CLUSTER.md) | Building the cluster, Flux, etcd backups and restore, troubleshooting |
| 🏞️ | [K8S_SITE.md](./docs/K8S_SITE.md) | The remote site: access paths, site LAN, router UI, power and wake-up, break-glass, one-time setup, moving to another site |
| 💻 | [REMOTE_ACCESS.md](./docs/REMOTE_ACCESS.md) | SSH from your laptop into WSL on the main PC: tailnet-only, SSH key + TOTP |
| 🤝 | [CONTRIBUTING.md](./CONTRIBUTING.md) | Branches, signed commits, Conventional Commits, Ansible style |
| 🧩 | [homelab-cluster docs](https://github.com/GreenMachine582/homelab-cluster/tree/main/docs) | Adding a service, secrets, M4 plan + Cloudflare setup |

---

## 🗂️ Repo structure

<details open>
<summary><b>Kubernetes-era layout</b></summary>

```text
HomeLab/
  inventories/
    k8s.yml                   # k8s → k8s_control_plane, k8s_workers, k8s_data
    group_vars/k8s.yml        # versions (Kubernetes, Cilium, Flux, sops, cloudflared), cluster settings
    group_vars/all/           # overrides.yml (IPs, gitignored), vault.yml (Ansible Vault, gitignored)
    host_vars/<node>.yml      # Argon case, l7 proxy, Wake-on-LAN, ...
  playbooks/                  # see "Getting started"; tasks/probe_ssh.yml is shared
  roles/
    users/  base_hardening/  firewall/  tailscale/      # every node
    node_network/  nvme_storage/  argon_case/           # static IPs, NVMe, Pi cases
    laptop_power/  wake_on_lan/                         # laptop-01 power, site wake-ups
    k8s_prereqs/  containerd/  kubeadm/                 # cluster prerequisites
    cilium_install/  k8s_node_config/  etcd_backup/     # CNI seed, labels/taints, snapshots
    k8s_client/                                         # the controller toolchain
  tailscale/policy.hujson.j2  # tailnet policy (tailscale_admin.yml)
  scripts/sign-breakglass.sh  # one-hour SSH certificates
  docs/K8S_*.md
  docs/REMOTE_ACCESS.md       # laptop → WSL: key + TOTP over the tailnet
```

</details>

---

## 🔒 Security

1. 🔑 **SSH:** key-only, no root login, non-standard port, `AllowTcpForwarding no`. `admin` (your key, sudo with a
   password) and `homelab` (the Ansible key, passwordless sudo).
2. 🧱 **Firewall:** UFW default-deny inbound. SSH and the API only from the site LAN and the tailnet. Cilium and
   kubelet ports only from the site LAN. Everything is trusted from the other nodes and the pod network. A 5-minute
   auto-rollback guards against lockout.
3. 🌐 **Tailscale:** nodes are tagged `tag:homelab` by admins only, can't connect to your devices, and never accept
   routes. The site subnet route is never auto-approved.
4. 🆘 **Break-glass:** one-hour SSH certificates signed by an offline CA, for when Tailscale is down.
5. 🔐 **Secrets:** Ansible Vault and `overrides.yml` stay on the controller and are never committed. Cluster
   secrets are SOPS + age in homelab-cluster.
6. 💻 **Remote access to WSL:** tailnet-only (admins' approved devices), then an SSH key and a TOTP code on every
   login. No public ports.
7. 🔀 **Change control:** protected `main`, signed commits, PRs, `commit-style` check.

---

## 💾 Backups

| Data | How | Where |
|---|---|---|
| etcd + PKI | `homelab-etcd-snapshot.timer`, daily, keeps 7 | laptop-01 `/var/backups/etcd` ✅ |
| Off-site copy | `etcd_fetch.yml` (weekly, and before risky changes) | `~/homelab-backups/etcd` at home ✅ |
| Backup target | External drive on a Pi, NFS | ⏳ M4 |
| age key, break-glass CA | Offline copies | Two places, one off-site |

Restore steps: [K8S_CLUSTER.md › etcd backups](./docs/K8S_CLUSTER.md#-etcd-backups).

---

## 🗺️ Roadmap

| Milestone | Scope | Status |
|---|---|---|
| M0 | Repo, age key, discord-gateway removed, splits frozen | ✅ |
| M1 | Nodes bootstrapped by Ansible, on the tailnet | ✅ |
| M2 | kubeadm + Cilium, etcd snapshot restore tested | ✅ |
| M3 | Flux, SOPS, branch protection, Cilium adopted | ✅ |
| M4 | Gateway, LB-IPAM, cert-manager, storage, cloudflared, backup NFS | 🚧 Backup target left |
| M5 | Prometheus, Grafana, Loki, Alloy, Uptime Kuma | ⏳ |
| M6 | BottleBot, GreenTechHub, Postgres, Authentik | ⏳ |
| M7 | Jellyfin and the rest | ⏳ |
| M8 | Cutover from Compose (legacy deleted here), full DR rebuild test | ⏳ |

---

## 🗄️ Legacy Compose stack (removed at M8)

> [!WARNING]
> Everything below describes the Docker Compose era: homelab-edge, Infisical, Semaphore, deploy-service and the
> polyrepo split. None of it runs on the Kubernetes nodes, and it's all deleted at the M8 cutover. Don't extend
> it.

<details>
<summary>Legacy architecture, files and docs</summary>

**Nodes (legacy names):** `homelab-edge` (edge, DNS, Ansible control), `homelab-observe` (monitoring),
`homelab-data-01`, `homelab-svc-01`, `homelab-svc-02`. Details are in [NODES.md](./NODES.md), and status in
[TODO.md](./TODO.md).

**Deployment phases:**

```
Phase 1:  PC ────────────────► homelab-edge        (bootstrap from PC, one-time)
Phase 2:  homelab-edge ──────► itself              (edge self-deploys its services)
Phase 3:  homelab-edge ──────► other nodes         (edge deploys observe + svc nodes)
Phase 4:  GitHub push ──► n8n/Camunda ──► edge     (automated deploys via automation endpoint)
```

**Legacy files:**
- Inventories: `inventories/bootstrap.ini`, `inventories/prod.yml`, `topology.yml`, `group_vars/{edge,observe,data}.yml`.
- Playbooks: `bootstrap_edge.yml`, `bootstrap_node.yml`, `deploy_edge.yml`, `apply_firewall.yml`,
  `resolve_node_ips.yml`, `update_all.yml`, `backup.yml`, `rollback.yml`, `healthcheck.yml`.
- Roles: `docker`, `docker_compose`, `fail2ban`, `unbound`, `alloy`, `infisical`, `semaphore`.
- Other: `docker-compose.edge.yml`, `docker-compose.svc01.yml`, `deploy-service/`, `services.yml`,
  `scripts/deploy.sh`, `.github/workflows/deploy.yml`.

**Legacy docs:**
- [BOOTSTRAP.md](./BOOTSTRAP.md): Phases 1–4
- [docs/NETWORK.md](./docs/NETWORK.md)
- [docs/TROUBLESHOOTING.md](./docs/TROUBLESHOOTING.md)
- [docs/repo_split_brief.md](./docs/repo_split_brief.md): the polyrepo design
- [docs/consolidated_brief.md](./docs/consolidated_brief.md)
- [docs/topology_data_brief.md](./docs/topology_data_brief.md)

**Polyrepo split (frozen at M0):**
- `homelab-edge-services` was live.
- `homelab-observe-services`, `camunda-platform` and `n8n-automation` were extracted.
- `authentik-sso` was in progress.
- `discord-gateway` was dropped.

Their services move into homelab-cluster in M5–M7.

</details>
