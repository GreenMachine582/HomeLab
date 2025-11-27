# Homelab
![GitHub release](https://img.shields.io/github/v/release/GreenMachine582/HomeLab?include_prereleases)
![GitHub deployments](https://img.shields.io/github/deployments/GreenMachine582/HomeLab/Production)

## Table of Contents
1. [Putty SSH Access](#1-putty-ssh-access)
2. [Install the project](#2-install-the-project)
   1. [Setup the SSH key for GitHub](#1-setup-the-ssh-key-for-github)
   2. [Clone the repository](#2-clone-the-repository)
3. [Harden the System](#3-harden-the-system)
4. [Install Docker](#4-install-docker)
5. [Setup the Project](#5-setup-the-project)
   1. [Mount the M.2 drive](#1-mount-the-m2-drive)
   2. [Update the Docker configuration](#2-update-the-docker-configuration)
   3. [Other setup steps](#3-other-setup-steps)

---

## 1. Putty SSH Access
1. Generate an SSH key pair using **PuTTYgen**.
2. Copy the public key to the server:
```bash
type <filename>.pub | ssh pi@<rpi-ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh"
```
**Or manually:**
Login to the server with the correct user.
```bash
mkdir ~/.ssh
nano ~/.ssh/authorized_keys
```
> Ensure the public key is on a single line, e.g. `ssh-ed25519 AAA... <user>`
---

## 2. Install the Project
### 2.1 Setup the SSH key for GitHub
1. Become root user:
```bash
sudo su -
```
2. Create SSH config file:
```bash
mkdir ~/.ssh
nano ~/.ssh/config
```
Add the following content:
```
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/github
```
3. Generate the GitHub SSH key:
```bash
cd ~/.ssh
ssh-keygen -t ed25519 -C "your_email"
cat ~/.ssh/github.pub
```
4. Add the public key to your GitHub account:
   - Go to `GitHub > Settings > SSH and GPG keys > New SSH key`
   - Paste the public key and give it a title.
   - Click `Add SSH key`.
---
### 2.2 Clone the repository
```bash
apt install git expect -y
cd ~
git clone git@github.com:GreenMachine582/HomeLab.git
mv HomeLab homelab
```
Setup GreenTechHub project:
```bash
git clone git@github.com:GreenMachine582/GreenTechHub.git
mkdir ~/homelab/python_projects
mv GreenTechHub ~/homelab/python_projects/greentechhub
```
---
### 2.3 Create `github-deploy` user
1. Create the user:
```bash
sudo adduser github-deploy --disabled-password --gecos ""
```
2. Fix permission for the GitHub key:
```bash
sudo chown github-deploy:github-deploy /root/.ssh/github
```
3. Setup SSH access for `github-deploy` (same steps as [section 1](#1-putty-ssh-access)).
> Ensure the key is of openSSH format and without passphase, if not, convert it using **PuTTYgen**.
4. Test the SSH connection
5. Allow passwordless execution of deploy script:
```bash
sudo visudo -f /etc/sudoers.d/github-deploy
```
Insert the following line:
```nano
github-deploy ALL=(root) NOPASSWD: /root/homelab/deploy_homelab.sh
github-deploy ALL=(root) NOPASSWD: /root/homelab/scripts/deploy_project.sh
```
---

## 3. Harden the System
1. Update the system and SSH configuration:
```bash
sudo apt update && sudo apt upgrade -y
sudo nano /etc/ssh/sshd_config
```
2. Change or ensure the following lines:
```bash
AddressFamily any -> AddressFamily inet
ListenAddress 0.0.0.0 -> ListenAddress 0.0.0.0
PermitRootLogin yes -> PermitRootLogin no
PublicKeyAuthentication yes
PasswordAuthentication yes -> PasswordAuthentication no
```
3. Restart the SSH service:
```bash
sudo systemctl restart ssh
```
4. Disable root Bash history:
```bash
sudo su -
sed -i -E 's/^HISTSIZE=/#HISTSIZE=/' ~/.bashrc
sed -i -E 's/^HISTFILESIZE=/#HISTFILESIZE=/' ~/.bashrc
echo "HISTFILESIZE=0" >> ~/.bashrc
history -c; history -w
source ~/.bashrc
```
5. Disable pi sudo nopassword:
```bash
rm /etc/sudoers.d/010_*
```
6. Set root and user password:
```bash
passwd root
passwd <user>
```
7. Disable Bluetooth & Wi-Fi (Optional):
```bash
echo "dtoverlay=disable-bt" >> /boot/config.txt
echo "dtoverlay=disable-wifi" >> /boot/config.txt
```
8. Allow IPv4 only:
```bash
mkdir -p /etc/sysctl.d

cat << "EOF" > /etc/sysctl.d/99-disable-ipv6.conf
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF

sysctl --system
```
9. Enable ufw and configure firewall rules:
```bash
apt install ufw -y
bash ~/homelab/scripts/setup-ufw.sh
```
To view the current status of **UFW** with numbered rules:
```bash
ufw status numbered verbose
```
> ⚠️ Test SSH access before applying the firewall rules to ensure you don't lock yourself out.
10. Disable swap:
```bash
systemctl disable --now systemd-zram-setup@zram0.service
systemctl mask systemd-zram-setup@zram0.service
```
11. Update APT index and upgrade packages:
```bash
apt update && apt upgrade -y
reboot
```
---

## 4. Install Docker
1. Run **Docker** [🌐install commands](https://docs.docker.com/engine/install/debian/):
```bash
sudo su -
apt-get update
apt-get install -y ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
```
2. Add the **Docker** repository:
```bash
echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
tee /etc/apt/sources.list.d/docker.list > /dev/null

```
3. Install Docker
```bash
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```
---

## 5. Setup the Project
> Ensure you have an M.2 drive installed and formatted with `ext4` filesystem.
 
> ⚠️ Run all commands as root
### 5.1 Mount the M.2 drive
1. Identify:
```bash
lsblk -o NAME,PARTUUID,FSTYPE,SIZE,MOUNTPOINT,LABEL
```
2. Mount:
```bash
mkdir /mnt/m2drive
mount /dev/<name> /mnt/m2drive
```
4. Make it persistent:
```bash
nano /etc/fstab
```
Add:
```
PARTUUID=<part_id> /mnt/m2drive ext4 defaults 0 2
```
5. Test:
```bash
df -h /mnt/m2drive
```
---
### 5.2 Update the Docker configuration
1. Change Docker's global volume storage location:
```bash
mkdir -p /mnt/m2drive/docker
mkdir -p /etc/docker
nano /etc/docker/daemon.json
```
Add the following content to the file:
```json
{
  "data-root": "/mnt/m2drive/docker"
}
```
2. Then restart Docker service to apply the changes:
```bash
systemctl restart docker
```
---

### 5.3 Configure static IP address
1. Install dhcpcd5:
```bash
apt install dhcpcd5 -y
nano /etc/dhcpcd.conf
```
3. Add the following lines at the end of the file:
```
interface eth0
static ip_address=192.168.xx.xx/24
static routers=192.168.xx.1
static domain_name_servers=192.168.xx.1 1.1.1.1
```
4. Apply:
```bash
systemctl restart dhcpcd
```
---

### 5.4 Other setup steps
1. Disable Apache2
```bash
systemctl disable --now apache2
```
2. Run project [🗒️setup script](./setup.sh):
> Ensure to add/configure `.env` files before running the setup script.
```bash
cd ~/homelab
bash setup.sh
```
3. Monthly Update Script
Edit the crontab and add the following line to run the monthly update script:
```bash
crontab -e
```
Add:
```
0 2 1 * * ~/homelab/monthly-update.sh
```
> Runs at 2 AM on the 1st of every month.

4. **Systemd** service testing 
Below are the implemented systemd services for the HomeLab setup. You can test and check their status using the following commands:
```bash
systemctl start on-boot.service
systemctl status on-boot.service
```
(Same for: `on-shutdown.service`, `on-ssh-success.service`)
