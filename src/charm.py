#!/usr/bin/env python3

import os
import subprocess
import sys

sys.path.append('lib')

from ops.charm import CharmBase
from ops.framework import (
    StoredState,
)
from ops.main import main
from ops.model import (
    ActiveStatus,
    WaitingStatus,
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
)
import charmhelpers.core.host as ch_host
import charmhelpers.core.templating as ch_templating
import interface_ceph_client


class CephISCSIGatewayCharm(CharmBase):
    state = StoredState()

    PACKAGES = ['ceph-iscsi', 'tcmu-runner', 'ceph-common']
    CEPH_CAPABILITIES = [
        "osd", "allow *",
        "mon", "allow *",
        "mgr", "allow r"]

    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.state.set_default(is_started=False)
        self.framework.observe(self.on.install, self)
        self.framework.observe(self.on.update_status, self)
        self.framework.observe(self.on.ceph_client_relation_joined, self)
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.framework.observe(self.ceph_client.on.pools_available, self)

    def on_install(self, event):
        apt_update(fatal=True)
        apt_install(self.PACKAGES, fatal=True)

    def on_update_status(self, event):
        if self.state.is_started:
            self.model.unit.status = ActiveStatus('Unit is ready')
        else:
            self.model.unit.status = WaitingStatus('not ready for reasons')

    def on_ceph_client_relation_joined(self, event):
        self.ceph_client.create_replicated_pool('iscsi')
        self.ceph_client.request_ceph_permissions(
            'ceph-iscsi',
            self.CEPH_CAPABILITIES)

    def on_pools_available(self, event):
        ceph_context = {
            'use_syslog':
                str(self.framework.model.config['use-syslog']).lower(),
            'loglevel': self.framework.model.config['loglevel']
        }
        ceph_context.update(self.ceph_client.get_pool_data())
        ceph_context['mon_hosts'] = ' '.join(ceph_context['mon_hosts'])

        restart_map = {
            '/etc/ceph/ceph.conf': ['rbd-target-api'],
            '/etc/ceph/iscsi-gateway.cfg': ['rbd-target-api'],
            '/etc/ceph/ceph.client.ceph-iscsi.keyring': ['rbd-target-api']}

        def daemon_reload_and_restart(service_name):
            subprocess.check_call(['systemctl', 'daemon-reload'])
            subprocess.check_call(['systemctl', 'restart', service_name])

        rfuncs = {
            'rbd-target-api': daemon_reload_and_restart}

        @ch_host.restart_on_change(restart_map, restart_functions=rfuncs)
        def render_configs():
            for config_file in restart_map.keys():
                ch_templating.render(
                    os.path.basename(config_file),
                    config_file,
                    ceph_context)
        render_configs()
        self.state.is_started = True
        self.model.unit.status = ActiveStatus('Unit is ready')


if __name__ == '__main__':
    main(CephISCSIGatewayCharm)
