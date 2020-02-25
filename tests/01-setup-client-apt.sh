#!/bin/bash

client="ubuntu/0"

juju run --unit $client "apt install --yes open-iscsi multipath-tools"
juju run --unit $client "systemctl start iscsi"
juju run --unit $client "systemctl start iscsid"
