# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import hashlib
from netaddr import IPNetwork, IPAddress, EUI


class DefaultIpV6Generator(object):
    def __init__(self, cidr, tenant_id, mac_address):
        self.cidr = cidr
        self.tenant_id = tenant_id
        self.mac_address = mac_address

    def next_ip(self):
        address = self._deduce_ip_address()
        self.mac_address = int(EUI(self.mac_address)) + 1
        return address

    def _deduce_ip_address(self):
        variable_segment = self._variable_segment()
        network = IPNetwork(self.cidr)
        return str(variable_segment & network.hostmask | network.cidr.ip)

    def _variable_segment(self):
        tenant_hash = hashlib.sha1(self.tenant_id).hexdigest()
        first_2_segments = int(tenant_hash[:8], 16) << 32
        constant = 0xff << 24
        ei_mac_address = int(EUI(self.mac_address)) & int("ffffff", 16)
        last_2_segments = constant | ei_mac_address
        return IPAddress(first_2_segments | last_2_segments)