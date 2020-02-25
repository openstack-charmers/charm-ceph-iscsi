#!/bin/bash -x

gw1="ceph-iscsi/0"
gw2="ceph-iscsi/1"

gw1_hostname=$(juju run --unit $gw1 "hostname -f")
gw2_hostname=$(juju run --unit $gw2 "hostname -f")
gw1_ip=$(juju status $gw1 --format=oneline | awk '{print $3}' | tr -d \\n )
gw2_ip=$(juju status $gw2 --format=oneline | awk '{print $3}' | tr -d \\n )
client_initiatorname=$(juju run --unit ubuntu/0 "grep -E '^InitiatorName' /etc/iscsi/initiatorname.iscsi")
client_initiatorname=$(echo $client_initiatorname | awk 'BEGIN {FS="="} {print $2}')
echo "!$gw1_hostname!"
echo "!$gw2_hostname!"
echo "!$gw1_ip!"
echo "!$gw2_ip!"
echo "!$client_initiatorname!"

gw_iqn="iqn.2003-01.com.canonical.iscsi-gw:iscsi-igw"

juju run --unit $gw1 "gwcli /iscsi-targets/ create $gw_iqn"
juju run --unit $gw1 "gwcli /iscsi-targets/${gw_iqn}/gateways create $gw1_hostname $gw1_ip skipchecks=true"
juju run --unit $gw1 "gwcli /iscsi-targets/${gw_iqn}/gateways create $gw2_hostname $gw2_ip skipchecks=true"
juju run --unit $gw1 "gwcli /disks create pool=rbd image=disk_1 size=1G"
juju run --unit $gw1 "gwcli /iscsi-targets/${gw_iqn}/hosts create ${client_initiatorname}"
juju run --unit $gw1 "gwcli /iscsi-targets/${gw_iqn}/hosts/${client_initiatorname} auth username=myiscsiusername password=myiscsipassword"
juju run --unit $gw1 "gwcli /iscsi-targets/${gw_iqn}/hosts/${client_initiatorname} disk add rbd/disk_1"
