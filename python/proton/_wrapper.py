#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

from cproton import pn_incref, pn_decref, \
    pn_py2void, pn_void2py, \
    pn_record_get, pn_record_def, pn_record_set, \
    PN_PYREF

from ._exceptions import ProtonException

from typing import Any, Callable, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from ._delivery import Delivery  # circular import
    from ._transport import SASL, Transport


class EmptyAttrs:

    def __contains__(self, name):
        return False

    def __getitem__(self, name):
        raise KeyError(name)

    def __setitem__(self, name, value):
        raise TypeError("does not support item assignment")


EMPTY_ATTRS = EmptyAttrs()


class Wrapper(object):
    """ Wrapper for python objects that need to be stored in event contexts and be retrived again from them
        Quick note on how this works:
        The actual *python* object has only 3 attributes which redirect into the wrapped C objects:
        _impl   The wrapped C object itself
        _attrs  This is a special pn_record_t holding a PYCTX which is a python dict
                every attribute in the python object is actually looked up here
        _record This is the C record itself (so actually identical to _attrs really but
                a different python type

        Because the objects actual attributes are stored away they must be initialised *after* the wrapping
        is set up. This is the purpose of the _init method in the wrapped  object. Wrapper.__init__ will call
        eht subclass _init to initialise attributes. So they *must not* be initialised in the subclass __init__
        before calling the superclass (Wrapper) __init__ or they will not be accessible from the wrapper at all.

    """

    def __init__(self, impl_or_constructor, get_context=None):
        init = False
        if callable(impl_or_constructor):
            # we are constructing a new object
            impl = impl_or_constructor()
            if impl is None:
                self.__dict__["_impl"] = impl
                self.__dict__["_attrs"] = EMPTY_ATTRS
                self.__dict__["_record"] = None
                raise ProtonException(
                    "Wrapper failed to create wrapped object. Check for file descriptor or memory exhaustion.")
            init = True
        else:
            # we are wrapping an existing object
            impl = impl_or_constructor
            pn_incref(impl)

        if get_context:
            record = get_context(impl)
            attrs = pn_void2py(pn_record_get(record, PYCTX))
            if attrs is None:
                attrs = {}
                pn_record_def(record, PYCTX, PN_PYREF)
                pn_record_set(record, PYCTX, pn_py2void(attrs))
                init = True
        else:
            attrs = EMPTY_ATTRS
            init = False
            record = None
        self.__dict__["_impl"] = impl
        self.__dict__["_attrs"] = attrs
        self.__dict__["_record"] = record
        if init:
            self._init()

    def __getattr__(self, name: str) -> Any:
        attrs = self.__dict__["_attrs"]
        if name in attrs:
            return attrs[name]
        else:
            raise AttributeError(name + " not in _attrs")

    def __setattr__(self, name: str, value: Any) -> None:
        if hasattr(self.__class__, name):
            object.__setattr__(self, name, value)
        else:
            attrs = self.__dict__["_attrs"]
            attrs[name] = value

    def __delattr__(self, name: str) -> None:
        attrs = self.__dict__["_attrs"]
        if attrs:
            del attrs[name]

    def __hash__(self) -> int:
        return hash(addressof(self._impl))

    def __eq__(self, other):
        if isinstance(other, Wrapper):
            return addressof(self._impl) == addressof(other._impl)
        return False

    def __ne__(self, other: Any) -> bool:
        if isinstance(other, Wrapper):
            return addressof(self._impl) != addressof(other._impl)
        return True

    def __del__(self) -> None:
        pn_decref(self._impl)

    def __repr__(self) -> str:
        return '<%s.%s 0x%x ~ 0x%x>' % (self.__class__.__module__,
                                        self.__class__.__name__,
                                        id(self), addressof(self._impl))


PYCTX = int(pn_py2void(Wrapper))
addressof = int
