
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


## Reboot Monthly (e.g., every 1st Sunday at 3 AM)
Edit the crontab:
```bash
sudo crontab -e
```
```bash
0 3 * * 0 [ $(date +\%d) -le 07 ] && /sbin/reboot
```
Explanation:
- Runs at 3 AM on Sundays.
- `date +%d -le 07` ensures it only runs in the first 7 days = "first Sunday".

## Apply Monthly System Patching
You can create a script like `/usr/local/bin/monthly-update.sh`:

```bash
#!/bin/bash
apt update
apt upgrade -y
apt autoremove -y
```

Make it executable:
```bash
chmod +x /usr/local/bin/monthly-update.sh
```
Then add to `cron`:
```bash
0 2 1 * * /usr/local/bin/monthly-update.sh >> /var/log/monthly-update.log 2>&1
```
Runs at 2 AM on the 1st of every month.
