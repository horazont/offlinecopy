import lxml.builder

from . import target


xmlns_1_0 = "https://xmlns.zombofant.net/fancysync/targets/1.0/"


E = lxml.builder.ElementMaker(namespace=xmlns_1_0)


def extract_flat_nodes(subtree):
    for path in subtree.iterchildren("{{{}}}path".format(xmlns_1_0)):
        yield target.State(path.get("state")), path.get("location")


def embed_flat_nodes(parent, nodes):
    for state, path in nodes:
        parent.append(E.path(state=state.value,
                             location=path))


def load_targets(subtree):
    for target_el in subtree.iterchildren("{{{}}}target".format(xmlns_1_0)):
        t = target.Target(
            target_el.get("src"),
            target_el.get("dest")
        )
        t.from_flat_nodes(extract_flat_nodes(target_el))
        yield t


def save_targets(parent, targets):
    for t in targets:
        el = E.target(src=t.src, dest=str(t.dest))
        embed_flat_nodes(el, t.iter_flat_nodes())
        parent.append(el)
