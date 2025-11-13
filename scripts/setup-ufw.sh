#!/bin/bash

# Reset and disable IPv6
ufw --force reset

# Disable IPv6 in UFW completely
sed -i 's/^IPV6=.*/IPV6=no/' /etc/default/ufw

# Default policy: deny incoming, allow outgoing
ufw default deny incoming
ufw default allow outgoing

# Allow loopback
ufw allow in on lo

# SSH with rate limiting
ufw limit 22/tcp

# HTTP and HTTPS
ufw allow 80/tcp
ufw allow 443/tcp

# DNS (UDP and TCP)
ufw allow 53/udp
ufw allow 53/tcp

# DHCP (client)
ufw allow 67/udp

# Enable UFW
ufw --force enable

echo "✅ UFW configured with simplified rules. IPv6 is disabled."
