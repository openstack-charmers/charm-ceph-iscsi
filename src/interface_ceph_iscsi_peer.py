#!/usr/bin/env python3

import logging
import socket

from ops.framework import (
    StoredState,
    EventBase,
    EventSetBase,
    EventSource,
    Object)


class HasPeersEvent(EventBase):
    pass


class ReadyPeersEvent(EventBase):
    pass


class CephISCSIGatewayPeerEvents(EventSetBase):
    has_peers = EventSource(HasPeersEvent)
    ready_peers = EventSource(ReadyPeersEvent)


class CephISCSIGatewayPeers(Object):

    on = CephISCSIGatewayPeerEvents()
    state = StoredState()
    PASSWORD_KEY = 'admin_password'
    READY_KEY = 'gateway_ready'
    FQDN_KEY = 'gateway_fqdn'

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.relation_name = relation_name
        self.this_unit = self.framework.model.unit
        self.framework.observe(
            charm.on[relation_name].relation_changed,
            self.on_changed)

    def on_changed(self, event):
        logging.info("CephISCSIGatewayPeers on_changed")
        self.on.has_peers.emit()
        if self.ready_peer_details:
            self.on.ready_peers.emit()

    def set_admin_password(self, password):
        logging.info("Setting admin password")
        self.peer_rel.data[self.peer_rel.app][self.PASSWORD_KEY] = password

    def announce_ready(self):
        logging.info("announcing ready")
        self.peer_rel.data[self.this_unit][self.READY_KEY] = 'True'
        self.peer_rel.data[self.this_unit][self.FQDN_KEY] = self.fqdn

    @property
    def ready_peer_details(self):
        peers = {
            self.framework.model.unit.name: {
                'fqdn': self.fqdn,
                'ip': self.cluster_bind_address}}
        for u in self.peer_rel.units:
            if self.peer_rel.data[u].get(self.READY_KEY) == 'True':
                peers[u.name] = {
                    'fqdn': self.peer_rel.data[u][self.FQDN_KEY],
                    'ip': self.peer_rel.data[u]['ingress-address']}
        return peers

    @property
    def fqdn(self):
        return socket.getfqdn()

    @property
    def is_joined(self):
        return self.peer_rel is not None

    @property
    def peer_rel(self):
        return self.framework.model.get_relation(self.relation_name)

    @property
    def peer_binding(self):
        return self.framework.model.get_binding(self.peer_rel)

    @property
    def cluster_bind_address(self):
        return str(self.peer_binding.network.bind_address)

    @property
    def admin_password(self):
        # https://github.com/canonical/operator/issues/148
        # return self.peer_rel.data[self.peer_rel.app].get(self.PASSWORD_KEY)
        return 'hardcodedpassword'

    @property
    def peer_addresses(self):
        addresses = [self.cluster_bind_address]
        for u in self.peer_rel.units:
            addresses.append(self.peer_rel.data[u]['ingress-address'])
        return sorted(addresses)
