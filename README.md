# Homelab
![GitHub release](https://img.shields.io/github/v/release/GreenMachine582/HomeLab?include_prereleases)

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
1. Create the SSH key pair using puttygen.
2. Copy and paste the public key to the server:
```bash
type <filename>.pub | ssh pi@<rpi-ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && chmod 700 ~/.ssh"
```
--or--
```bash
mkdir ~/.ssh
nano ~/.ssh/authorized_keys
```
> **_NOTE_**: Ensure the public key is on a single line without any line breaks. e.g. `ssh-ed25519 AAA... <user>`
---

## 2. Install the project
### 1. Setup the SSH key for GitHub:
1. Define GitHub SSH config:
```bash
sudo su -
```
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
2. Generate a new SSH key pair: with filename `github` and email `your_email`:
```bash
cd ~/.ssh
ssh-keygen -t ed25519 -C "your_email"
cat ~/.ssh/github.pub
```
3. Copy the public key to your clipboard.
4. Add the public key to your GitHub account:
   - Go to `GitHub > Settings > SSH and GPG keys > New SSH key`
   - Paste the public key and give it a title.
   - Click `Add SSH key`.
### 2. Clone the repository:
```bash
apt install git -y
cd ~
git clone git@github.com:GreenMachine582/HomeLab.git
```
```bash
mv HomeLab homelab
```

## 3. Harden the System
1. Change the SSH port to `2189`:
```bash
sudo apt update && sudo apt upgrade -y
sudo nano /etc/ssh/sshd_config
```
2. Uncomment and change the following lines:
```bash
AddressFamily any -> AddressFamily inet
ListenAddress 0.0.0.0 -> ListenAddress 0.0.0.0
PermitRootLogin yes -> PermitRootLogin no
PublicKeyAuthentication yes
PasswordAuthentication yes -> PasswordAuthentication no
```
3. Then restart the SSH service:
```bash
sudo systemctl restart ssh
```
4. Switch to root user:
```bash
sudo su -
```
5. Disable root Bash history:
```bash
sed -i -E 's/^HISTSIZE=/#HISTSIZE=/' ~/.bashrc
sed -i -E 's/^HISTFILESIZE=/#HISTFILESIZE=/' ~/.bashrc
echo "HISTFILESIZE=0" >> ~/.bashrc
history -c; history -w
source ~/.bashrc
```
6. Disable pi sudo nopassword:
```bash
rm /etc/sudoers.d/010_*
```
7. Set root and user password:
```bash
passwd root
passwd <user>
```
8. Disable Bluetooth & Wi-Fi (Optional):
```bash
echo "dtoverlay=disable-bt" >> /boot/config.txt
```
```bash
echo "dtoverlay=disable-wifi" >> /boot/config.txt
```
9. Allow IPv4 only:
```bash
cp /etc/sysctl.conf /etc/sysctl.conf.backup
cat << "EOF" >> /etc/sysctl.conf
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
net.ipv6.conf.lo.disable_ipv6 = 1
EOF
sysctl -p
```
10. Enable ufw and configure firewall rules:
```bash
apt install ufw -y
bash homelab/scripts/setup-ufw.sh
```
To view the current status of UFW with numbered rules:
```bash
ufw status numbered verbose
```
> **_NOTE_**: Test SSH access before applying the firewall rules to ensure you don't lock yourself out.
11. Disable swap:
```bash
systemctl disable dphys-swapfile
systemctl stop dphys-swapfile
```

12. Update APT index and upgrade packages:
```bash
apt update && apt upgrade -y
```
```bash
reboot
```
---

## 4. Install Docker
1. Switch to root user:
```bash
sudo su -
```
2. Run docker [🌐install commands](https://docs.docker.com/engine/install/debian/):
```bash
apt-get update
apt-get install ca-certificates curl gnupg lsb-release
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null
```
```bash
apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```
---

## 5. Setup the Project
> **_NOTE_**: Ensure you have an M.2 drive installed and formatted with `ext4` filesystem.
 
> **_NOTE_**: Chnage to root user before running the commands below.
### 1. Mount the M.2 drive:
1. Identify the M.2 drive:
```bash
lsblk -o NAME,PARTUUID,FSTYPE,SIZE,MOUNTPOINT,LABEL
```
2. Create a mount point for the M.2 drive and then mount it:
```bash
mkdir /mnt/m2drive
mount /dev/<name> /mnt/m2drive
```
4. To make the mount persistent across reboots, edit the `/etc/fstab` file:
```bash
nano /etc/fstab
```
Add the following line to the end of the file:
```
PARTUUID=<part_id> /mnt/m2drive ext4 defaults 0 2
```
5. Test it:
```bash
df -h /mnt/m2drive
```
### 2. Update the Docker configuration:
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
### 3. Configure static IP address:
1. Install dhcpcd5:
```bash
apt install dhcpcd5 -y
```
2. Edit the dhcpcd configuration file:
```bash
nano /etc/dhcpcd.conf
```
3. Add the following lines at the end of the file:
```
interface eth0
static ip_address=192.168.50.10/24
static routers=192.168.50.1
static domain_name_servers=192.168.50.1 1.1.1.1
```
4. Restart the dhcpcd service:
```bash
systemctl restart dhcpcd
```
### 4. Other setup steps:
1. Disable and stop Apache2 service as Caddy on ports is used instead
```bash
systemctl disable apache2
systemctl stop apache2
```
2. Run projects [🗒️setup script](./setup.sh):
> **_NOTE_**: Ensure to add/configure `.env` files before running the setup script.
```bash
cd ~/homelab
bash setup.sh
```
3. Monthly Update Script
Edit the crontab and add the following line to run the monthly update script:
```bash
crontab -e
```
```
0 2 1 * * ~/homelab/monthly-update.sh
```
> **_NOTE_**: Runs at 2 AM on the 1st of every month.

4. To test and check the setup of the systemd services 
Below are the implemented systemd services for the HomeLab setup. You can test and check their status using the following commands:
- on-boot.service
- on-shutdown.service
- on-ssh-success.service
```bash
systemctl start on-boot.service
```
```bash
systemctl status on-boot.service
```
