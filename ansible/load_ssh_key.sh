#!/usr/bin/expect -f

set timeout -1

# Key path passed as argument
set key [lindex $argv 0]

# Read passphrase from environment
set passphrase $env(SSH_KEY_PASSPHRASE)

spawn ssh-add $key
expect "Enter passphrase"
send "$passphrase\r"
expect eof
