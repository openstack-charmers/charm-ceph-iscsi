#!/bin/bash

UPDATE=""
while getopts ":u" opt; do
  case $opt in
    u) UPDATE=true;;
  esac
done

git submodule update --init

if [[ -z "$UPDATE" ]]; then
    pip install -t lib -r build-requirements.txt
else
    git -C mod/operator pull origin master
    git -C mod/ops-openstack pull origin master
    git -C mod/charm-helpers pull origin master
    pip install -t lib -r build-requirements.txt --upgrade
fi

ln -f -t lib -s ../mod/operator/ops
ln -f -t lib -s ../mod/interface-ceph-client/interface_ceph_client.py
ln -f -t lib -s ../mod/ops-openstack/ops_openstack.py
ln -f -t lib -s ../mod/ops-openstack/adapters.py
