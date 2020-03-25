import json
from ops.framework import (
    Object,
)


class TlsRequires(Object):
    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.name = self.relation_name = key

    def request_application_cert(self, cn, sans):
        """
        Request a client certificate and key be generated for the given
        common name (`cn`) and list of alternative names (`sans`).

        This can be called multiple times to request more than one client
        certificate, although the common names must be unique.  If called
        again with the same common name, it will be ignored.
        """
        relations = self.framework.model.relations[self.name]
        if not relations:
            return
        # assume we'll only be connected to one provider
        relation = relations[0]
        unit = self.framework.model.unit
        requests = relation.data[unit].get('application_cert_requests', '{}')
        requests = json.loads(requests)
        requests[cn] = {'sans': sans}
        relation.data[unit]['application_cert_requests'] = json.dumps(
            requests,
            sort_keys=True)

    @property
    def root_ca_cert(self):
        """
        Root CA certificate.
        """
        # only the leader of the provider should set the CA, or all units
        # had better agree
        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if relation.data[unit].get('ca'):
                    return relation.data[unit].get('ca')

    @property
    def chain(self):
        """
        Root CA certificate.
        """
        # only the leader of the provider should set the CA, or all units
        # had better agree
        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if relation.data[unit].get('chain'):
                    return relation.data[unit].get('chain')

    @property
    def server_certs(self):
        """
        List of [Certificate][] instances for all available server certs.
        """
        unit_name = self.framework.model.unit.name.replace('/', '_')
        field = '{}.processed_requests'.format(unit_name)

        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if field not in relation.data[unit]:
                    continue
                certs_data = relation.data[unit][field]
                if not certs_data:
                    continue
                certs_data = json.loads(certs_data)
                if not certs_data:
                    continue
                return list(certs_data.values())[0]

    @property
    def client_certs(self):
        """
        List of [Certificate][] instances for all available client certs.
        """
        unit_name = self.framework.model.unit.name.replace('/', '_')
        field = '{}.processed_client_requests'.format(unit_name)

        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if field not in relation.data[unit]:
                    continue
                certs_data = relation.data[unit][field]
                if not certs_data:
                    continue
                certs_data = json.loads(certs_data)
                if not certs_data:
                    continue
                return list(certs_data.values())[0]

    @property
    def application_certs(self):
        """
        List of [Certificate][] instances for all available application certs.
        """
        unit_name = self.framework.model.unit.name.replace('/', '_')
        field = '{}.processed_application_requests'.format(unit_name)

        for relation in self.framework.model.relations[self.name]:
            for unit in relation.units:
                if field not in relation.data[unit]:
                    continue
                certs_data = relation.data[unit][field]
                if not certs_data:
                    continue
                certs_data = json.loads(certs_data)
                if not certs_data:
                    continue
                return certs_data['app_data']
