
## Cloudflare DDNS
Uses ports `1000`

## Grafana
Uses ports `3000`

## GreenTechHub
Uses ports `8000`

## Node Exporter
Uses ports `9100`

## NTFY
Uses ports `8085`

## Obsidian
Uses ports `27123`

## Portainer
Uses ports `9443`

## PyFinBot
Uses ports `8001`

## Prometheus
Uses ports `9090`

## Rust Desk
Uses ports `21115`


Change Docker's global volume storage location
```bash
sudo nano /etc/docker/daemon.json
```
Add the following content to the file:
```json
{
  "data-root": "/mnt/m2drive/docker"
}
```
The restart Docker service to apply the changes:
```bash
sudo systemctl restart docker
```
