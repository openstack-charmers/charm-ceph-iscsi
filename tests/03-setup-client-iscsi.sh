#!/bin/bash

client="ubuntu/0"

gw1="ceph-iscsi/0"

gw1_ip=$(juju status $gw1 --format=oneline | awk '{print $3}' | tr -d \\n )

juju run --unit $client "iscsiadm -m discovery -t st -p $gw1_ip"

target_name="iqn.2003-01.com.canonical.iscsi-gw:iscsi-igw"

juju run --unit $client "iscsiadm --mode node --targetname ${target_name} --op=update --name node.session.auth.authmethod --value=CHAP"
juju run --unit $client "iscsiadm --mode node --targetname ${target_name} --op=update --name node.session.auth.username --value=myiscsiusername"
juju run --unit $client "iscsiadm --mode node --targetname ${target_name} --op=update --name node.session.auth.password --value=myiscsipassword"
juju run --unit $client "iscsiadm --mode node --targetname ${target_name} --login"
sleep 5
juju ssh ubuntu/0 "ls -l /dev/dm-0"
