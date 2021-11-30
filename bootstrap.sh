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

apt-get install -y --force-yes asterisk mc

sed --in-place 's/;verbose = 3/verbose = 9/' '/etc/asterisk/asterisk.conf'

cat /vagrant/asterisk/manager.conf > /etc/asterisk/manager.conf

cat /vagrant/asterisk/sip.conf > /etc/asterisk/sip.conf

cat /vagrant/asterisk/extensions.conf > /etc/asterisk/extensions.conf

service asterisk restart
