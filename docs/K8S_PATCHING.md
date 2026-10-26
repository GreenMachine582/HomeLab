# 🩹 Patching the cluster nodes

Runbook for `playbooks/patch_nodes.yml`: OS updates on laptop-01 and the Pis, one node at a time, with a drain and
reboot only where needed. Run it **monthly** (first Saturday) and **straight away** when a security advisory lands for
Debian, Raspberry Pi OS, OpenSSH, the kernel or another package on the nodes.

Everything runs from **WSL on the main PC**, in the `~/homelab` clone, like [K8S_BOOTSTRAP.md](./K8S_BOOTSTRAP.md).

**Quick links:** [🔄 What patches what](#-what-patches-what) · [▶️ Run](#️-run) · [⚙️ What it does](#️-what-it-does) ·
[⏱️ What to expect](#️-what-to-expect) · [✅ Verify](#-verify) · [🩺 Troubleshooting](#-troubleshooting)

---

## 🔄 What patches what

| What | How | Reboots |
| --- | --- | --- |
| Debian security updates | `unattended-upgrades`, daily, set by `base_hardening` | Never |
| Everything else, Raspberry Pi OS kernel and firmware included | `patch_nodes.yml`, monthly or on an advisory | When needed |
| kubelet, kubeadm, kubectl, containerd.io | Held (decision 27). Never moved by either of the above | n/a |

Kubernetes upgrades are a separate, deliberate PR (`cluster.yml` with a new `k8s_version`), not part of patching.
`update_all.yml` is the legacy Docker stack's playbook: don't use it on these nodes.

No cron runs this. A reboot of the only control plane or of the data node should have someone watching, so it's a
monthly manual run with a reminder.

## ▶️ Run

```bash
cd ~/homelab && git pull

# 1. What's pending on each node. Changes nothing.
ansible-playbook -i inventories/k8s.yml playbooks/patch_nodes.yml -e patch_report_only=true

# 2. Patch everything.
ansible-playbook -i inventories/k8s.yml playbooks/patch_nodes.yml

# 3. Full health report.
ansible-playbook -i inventories/k8s.yml playbooks/cluster_status.yml
```

| Extra var | Effect |
| --- | --- |
| `patch_report_only=true` | List upgradable and held packages, kernel and uptime per node, then stop |
| `patch_nodes=rpi-01,rpi-02` | Patch only these nodes. Use this, not `--limit`: kubectl runs on laptop-01, so it must stay in the run |
| `patch_force_reboot=true` | Reboot every patched node even if nothing asks for it (e.g. a fix that only applies after a restart of a long-running service) |
| `patch_allow_unhealthy=true` | Skip the pre-flight health gate |
| `patch_drain_timeout=600s` | Longer drain timeout (default `300s`) |

From home, the nodes are reached over Tailscale (the probe picks the endpoint), so nothing needs the site LAN.

## ⚙️ What it does

1. **Probe**: finds each node's SSH endpoint, as `cluster_status.yml` does.
2. **Pending upgrades**: `apt update`, then a per-node report. `patch_report_only` stops here.
3. **Pre-flight**: every node Ready and every pod Running or Completed. Otherwise it stops before touching anything.
4. **Patch, one node at a time**: rpi-01 and rpi-02, then rpi-03 (data node), then laptop-01 (control plane). Each
   node gets `apt dist-upgrade` with autoremove. It reboots when any of these apply:
   - a new kernel was installed (`/lib/modules` changed),
   - a package that only applies at boot changed (kernel, firmware, bootloader, libc, systemd, udev, OpenSSL, D-Bus),
   - `/var/run/reboot-required` exists (Debian 13 and Raspberry Pi OS don't usually write it),
   - `patch_force_reboot=true`.

   A reboot is: `kubectl drain`, reboot (the `systemd-run` way `argon_case` uses, checked by boot ID), wait for the
   node to be Ready, `kubectl uncordon`, wait for its Cilium agent. If any step fails the node is uncordoned and the
   run stops. The nodes after it aren't touched.
5. **Summary**: per node kernel, uptime, packages changed, rebooted or not; then nodes and any unhealthy pods.

The boot and shutdown Discord alerts from `base_hardening` fire for each reboot. That's expected.

## ⏱️ What to expect

| Node | While it reboots |
| --- | --- |
| rpi-01, rpi-02 | Pods move to the other nodes. Little visible. |
| rpi-03 | Postgres, Authentik, Grafana and cloudflared are down (local PVs pin them there, decision 37). A few minutes. |
| laptop-01 | The API is down: no kubectl, no Flux reconciles, no new pods. Running pods keep serving. A few minutes. |

A full run with every node rebooting takes about 20–30 minutes.

## ✅ Verify

- The summary shows `0 still upgradable` (held packages aside) and a new boot time on rebooted nodes.
- `cluster_status.yml`: all nodes Ready, Cilium healthy, the Gateway check passes.
- `flux get kustomizations -A` all Ready; the playground, Postgres and Authentik pods Running.

## 🩺 Troubleshooting

- **Pre-flight fails**: fix what it names first (`cluster_status.yml`). In a security rush where the unhealthy pod is
  unrelated, re-run with `-e patch_allow_unhealthy=true`.
- **Drain times out**: usually a PodDisruptionBudget or a pod with no controller. `kubectl get pods -A -o wide
  --field-selector spec.nodeName=<node>` shows what's left. The node was uncordoned again. Fix it, then re-run with
  `-e patch_nodes=<node>`.
- **Node doesn't come back** (900 s): check it over Tailscale or break-glass (`K8S_SITE.md`). A Pi that fails to boot a
  new kernel needs hands at the site. The node stays drained, so its pods have moved (except rpi-03's).
- **Something broke after an upgrade**: `grep " upgrade " /var/log/dpkg.log` on the node lists what changed;
  `apt install <pkg>=<old version>` rolls one package back if the old version is still in the archive or
  `/var/cache/apt/archives`.
