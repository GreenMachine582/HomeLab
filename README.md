
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

Disable and stop Apache2 service as Caddy is used instead
```bash
sudo systemctl disable apache2
sudo systemctl stop apache2
```

```bash
cd HomeLab
```

```bash
bash setup.sh
```


## Monthly Update Script

Make it executable:
```bash
chmod +x monthly-update.sh
```
Edit the crontab:
```bash
sudo crontab -e
```
Then add to `cron`:
```bash
0 2 1 * * /root/HomeLab/monthly-update.sh
0 2 1 * * ~/homelab/monthly-update.sh
```
Runs at 2 AM on the 1st of every month.


## On Boot Script

Make it executable:
```bash
chmod +x on-boot.sh
```

Save this as `/etc/systemd/system/on-boot.service`:
```bash
[Unit]
Description=Run a script on boot
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/root/homelab/on-boot.sh

[Install]
WantedBy=multi-user.target
```

Enable and test the service:
```bash
sudo systemctl daemon-reexec
sudo systemctl daemon-reload
sudo systemctl enable on-boot.service
sudo systemctl start on-boot.service
```
To test boot behavior without rebooting:
```bash
sudo systemctl restart on-boot.service
```