Ceph iSCSI Gateway charm
========================

To use, first pull in dependencies:

```bash
./charm-prep.sh
```

To deploy with an example and test:

```bash
cd test
./deploy.sh
./01-setup-client-apt.sh
./02-setup-gw.sh
./03-setup-client-iscsi.sh
```

To run the charm tests (tested on OpenStack provider):
tox -e func-smoke
