# ☸️ Building the Kubernetes cluster

Runbook for `playbooks/cluster.yml`: turns nodes prepared by [`bootstrap.yml`](./K8S_BOOTSTRAP.md) into a kubeadm cluster
with Cilium. This is milestone M2 of the Kubernetes migration. Flux and everything inside the cluster then live in
[homelab-cluster](https://github.com/GreenMachine582/homelab-cluster).

Runs from **WSL on the main PC**, in `~/homelab`, like the bootstrap.

**Quick links:** [📦 What you get](#-what-you-get) · [📋 Before the first run](#-before-the-first-run) · [▶️ Run](#️-run) ·
[✅ Verify](#-verify) · [🐝 Cilium and Flux](#-cilium-and-flux) · [🔌 Envoy and the Pi 4s](#-envoy-and-the-pi-4s) ·
[🔄 Flux](#-flux-m3) · [💾 etcd backups](#-etcd-backups) · [🗄️ Backup drive](#️-backup-drive-m4) ·
[🩺 Troubleshooting](#-troubleshooting)

---

## 📦 What you get

| Setting           | Value                                                                  | Where                     |
|-------------------|------------------------------------------------------------------------|---------------------------|
| Kubernetes        | v1.36.5, packages held                                                 | `group_vars/k8s.yml`      |
| Container runtime | containerd 2.4 (`containerd.io`, Docker's apt repo), systemd cgroups   | `roles/containerd`        |
| CNI               | Cilium 1.20.1 (held: 1.20.2 needs kernel BTF, absent on Pi kernels), kube-proxy replacement, IPAM `kubernetes` | `group_vars/k8s.yml`, `roles/cilium_install/vars` |
| Pod / Service     | 10.244.0.0/16 / 10.96.0.0/12                                           | `group_vars/k8s.yml`      |
| API endpoint      | `k8s-api:6443` (every node's `/etc/hosts` → control plane `node_ip`)   | `roles/k8s_prereqs`       |
| Control plane     | `laptop-01`, keeps its `NoSchedule` taint                              | `inventories/k8s.yml`     |
| Workers           | `rpi-03`, labelled `homelab/role=data`, `homelab/storage=nvme`; `rpi-01`, `rpi-02` (Pi 4, no Envoy: `homelab/l7-proxy=unsupported`) | `roles/k8s_node_config`   |
| Local volumes     | `/mnt/nvme/k8s/<name>` on rpi-03 for the `local-nvme` PVs: `postgres`, `postgres-dumps`, `prometheus`, `grafana`, owned by the uid each image runs as | `roles/k8s_local_volumes` |

Why these versions: 1.37 is out, but Cilium 1.20 is only tested on Kubernetes 1.33–1.36. Debian 13 ships containerd
1.7, and Kubernetes 1.36 needs 2.x. Bumping any of them is a PR that edits `group_vars/k8s.yml`.

> [!NOTE]
> rpi-03 has **no database taint**, by design (`k8s_data_taint_enabled: false`). The `local-nvme` PVs' node
> affinity already pins stateful pods there. A taint would push general pods off the strongest worker, which is
> also one of the two Envoy nodes, onto rpi-01 (2 GB) and rpi-02. Postgres is protected by Guaranteed QoS and a
> PriorityClass instead. Revisit when pc-01 or another big worker joins.

---

## 📋 Before the first run

1. Every node is bootstrapped (`bootstrap.yml`). `cluster.yml` refuses nodes where the `homelab` key doesn't work yet.
2. **Controller tooling**: run once, and again after bumping `k8s_version` or `cilium_cli_version`:
   ```bash
   ansible-playbook playbooks/controller.yml -K      # -K: your WSL sudo password
   ```
   It installs `sshpass`, the Ansible collections, kubectl and cilium-cli at the cluster's versions, and flux, sops,
   age and cloudflared. It adds
   `k8s-api` to `/etc/hosts`: the fetched kubeconfig points at `https://k8s-api:6443`, and on WSL it also sets
   `generateHosts = false` in `/etc/wsl.conf` so the entry survives restarts. It also exports
   `KUBECONFIG=~/.kube/homelab.conf` in `~/.bashrc`. kubectl and cilium are on laptop-01 as well (`homelab` user).
   Last, it writes `~/.ssh/config.d/homelab` (included from `~/.ssh/config`), so `ssh rpi-03` logs in as `admin` with
   the `homelab-edge` key on `ssh_port`, by MagicDNS name. Only that file is managed; the rest of `~/.ssh/config` is
   yours. Re-run just this part with `--tags ssh_config`.

---

## ▶️ Run

```bash
ansible-playbook playbooks/cluster.yml --syntax-check
ansible-playbook playbooks/cluster.yml
```

The plays, in order:
1. **Probe**: finds each node's SSH endpoint (`tasks/probe_ssh.yml`, as in the bootstrap).
2. **All nodes**:
   - kernel modules and sysctls, `k8s-api` in `/etc/hosts`;
   - on the Pi, `cgroup_enable=memory` plus a reboot if the memory cgroup is off;
   - containerd; kubelet/kubeadm/kubectl pinned and held, kubelet pinned to `node_ip`;
   - UFW: trusts the other nodes and the pod network, allows 6443 from the LAN and the tailnet, routed policy `allow`.
3. **laptop-01**: `kubeadm init` without kube-proxy, then the admin kubeconfig copied to
   `/home/homelab/.kube/config` and fetched to WSL as `~/.kube/homelab.conf`. Then Cilium, waiting until it's healthy.
4. **Workers**: `kubeadm join` via `k8s-api` with a 30-minute token.
5. **Labels and taints**, once every node is Ready.
6. **Local volumes** on `k8s_data` nodes: the PV directories under `/mnt/nvme/k8s`. The play refuses to run if the NVMe
   isn't mounted. To add a directory, add an entry to `k8s_local_volumes`, then run
   `ansible-playbook playbooks/cluster.yml --tags volumes --limit rpi-03`. Removing an entry never deletes data.

Swap stays on (Debian swap partition, Pi OS zram): kubelet runs with `failSwapOn: false` and
`swapBehavior: NoSwap`, so pods never swap. kubeadm's Swap preflight warning is expected and ignored.

---

## ✅ Verify

```bash
ansible-playbook playbooks/cluster_status.yml -e connectivity_test=true
kubectl get nodes -o wide                  # all four Ready, v1.36.5, INTERNAL-IP = LAN IPs
ansible-playbook playbooks/cluster.yml     # re-run: no changes
```

`cluster_status.yml` is read-only and safe any time.

<details>
<summary>What it reports</summary>

It reports:
- per node: LAN addresses (and warns if a node has more than one), routes to the other nodes, UFW, the kernel
  features Cilium uses, and `src_valid_mark` (warns if it's 1);
- per node, under `kubelet`:
  - boot time
  - kubelet and containerd state
  - swap, NTP sync, free disk
  - the kubelet client cert expiry
  - whether the API answers, how its name resolves, and its `/etc/hosts` line
  - cloud-init's `manage_etc_hosts`
  - the last kubelet errors;
- from the control plane: nodes, Cilium nodes, all pods, `cilium status`, and the deployed Cilium Helm values
  (what homelab-cluster's HelmRelease must match), plus the Gateway API state;
- from the controller (WSL): that `whoami.home.green-tech-hub.com` resolves to the Gateway (`192.168.50.240`)
  through the Cloudflare `*.home` record, that HTTPS returns 200 with a verified certificate, and that HTTP returns
  the 301 redirect. It warns if any of these fail. The record is set by hand; see homelab-cluster
  `docs/M4_PLATFORM.md` "Cloudflare setup". It probes the API on laptop-01's LAN IP first. If that's unreachable,
  laptop-01's subnet route isn't approved (the usual state from home), and the warning says so instead of
  blaming the Gateway.

With `connectivity_test=true` it also runs `cilium connectivity test` and removes the test namespaces afterwards.
Its pods only go to nodes labelled `homelab/l7-proxy=supported` (see "Envoy and the Pi 4s" below), and with the
control plane tainted that leaves rpi-03, so it runs with `--single-node`. `-e connectivity_test_all_nodes=true`
spreads it over every node to exercise cross-node traffic; L7/FQDN/TLS tests then fail on the Pi 4s. Add
`-e connectivity_test_only=<name>` (a substring of a test name, e.g. `echo-ingress-l7`) to run only matching tests,
which takes a minute or two instead of ~30. When tests fail it prints the Cilium agent and Envoy state, Hubble flows
for the test namespace, and the host's proxy path (TPROXY rule hits, proxy listeners and their socket options,
rp_filter, ip rules, UFW).

</details>

---

## 🐝 Cilium and Flux

> [!IMPORTANT]
> **Since M3, Flux owns the Cilium release.** Upgrades and setting changes go through a homelab-cluster PR
> (`infrastructure/controllers/cilium/helmrelease.yaml`).

- `cluster.yml` still installs Cilium on a fresh cluster, because Flux can't start without a CNI.
- When the HelmRelease exists, `cluster.yml` skips the upgrade and says so. It also flags `cilium_version` if it
  doesn't match what's running.
- `-e cilium_ansible_upgrade=true` overrides that. It's an escape hatch, for use only with the HelmRelease
  suspended (`flux suspend helmrelease cilium -n kube-system`).
- Never delete the HelmRelease to hand Cilium back: helm-controller uninstalls a release when its HelmRelease is
  deleted.
- `_cilium_settings` holds only the core networking values. Gateway API and L2 announcements (M4) are set only in
  the HelmRelease, because they need CRDs that Flux installs. So:
  - a rebuild comes up with a plain CNI, and Flux adds them;
  - the escape hatch (`--reset-values`) drops them until the HelmRelease is resumed.

<details>
<summary>How <code>cluster.yml</code> applies Cilium settings (fresh installs and the override)</summary>

Before Flux (and with the override), Cilium settings come from `roles/cilium_install/vars/main.yml`. `cluster.yml`
records the applied set in the `homelab-cilium-settings` ConfigMap and runs `cilium upgrade` when the version or any
setting changes. The chart's
`rollOutCiliumPods`/`rollOutPods` options are on, so the agent, operator and Envoy pods restart to pick up the
change. If the agent logs `Mismatch found … config-drift-checker`, the running agent doesn't match `cilium-config`;
`kubectl -n kube-system rollout restart ds/cilium` fixes it.

</details>

### 🔌 Envoy and the Pi 4s

Cilium's Envoy (L7, FQDN and TLS policy, and the Gateway) can't run on rpi-01/02. Envoy's tcmalloc needs a 48-bit
virtual address space, and the Raspberry Pi kernel for the Pi 4 (`bcm2711_defconfig`) is built 39-bit, so it aborts
at start (`TCMalloc assumes a 48-bit virtual address space`). The Pi 5 kernel is 47-bit, and laptop-01 is 48-bit.

- `host_vars` sets `cilium_l7_proxy: false` on the Pi 4s; `k8s_node_config` labels every node
  `homelab/l7-proxy=supported|unsupported`.
- The `cilium-envoy` DaemonSet only runs on `supported` nodes (`envoy.nodeSelector` in
  `roles/cilium_install/vars/main.yml` and homelab-cluster's HelmRelease).
- **Anything that needs L7/FQDN/TLS policy, or serves through the Gateway, must have
  `nodeSelector: {homelab/l7-proxy: supported}`.** On a Pi 4 such a pod's policy can't be enforced by a proxy:
  endpoint updates stall and FQDN rules can let traffic through.
- **The Pi 4 agents run with the L7 proxy off** (homelab-cluster's `no-l7-proxy` CiliumNodeConfig, which selects
  `homelab/l7-proxy=unsupported`). With it on, each endpoint update waits for an Envoy that isn't there, and new pods
  on those nodes stay in `ContainerCreating`. An agent reads the config only when it starts, so restart a Pi 4's
  cilium pod after changing it. `cluster_status.yml` reports each agent's proxy state, endpoints not ready, and pods
  stuck Pending, and warns about each.
- With the proxy on, the Pi 4 agents logged `Envoy: Version check failed`. The connectivity test still ignores
  those lines.
- `cluster_status.yml` prints each node's `virtual address bits` among its kernel features.

---

## 🔄 Flux (M3)

Everything inside the cluster comes from [homelab-cluster](https://github.com/GreenMachine582/homelab-cluster) `main`,
path `clusters/prod`. Flux is installed from manifests committed there (`clusters/prod/flux-system`), not with
`flux bootstrap github`. The repo is public, so Flux needs no deploy key or token. `main` only takes signed commits
through PRs, so Flux's own manifests arrive by PR like everything else.

```bash
ansible-playbook playbooks/controller.yml -K --tags client   # flux, sops, age, cloudflared on the controller
ansible-playbook playbooks/flux_bootstrap.yml                 # install / repair Flux
flux get kustomizations
```

`flux_bootstrap.yml`:
1. Checks that `~/.config/sops/age/keys.txt` holds the key `.sops.yaml` encrypts to (`sops_age_recipient`).
2. Creates the `sops-age` secret in `flux-system`.
3. Applies `gotk-components.yaml` and then `gotk-sync.yaml` from `main`.
4. Waits until the `flux-system` and `apps` Kustomizations are Ready.

Re-running it is also the recovery step when Flux is broken or was deleted.

**Status:** M3 done (20 Oct 2026).
- Flux v2.9.6 runs everything from homelab-cluster `main`, Cilium included.
- SOPS was proven by a smoke test: homelab-cluster PR #1 applied a namespace, ConfigMap and SOPS Secret, which
  decrypted, and PR #2 removed them, which pruned.
- Flux posts every pulled commit and applied change to Discord `#homelab-deploys` (homelab-cluster #20).
- Every playbook run from the controller posts one `🤖 [Ansible]` summary (hosts, totals, duration), and the nodes
  don't post login alerts for it ([REMOTE_ACCESS.md](./REMOTE_ACCESS.md)).

**Upgrading Flux:** bump `flux_version` in `group_vars/k8s.yml` (HomeLab PR). In a homelab-cluster PR, replace
`gotk-components.yaml` with that release's `install.yaml`. Flux applies its own upgrade once that PR is merged. Then
re-run `controller.yml --tags flux` for the CLI.

**cloudflared CLI:** used only for the locally managed tunnel (homelab-cluster `docs/M4_PLATFORM.md`, "Cloudflare
setup"). Its version and the per-architecture SHA-256 from the release notes are pinned in `group_vars/k8s.yml`.
Keep the version the same as the cloudflared image in homelab-cluster. Install or upgrade with
`controller.yml -K --tags cloudflared`.

---

## 💾 etcd backups

`cluster.yml` (tag `etcd_backup`, role `roles/etcd_backup`) sets up daily snapshots on laptop-01:

- `etcdctl`/`etcdutl` come from the etcd release that matches kubeadm's etcd image (read from
  `/etc/kubernetes/manifests/etcd.yaml`), so they upgrade with the cluster.
- `homelab-etcd-snapshot.timer` runs `/usr/local/sbin/etcd-snapshot.sh` daily at 03:30 (plus up to 15 minutes, and it
  catches up after downtime). The script saves `etcd-<stamp>.db`, checks it with `etcdutl snapshot status`, and
  archives `/etc/kubernetes/pki` as `pki-<stamp>.tar.gz` next to it. It keeps 7 of each in `/var/backups/etcd`
  (root-only: these files hold every Secret and the CA keys). It posts to Discord only when it fails.
- The first run of the role takes a snapshot right away.

```bash
ansible-playbook playbooks/cluster.yml --tags etcd_backup   # install or update
ansible-playbook playbooks/etcd_fetch.yml                    # newest snapshot + PKI → ~/homelab-backups/etcd (keeps 7)
ansible-playbook playbooks/etcd_restore_test.yml             # restore rehearsal
```

**Restore rehearsal** (`etcd_restore_test.yml`, the M2 exit): it takes a fresh snapshot through the service, restores
it into `/var/tmp/etcd-restore-test`, and starts a throwaway etcd on `127.0.0.1:12379`. It then checks that
`kube-system` and the same nodes as the live cluster are in the restored data, and cleans up. The live etcd isn't
touched. Run it after Kubernetes or etcd upgrades too.

Each snapshot and PKI archive is also copied to the [backup drive](#️-backup-drive-m4) on rpi-02, which keeps 30.
That copy is at the site too, so it isn't off-site: still run `etcd_fetch.yml` from home (weekly, and before risky
changes).

Postgres works the same way. homelab-cluster's `pg-dump` CronJob writes a daily dump to
`/mnt/nvme/k8s/postgres-dumps` on rpi-03, next to the database, and keeps 7.
`ansible-playbook playbooks/pg_dump_fetch.yml` copies the newest to `~/homelab-backups/postgres` (mode 0600, keeps 7).
Run it with `etcd_fetch.yml`.

```bash
ansible-playbook playbooks/pg_dump_fetch.yml      # newest dump → ~/homelab-backups/postgres
ansible-playbook playbooks/pg_restore_test.yml    # restore rehearsal (M5 exit)
ansible-playbook playbooks/alert_test.yml         # alerting rehearsal (M5 exit), about 20 minutes
```

**Restore rehearsal** (`pg_restore_test.yml`): it loads the newest fetched dump, the off-node copy, into a throwaway
pod in a `restore-test` namespace, using the live StatefulSet's image. It checks that the restored database list
matches the live one and that Authentik has users, then deletes the namespace. The live database isn't touched. Run
it after Postgres upgrades too.

**Alerting rehearsal** (`alert_test.yml`): it starts a crash-looping pod in an `alert-test` namespace and a `pg_dump`
Job from the real CronJob pointed at a host that doesn't exist. It waits up to 25 minutes for `KubePodCrashLooping`
and `KubeJobFailed` to fire in Alertmanager (both rules wait 15), then asks you to confirm they posted to
`#homelab-alerts` before cleaning up. The *resolved* posts follow about 5 minutes later. Run it after
kube-prometheus-stack or Alertmanager changes. `-e alert_test_keep=true` skips the cleanup.

> [!NOTE]
> A failed `pg_dump` Job keeps `KubeJobFailed` firing, reposted every 12 h, until the Job is deleted:
> `kubectl -n postgres delete job <name>`.

The real restore steps are in homelab-cluster `docs/M5_WORKLOADS.md` › Postgres runbook.

### 🚨 Real restore (disaster only)

<details>
<summary>Steps</summary>

Single control plane, so a restore puts the whole cluster back to the snapshot's moment; anything created since is
lost. On laptop-01, as root:

1. If the PKI is gone too (rebuilt laptop): `tar -xzf pki-<stamp>.tar.gz -C /etc/kubernetes`, from the same stamp.
2. Stop the control plane: `mkdir /root/manifests && mv /etc/kubernetes/manifests/*.yaml /root/manifests/`, then wait
   until `crictl ps` shows no `etcd` or `kube-apiserver`.
3. `mv /var/lib/etcd /var/lib/etcd.broken`, then:
   ```bash
   etcdutl snapshot restore /var/backups/etcd/etcd-<stamp>.db --data-dir /var/lib/etcd \
     --name laptop-01 --initial-cluster laptop-01=https://<node_ip>:2380 \
     --initial-advertise-peer-urls https://<node_ip>:2380
   ```
   (Name and URLs as in `/root/manifests/etcd.yaml`.)
4. `mv /root/manifests/*.yaml /etc/kubernetes/manifests/`, then wait for `kubectl get nodes` from the PC.
5. `kubectl -n kube-system rollout restart ds/cilium deploy/coredns`, then `cluster_status.yml -e connectivity_test=true`.

This covers a broken etcd on a working laptop-01. A rebuilt laptop-01 also needs the kubelet config, kubeconfigs and
static pod manifests regenerated from the restored PKI (`kubeadm init phase …`). That path isn't tested yet; it's
part of the M8 DR test.

</details>

---

## 🗄️ Backup drive (M4)

`playbooks/backup_drive.yml` (role `roles/backup_drive`) turns the USB drive on the `k8s_backup` node (rpi-02, a
TOSHIBA 1 TB HDD) into the backup target from decision 18:

| What | How |
|------|-----|
| Drive | ext4 labelled `homelab-backup`, mounted by UUID at `/mnt/backup` with `nofail`: rpi-02 boots and stays a worker without it |
| NFS | NFSv4 only (2049/tcp). One directory per writer, each exported to that node's IP only, `all_squash` to the `homelab-backup` user |
| Name | `homelab-backup` in every node's `/etc/hosts` (like `k8s-api`), so moving the drive is an Ansible re-run |
| etcd | laptop-01 automounts `homelab-backup:/mnt/backup/etcd` at `/mnt/backup`. The snapshot script copies each snapshot and PKI archive there, checks the copy and keeps 30 |
| Postgres | homelab-cluster's `pg-dump-offnode` CronJob copies the newest dump to `/mnt/backup/postgres` through an NFS PV, and keeps 30 |

> [!IMPORTANT]
> The drive holds every Secret, the cluster CA keys and every password hash. That's why the exports name single IPs.
> The other nodes are firewall-trusted, so it's the exports that keep rpi-01 out, and UFW keeps out everything that
> isn't a node.

**First run:**

```bash
ansible-playbook playbooks/backup_drive.yml --tags identify        # which Pi, and the drive's /dev/disk/by-id link
# Put the link in overrides.yml as disk_rpi_02_backup, then format it (erases the drive):
ansible-playbook playbooks/backup_drive.yml -e backup_drive_format=true
```

The role formats only a drive that is empty or NTFS, isn't mounted, and only when `-e backup_drive_format=true` is
given. When the drive already carries the `homelab-backup` label it is never formatted again, so a plain
`ansible-playbook playbooks/backup_drive.yml` is safe to re-run. `cluster.yml --tags etcd_backup` keeps the etcd side
up to date too.

**Verify** (this is the M4 exit: an etcd snapshot lands on the backup target):

```bash
ansible-playbook playbooks/backup_drive.yml --tags verify
```

It checks that rpi-02 has the drive mounted (ext4, `homelab-backup`), `nfs-server` active and exactly one export per
writer, with `all_squash`. It then runs `homelab-etcd-snapshot` on laptop-01, checks the log says `Copied to`, and
checks that a new `etcd-<stamp>.db` and `pki-<stamp>.tar.gz` are on the drive. Apart from that one snapshot it
changes nothing.

> [!TIP]
> `ssh rpi-02` logs in as admin, whose sudo asks for a password, so by hand use `ssh -t rpi-02 'sudo exportfs -v'`.
> Without `-t`, sudo has no terminal to ask on.

<details>
<summary>When the drive or rpi-02 is down</summary>

- **etcd:** the local snapshot is still taken and kept. The copy fails, and a `⚠️ [etcd] … copy to the backup drive
  failed` message goes to Discord. The mount is `soft`, so laptop-01 doesn't hang. Copies resume on the next run once
  the drive is back. Missed days aren't backfilled, but the 7 local snapshots are there to copy by hand.
- **Postgres:** the `pg-dump` CronJob doesn't depend on the drive. Only `pg-dump-offnode` fails, and `KubeJobFailed`
  alerts on it.
- **rpi-02 booted without the drive:** `nfs-server` has `RequiresMountsFor=/mnt/backup`, so it stays down and never
  exports the empty directories on the SD card. Plug the drive in, then `sudo mount /mnt/backup && sudo systemctl start nfs-server`.
- **Restoring from the drive:** copy a file off with `ssh -t rpi-02 'sudo install -o admin -m 0600 /mnt/backup/etcd/etcd-<stamp>.db /tmp/'`
  and `scp rpi-02:/tmp/etcd-<stamp>.db .` (then delete `/tmp`'s copy),
  then follow [Real restore](#-real-restore-disaster-only) (etcd) or the Postgres runbook.

</details>

---

## 🩺 Troubleshooting

<details>
<summary>Symptoms and fixes</summary>

- **`cluster.yml` says a node isn't bootstrapped**: run `bootstrap.yml --limit <node>` first.
- **`kubectl` can't resolve `k8s-api`**: re-run `controller.yml -K --tags client` (it writes the hosts entry in WSL).
- **`cilium-health-ep … no route to host` / pods can't reach the other node**: cross-node (VXLAN) traffic is being
  dropped. Run `cluster_status.yml`. If it warns about a second LAN address (e.g. laptop Wi-Fi), that's the likely
  source. `ufw_rules` allow Cilium's ports (8472/udp, 4240, 4244, 10250) from the whole LAN for this reason.
- **The Pis go NotReady after a reboot or power cut** (kubelet logs "node not registered", `kubectl logs` fails with
  `Authorization error (user=kube-apiserver-kubelet-client … nodes/proxy)`): in `cluster_status.yml`, look at
  `resolve k8s-api` and the `/etc/hosts` line under `kubelet`. Raspberry Pi OS runs cloud-init with
  `manage_etc_hosts: true`, which rebuilds `/etc/hosts` on every boot. `k8s_prereqs` writes the `k8s-api` line into
  `/etc/cloud/templates/hosts.debian.tmpl` as well, so it survives. If it's missing, run
  `cluster.yml --tags prereqs --limit 'rpi-*'`. This happened after the 18 Oct 2026 site power cut. Flux's
  controllers were on a Pi, so Flux stopped too.
- **A node stays NotReady**: check `cilium status`. Check that UFW lists the other nodes and `10.244.0.0/16` as
  trusted (`sudo ufw status numbered`), and that `ufw status verbose` shows `allow (routed)`.
- **A node's IP changed** (DHCP reservations are still deferred): update `overrides.yml` and re-run `cluster.yml` for
  `/etc/hosts` and kubelet. If it was laptop-01, that re-run also upgrades Cilium with the new `k8sServiceHost`. The
  API certificate includes the old IP but also `k8s-api`, so clients keep working by name.
- **L7, FQDN or TLS-SNI connectivity tests time out (curl exit 28), everything else passes**: traffic redirected to
  Envoy or the DNS proxy isn't reaching it. The cause here was `net.ipv4.conf.all.src_valid_mark=1`, which
  `tailscaled` sets on every start (its connmark workaround for strict `rp_filter`, which we don't use). The source
  check then follows the proxy mark to table 2004's `local default`, and the
  kernel drops the packet as `IP_LOCAL_SOURCE`, both redirected pod traffic arriving on `lxc*` and the replies to
  Envoy's upstream connections arriving on `eth0`. `k8s_prereqs` sets `src_valid_mark=0` (and, as a fallback,
  `accept_local=1` on the pod `lxc*` interfaces) in `/etc/sysctl.d/99-zzz-homelab-cilium-proxy.conf`. Because
  tailscaled overrides that file, `homelab-src-valid-mark.service` sets it back right after tailscaled starts and
  its timer re-checks every minute (`journalctl -u homelab-src-valid-mark` logs each reset). `cluster_status.yml`
  warns if a node shows `src_valid_mark: 1` or the timer isn't active. If it recurs, run
  `cluster_status.yml -e connectivity_test=true -e connectivity_test_only=echo-ingress-l7`. The proxy path report
  shows `src_valid_mark`/`accept_local` and the kernel's drop reasons during the test.
- **`check-log-errors` fails on the Pi** with `CONFIG_INET_UDP_DIAG` and GENEVE BIG TCP warnings: the Raspberry Pi
  OS kernel lacks those options. Both are harmless. `cluster_status.yml` counts a run as passed when those two lines
  are its only failure; any other failed test or log line still fails it.

</details>
