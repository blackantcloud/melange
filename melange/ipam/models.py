# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http: //www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
SQLAlchemy models for Melange data
"""
import netaddr
from netaddr import IPNetwork, IPAddress
from melange.common.exception import MelangeError
from melange.db import api as db_api


class ModelBase(object):
    @classmethod
    def create(cls, values):
        instance = cls(values)
        return instance.save()

    def save(self):
        self.validate()
        return db_api.save(self)

    def delete(self):
        db_api.delete(self)

    def __init__(self, values):
        self.update(values)

    def validate(self):
        if not self.is_valid():
            raise InvalidModelError(self.errors)

    def is_valid(self):
        return True

    @classmethod
    def find(cls, id):
        model = cls.find_by_id(id)
        if model == None:
            raise ModelNotFoundError("%s Not Found" % cls.__name__)
        return model

    @classmethod
    def find_by_id(cls, id):
        return db_api.find(cls, id)

    def update(self, values):
        """dict.update() behaviour."""
        for k, v in values.iteritems():
            self[k] = v

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        self._i = iter(db_api.columns_of(self))
        return self

    def __eq__(self, other):
        if not hasattr(other, 'id'):
            return False
        return type(other) == type(self) and other.id == self.id

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def keys(self):
        return self.__dict__.keys()

    def values(self):
        return self.__dict__.values()

    def items(self):
        return self.__dict__.items()

    def to_dict(self):
        return self.__dict__()

    def data(self):
        return dict([(field, self[field])
                    for field in self.data_fields()])

    def data_fields(self):
        return []


class IpBlock(ModelBase):

    @classmethod
    def find_by_network_id(cls, network_id):
        return db_api.find_by(cls, network_id=network_id)

    @classmethod
    def find_or_allocate_ip(cls, ip_block_id, address):
        block = IpBlock.find(ip_block_id)
        allocated_ip = IpAddress.find_by_block_and_address(block.id, address)

        if allocated_ip and allocated_ip.locked():
            raise AddressLockedError()

        return (allocated_ip or block.allocate_ip(address=address))

    @classmethod
    def find_all(cls, **kwargs):
        return db_api.find_all_by(cls, **kwargs).all()

    @classmethod
    def allowed_by_policy(cls, ip_block, policy, address):
        return policy == None or policy.allows(ip_block.cidr, address)

    def policy(self, eager_load_rules=False):
        policy = Policy.find_by_id(self.policy_id)
        if policy == None:
            return None
        if eager_load_rules:
            policy.eager_load()
        return policy

    def allocate_ip(self, port_id=None, address=None):
        candidate_ip = None
        allocated_addresses = [ip_addr.address
                               for ip_addr in
                               IpAddress.find_all_by_ip_block(self.id)]

        candidate_ip = self._check_address(address, allocated_addresses) or \
                       self._generate_ip(allocated_addresses)

        if not candidate_ip:
            raise NoMoreAddressesError("IpBlock is full")

        return IpAddress({'address': candidate_ip, 'port_id': port_id,
                          'ip_block_id': self.id}).save()

    def _check_address(self, address, allocated_addresses):

        if not address:
            return

        if address in allocated_addresses:
            raise DuplicateAddressError()

        if netaddr.IPAddress(address) not in IPNetwork(self.cidr):
            raise AddressDoesNotBelongError(
                "Address does not belong to IpBlock")

        policy = self.policy(eager_load_rules=True)
        if not IpBlock.allowed_by_policy(self, policy, address):
            raise AddressDisallowedByPolicyError(
                "Block policy does not allow this address")

        return address

    def _generate_ip(self, allocated_addresses):
        #TODO: very inefficient way to generate ips,
        #will look at better algos for this
        policy = self.policy(eager_load_rules=True)
        for ip in IPNetwork(self.cidr):
            if IpBlock.allowed_by_policy(self, policy, str(ip)) and (str(ip)
                                                   not in allocated_addresses):
                return str(ip)
        return None

    def find_allocated_ip(self, address):
        ip_address = IpAddress.find_by_block_and_address(self.id, address)
        if ip_address == None:
            raise ModelNotFoundError("IpAddress Not Found")
        return ip_address

    def deallocate_ip(self, address):
        ip_address = IpAddress.find_by_block_and_address(self.id, address)
        if ip_address != None:
            ip_address.deallocate()

    def validate_cidr(self):
        try:
            IPNetwork(self.cidr)
        except Exception:
            self.errors.append({'cidr': 'cidr is invalid'})

    def validate_uniqueness_for_public_ip_block(self):
        if self.type == 'public' and \
        db_api.find_by(IpBlock, type=self.type, cidr=self.cidr):
            self.errors.append({'cidr': 'cidr for public ip is not unique'})

    def is_valid(self):
        self.errors = []
        self.validate_cidr()
        self.validate_uniqueness_for_public_ip_block()
        return self.errors == []

    def data_fields(self):
        return ['id', 'cidr', 'network_id']


class IpAddress(ModelBase):

    @classmethod
    def find_all_by_ip_block(cls, ip_block_id, **kwargs):
        return db_api.find_all_by(IpAddress, ip_block_id=ip_block_id, **kwargs)

    @classmethod
    def find_by_block_and_address(cls, ip_block_id, address):
        return db_api.find_by(IpAddress, ip_block_id=ip_block_id,
                              address=address)

    @classmethod
    def delete_deallocated_addresses(self):
        return db_api.delete_deallocated_addresses()

    def add_inside_locals(self, ip_addresses):
        return db_api.save_nat_relationships([
            {"inside_global_address_id": self.id,
             "inside_local_address_id": local_address.id}
            for local_address in ip_addresses])

    def deallocate(self):
        self.update({"marked_for_deallocation": True})
        return self.save()

    def restore(self):
        self.update({"marked_for_deallocation": False})
        self.save()

    def inside_globals(self, **kwargs):
        return db_api.find_inside_globals_for(self.id, **kwargs)

    def add_inside_globals(self, ip_addresses):
        return db_api.save_nat_relationships([
            {"inside_global_address_id": global_address.id,
             "inside_local_address_id": self.id}
            for global_address in ip_addresses])

    def inside_locals(self, **kwargs):
        return db_api.find_inside_locals_for(self.id, **kwargs)

    def remove_inside_globals(self, inside_global_address=None):
        return db_api.remove_inside_globals(self.id, inside_global_address)

    def remove_inside_locals(self, inside_local_address=None):
        return db_api.remove_inside_locals(self.id, inside_local_address)

    def locked(self):
        return self.marked_for_deallocation

    def data_fields(self):
        return ['id', 'ip_block_id', 'address', 'port_id']


class Policy(ModelBase):

    @classmethod
    def find_by_name(cls, name):
        return db_api.find_by(Policy, name=name)

    def ip_rules(self):
        if hasattr(self, 'ip_range_rules'):
            return self.ip_range_rules
        return self._find_ip_range_rules()

    def allows(self, cidr, address):
        return not any(ip_rule.contains(cidr, address)
                       for ip_rule in self.ip_rules())

    def eager_load(self):
        self._load_ip_range_rules()
        return self

    def _load_ip_range_rules(self):
        self.ip_range_rules = self._find_ip_range_rules()

    def _find_ip_range_rules(self):
        return IpRange.find_all_by_policy(self.id).all()


class IpRange(ModelBase):

    @classmethod
    def find_all_by_policy(cls, policy_id):
        return db_api.find_all_by(cls, policy_id=policy_id)

    def contains(self, cidr, address):
        end_index = self.offset + self.length
        end_index_overshoots_length_for_negative_offset = (self.offset < 0
                                                           and end_index >= 0)
        if end_index_overshoots_length_for_negative_offset:
            end_index = None
        return IPAddress(address) in IPNetwork(cidr)[self.offset:end_index]


def models():
    return {'IpBlock': IpBlock, 'IpAddress': IpAddress, 'Policy': Policy,
            'IpRange': IpRange}


class NoMoreAddressesError(MelangeError):

    def _error_message(self):
        return "no more addresses"


class DuplicateAddressError(MelangeError):

    def _error_message(self):
        return "Address is already allocated"


class AddressDoesNotBelongError(MelangeError):

    def _error_message(self):
        return "Address does not belong here"


class AddressLockedError(MelangeError):

    def _error_message(self):
        return "Address is locked"


class ModelNotFoundError(MelangeError):

    def _error_message(self):
        return "Not Found"


class AddressDisallowedByPolicyError(MelangeError):

    def _error_message(self):
        return "Policy does not allow this address"


class InvalidModelError(MelangeError):

    def __init__(self, errors, message=None):
        self.errors = errors
        super(InvalidModelError, self).__init__(message)

    def __str__(self):
        return "The following values are invalid: %s" % str(self.errors)

    def _error_message(self):
        return str(self)