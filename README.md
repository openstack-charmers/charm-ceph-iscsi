# Overview

The charm provides the Ceph iSCSI gateway service. It is intended to be used
in conjunction with the ceph-osd and ceph-mon charms.

> **Warning**: This charm is in a preview state for testing and should not
  be used outside of the lab.

# Usage

## Deployment

When deploying ceph-iscsi ensure that exactly two units of the charm are being
deployed, this will provide multiple data paths to clients. 

> **Note**: Deploying four units is also theoretical possible but has not
  been tested.

The charm cannot be placed in a lxd container. However, it can be located
with the ceph-osd charms. Co-location with other charms is likely to be
fine but is untested.

A sample `bundle.yaml` file's contents:

```yaml
    series: focal
    machines:
      '0':
      '1':
      '2':
    applications:
      ceph-iscsi:
        charm: cs:ceph-iscsi
        num_units: 2
        to:
        - '0'
        - '1'
      ceph-osd:
        charm: cs:ceph-osd
        num_units: 3
        storage:
          osd-devices: /dev/vdb
        to:
        - '0'
        - '1'
        - '2'
      ceph-mon:
        charm: cs:ceph-mon
        num_units: 3
        options:
          monitor-count: '3'
        to:
        - lxd:0
        - lxd:1
        - lxd:2
    relations:
    - - ceph-mon:client
      - ceph-iscsi:ceph-client
    - - ceph-osd:mon
      - ceph-mon:osd
```

> **Important**: Make sure the designated block device passed to the ceph-osd
  charms exists and is not currently in use.

Deploy the bundle:

    juju deploy ./bundle.yaml


## Managing Targets

The charm provides an action for creating a simple target. If more complex
managment of targets is requires then the `gwcli` tool should be used. `gwcli`
is available from the root account on the gateway nodes.

```bash
   $ juju ssh ceph-iscsi/1
   $ sudo gwcli
   /> ls
```

## Actions

This section covers Juju [actions][juju-docs-actions] supported by the charm.
Actions allow specific operations to be performed on a per-unit basis.

### create-target

Run this action to create an iscsi target.

```bash
    $ juju run-action --wait ceph-iscsi/0 create-target \
        image-size=2G \
        image-name=bob \
        pool-name=superssd \
        client-initiatorname=iqn.1993-08.org.debian:01:aaa2299be916 \
        client-username=usera \
        client-password=testpass
    unit-ceph-iscsi-0:
      UnitId: ceph-iscsi/0
      id: "28"
      results:
        iqn: iqn.2003-01.com.ubuntu.iscsi-gw:iscsi-igw
      status: completed
      timing:
        completed: 2020-05-08 09:49:52 +0000 UTC
        enqueued: 2020-05-08 09:49:36 +0000 UTC
        started: 2020-05-08 09:49:37 +0000 UTC

### pause

Pause the ceph-iscsi unit. This action will stop the rbd services.

### resume

Resume the ceph-iscsi unit. This action will start the rbd services if paused.

## Network spaces

This charm supports the use of Juju [network spaces][juju-docs-spaces] (Juju
`v.2.0`). This feature optionally allows specific types of the application's
network traffic to be bound to subnets that the underlying hardware is
connected to.

> **Note**: Spaces must be configured in the backing cloud prior to deployment.

The ceph-iscsi charm exposes the following traffic types (bindings):

- 'public' (front-side)
- 'cluster' (back-side)

For example, providing that spaces 'data-space' and 'cluster-space' exist, the
deploy command above could look like this:

    juju deploy --config ceph-iscsi.yaml -n 2 ceph-iscsi \
       --bind "public=data-space cluster=cluster-space"

Alternatively, configuration can be provided as part of a bundle:

```yaml
    ceph-iscsi:
      charm: cs:ceph-iscsi
      num_units: 2
      bindings:
        public: data-space
        cluster: cluster-space
```

# VMWare integration

1. Create ceph pool if required.

   To create a new pool to back the iscsi targets run the create-pool action
   from the ceph-mon charm.

```bash
   $ juju run-action --wait ceph-mon/0 create-pool name=iscsi-targets
   UnitId: ceph-mon/0
   results:
     Stderr: |
       pool 'iscsi-targets' created
       set pool 2 size to 3
       set pool 2 target_size_ratio to 0.1
       enabled application 'unknown' on pool 'iscsi-targets'
       set pool 2 pg_autoscale_mode to on
   status: completed
   timing:
     completed: 2020-04-08 06:42:00 +0000 UTC
     enqueued: 2020-04-08 06:41:38 +0000 UTC
     started: 2020-04-08 06:41:42 +0000 UTC
```

2. Collect the Initiator name for adapter.

   From the VMWare admin UI select the `Adapters` tab in the Storage
   context. Ensure `iSCSI enabled` is set to `Enabled`.

   Click 'Configure iSCSI' and take a note of the `iqn` name.

4. Create iSCSI target.

   Run the action to create a target for VMWare to use.

> **Note**: The username should be more than eight characters and the password
  between twelve and sixteen characters.

```bash
   $ juju run-action --wait ceph-iscsi/0 create-target \
       client-initiatorname="iqn.1998-01.com.vmware:node-caloric-02f98bac" \
       client-username=vmwareclient \
       client-password=12to16characters \
       image-size=10G \
       image-name=disk_1 \
       pool-name=iscsi-targets
   UnitId: ceph-iscsi/0
   results:
     Stdout: |
       Warning: Could not load preferences file /root/.gwcli/prefs.bin.
     iqn: iqn.2003-01.com.ubuntu.iscsi-gw:iscsi-igw
   status: completed
   timing:
     completed: 2020-04-08 06:58:34 +0000 UTC
     enqueued: 2020-04-08 06:58:15 +0000 UTC
     started: 2020-04-08 06:58:19 +0000 UTC
```

5. Add target to VMWare.

   Follow the [Ceph iSCSI Gateway][ceph-vmware] documentation to use the new
   target. Use CHAP username and password provided to the `create-target`
   action.

> **Warning**: As of the time of writing the workaround to set the CHAP
  credentials via the esx cli is still needed.

## Development

The charm needs to pull in its dependencies before it can be deployed. To
pull in the dependency versions that correspond to this version of the 
charm then run the `build` tox target.

To update all dependencies to their latest versions then run the `update-deps`
tox target.

<!-- LINKS -->

[cg]: https://docs.openstack.org/charm-guide
[cdg]: https://docs.openstack.org/project-deploy-guide/charm-deployment-guide
[juju-docs-spaces]: https://jaas.ai/docs/spaces
[juju-docs-actions]: https://jaas.ai/docs/actions
[ceph-vmware]: https://docs.ceph.com/docs/master/rbd/iscsi-initiator-esx/
