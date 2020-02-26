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
    MaintenanceStatus,
    WaitingStatus,
)
from charmhelpers.fetch import (
    apt_install,
    apt_update,
)
import charmhelpers.contrib.openstack.utils as os_utils
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

    RESTART_MAP = {
        '/etc/ceph/ceph.conf': ['rbd-target-api'],
        '/etc/ceph/iscsi-gateway.cfg': ['rbd-target-api'],
        '/etc/ceph/ceph.client.ceph-iscsi.keyring': ['rbd-target-api']}

    def __init__(self, framework, key):
        super().__init__(framework, key)
        self.state.set_default(is_started=False)
        self.state.set_default(is_paused=False)
        self.framework.observe(self.on.install, self)
        self.framework.observe(self.on.update_status, self)
        self.framework.observe(self.on.ceph_client_relation_joined, self)
        self.ceph_client = interface_ceph_client.CephClientRequires(
            self,
            'ceph-client')
        self.framework.observe(self.ceph_client.on.pools_available, self)
        self.framework.observe(self.on.pause_action, self)

    def on_install(self, event):
        apt_update(fatal=True)
        apt_install(self.PACKAGES, fatal=True)

    def update_status(self):
        if self.state.is_paused:
            self.model.unit.status = MaintenanceStatus(
                "Paused. Use 'resume' action to resume normal service.")
            return
        if self.state.is_started:
            self.model.unit.status = ActiveStatus('Unit is ready')
        else:
            self.model.unit.status = WaitingStatus('not ready for reasons')

    def on_update_status(self, event):
        self.update_status()

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


        def daemon_reload_and_restart(service_name):
            subprocess.check_call(['systemctl', 'daemon-reload'])
            subprocess.check_call(['systemctl', 'restart', service_name])

        rfuncs = {
            'rbd-target-api': daemon_reload_and_restart}

        @ch_host.restart_on_change(self.RESTART_MAP, restart_functions=rfuncs)
        def render_configs():
            for config_file in restart_map.keys():
                ch_templating.render(
                    os.path.basename(config_file),
                    config_file,
                    ceph_context)
        render_configs()
        self.state.is_started = True
        self.update_status()

    def services(self):
        _svcs = []
        for svc in self.RESTART_MAP.values():
            _svcs.extend(svc)
        return list(set(_svcs))

    def on_pause_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'pause',
            services=self.services(),
            charm_func=None)
        self.state.is_paused = True
        self.update_status()

    def on_resume_action(self, event):
        _, messages = os_utils.manage_payload_services(
            'resume',
            services=self.services(),
            charm_func=None)
        self.state.is_paused = False
        self.update_status()

if __name__ == '__main__':
    main(CephISCSIGatewayCharm)
