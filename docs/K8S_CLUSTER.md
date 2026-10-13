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
| CNI               | Cilium 1.20.2, kube-proxy replacement, IPAM `kubernetes`               | `group_vars/k8s.yml`      |
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
2. **Resolve `k8s-api` on the PC**: the fetched kubeconfig points at `https://k8s-api:6443`.
   ```bash
   echo "<laptop-01 IP> k8s-api" | sudo tee -a /etc/hosts      # WSL
   ```
   On Windows too, if you use kubectl there: add the same line to `C:\Windows\System32\drivers\etc\hosts`.
3. Optional in WSL: `kubectl` (same minor, 1.36) and the `cilium` CLI. The playbook installs both on laptop-01 anyway.

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
export KUBECONFIG=~/.kube/homelab.conf
kubectl get nodes -o wide                  # both Ready, v1.36.5, INTERNAL-IP = LAN IPs
kubectl -n kube-system get pods            # cilium, coredns, control plane Running; no kube-proxy
ssh -p <ssh_port> -i .ssh/homelab homelab@<laptop-01 IP> 'cilium status && cilium connectivity test'
ansible-playbook playbooks/cluster.yml     # re-run: no changes
```

Still to come for the M2 exit: the etcd snapshot and a restore rehearsal (next PR).

## Troubleshooting

- **`cluster.yml` says a node isn't bootstrapped**: run `bootstrap.yml --limit <node>` first.
- **`kubectl` can't resolve `k8s-api`**: add the hosts entry on the PC (above).
- **A node stays NotReady**: check `cilium status`. Check that UFW lists the other nodes and `10.244.0.0/16` as
  trusted (`sudo ufw status numbered`), and that `ufw status verbose` shows `allow (routed)`.
- **A node's IP changed** (DHCP reservations are still deferred): update `overrides.yml` and re-run `cluster.yml` for
  `/etc/hosts` and kubelet. If it was laptop-01, also re-run `cilium upgrade --set k8sServiceHost=<new IP>`. The API
  certificate includes the old IP but also `k8s-api`, so clients keep working by name.
