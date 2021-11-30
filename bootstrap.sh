#!/usr/bin/env bash
set -o errexit
set -o nounset

typeset -r VM_IP_ADDRESS=${1}
if [[ -z "${VM_IP_ADDRESS}" ]]; then
  echo "ERROR: IP address is required"
  exit 1
fi

apt-get update -y
apt-get upgrade -y

apt-get install asterisk -y
