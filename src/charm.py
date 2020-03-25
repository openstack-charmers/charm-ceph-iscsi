#!/usr/bin/env python3

import socket
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
import interface_tls_certificates

import adapters
import ops_openstack
import gwcli_client

logger = logging.getLogger(__name__)


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


class TLSCertificatesAdapter(adapters.OpenStackOperRelationAdapter):

    def __init__(self, relation):
        super(TLSCertificatesAdapter, self).__init__(relation)

    @property
    def enable_tls(self):
        return bool(self.relation.application_certs)


class CephISCSIGatewayAdapters(adapters.OpenStackRelationAdapters):

    relation_adapters = {
        'ceph-client': CephClientAdapter,
        'cluster': GatewayClientPeerAdapter,
        'certificates': TLSCertificatesAdapter,
    }


class CephISCSIGatewayCharmBase(ops_openstack.OSBaseCharm):

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
        logging.info("Using {} class".format(self.release))
        self.state.set_default(target_created=False)
        self.state.set_default(enable_tls=False)
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.peers = interface_ceph_iscsi_peer.CephISCSIGatewayPeers(
            self,
            'cluster')
        self.tls = interface_tls_certificates.TlsRequires(self, "certificates")
        self.adapters = CephISCSIGatewayAdapters(
            (self.ceph_client, self.peers, self.tls),
            self)
        self.framework.observe(self.on.ceph_client_relation_joined, self)
        self.framework.observe(self.ceph_client.on.pools_available, self)
        self.framework.observe(self.peers.on.has_peers, self)
        self.framework.observe(self.peers.on.ready_peers, self)
        self.framework.observe(self.on.create_target_action, self)
        self.framework.observe(self.on.certificates_relation_joined, self)
        self.framework.observe(self.on.certificates_relation_changed, self)

    def on_create_target_action(self, event):
        gw_client = gwcli_client.GatewayClient()
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
            self.model.config['rbd-pool'],
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
            self.model.config['rbd-pool'],
            event.params['image-name'])

    def setup_default_target(self):
        gw_client = gwcli_client.GatewayClient()
        gw_client.create_target(self.DEFAULT_TARGET)
        for gw_unit, gw_config in self.peers.ready_peer_details.items():
            gw_client.add_gateway_to_target(
                self.DEFAULT_TARGET,
                gw_config['ip'],
                gw_config['fqdn'])
        self.state.target_created = True

    def on_ready_peers(self, event):
        if not self.unit.is_leader():
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
        if self.unit.is_leader() and not self.peers.admin_password:
            logging.info("Setting admin password")
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for i in range(8))
            self.peers.set_admin_password(password)

    def on_ceph_client_relation_joined(self, event):
        logging.info("Requesting replicated pool")
        self.ceph_client.create_replicated_pool(
            self.model.config['rbd-pool'])
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

    def on_certificates_relation_joined(self, event):
        addresses = set()
        for binding_name in ['public', 'cluster']:
            binding = self.model.get_binding(binding_name)
            addresses.add(binding.network.ingress_address)
            addresses.add(binding.network.bind_address)
        sans = [str(s) for s in addresses]
        sans.append(socket.gethostname())
        self.tls.request_application_cert(socket.getfqdn(), sans)

    def on_certificates_relation_changed(self, event):
        app_certs = self.tls.application_certs
        if not all([self.tls.root_ca_cert, app_certs]):
            return
        if self.tls.chain:
            # Append chain file so that clients that trust the root CA will
            # trust certs signed by an intermediate in the chain
            ca_cert_data = self.tls.root_ca_cert + os.linesep + self.tls.chain
        pem_data = app_certs['cert'] + os.linesep + app_certs['key']
        tls_files = {
            '/etc/ceph/iscsi-gateway.crt': app_certs['cert'],
            '/etc/ceph/iscsi-gateway.key': app_certs['key'],
            '/etc/ceph/iscsi-gateway.pem': pem_data,
            '/usr/local/share/ca-certificates/vault_ca_cert.crt': ca_cert_data}
        for tls_file, tls_data in tls_files.items():
            with open(tls_file, 'w') as f:
                f.write(tls_data)
        subprocess.check_call(['update-ca-certificates'])
        cert_out = subprocess.check_output(
            ('openssl x509 -inform pem -in /etc/ceph/iscsi-gateway.pem '
             '-pubkey -noout').split())
        with open('/etc/ceph/iscsi-gateway-pub.key', 'w') as f:
            f.write(cert_out.decode('UTF-8'))
        self.state.enable_tls = True
        self.on_pools_available(event)


@ops_openstack.charm_class
class CephISCSIGatewayCharmJewel(CephISCSIGatewayCharmBase):

    state = StoredState()
    release = 'jewel'


@ops_openstack.charm_class
class CephISCSIGatewayCharmOcto(CephISCSIGatewayCharmBase):

    state = StoredState()
    release = 'octopus'

if __name__ == '__main__':
    main(ops_openstack.get_charm_class_for_release())
