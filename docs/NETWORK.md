# Network

Reference for IP assignments, firewall rules, DNS configuration, Tailscale ACLs, and traffic flow.

<!-- TOC -->
* [Network](#network)
  * [IP Assignments](#ip-assignments)
    * [LAN (Static DHCP)](#lan-static-dhcp)
    * [Tailscale (100.x.x.x)](#tailscale-100xxx)
    * [Service Ports](#service-ports)
  * [Firewall Rules](#firewall-rules)
    * [`homelab-edge`](#homelab-edge)
    * [`homelab-observe`](#homelab-observe)
    * [`homelab-svc-01`](#homelab-svc-01)
    * [`homelab-svc-02` and `homelab-svc-03`](#homelab-svc-02-and-homelab-svc-03)
    * [Updating Rules](#updating-rules)
  * [DNS](#dns)
    * [Internal — Pi-hole + Unbound](#internal--pi-hole--unbound)
    * [Adding a New Internal Hostname](#adding-a-new-internal-hostname)
    * [External — Cloudflare](#external--cloudflare)
  * [Tailscale](#tailscale)
    * [Mode](#mode)
    * [ACLs](#acls)
    * [Key Rotation](#key-rotation)
    * [MagicDNS](#magicdns)
  * [Traffic Flow](#traffic-flow)
    * [External Request (Public Hostname)](#external-request-public-hostname)
    * [Internal Request (LAN Client)](#internal-request-lan-client)
    * [Ansible Deploy (Phase 3+)](#ansible-deploy-phase-3)
    * [Automated Deploy (Phase 4)](#automated-deploy-phase-4)
<!-- TOC -->

---

## IP Assignments

### LAN (Static DHCP)

| Node              | Local IP      | Role                           |
|-------------------|---------------|--------------------------------|
| `homelab-edge`    | 192.168.1.10  | Edge, DNS, Ansible control     |
| `homelab-observe` | 192.168.1.11  | Monitoring                     |
| `homelab-svc-01`  | 192.168.1.20  | Camunda, databases             |
| `homelab-svc-02`  | 192.168.1.21  | GreenTechHub                   |
| `homelab-svc-03`  | 192.168.1.22  | Jellyfin                       |

Configure static DHCP reservations on your router by MAC address. These values are also set in `host_vars/` and must stay in sync.

### Tailscale (100.x.x.x)

| Node              | Tailscale IP  |
|-------------------|---------------|
| `homelab-edge`    | 100.x.x.1     |
| `homelab-observe` | 100.x.x.2     |
| `homelab-svc-01`  | 100.x.x.3     |
| `homelab-svc-02`  | 100.x.x.4     |
| `homelab-svc-03`  | 100.x.x.5     |

Tailscale IPs are assigned by the coordination server and stable per device. Update `group_vars/all.yml` if they change.

### Service Ports

| Service           | Node              | Port  |
|-------------------|-------------------|-------|
| Grafana           | `homelab-observe` | 3000  |
| Prometheus        | `homelab-observe` | 9090  |
| Alertmanager      | `homelab-observe` | 9093  |
| Uptime Kuma       | `homelab-observe` | 3001  |
| Portainer         | `homelab-observe` | 9000  |
| Camunda           | `homelab-svc-01`  | 8080  |
| GreenTechHub      | `homelab-svc-02`  | 8000  |
| Jellyfin          | `homelab-svc-03`  | 8096  |
| Pi-hole admin     | `homelab-edge`    | 80    |
| SSH (all nodes)   | all               | 22    |

---

## Firewall Rules

All nodes use `ufw` with a default-deny inbound policy. Rules are applied by the `base_hardening` role and node-specific group vars.

### `homelab-edge`

| Port | Protocol | Source  | Reason                        |
|------|----------|---------|-------------------------------|
| 22   | TCP      | any     | SSH admin access              |
| 53   | TCP/UDP  | LAN     | Pi-hole DNS (LAN only)        |
| 80   | TCP      | LAN     | Pi-hole admin UI (LAN only)   |

No ports are forwarded from the router. Cloudflare Tunnel connects outbound — all external traffic enters through it.

### `homelab-observe`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| 22   | TCP      | LAN / VPN | SSH (edge + admin devices)    |
| 3000 | TCP      | LAN / VPN | Grafana                       |
| 9090 | TCP      | LAN / VPN | Prometheus                    |
| 9093 | TCP      | LAN / VPN | Alertmanager                  |
| 3001 | TCP      | LAN / VPN | Uptime Kuma                   |
| 9000 | TCP      | LAN / VPN | Portainer                     |

No public exposure. Accessible via Tailscale from admin devices.

### `homelab-svc-01`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| 22   | TCP      | LAN / VPN | SSH (edge only)               |
| 8080 | TCP      | LAN / VPN | Camunda                       |
| 5432 | TCP      | LAN / VPN | PostgreSQL (internal only)    |
| 9200 | TCP      | LAN / VPN | Elasticsearch (internal only) |

### `homelab-svc-02` and `homelab-svc-03`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| 22   | TCP      | LAN / VPN | SSH (edge only)               |
| 8000 | TCP      | LAN / VPN | GreenTechHub (svc-02)         |
| 8096 | TCP      | LAN / VPN | Jellyfin (svc-03)             |

### Updating Rules

Firewall rules are managed by Ansible. Do not apply `ufw` changes manually — they will be overwritten on the next 
deploy. Instead, edit `group_vars/<node>.yml` or the `firewall` role and re-run the relevant playbook:

```bash
ansible-playbook -i inventories/prod.ini playbooks/deploy_edge.yml --tags firewall --vault-password-file .vault_pass
```

---

## DNS

### Internal — Pi-hole + Unbound

Pi-hole on `homelab-edge` (192.168.1.10) is the DNS server for all LAN clients. Set it as the primary DNS on your 
router's DHCP config.

Internal hostnames are defined in `templates/pihole/custom.list.j2` and deployed by Ansible. Do not edit 
`/etc/pihole/custom.list` directly on the node.

| Hostname                     | Resolves to   | Port |
|------------------------------|---------------|------|
| `grafana.homelab.local`      | 192.168.1.11  | 3000 |
| `prometheus.homelab.local`   | 192.168.1.11  | 9090 |
| `alertmanager.homelab.local` | 192.168.1.11  | 9093 |
| `uptime.homelab.local`       | 192.168.1.11  | 3001 |
| `portainer.homelab.local`    | 192.168.1.11  | 9000 |
| `camunda.homelab.local`      | 192.168.1.20  | 8080 |
| `greentechhub.homelab.local` | 192.168.1.21  | 8000 |
| `jellyfin.homelab.local`     | 192.168.1.22  | 8096 |

Clients access services at `http://<hostname>:<port>`. Traffic between nodes travels over Tailscale (encrypted), so a 
separate internal TLS layer is not required.

Upstream resolution is handled by **Unbound** running on `homelab-edge`, which performs recursive DNSSEC-validated 
lookups directly against root servers — no third-party upstream DNS.

### Adding a New Internal Hostname

1. Add an entry to `templates/pihole/custom.list.j2`
2. Run the edge deploy playbook:
   ```bash
   ansible-playbook -i inventories/prod.ini playbooks/deploy_edge.yml --tags pihole --vault-password-file .vault_pass
   ```

### External — Cloudflare

Public hostnames (`*.yourdomain.com`) are managed in Cloudflare DNS. TLS terminates at Cloudflare. The Cloudflare 
Tunnel config in `host_vars/homelab-edge.yml` maps each public hostname to an internal `host:port`.

Pi-hole has no involvement in external DNS resolution.

---

## Tailscale

### Mode

Tailscale is installed on **every node** individually. Each node has its own Tailscale IP and maintains a direct 
encrypted connection to the Tailscale coordination server, independently of all other nodes.

`homelab-edge` additionally runs in **subnet router** mode, advertising `192.168.1.0/24` to the Tailscale network. This 
is a convenience for reaching LAN devices that do not have Tailscale installed (e.g. a router, NAS, or IoT device) — it 
is not a dependency for accessing homelab nodes.

Because every node has its own Tailscale connection, the edge going dark has no impact on your ability to SSH into or 
manage any other node over VPN. LAN access (direct IP on port 22) remains available regardless.

### ACLs

Tailscale ACLs are defined in the Tailscale admin console (not in this repo). Recommended policy:

| Source            | Destination         | Ports            | Reason                              |
|-------------------|---------------------|------------------|-------------------------------------|
| `homelab-edge`    | all homelab nodes   | 22               | Ansible SSH                         |
| `homelab-observe` | all homelab nodes   | 9100, 8080       | Prometheus scrape (node + cAdvisor) |
| `tag:admin`       | all homelab nodes   | 22               | Admin SSH access                    |
| `tag:admin`       | `homelab-observe`   | 3000, 3001, 9000 | Grafana, Uptime Kuma, Portainer     |
| all homelab nodes | `homelab-observe`   | 3100             | Loki log ingestion                  |
| `homelab-edge`    | `homelab-svc-01/02` | 8080, 8000       | Cloudflare Tunnel routing           |
| deny              | all                 | all              | Default deny                        |

Tag admin devices in the Tailscale console as `tag:admin`. This gives you fine-grained per-node ACL control — tighter 
than a blanket subnet route allow rule.

> The edge subnet router (`192.168.1.0/24`) should **not** be granted broad access in ACLs. It exists only to reach 
> non-Tailscale LAN devices; homelab nodes are accessed directly by their own Tailscale IPs.

### Key Rotation

Tailscale auth keys are stored in `secrets/vault.yml`. On expiry, generate a new reusable key from the Tailscale admin 
console and update the vault:

```bash
ansible-vault edit secrets/vault.yml --vault-password-file .vault_pass
```

Then re-run the relevant deploy playbook to apply the new key.

### MagicDNS

Tailscale MagicDNS resolves node hostnames (e.g. `homelab-edge`) to Tailscale IPs automatically for devices on the VPN. 
This complements Pi-hole's `.homelab.local` zone — MagicDNS handles node-to-node resolution within Tailscale; Pi-hole 
handles service-level `.homelab.local` resolution for LAN clients.

---

## Traffic Flow

### External Request (Public Hostname)

```
Client → Cloudflare DNS → Cloudflare edge (TLS termination)
    → Cloudflare Tunnel (outbound from homelab-edge)
    → cloudflared on homelab-edge
    → target service on internal host:port
```

No ports open on the router. No direct internet exposure of any homelab node.

### Internal Request (LAN Client)

```
LAN client → Pi-hole DNS (192.168.1.10:53)
    → resolves service.homelab.local → node IP
    → direct connection to node:port over LAN
```

### Ansible Deploy (Phase 3+)

```
homelab-edge (homelab user)
    → SSH to target node (22)
    → executes tasks as homelab user with passwordless sudo
```

### Automated Deploy (Phase 4)

```
GitHub push → .github/workflows/deploy.yml
    → HTTP POST to n8n/Camunda endpoint (via Cloudflare Tunnel)
    → n8n/Camunda SSHes to homelab-edge as deploy user (via Tailscale)
    → scripts/deploy.sh → ansible-playbook
    → Ansible SSHes to all target nodes
```