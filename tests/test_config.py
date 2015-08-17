import contextlib
import unittest
import unittest.mock

import lxml.etree

import offlinecopy.config as config
import offlinecopy.target as target


class Testextract_flat_nodes(unittest.TestCase):
    def test_find_flat_nodes(self):
        subtree = config.E.target(
            config.E.path(
                location="A",
                state="evicted"
            ),
            config.E.path(
                location="A/B/C",
                state="included"
            ),
            config.E.path(
                location="A/B/C/D",
                state="evicted"
            ),
            config.E.path(
                location="A/E",
                state="included"
            )
        )

        self.assertSequenceEqual(
            list(config.extract_flat_nodes(subtree)),
            [
                (target.State.EVICTED, "A"),
                (target.State.INCLUDED, "A/B/C"),
                (target.State.EVICTED, "A/B/C/D"),
                (target.State.INCLUDED, "A/E"),
            ]
        )


class Testembed_flat_nodes(unittest.TestCase):
    def test_embed_flat_nodes(self):
        flat_nodes = [
            (target.State.EVICTED, "A"),
            (target.State.INCLUDED, "A/B/C"),
            (target.State.EVICTED, "A/B/C/D"),
            (target.State.INCLUDED, "A/E"),
        ]

        subtree = config.E.target()

        config.embed_flat_nodes(
            subtree,
            flat_nodes
        )

        self.assertSequenceEqual(
            list(config.extract_flat_nodes(subtree)),
            flat_nodes
        )


class Testload_targets(unittest.TestCase):
    def test_load_targets_from_etree(self):
        target1 = config.E.target(
            src="foo",
            dest="bar",
        )

        target2 = config.E.target(
            src="baz",
            dest="fnord"
        )

        subtree = config.E.targets(
            target1,
            target2
        )

        base = unittest.mock.Mock()
        with contextlib.ExitStack() as stack:
            extract_flat_nodes = stack.enter_context(unittest.mock.patch(
                "offlinecopy.config.extract_flat_nodes",
                new=base.extract_flat_nodes,
            ))
            Target = stack.enter_context(unittest.mock.patch(
                "offlinecopy.target.Target",
                new=base.Target,
            ))

            targets = list(config.load_targets(subtree))

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.Target("foo", "bar"),
                unittest.mock.call.extract_flat_nodes(target1),
                unittest.mock.call.Target().from_flat_nodes(
                    extract_flat_nodes(),
                ),
                unittest.mock.call.Target("baz", "fnord"),
                unittest.mock.call.extract_flat_nodes(target2),
                unittest.mock.call.Target().from_flat_nodes(
                    extract_flat_nodes()
                )
            ]
        )

        self.assertSequenceEqual(
            targets,
            [
                base.Target(),
                base.Target(),
            ]
        )


class Testsave_targets(unittest.TestCase):
    def test_save_targets_to_etree(self):
        base = unittest.mock.Mock()

        target1 = base.target1
        target1.src = "foo"
        target1.dest = "bar"

        target2 = base.target2
        target2.src = "baz"
        target2.dest = "fnord"

        with contextlib.ExitStack() as stack:
            embed_flat_nodes = stack.enter_context(unittest.mock.patch(
                "offlinecopy.config.embed_flat_nodes",
                new=base.embed_flat_nodes
            ))
            E = stack.enter_context(unittest.mock.patch(
                "offlinecopy.config.E",
                new=base.E
            ))

            config.save_targets(base.parent_, [target1, target2])

        calls = list(base.mock_calls)
        self.assertSequenceEqual(
            calls,
            [
                unittest.mock.call.E.target(src="foo", dest="bar"),
                unittest.mock.call.target1.iter_flat_nodes(),
                unittest.mock.call.embed_flat_nodes(
                    E.target(),
                    target1.iter_flat_nodes()
                ),
                unittest.mock.call.parent_.append(E.target()),
                unittest.mock.call.E.target(src="baz", dest="fnord"),
                unittest.mock.call.target2.iter_flat_nodes(),
                unittest.mock.call.embed_flat_nodes(
                    E.target(),
                    target2.iter_flat_nodes()
                ),
                unittest.mock.call.parent_.append(E.target()),
            ]
        )
