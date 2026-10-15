# Building the Kubernetes cluster

Runbook for `playbooks/cluster.yml`: turns nodes prepared by [`bootstrap.yml`](./K8S_BOOTSTRAP.md) into a kubeadm cluster
with Cilium. This is milestone M2 of the Kubernetes migration. Flux and everything inside the cluster then live in
[homelab-cluster](https://github.com/GreenMachine582/homelab-cluster).

Runs from **WSL on the main PC**, in `~/homelab`, like the bootstrap.

## What you get

| Setting           | Value                                                                  | Where                     |
|-------------------|------------------------------------------------------------------------|---------------------------|
| Kubernetes        | v1.36.5, packages held                                                 | `group_vars/k8s.yml`      |
| Container runtime | containerd 2.4 (`containerd.io`, Docker's apt repo), systemd cgroups   | `roles/containerd`        |
| CNI               | Cilium 1.20.1 (held: 1.20.2 needs kernel BTF, absent on Pi kernels), kube-proxy replacement, IPAM `kubernetes`, eBPF TPROXY | `group_vars/k8s.yml`, `roles/cilium_install/vars` |
| Pod / Service     | 10.244.0.0/16 / 10.96.0.0/12                                           | `group_vars/k8s.yml`      |
| API endpoint      | `k8s-api:6443` (every node's `/etc/hosts` → control plane `node_ip`)   | `roles/k8s_prereqs`       |
| Control plane     | `laptop-01`, keeps its `NoSchedule` taint                              | `inventories/k8s.yml`     |
| Workers           | `rpi-03`, labelled `homelab/role=data`, `homelab/storage=nvme`         | `roles/k8s_node_config`   |

Why these versions: 1.37 is out, but Cilium 1.20 is only tested on Kubernetes 1.33–1.36. Debian 13 ships containerd
1.7, and Kubernetes 1.36 needs 2.x. Bumping any of them is a PR that edits `group_vars/k8s.yml` (and
`roles/containerd/defaults`).

The **database taint** on rpi-03 is off (`k8s_data_taint_enabled: false`). With only one worker, it would leave
general pods nowhere to run. Turn it on once rpi-01/02 join.

## Before the first run

1. Both nodes are bootstrapped (`bootstrap.yml`). `cluster.yml` refuses nodes where the `homelab` key doesn't work yet.
2. **Controller tooling**: run once, and again after bumping `k8s_version` or `cilium_cli_version`:
   ```bash
   ansible-playbook playbooks/controller.yml -K      # -K: your WSL sudo password
   ```
   It installs `sshpass`, the Ansible collections, and kubectl and cilium-cli at the cluster's versions. It adds
   `k8s-api` to `/etc/hosts`: the fetched kubeconfig points at `https://k8s-api:6443`, and on WSL it also sets
   `generateHosts = false` in `/etc/wsl.conf` so the entry survives restarts. It also exports
   `KUBECONFIG=~/.kube/homelab.conf` in `~/.bashrc`. kubectl and cilium are on laptop-01 as well (`homelab` user).

## Run

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

Swap stays on (Debian swap partition, Pi OS zram): kubelet runs with `failSwapOn: false` and
`swapBehavior: NoSwap`, so pods never swap. kubeadm's Swap preflight warning is expected and ignored.

## Verify (M2)

```bash
ansible-playbook playbooks/cluster_status.yml -e connectivity_test=true
kubectl get nodes -o wide                  # both Ready, v1.36.5, INTERNAL-IP = LAN IPs
ansible-playbook playbooks/cluster.yml     # re-run: no changes
```

`cluster_status.yml` is read-only and safe any time. It reports:
- per node: LAN addresses (and warns if a node has more than one), routes to the other nodes, and UFW;
- from the control plane: nodes, Cilium nodes, all pods, and `cilium status`.

With `connectivity_test=true` it also runs `cilium connectivity test` and removes the test namespaces afterwards.
With the control plane tainted and one worker, the test runs in single-node mode. Add
`-e connectivity_test_only=<name>` (a substring of a test name, e.g. `echo-ingress-l7`) to run only matching tests,
which takes a minute or two instead of ~30. When tests fail it prints the Cilium agent and Envoy state, Hubble flows
for the test namespace, and the host's proxy path (TPROXY rule hits, proxy listeners and their socket options,
rp_filter, ip rules, UFW).

Cilium settings live in `roles/cilium_install/vars/main.yml`. `cluster.yml` records the applied set in the
`homelab-cilium-settings` ConfigMap and runs `cilium upgrade` when the version or any setting changes, so the agents
restart once after a settings change.

Still to come for the M2 exit: the etcd snapshot and a restore rehearsal (next PR).

## Troubleshooting

- **`cluster.yml` says a node isn't bootstrapped**: run `bootstrap.yml --limit <node>` first.
- **`kubectl` can't resolve `k8s-api`**: add the hosts entry on the PC (above).
- **`cilium-health-ep … no route to host` / pods can't reach the other node**: cross-node (VXLAN) traffic is being
  dropped. Run `cluster_status.yml`. If it warns about a second LAN address (e.g. laptop Wi-Fi), that's the likely
  source. `ufw_rules` allow Cilium's ports (8472/udp, 4240, 4244, 10250) from the whole LAN for this reason.
- **A node stays NotReady**: check `cilium status`. Check that UFW lists the other nodes and `10.244.0.0/16` as
  trusted (`sudo ufw status numbered`), and that `ufw status verbose` shows `allow (routed)`.
- **A node's IP changed** (DHCP reservations are still deferred): update `overrides.yml` and re-run `cluster.yml` for
  `/etc/hosts` and kubelet. If it was laptop-01, that re-run also upgrades Cilium with the new `k8sServiceHost`. The
  API certificate includes the old IP but also `k8s-api`, so clients keep working by name.
- **L7, FQDN or TLS-SNI connectivity tests time out (curl exit 28), everything else passes**: traffic redirected to
  Envoy or the DNS proxy isn't reaching it. On the Raspberry Pi OS kernel the iptables TPROXY rule matched and
  Envoy's sockets had `IP_TRANSPARENT`, yet nothing reached the proxy, so Cilium uses eBPF TPROXY
  (`bpf.tproxy=true`) instead. If it recurs, run `cluster_status.yml -e connectivity_test=true -e
  connectivity_test_only=echo-ingress-l7` and read the proxy path report.
- **`check-log-errors` fails on the Pi** with `CONFIG_INET_UDP_DIAG` and GENEVE BIG TCP warnings: the Raspberry Pi
  OS kernel lacks those options. Both are harmless.
