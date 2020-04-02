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

A sample `bundle.yaml` file's contents:

```yaml
    series: focal
    applications:
      ceph-iscsi:
        charm: cs:ceph-iscsi
        num_units: 2
      ceph-osd:
        charm: cs:ceph-osd
        num_units: 3
        storage:
          osd-devices: /dev/vdb
        options:
          source: cloud:bionic-train
      ceph-mon:
        charm: cs:ceph-mon
        num_units: 3
        options:
          monitor-count: '3'
          source: cloud:bionic-train
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
    $ juju run-action ceph-iscsi/0 create-target \
        image-size=2G \
        image-name=bob \
        client-initiatorname=iqn.1993-08.org.debian:01:aaa2299be916 \
        client-username=usera \
        client-password=testpass
    Action queued with id: "28"
```

If the iqn of the created target is returned in the ouput from the action:

```bash
    $ juju show-action-output 28
    UnitId: ceph-iscsi/0
    results:
      iqn: iqn.2003-01.com.ubuntu.iscsi-gw:iscsi-igw
    status: completed
    timing:
      completed: 2020-04-02 13:32:02 +0000 UTC
      enqueued: 2020-04-02 13:18:42 +0000 UTC
      started: 2020-04-02 13:18:45 +0000 UTC
```

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

