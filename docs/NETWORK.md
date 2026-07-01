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

| Node              | IP var        | Role                           |
|-------------------|---------------|--------------------------------|
| `homelab-edge`    | `ip_edge`     | Edge, DNS, Ansible control     |
| `homelab-observe` | `ip_observe`  | Monitoring                     |
| `homelab-svc-01`  | `ip_svc_01`   | Camunda, databases             |
| `homelab-svc-02`  | `ip_svc_02`   | GreenTechHub                   |
| `homelab-svc-03`  | `ip_svc_03`   | Jellyfin                       |

IP values and `lan_subnet` are defined in `inventories/group_vars/all/overrides.yml`. `main.yml` holds `EDIT_BEFORE_USE` placeholders; `overrides.yml` overrides them with real values. When IPs change, update `overrides.yml` only. Also configure static DHCP reservations on your router by MAC address.

### Tailscale (100.x.x.x)

| Node              | Tailscale IP  |
|-------------------|---------------|
| `homelab-edge`    | 100.x.x.1     |
| `homelab-observe` | 100.x.x.2     |
| `homelab-svc-01`  | 100.x.x.3     |
| `homelab-svc-02`  | 100.x.x.4     |
| `homelab-svc-03`  | 100.x.x.5     |

Tailscale IPs are assigned by the coordination server and stable per device. Update `group_vars/all/overrides.yml` if they change.

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
| Infisical — Caddy HTTPS (Tailscale only)  | `homelab-edge` | 8443 |
| Semaphore — Caddy HTTPS (Tailscale only)  | `homelab-edge` | 8444 |
| Infisical direct (Tailscale only, non-browser) | `homelab-edge` | 8222 |
| Semaphore direct (Tailscale only, non-browser) | `homelab-edge` | 3010 |
| SSH (all nodes)   | all               | `ssh_port` |

---

## Firewall Rules

All nodes use `ufw` with a default-deny inbound policy. Rules are applied by the `base_hardening` role and node-specific group vars.

### `homelab-edge`

| Port | Protocol | Source  | Reason                        |
|------|----------|---------|-------------------------------|
| `ssh_port` | TCP  | any     | SSH admin access              |
| 53   | TCP/UDP  | LAN     | Pi-hole DNS (LAN only)        |
| 80   | TCP      | LAN     | Pi-hole admin UI (LAN only)   |
| 8443 | TCP      | `tailscale_cgnat_range` | Caddy HTTPS — Infisical (`homelab-edge.<tailnet>.ts.net:8443`) |
| 8444 | TCP      | `tailscale_cgnat_range` | Caddy HTTPS — Semaphore (`homelab-edge.<tailnet>.ts.net:8444`) |
| 8222 | TCP      | `tailscale_cgnat_range` (`100.64.0.0/10`) | Infisical direct port (Tailscale only — non-browser clients) |
| 3010 | TCP      | `tailscale_cgnat_range` (`100.64.0.0/10`) | Semaphore direct port (Tailscale only — non-browser clients) |

No ports are forwarded from the router. Cloudflare Tunnel connects outbound — all external traffic enters through it.

> **Access paths for Infisical and Semaphore:** Caddy serves HTTPS on ports
> 8443/8444 via `homelab-edge.<tailnet>.ts.net` (Tailscale, browser-trusted
> Let's Encrypt cert via `tailscale cert`) — Tailscale CGNAT range only.
> Direct ports 8222/3010 remain for non-browser Tailscale clients. Do not
> widen either port range beyond `tailscale_cgnat_range` — see
> `group_vars/all/main.yml`.

### `homelab-observe`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| `ssh_port` | TCP  | LAN / VPN | SSH (edge + admin devices)    |
| 3000 | TCP      | LAN / VPN | Grafana                       |
| 9090 | TCP      | LAN / VPN | Prometheus                    |
| 9093 | TCP      | LAN / VPN | Alertmanager                  |
| 3001 | TCP      | LAN / VPN | Uptime Kuma                   |
| 9000 | TCP      | LAN / VPN | Portainer                     |

No public exposure. Accessible via Tailscale from admin devices.

### `homelab-svc-01`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| `ssh_port` | TCP  | LAN / VPN | SSH (edge only)               |
| 8080 | TCP      | LAN / VPN | Camunda                       |
| 5432 | TCP      | LAN / VPN | PostgreSQL (internal only)    |
| 9200 | TCP      | LAN / VPN | Elasticsearch (internal only) |

### `homelab-svc-02` and `homelab-svc-03`

| Port | Protocol | Source    | Reason                        |
|------|----------|-----------|-------------------------------|
| `ssh_port` | TCP  | LAN / VPN | SSH (edge only)               |
| 8000 | TCP      | LAN / VPN | GreenTechHub (svc-02)         |
| 8096 | TCP      | LAN / VPN | Jellyfin (svc-03)             |

### Updating Rules

Firewall rules are managed by Ansible. Do not apply `ufw` changes manually — they will be overwritten on the next 
deploy. Instead, edit `ufw_rules` in `group_vars/<node>.yml` and run:

```bash
ansible-playbook playbooks/apply_firewall.yml --limit homelab-edge
```

---

## DNS

### Internal — Pi-hole + Unbound

Pi-hole on `homelab-edge` (`ip_edge`) is the DNS server for all LAN clients. Set it as the primary DNS on your 
router's DHCP config.

Internal hostnames are configured as static entries in the `homelab-edge-services` repo (Pi-hole's `custom.list`). Do not edit `/etc/pihole/custom.list` directly — it is overwritten on every `deploy-service` deploy of `homelab-edge-services`.

| Hostname                     | Resolves to   | Port |
|------------------------------|---------------|------|
| `grafana.homelab.local`      | `ip_observe`  | 3000 |
| `prometheus.homelab.local`   | `ip_observe`  | 9090 |
| `alertmanager.homelab.local` | `ip_observe`  | 9093 |
| `uptime.homelab.local`       | `ip_observe`  | 3001 |
| `portainer.homelab.local`    | `ip_observe`  | 9000 |
| `camunda.homelab.local`      | `ip_svc_01`   | 8080 |
| `greentechhub.homelab.local` | `ip_svc_02`   | 8000 |
| `jellyfin.homelab.local`     | `ip_svc_03`   | 8096 |

Clients access services at `http://<hostname>:<port>`. Traffic between nodes travels over Tailscale (encrypted), so a 
separate internal TLS layer is not required.

Upstream resolution is handled by **Unbound** running on `homelab-edge`, which performs recursive DNSSEC-validated 
lookups directly against root servers — no third-party upstream DNS.

### Adding a New Internal Hostname

1. Add an entry to both `pihole_custom_dns` and `caddy_routes` in `group_vars/edge.yml` (DNS resolves to `ip_edge`; Caddy proxies to the backend)
2. Run the edge deploy playbook:
   ```bash
   ansible-playbook playbooks/deploy_edge.yml --tags pihole,caddy
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

`homelab-edge` additionally runs in **subnet router** mode, advertising `lan_subnet` to the Tailscale network. This 
is a convenience for reaching LAN devices that do not have Tailscale installed (e.g. a router, NAS, or IoT device) — it 
is not a dependency for accessing homelab nodes.

Because every node has its own Tailscale connection, the edge going dark has no impact on your ability to SSH into or 
manage any other node over VPN. LAN access (direct IP on `ssh_port`) remains available regardless.

> **`homelab-edge` joins the tailnet during Phase 1** (not Phase 2, as every
> other node does) — `bootstrap_edge.yml` brings Tailscale up before Infisical,
> because both Infisical and Semaphore (provisioned, seeded, and brought up
> later in that same single-pass play — see [What the Bootstrap Playbook
> Does](../BOOTSTRAP.md#what-the-bootstrap-playbook-does)) are Tailscale-only
> services that must be reachable for the operator by the time Phase 1
> finishes. (The provisioning-and-seed step itself doesn't need Tailscale at
> all — it runs over loopback, pre-firewall, in the one window where
> `127.0.0.1:8222` is reachable unauthenticated; see
> `roles/infisical/tasks/bootstrap_instance.yml`'s header comment.)
> `deploy_edge.yml` re-runs the `tailscale` role in Phase 2 too — idempotent,
> a no-op once the node is already joined.

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

> The edge subnet router (`lan_subnet`) should **not** be granted broad access in ACLs. It exists only to reach 
> non-Tailscale LAN devices; homelab nodes are accessed directly by their own Tailscale IPs.

### Key Rotation

Tailscale auth keys are stored in `inventories/group_vars/all/vault.yml`. On expiry, generate a new reusable key from the Tailscale admin 
console and update the vault:

```bash
ansible-vault edit inventories/group_vars/all/vault.yml
```

Then re-run the relevant deploy playbook to apply the new key.

### MagicDNS

Tailscale MagicDNS resolves node hostnames (e.g. `homelab-edge`) to Tailscale IPs automatically for devices on the VPN. 
This complements Pi-hole's `.homelab.local` zone — MagicDNS handles node-to-node resolution within Tailscale; Pi-hole 
handles service-level `.homelab.local` resolution for LAN clients.

### Tailscale HTTPS Certificates

`homelab-edge` provisions a browser-trusted Let's Encrypt certificate for its MagicDNS FQDN 
(`homelab-edge.<tailnet>.ts.net`) via the `tailscale cert` command. Tailscale acts as the DNS-01 ACME proxy — no public 
port exposure required. The cert is written to `/var/lib/tailscale/certs/` and mounted read-only into the Caddy 
container, which serves it on ports 8443/8444 for Infisical and Semaphore respectively.

This gives Tailscale-connected browsers a green padlock at `https://homelab-edge.<tailnet>.ts.net:8443/8444` with no 
per-device trust setup. LAN access via `*.homelab.local` uses plain HTTP — no TLS on the LAN path (ACME cannot issue
certs for `.local` domains and Caddy's local CA requires per-device trust installation).

The cert is provisioned by the `tailscale` Ansible role (`tailscale_cert_enabled: true` on the edge node) and renewed 
weekly via cron.

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
LAN client → Pi-hole DNS (<ip_edge>:53)
    → resolves service.homelab.local → node IP
    → direct connection to node:port over LAN
```

### Tailscale-Only Service Access (Infisical / Semaphore)

**Browser (Tailscale):**
```
Admin device (on tailnet) → https://homelab-edge.<tailnet>.ts.net:{8443,8444}
    → ufw allows 100.64.0.0/10 on that port → Caddy → container on homelab-edge
```

**Non-browser / API (Tailscale):**
```
Admin device (on tailnet) → http://<edge-tailscale-ip>:{8222,3010}
    → ufw allows 100.64.0.0/10 on that port → container on homelab-edge
```

No Pi-hole hostname, no LAN reachability — by design (see [Firewall Rules](#firewall-rules)).
The device making the request must itself be a tailnet member; there is no other path in.

### Ansible Deploy (Phase 3+)

```
homelab-edge (homelab user)
    → SSH to target node (<ssh_port>)
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