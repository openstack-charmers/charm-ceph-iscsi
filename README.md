# Overview

The ceph-iscsi charm deploys the [Ceph iSCSI gateway
service][ceph-iscsi-upstream]. The charm is intended to be used in conjunction
with the [ceph-osd][ceph-osd-charm] and [ceph-mon][ceph-mon-charm] charms.

> **Warning**: This charm is in a preview state and should not be used in
  production. See the [OpenStack Charm Guide][cg-preview-charms] for more
  information on preview charms.

# Usage

## Configuration

See file `config.yaml` for the full list of options, along with their
descriptions and default values.

## Deployment

We are assuming a pre-existing Ceph cluster.

To provide multiple data paths to clients deploy exactly two ceph-iscsi units:

    juju deploy -n 2 cs:~openstack-charmers-next/ceph-iscsi

Then add a relation to the ceph-mon application:

    juju add-relation ceph-iscsi:ceph-client ceph-mon:client

**Notes**:

* Deploying four ceph-iscsi units is theoretical possible but it is not an
  officially supported configuration.
* The ceph-iscsi application cannot be containerised.
* Co-locating ceph-iscsi with another application is only supported with
  ceph-osd, although doing so with other applications may still work.

## Actions

This section covers Juju [actions][juju-docs-actions] supported by the charm.
Actions allow specific operations to be performed on a per-unit basis.

* `add-trusted-ip`
* `create-target`
* `pause`
* `resume`
* `security-checklist`

To display action descriptions run `juju actions ceph-iscsi`. If the charm is
not deployed then see file `actions.yaml`.

## iSCSI target management

### Create an iSCSI target

An iSCSI target can be created easily with the charm's `create-target` action:

    juju run-action --wait ceph-iscsi/0 create-target \
       client-initiatorname=iqn.1993-08.org.debian:01:aaa2299be916 \
       client-username=myiscsiusername \
       client-password=myiscsipassword \
       image-size=5G \
       image-name=small \
       pool-name=images

In the above, all option values are generally user-defined with the exception
of the initiator name (`client-initiatorname`). An iSCSI initiator is
essentially an iSCSI client and so its name is client-dependent. Some
initiators may impose policy on credentials (`client-username` and
`client-password`).

> **Important**: The underlying machines for the ceph-iscsi units must have
  internal name resolution working (i.e. the machines must be able to resolve
  each other's hostnames).

### The `gwcli` utility

The management of targets, beyond the target-creation action described above,
can be accomplished via the `gwcli` utility. This CLI tool has its own shell,
and is available from any ceph-iscsi unit:

    juju ssh ceph-iscsi/1
    sudo gwcli
    /> help

## VMWare integration

Ceph can be used to back iSCSI targets for VMWare initiators.

Begin by accessing the VMWare admin web UI.

These instructions were written using VMWare ESXi 6.7.0.

### Create a Ceph pool

If desired, create a Ceph pool to back the VMWare targets with the ceph-mon
charm's `create-pool` action:

    juju run-action --wait ceph-mon/0 create-pool name=vmware-iscsi

### Enable the initiator

From the web UI select the `Adapters` tab in the `Storage` context. Click
`Configure iSCSI` and enable iSCSI.

Take a note of the initiator name, or UID. Here the UID we'll use is
`iqn.1998-01.com.vmware:node-gadomski-6a5e962a`.

### Create an iSCSI target

With the `create-target` action create a target for VMWare to use. Use the pool
that may have been created previously:

    juju run-action --wait ceph-iscsi/0 create-target \
       client-initiatorname=iqn.1998-01.com.vmware:node-gadomski-6a5e962a \
       client-username=vmwareclient \
       client-password=12to16characters \
       image-size=5G \
       image-name=disk-1 \
       pool-name=vmware-iscsi

> **Note**: VMWare imposes a policy on credentials. The username should be more
  than eight characters and the password between twelve and sixteen characters.

### Add a target to VMWare

Follow the [Ceph iSCSI gateway for VMWare][ceph-iscsi-vmware-upstream]
documentation to use the new target. Use the (CHAP) username and password
passed to the `create-target` action.

When finished, under the `Devices` tab you should see the created target. To
make more devices available to VMWare simply create more targets (use a
different image name and optionally a different image size). You will need to
`Rescan` and `Refresh` for the new devices to appear.

> **Note**: At the time of writing, the redundant task of setting the
  credentials via the ESX CLI is still a necessity. This will require you to
  enable SSH under `Manage` > `Services` > `TSM-SSH` > `Actions` (Start).

<!--

# Bugs

Please report bugs on [Launchpad][lp-bugs-charm-ceph-iscsi].

For general charm questions refer to the [OpenStack Charm Guide][cg].

-->

<!-- LINKS -->

[ceph-mon-charm]: https://jaas.ai/ceph-mon
[ceph-osd-charm]: https://jaas.ai/ceph-osd
[cg]: https://docs.openstack.org/charm-guide
[cg-preview-charms]: https://docs.openstack.org/charm-guide/latest/openstack-charms.html#tech-preview-charms-beta
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide
[juju-docs-actions]: https://jaas.ai/docs/actions
[ceph-iscsi-upstream]: https://docs.ceph.com/docs/master/rbd/iscsi-overview/
[ceph-iscsi-vmware-upstream]: https://docs.ceph.com/docs/master/rbd/iscsi-initiator-esx/
[lp-bugs-charm-ceph-iscsi]: https://bugs.launchpad.net/charm-ceph-iscsi/+filebug
