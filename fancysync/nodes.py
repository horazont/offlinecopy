import itertools
import os.path


def rebase_rules(prefix, rules):
    prefix += "/"
    for type_, path in rules:
        yield type_, prefix+path


class Node:
    def __init__(self, name):
        if not name or not isinstance(name, str):
            raise ValueError("name must be non-empty string")
        if "/" in name or "\0" in name:
            raise ValueError("invalid file or directory name")
        self.name = name

        self._childmap = {}

    def childmap(self):
        return self._childmap

    def evict(self, name):
        parts = os.path.split(name)
        if parts[0] == "":
            parts = parts[1:]
        node = EvictNode(parts[0])
        self._childmap[parts[0]] = node
        if len(parts) > 1:
            node.evict(os.path.join(*parts[1:]))

    def include(self, name):
        parts = os.path.split(name)
        if parts[0] == "":
            parts = parts[1:]

        if len(parts) > 1:
            evict_node = self._childmap.setdefault(
                parts[0],
                EvictNode(parts[0]))
            evict_node.include(os.path.join(*parts[1:]))
        else:
            try:
                existing = self._childmap[parts[0]]
            except KeyError:
                self._childmap[parts[0]] = IncludeNode(parts[0])
            else:
                if not isinstance(existing, IncludeNode):
                    raise ValueError("conflicts with eviction rule")

    def iter_child_rules(self):
        children = sorted(self._childmap.values(), key=lambda x: x.name)

        return rebase_rules(
            self.name,
            itertools.chain(
                *(child.iter_rules()
                  for child in children)
            )
        )


class EvictNode(Node):
    def iter_rules(self):
        yield ("-", self.name)


class IncludeNode(Node):
    def iter_rules(self):
        yield ("+", self.name)


class Target:
    def __init__(self, src, dest):
        self.src = src
        self.dest = dest

    def iter_filter_rules(self):
        return iter([])

    def evict(self, path):
        pass
