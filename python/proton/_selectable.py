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

from ._events import Event
from ._io import PN_INVALID_SOCKET

from typing import Callable, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from ._events import EventType
    from ._handlers import ConnectSelectable
    from ._reactor import Container, EventInjector, TimerSelectable
    from socket import socket


class Selectable(object):

    def __init__(self, delegate, reactor):
        self._delegate = delegate
        self.reading = False
        self.writing = False
        self._deadline = 0
        self._terminal = False
        self._released = False
        self._terminated = False
        self._reactor = reactor
        self.push_event(self, Event.SELECTABLE_INIT)

    def close(self) -> None:
        if self._delegate and not self._released:
            self._delegate.close()

    def fileno(self) -> int:
        if self._delegate:
            return self._delegate.fileno()
        else:
            return PN_INVALID_SOCKET

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def _get_deadline(self):
        tstamp = self._deadline
        if tstamp:
            return tstamp
        else:
            return None

    def _set_deadline(self, deadline):
        if not deadline:
            self._deadline = 0
        else:
            self._deadline = deadline

    deadline = property(_get_deadline, _set_deadline)

    def push_event(self, context, etype):
        self._reactor.push_event(context, etype)

    def update(self) -> None:
        if not self._terminated:
            if self._terminal:
                self._terminated = True
                self.push_event(self, Event.SELECTABLE_FINAL)
            else:
                self.push_event(self, Event.SELECTABLE_UPDATED)

    def readable(self) -> None:
        self.push_event(self, Event.SELECTABLE_READABLE)

    def writable(self) -> None:
        self.push_event(self, Event.SELECTABLE_WRITABLE)

    def expired(self) -> None:
        self.push_event(self, Event.SELECTABLE_EXPIRED)

    @property
    def is_terminal(self) -> bool:
        return self._terminal

    def terminate(self) -> None:
        self._terminal = True

    def release(self) -> None:
        self._released = True
