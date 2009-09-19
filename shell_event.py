
# Copyright (C) 2009 Mark Seaborn
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301 USA.


class EventDistributor(object):

    def __init__(self):
        self._callbacks = []

    def add(self, callback):
        def remover():
            self._callbacks.remove(callback)
        self._callbacks.append(callback)
        return remover

    def send(self, *args):
        for callback in self._callbacks[:]:
            callback(*args)


class ObservableCell(object):

    def __init__(self, value):
        self._on_change = EventDistributor()
        self.add_observer = self._on_change.add
        self._value = value

    def set(self, value):
        self._value = value
        self._on_change.send()

    def get(self):
        return self._value


class ObservableRedirector(object):

    def __init__(self, obs):
        self._on_change = EventDistributor()
        self.add_observer = self._on_change.add
        self._remove_old = lambda: None
        self.set(obs)

    def set(self, obs):
        self._remove_old()
        def on_change():
            self._value = obs.get()
            self._on_change.send()
        on_change()
        self._remove_old = obs.add_observer(on_change)

    def get(self):
        return self._value
