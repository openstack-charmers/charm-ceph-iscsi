#!/bin/bash

rm -rf lib/*
rm adapters.py interface_ceph_client.py ops ops_openstack.py

pip install -t lib/ git+https://github.com/juju/charm-helpers.git

git submodule init
git submodule update
(cd lib; ln -s ../mod/operator/ops;)
(cd lib; ln -s ../mod/interface-ceph-client/interface_ceph_client.py;)
(cd lib; ln -s ../mod/ops-openstack/ops_openstack.py)
(cd lib; ln -s ../mod/ops-openstack/adapters.py)
(cd mod/interface-ceph-client; git pull origin master)
(cd mod/operator; git pull origin master)
(cd mod/ops-openstack; git pull origin master)
