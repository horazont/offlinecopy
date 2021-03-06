import itertools
import os.path
import pathlib

from enum import Enum


def rebase_rules(prefix, rules):
    prefix += "/"
    for type_, path in rules:
        if path is None:
            yield type_, prefix.rstrip("/")
        else:
            yield type_, prefix+path


def path_split(path):
    parts = list(os.path.split(path))
    prev_lhs = None
    while parts[0] != prev_lhs:
        prev_lhs = parts[0]
        parts[:1] = os.path.split(parts[0])
    parts[0] = parts[0].rstrip("/")
    return tuple(part for part in parts if part)


class State(Enum):
    INCLUDED = "included"
    EVICTED = "evicted"


class Node:
    def __init__(self, parent=None):
        self.parent = parent
        self.childmap = {}
        self.state = None

    def get_state(self):
        if self.state is not None:
            return self.state
        if self.parent is not None:
            return self.parent.get_state()
        return State.INCLUDED

    def get_node(self, path):
        parts = path_split(path)
        node = self
        for i, part in enumerate(parts):
            try:
                node = node.childmap[part]
            except KeyError:
                return node, parts[i:]
        return node, ()

    def ensure_node(self, path):
        node, subpath = self.get_node(path)
        for part in subpath:
            node = node.childmap.setdefault(
                part,
                Node(parent=node)
            )
        return node

    def _iter_rules(self, parent_state):
        for segment, child in sorted(self.childmap.items(),
                                     key=lambda x: x[0]):
            yield from rebase_rules(
                segment,
                child._iter_rules(self.get_state())
            )

        if self.state == State.INCLUDED:
            if self.parent is not None:
                yield ("+", None)
        elif self.childmap and self.get_state() == State.EVICTED:
            yield ("-", "*")
            if     (self.parent is not None and
                    self.parent.get_state() == State.EVICTED):
                yield ("+", None)
        elif self.state == State.EVICTED:
            if self.parent is None:
                yield ("-", "*")
            else:
                yield ("-", None)

    def iter_rules(self):
        yield from self._iter_rules(State.INCLUDED)

    def iter_nodes(self):
        if self.state is not None:
            yield (self.state, None if self.parent is not None else "")
        for segment, child in sorted(self.childmap.items(),
                                     key=lambda x: x[0]):
            yield from rebase_rules(
                segment,
                child.iter_nodes()
            )

    def prune(self):
        for segment, child in list(self.childmap.items()):
            child.prune()
            if child.state == self.get_state() and not child.childmap:
                del self.childmap[segment]

    def clear(self):
        self.childmap.clear()
        self.state = None


class Target:
    def __init__(self, src, dest):
        self.src = src
        self.dest = pathlib.Path(dest)

        self.rules = Node()
        self.rules.state = State.EVICTED

    def iter_filter_rules(self):
        return self.rules.iter_rules()

    def iter_flat_nodes(self):
        return self.rules.iter_nodes()

    def get_state(self, path):
        return self.rules.get_node(path)[0].get_state()

    def evict(self, path):
        if self.get_state(path) == State.EVICTED:
            return
        node = self.rules.ensure_node(path)
        node.state = State.EVICTED

    def include(self, path):
        if self.get_state(path) == State.INCLUDED:
            return
        node = self.rules.ensure_node(path)
        node.state = State.INCLUDED

    def from_flat_nodes(self, flat_nodes):
        self.rules.clear()
        for state, path in flat_nodes:
            node = self.rules.ensure_node(path)
            node.state = state

    def prune(self):
        self.rules.prune()
