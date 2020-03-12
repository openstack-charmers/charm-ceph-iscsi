#!/usr/bin/env python3

import logging
import os
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

import adapters
import ops_openstack

logger = logging.getLogger()


class CephClientAdapter(adapters.OpenStackOperRelationAdapter):

    def __init__(self, relation):
        super(CephClientAdapter, self).__init__(relation)

    @property
    def mon_hosts(self):
        hosts = self.relation.get_relation_data()['mon_hosts']
        return ' '.join(sorted(hosts))

    @property
    def auth_supported(self):
        return self.relation.get_relation_data()['auth']

    @property
    def key(self):
        return self.relation.get_relation_data()['key']


class PeerAdapter(adapters.OpenStackOperRelationAdapter):

    def __init__(self, relation):
        super(PeerAdapter, self).__init__(relation)


class GatewayClientPeerAdapter(PeerAdapter):

    def __init__(self, relation):
        super(GatewayClientPeerAdapter, self).__init__(relation)

    @property
    def gw_hosts(self):
        hosts = self.relation.peer_addresses
        return ' '.join(sorted(hosts))


class CephISCSIGatewayAdapters(adapters.OpenStackRelationAdapters):

    relation_adapters = {
        'ceph-client': CephClientAdapter,
        'cluster': GatewayClientPeerAdapter,
    }


class GatewayClient():

    def run(self, path, cmd):
        _cmd = ['gwcli', path]
        _cmd.extend(cmd.split())
        logging.info(_cmd)
        print(_cmd)
        subprocess.check_call(_cmd)

    def create_target(self, iqn):
        self.run(
            "/iscsi-targets/",
            "create {}".format(iqn))

    def add_gateway_to_target(self, iqn, gateway_ip, gateway_fqdn):
        self.run(
            "/iscsi-targets/{}/gateways/".format(iqn),
            "create {} {}".format(gateway_fqdn, gateway_ip))

    def create_pool(self, pool_name, image_name, image_size):
        self.run(
            "/disks",
            "create pool={} image={} size={}".format(
                pool_name,
                image_name,
                image_size))

    def add_client_to_target(self, iqn, initiatorname):
        self.run(
            "/iscsi-targets/{}/hosts/".format(iqn),
            "create {}".format(initiatorname))

    def add_client_auth(self, iqn, initiatorname, username, password):
        self.run(
            "/iscsi-targets/{}/hosts/{}".format(iqn, initiatorname),
            "auth username={} password={}".format(username, password))

    def add_disk_to_client(self, iqn, initiatorname, pool_name, image_name):
        self.run(
            "/iscsi-targets/{}/hosts/{}".format(iqn, initiatorname),
            "disk add {}/{}".format(pool_name, image_name))


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
    REQUIRED_RELATIONS = ['ceph-client', 'cluster']

    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.state.set_default(target_created=False)
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.peers = interface_ceph_iscsi_peer.CephISCSIGatewayPeers(
            self,
            'cluster')
        self.adapters = CephISCSIGatewayAdapters(
            (self.ceph_client, self.peers),
            self)
        self.framework.observe(self.on.ceph_client_relation_joined, self)
        self.framework.observe(self.ceph_client.on.pools_available, self)
        self.framework.observe(self.peers.on.has_peers, self)
        self.framework.observe(self.peers.on.ready_peers, self)
        self.framework.observe(self.on.create_target_action, self)

    def on_create_target_action(self, event):
        gw_client = GatewayClient()
        gw_client.create_target(event.params['iqn'])
        for gw_unit, gw_config in self.peers.ready_peer_details.items():
            added_gateways = []
            if gw_unit in event.params['gateway-units']:
                gw_client.add_gateway_to_target(
                    event.params['iqn'],
                    gw_config['ip'],
                    gw_config['fqdn'])
                added_gateways.append(gw_unit)
        gw_client.create_pool(
            'iscsi',
            event.params['image-name'],
            event.params['image-size'])
        gw_client.add_client_to_target(
            event.params['iqn'],
            event.params['client-initiatorname'])
        gw_client.add_client_auth(
            event.params['iqn'],
            event.params['client-initiatorname'],
            event.params['client-username'],
            event.params['client-password'])
        gw_client.add_disk_to_client(
            event.params['iqn'],
            event.params['client-initiatorname'],
            'iscsi',
            event.params['image-name'])

    def setup_default_target(self):
        gw_client = GatewayClient()
        gw_client.create_target(self.DEFAULT_TARGET)
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
                    self.adapters)
        logging.info("Rendering config")
        render_configs()
        logging.info("Setting started state")
        self.peers.announce_ready()
        self.state.is_started = True
        self.update_status()
        logging.info("on_pools_available: status updated")


if __name__ == '__main__':
    main(CephISCSIGatewayCharm)
