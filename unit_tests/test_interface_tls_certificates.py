#!/usr/bin/env python3

import unittest
import sys

sys.path.append('lib')  # noqa
sys.path.append('src')  # noqa

import interface_tls_certificates as tls_int

from ops.testing import Harness
from ops.charm import CharmBase


class TestTlsRequires(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(CharmBase, meta='''
            name: ceph-iscsi
            requires:
              certificates:
                interface: tls-certificates
        ''')

    def add_cert_relation(self, rel_data):
        rel_id = self.harness.add_relation('certificates', 'vault')
        self.harness.add_relation_unit(
            rel_id,
            'vault/0')
        self.harness.update_relation_data(
            rel_id,
            'vault/0',
            rel_data)
        return rel_id

    def test_request_application_cert(self):
        self.add_cert_relation({})
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.certs.request_application_cert('mycn', ['san1', 'san2'])

        rel_data = self.harness.charm.model.get_relation('certificates').data
        our_unit = self.harness.charm.unit
        self.assertEqual(
            rel_data[our_unit]['application_cert_requests'],
            '{"mycn": {"sans": ["san1", "san2"]}}')

    def test_root_ca_cert(self):
        rel_data = {
            'ceph-iscsi_0.processed_application_requests':
                '{"app_data": {"cert": "appcert", "key": "appkey"}}',
            'ca': 'newca'}
        self.add_cert_relation(rel_data)
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.assertEqual(
            self.certs.root_ca_cert,
            'newca')

    def test_chain(self):
        rel_data = {
            'ceph-iscsi_0.processed_application_requests':
                '{"app_data": {"cert": "appcert", "key": "appkey"}}',
            'chain': 'newchain',
            'ca': 'newca'}
        self.add_cert_relation(rel_data)
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.assertEqual(
            self.certs.chain,
            'newchain')

    def test_server_certs(self):
        rel_data = {
            'ceph-iscsi_0.processed_requests':
                '{"app_data": {"cert": "appcert", "key": "appkey"}}',
            'ca': 'newca'}
        self.add_cert_relation(rel_data)
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.assertEqual(
            self.certs.server_certs,
            {'cert': 'appcert', 'key': 'appkey'})

    def test_client_certs(self):
        rel_data = {
            'ceph-iscsi_0.processed_client_requests':
                '{"app_data": {"cert": "appcert", "key": "appkey"}}',
            'ca': 'newca'}
        self.add_cert_relation(rel_data)
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.assertEqual(
            self.certs.client_certs,
            {'cert': 'appcert', 'key': 'appkey'})

    def test_application_certs(self):
        rel_data = {
            'ceph-iscsi_0.processed_application_requests':
                '{"app_data": {"cert": "appcert", "key": "appkey"}}',
            'ca': 'newca'}
        self.add_cert_relation(rel_data)
        self.harness.begin()
        self.certs = tls_int.TlsRequires(self.harness.charm, 'certificates')
        self.assertEqual(
            self.certs.application_certs,
            {'cert': 'appcert', 'key': 'appkey'})
