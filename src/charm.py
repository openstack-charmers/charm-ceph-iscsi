#!/usr/bin/env python3

import logging
import os
import socket
import subprocess
import sys
import string
import secrets

sys.path.append('lib')

from ops.framework import (
    StoredState,
)
from ops.main import main
import charmhelpers.core.host as ch_host
import charmhelpers.core.templating as ch_templating
import interface_ceph_client
import interface_ceph_iscsi_peer

import ops_openstack

logger = logging.getLogger()

class GatewayClient():
    
    CREATE_TARGET = "/iscsi-targets/ create {gw_iqn}"
    def run(self, path, cmd):
        _cmd = ['gwcli', path]
        _cmd.extend(cmd.split())
        logging.info(_cmd)
        subprocess.check_call(_cmd)

    def create_target(self, gw_iqn):
        self.run(
            "/iscsi-targets/",
            "create {gw_iqn}".format(gw_iqn=gw_iqn))
        
    def add_gateway_to_target(self, target, gateway_ip, gateway_fqdn):
        self.run(
            "/iscsi-targets/{}/gateways/".format(target),
            "create {} {}".format(gateway_fqdn, gateway_ip),
        )

class CephISCSIGatewayCharm(ops_openstack.OSBaseCharm):
    state = StoredState()
    PACKAGES = ['ceph-iscsi', 'tcmu-runner', 'ceph-common']
    CEPH_CAPABILITIES = [
        "osd", "allow *",
        "mon", "allow *",
        "mgr", "allow r"]

    RESTART_MAP = {
        '/etc/ceph/ceph.conf': ['rbd-target-api'],
        '/etc/ceph/iscsi-gateway.cfg': ['rbd-target-api'],
        '/etc/ceph/ceph.client.ceph-iscsi.keyring': ['rbd-target-api']}

    DEFAULT_TARGET = "iqn.2003-01.com.ubuntu.iscsi-gw:iscsi-igw"

    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.state.set_default(target_created=False)
        self.framework.observe(self.on.ceph_client_relation_joined, self)
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.framework.observe(self.ceph_client.on.pools_available, self)
        self.peers = interface_ceph_iscsi_peer.CephISCSIGatewayPeers(
            self,
            'cluster')
        self.framework.observe(self.peers.on.has_peers, self)
        self.framework.observe(self.peers.on.ready_peers, self)

    def setup_default_target(self):
        gw_client = GatewayClient()
        gw_client.create_target(self.DEFAULT_TARGET)
        gw_client.add_gateway_to_target(
            self.DEFAULT_TARGET,
            self.peers.cluster_bind_address,
            socket.getfqdn())
        for gw_unit, gw_config in self.peers.ready_peer_details.items():
            gw_client.add_gateway_to_target(
                self.DEFAULT_TARGET,
                gw_config['ip'],
                gw_config['fqdn'])
        self.state.target_created = True

    def on_ready_peers(self, event):
        if not self.model.unit.is_leader():
            logging.info("Leader should do setup")
            return
        if not self.state.is_started:
            logging.info("Cannot perform setup yet, not started")
            event.defer()
            return
        if self.state.target_created:
            logging.info("Initial target setup already complete")
            return
        else:
            self.setup_default_target()

    def on_has_peers(self, event):
        logging.info("Unit has peers")
        if self.model.unit.is_leader() and not self.peers.admin_password:
            logging.info("Setting admin password")
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for i in range(8))
            self.peers.set_admin_password(password)

    def on_ceph_client_relation_joined(self, event):
        logging.info("Requesting replicated pool")
        self.ceph_client.create_replicated_pool('iscsi')
        logging.info("Requesting permissions")
        self.ceph_client.request_ceph_permissions(
            'ceph-iscsi',
            self.CEPH_CAPABILITIES)

    def on_pools_available(self, event):
        logging.info("on_pools_available")
        if not self.peers.admin_password:
            logging.info("Defering setup")
            event.defer()
            return
        ceph_context = {
            'use_syslog':
                str(self.framework.model.config['use-syslog']).lower(),
            'loglevel': self.framework.model.config['loglevel'],
            'admin_password': self.peers.admin_password,
        }
        ceph_context.update(self.ceph_client.get_pool_data())
        ceph_context['mon_hosts'] = ' '.join(ceph_context['mon_hosts'])
        ceph_context['gw_hosts'] = ' '.join(sorted(self.peers.peer_addresses))

        def daemon_reload_and_restart(service_name):
            subprocess.check_call(['systemctl', 'daemon-reload'])
            subprocess.check_call(['systemctl', 'restart', service_name])

        rfuncs = {
            'rbd-target-api': daemon_reload_and_restart}

        @ch_host.restart_on_change(self.RESTART_MAP, restart_functions=rfuncs)
        def render_configs():
            for config_file in self.RESTART_MAP.keys():
                ch_templating.render(
                    os.path.basename(config_file),
                    config_file,
                    ceph_context)
        logging.info("Rendering config")
        render_configs()
        logging.info("Setting started state")
        self.peers.announce_ready()
        self.state.is_started = True
        self.update_status()
        logging.info("on_pools_available: status updated")


if __name__ == '__main__':
    main(CephISCSIGatewayCharm)
