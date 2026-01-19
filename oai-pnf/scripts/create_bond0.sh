#!/bin/bash

# Create Bond0
nmcli con add type bond con-name bond0 ifname bond0 mode active-backup

# Activate Bond0
nmcli con up bond0

