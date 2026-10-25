#!/usr/bin/env bash
# Phase 0, Step 4.1: default Mininet self-test (no custom controller yet).
# Confirms Mininet's own built-in controller + OVS can get 0% packet loss.
# Needs sudo (Mininet always does) and will prompt you.
set -uo pipefail

echo "Running: sudo mn --test pingall"
sudo mn --test pingall

echo
echo "Cleaning up any leftover Mininet state..."
sudo mn -c
