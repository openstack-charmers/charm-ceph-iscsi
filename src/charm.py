#!/usr/bin/env python3

import socket
import logging
import os
import subprocess
import sys
import string
import secrets
from pathlib import Path

sys.path.append('lib')

from ops.framework import (
    StoredState,
    EventSource,
    EventBase,
    ObjectEvents,
)
from ops.main import main
import ops.model
import charmhelpers.core.host as ch_host
import charmhelpers.core.templating as ch_templating
import interface_ceph_client
import interface_ceph_iscsi_peer
import ca_client

import adapters
import ops_openstack
import gwcli_client
import cryptography.hazmat.primitives.serialization as serialization
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
        try:
            return bool(self.relation.application_certificate)
        except ca_client.CAClientError:
            return False


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


    DEFAULT_TARGET = "iqn.2003-01.com.ubuntu.iscsi-gw:iscsi-igw"
    REQUIRED_RELATIONS = ['ceph-client', 'cluster']

    # Two has been tested but four is probably fine too but needs
    # validating
    ALLOWED_UNIT_COUNTS = [2]

    CEPH_CONFIG_PATH = Path('/etc/ceph')
    CEPH_ISCSI_CONFIG_PATH = CEPH_CONFIG_PATH / 'iscsi'
    GW_CONF = CEPH_CONFIG_PATH / 'iscsi-gateway.cfg'
    CEPH_CONF = CEPH_ISCSI_CONFIG_PATH / 'ceph.conf'
    GW_KEYRING = CEPH_ISCSI_CONFIG_PATH / 'ceph.client.ceph-iscsi.keyring'
    TLS_KEY_PATH = CEPH_CONFIG_PATH / 'iscsi-gateway.key'
    TLS_PUB_KEY_PATH = CEPH_CONFIG_PATH / 'iscsi-gateway-pub.key'
    TLS_CERT_PATH = CEPH_CONFIG_PATH / 'iscsi-gateway.crt'
    TLS_KEY_AND_CERT_PATH = CEPH_CONFIG_PATH / 'iscsi-gateway.pem'
    TLS_CA_CERT_PATH = Path(
        '/usr/local/share/ca-certificates/vault_ca_cert.crt')

    GW_SERVICES = ['rbd-target-api', 'rbd-target-gw']

    RESTART_MAP = {
        str(GW_CONF): GW_SERVICES,
        str(CEPH_CONF): GW_SERVICES,
        str(GW_KEYRING): GW_SERVICES}

    release = 'default'

    def __init__(self, framework, key):
        super().__init__(framework, key)
        logging.info("Using {} class".format(self.release))
        self.state.set_default(
            target_created=False,
            enable_tls=False,
            additional_trusted_ips=[])
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.peers = interface_ceph_iscsi_peer.CephISCSIGatewayPeers(
            self,
            'cluster')
        self.ca_client = ca_client.CAClient(
            self,
            'certificates')
        self.adapters = CephISCSIGatewayAdapters(
            (self.ceph_client, self.peers, self.ca_client),
            self)
        self.framework.observe(
            self.ceph_client.on.broker_available,
            self.request_ceph_pool)
        self.framework.observe(
            self.ceph_client.on.pools_available,
            self.render_config)
        self.framework.observe(
            self.peers.on.has_peers,
            self)
        self.framework.observe(
            self.ca_client.on.tls_app_config_ready,
            self.on_tls_app_config_ready)
        self.framework.observe(
            self.ca_client.on.ca_available,
            self.on_ca_available)
        self.framework.observe(
            self.on.config_changed,
            self.render_config)
        self.framework.observe(
            self.on.upgrade_charm,
            self.render_config)
        self.framework.observe(
            self.on.create_target_action,
            self)
        self.framework.observe(
            self.on.add_trusted_ip_action,
            self)

    def on_install(self, event):
        if ch_host.is_container():
            logging.info("Installing into a container is not supported")
            self.update_status()
        else:
            self.install_pkgs()


    def on_has_peers(self, event):
        logging.info("Unit has peers")
        if self.unit.is_leader() and not self.peers.admin_password:
            logging.info("Setting admin password")
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for i in range(8))
            self.peers.set_admin_password(password)

    def request_ceph_pool(self, event):
        logging.info("Requesting replicated pool")
        self.ceph_client.create_replicated_pool(
            self.model.config['rbd-metadata-pool'])
        logging.info("Requesting permissions")
        self.ceph_client.request_ceph_permissions(
            'ceph-iscsi',
            self.CEPH_CAPABILITIES)
        self.ceph_client.request_osd_settings({
            'osd heartbeat grace': 20,
            'osd heartbeat interval': 5})

    def refresh_request(self, event):
        self.render_config(event)
        self.request_ceph_pool(event)

    def render_config(self, event):
        if not self.peers.admin_password:
            logging.info("Defering setup")
            event.defer()
            return
        if not self.ceph_client.pools_available:
            logging.info("Defering setup")
            event.defer()
            return

        self.CEPH_ISCSI_CONFIG_PATH.mkdir(
            exist_ok=True, 
            mode=0o750)

        def daemon_reload_and_restart(service_name):
            subprocess.check_call(['systemctl', 'daemon-reload'])
            subprocess.check_call(['systemctl', 'restart', service_name])

        rfuncs = {
            'rbd-target-api': daemon_reload_and_restart}

        @ch_host.restart_on_change(self.RESTART_MAP, restart_functions=rfuncs)
        def _render_configs():
            for config_file in self.RESTART_MAP.keys():
                ch_templating.render(
                    os.path.basename(config_file),
                    config_file,
                    self.adapters)
        logging.info("Rendering config")
        _render_configs()
        logging.info("Setting started state")
        self.peers.announce_ready()
        self.state.is_started = True
        self.update_status()
        logging.info("on_pools_available: status updated")

    def on_ca_available(self, event):
        addresses = set()
        for binding_name in ['public', 'cluster']:
            binding = self.model.get_binding(binding_name)
            addresses.add(binding.network.ingress_address)
            addresses.add(binding.network.bind_address)
        sans = [str(s) for s in addresses]
        sans.append(socket.gethostname())
        self.ca_client.request_application_certificate(socket.getfqdn(), sans)

    def on_tls_app_config_ready(self, event):
        self.TLS_KEY_PATH.write_bytes(
            self.ca_client.application_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()))
        self.TLS_CERT_PATH.write_bytes(
            self.ca_client.application_certificate.public_bytes(
                encoding=serialization.Encoding.PEM))
        self.TLS_CA_CERT_PATH.write_bytes(
            self.ca_client.ca_certificate.public_bytes(
                encoding=serialization.Encoding.PEM))
        self.TLS_KEY_AND_CERT_PATH.write_bytes(
            self.ca_client.application_certificate.public_bytes(
                encoding=serialization.Encoding.PEM) +
            b'\n' +
            self.ca_client.application_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption())
        )
        self.TLS_PUB_KEY_PATH.write_bytes(
            self.ca_client.application_key.public_key().public_bytes(
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
                encoding=serialization.Encoding.PEM))
        subprocess.check_call(['update-ca-certificates'])
        self.state.enable_tls = True
        self.refresh_request(event)

    def custom_status_check(self):
        if ch_host.is_container():
            self.unit.status = ops.model.BlockedStatus(
                'Charm cannot be deployed into a container')
            return False
        if self.peers.unit_count not in self.ALLOWED_UNIT_COUNTS:
            self.unit.status = ops.model.BlockedStatus(
                '{} is an invalid unit count'.format(self.peers.unit_count))
            return False
        return True

    # Actions

    def on_add_trusted_ip_action(self, event):
        if self.unit.is_leader():
            self.state.additional_trusted_ips = event.params.get('ips')
            logging.info(len(self.state.additional_trusted_ips))
            self.peers.set_allowed_ips(
                self.state.additional_trusted_ips)
        else:
            event.fail("Action must be run on leader")

    def on_create_target_action(self, event):
        gw_client = gwcli_client.GatewayClient()
        target = event.params.get('iqn', self.DEFAULT_TARGET)
        gateway_units = event.params.get(
            'gateway-units',
            [u for u in self.peers.ready_peer_details.keys()])
        gw_client.create_target(target)
        for gw_unit, gw_config in self.peers.ready_peer_details.items():
            added_gateways = []
            if gw_unit in gateway_units:
                gw_client.add_gateway_to_target(
                    target,
                    gw_config['ip'],
                    gw_config['fqdn'])
                added_gateways.append(gw_unit)
        gw_client.create_pool(
            event.params['pool-name'],
            event.params['image-name'],
            event.params['image-size'])
        gw_client.add_client_to_target(
            target,
            event.params['client-initiatorname'])
        gw_client.add_client_auth(
            target,
            event.params['client-initiatorname'],
            event.params['client-username'],
            event.params['client-password'])
        gw_client.add_disk_to_client(
            target,
            event.params['client-initiatorname'],
            event.params['pool-name'],
            event.params['image-name'])
        event.set_results({'iqn': target})


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
