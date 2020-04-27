#!/usr/bin/env python3

# Copyright 2020 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import unittest
import sys

sys.path.append('lib')  # noqa
sys.path.append('src')  # noqa

from mock import call, patch, MagicMock, ANY

from ops.testing import Harness, _TestingModelBackend
from ops.model import (
    BlockedStatus,
)
from ops import framework, model

import charm


class CharmTestCase(unittest.TestCase):

    def setUp(self, obj, patches):
        super().setUp()
        self.patches = patches
        self.obj = obj
        self.patch_all()

    def patch(self, method):
        _m = patch.object(self.obj, method)
        mock = _m.start()
        self.addCleanup(_m.stop)
        return mock

    def patch_all(self):
        for method in self.patches:
            setattr(self, method, self.patch(method))


class TestCephISCSIGatewayCharmBase(CharmTestCase):

    PATCHES = [
        'ch_templating',
        'gwcli_client',
        'subprocess',
    ]

    def setUp(self):
        super().setUp(charm, self.PATCHES)
        self.harness = Harness(
            charm.CephISCSIGatewayCharmBase,
        )
        self.gwc = MagicMock()
        self.gwcli_client.GatewayClient.return_value = self.gwc

        # BEGIN: Workaround until
        # https://github.com/canonical/operator/pull/196 lands
        class _TestingOPSModelBackend(_TestingModelBackend):

            def relation_ids(self, relation_name):
                return self._relation_ids_map.get(relation_name, [])

            # Hardcoded until network_get is implemented in
            # _TestingModelBackend
            def network_get(self, endpoint_name, relation_id=None):
                network_data = {
                    'bind-addresses': [{
                        'interface-name': 'eth0',
                        'addresses': [{
                            'cidr': '10.0.0.0/24',
                            'value': '10.0.0.10'}]}],
                    'ingress-addresses': ['10.0.0.10'],
                    'egress-subnets': ['10.0.0.0/24']}
                return network_data

        self.harness._backend = _TestingOPSModelBackend(
            self.harness._unit_name)
        self.harness._model = model.Model(
            self.harness._unit_name,
            self.harness._meta,
            self.harness._backend)
        self.harness._framework = framework.Framework(
            ":memory:",
            self.harness._charm_dir,
            self.harness._meta,
            self.harness._model)
        # END Workaround

    def test_init(self):
        self.harness.begin()
        self.assertFalse(self.harness.charm.state.target_created)
        self.assertFalse(self.harness.charm.state.enable_tls)
        self.assertEqual(self.harness.charm.state.additional_trusted_ips, [])

    def add_cluster_relation(self):
        rel_id = self.harness.add_relation('cluster', 'ceph-iscsi')
        self.harness.add_relation_unit(
            rel_id,
            'ceph-iscsi/1',
            {
                'ingress-address': '10.0.0.2',
                'gateway_ready': 'True',
                'gateway_fqdn': 'ceph-iscsi-1.example'
            }
        )
        return rel_id

    @patch('socket.getfqdn')
    def test_on_create_target_action(self, _getfqdn):
        _getfqdn.return_value = 'ceph-iscsi-0.example'
        self.add_cluster_relation()
        self.harness.begin()
        action_event = MagicMock()
        action_event.params = {
            'iqn': 'iqn.mock.iscsi-gw:iscsi-igw',
            'gateway-units': 'ceph-iscsi/0 ceph-iscsi/1',
            'pool-name': 'iscsi-pool',
            'image-name': 'disk1',
            'image-size': '5G',
            'client-initiatorname': 'client-initiator',
            'client-username': 'myusername',
            'client-password': 'mypassword'}
        self.harness.charm.on_create_target_action(action_event)
        self.gwc.add_gateway_to_target.assert_has_calls([
            call(
                'iqn.mock.iscsi-gw:iscsi-igw',
                '10.0.0.10',
                'ceph-iscsi-0.example'),
            call(
                'iqn.mock.iscsi-gw:iscsi-igw',
                '10.0.0.2',
                'ceph-iscsi-1.example')])

        self.gwc.create_pool.assert_called_once_with(
            'iscsi-pool',
            'disk1',
            '5G')
        self.gwc.add_client_to_target.assert_called_once_with(
            'iqn.mock.iscsi-gw:iscsi-igw',
            'client-initiator')
        self.gwc.add_client_auth.assert_called_once_with(
            'iqn.mock.iscsi-gw:iscsi-igw',
            'client-initiator',
            'myusername',
            'mypassword')
        self.gwc.add_disk_to_client.assert_called_once_with(
            'iqn.mock.iscsi-gw:iscsi-igw',
            'client-initiator',
            'iscsi-pool',
            'disk1')

    @patch.object(charm.secrets, 'choice')
    def test_on_has_peers(self, _choice):
        _choice.return_value = 'r'
        self.add_cluster_relation()
        self.harness.begin()
        self.assertIsNone(
            self.harness.charm.peers.admin_password)
        self.harness.set_leader()
        self.harness.charm.peers.on.has_peers.emit()
        self.assertEqual(
            self.harness.charm.peers.admin_password, 'rrrrrrrr')

    def test_on_has_peers_not_leader(self):
        self.add_cluster_relation()
        self.harness.begin()
        self.assertIsNone(
            self.harness.charm.peers.admin_password)
        self.harness.set_leader(False)
        self.harness.charm.peers.on.has_peers.emit()
        self.assertIsNone(
            self.harness.charm.peers.admin_password)

    def test_on_has_peers_existing_password(self):
        rel_id = self.add_cluster_relation()
        self.harness.update_relation_data(
            rel_id,
            'ceph-iscsi',
            {'admin_password': 'existing password'})
        self.harness.begin()
        self.harness.set_leader()
        self.harness.charm.peers.on.has_peers.emit()
        self.assertEqual(
            self.harness.charm.peers.admin_password,
            'existing password')

    def test_on_ceph_client_relation_joined(self):
        rel_id = self.harness.add_relation('ceph-client', 'ceph-mon')
        self.harness.update_config(
            key_values={'rbd-metadata-pool': 'iscsi-pool'})
        self.harness.begin()
        self.harness.add_relation_unit(
            rel_id,
            'ceph-mon/0',
            {'ingress-address': '10.0.0.3'},
        )
        rel_data = self.harness.get_relation_data(rel_id, 'ceph-iscsi/0')
        req_osd_settings = json.loads(rel_data['osd-settings'])
        self.assertEqual(
            req_osd_settings,
            {'osd heartbeat grace': 20, 'osd heartbeat interval': 5})
        req_pool = json.loads(rel_data['broker_req'])
        self.assertEqual(
            req_pool['ops'],
            [{
                'app-name': None,
                'group': None,
                'group-namespace': None,
                'max-bytes': None,
                'max-objects': None,
                'name': 'iscsi-pool',
                'op': 'create-pool',
                'pg_num': None,
                'replicas': 3,
                'weight': None},
                {
                    'client': 'ceph-iscsi',
                    'op': 'set-key-permissions',
                    'permissions': [
                        'osd',
                        'allow *',
                        'mon',
                        'allow *',
                        'mgr',
                        'allow r']}])

    def test_on_pools_available(self):
        rel_id = self.add_cluster_relation()
        self.harness.update_relation_data(
            rel_id,
            'ceph-iscsi',
            {'admin_password': 'existing password',
             'gateway_ready': False})
        self.harness.begin()
        self.harness.charm.ceph_client.on.pools_available.emit()
        self.ch_templating.render.assert_has_calls([
            call('ceph.conf', '/etc/ceph/ceph.conf', ANY),
            call('iscsi-gateway.cfg', '/etc/ceph/iscsi-gateway.cfg', ANY),
            call(
                'ceph.client.ceph-iscsi.keyring',
                '/etc/ceph/ceph.client.ceph-iscsi.keyring', ANY)])
        self.assertTrue(self.harness.charm.state.is_started)
        rel_data = self.harness.get_relation_data(rel_id, 'ceph-iscsi/0')
        self.assertEqual(rel_data['gateway_ready'], 'True')

    @patch('socket.gethostname')
    def test_on_certificates_relation_joined(self, _gethostname):
        _gethostname.return_value = 'server1'
        rel_id = self.harness.add_relation('certificates', 'vault')
        self.harness.begin()
        self.harness.add_relation_unit(
            rel_id,
            'vault/0',
            {'ingress-address': '10.0.0.3'},
        )
        rel_data = self.harness.get_relation_data(rel_id, 'ceph-iscsi/0')
        self.assertEqual(
            rel_data['application_cert_requests'],
            '{"server1": {"sans": ["10.0.0.10", "server1"]}}')

    @patch('socket.gethostname')
    def test_on_certificates_relation_changed(self, _gethostname):
        _gethostname.return_value = 'server1'
        self.subprocess.check_output.return_value = b'pubkey'
        rel_id = self.harness.add_relation('certificates', 'vault')
        self.add_cluster_relation()
        self.harness.begin()
        with patch('builtins.open', unittest.mock.mock_open()) as _open:
            self.harness.add_relation_unit(
                rel_id,
                'vault/0',
                remote_unit_data={
                    'ceph-iscsi_0.processed_application_requests':
                        '{"app_data": {"cert": "appcert", "key": "appkey"}}',
                    'ca': 'ca'})
        expect_calls = [
            call('/etc/ceph/iscsi-gateway.crt', 'w'),
            call('/etc/ceph/iscsi-gateway.key', 'w'),
            call('/etc/ceph/iscsi-gateway.pem', 'w'),
            call('/usr/local/share/ca-certificates/vault_ca_cert.crt', 'w')]
        for open_call in expect_calls:
            self.assertIn(open_call, _open.call_args_list)
        handle = _open()
        handle.write.assert_has_calls([
            call('appcert'),
            call('appkey'),
            call('appcert\nappkey'),
            call('ca'),
            call('pubkey')])
        self.subprocess.check_call.assert_called_once_with(
            ['update-ca-certificates'])
        self.subprocess.check_output.assert_called_once_with(
            ['openssl', 'x509', '-inform', 'pem', '-in',
             '/etc/ceph/iscsi-gateway.pem', '-pubkey', '-noout'])
        self.assertTrue(self.harness.charm.state.enable_tls)

    def test_custom_status_check(self):
        self.harness.add_relation('ceph-client', 'ceph-mon')
        self.harness.add_relation('cluster', 'ceph-iscsi')
        self.harness.begin()
        self.harness.charm.on.update_status.emit()
        self.assertEqual(
            self.harness.charm.unit.status.message,
            '1 is an invalid unit count')
        self.assertIsInstance(
            self.harness.charm.unit.status,
            BlockedStatus)
