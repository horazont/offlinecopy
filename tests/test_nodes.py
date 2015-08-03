import contextlib
import unittest
import unittest.mock

import fancysync.nodes as nodes


class Testrebase_rules(unittest.TestCase):
    def test_add_prefix(self):
        rules = [
            ("X", "A/B"),
            ("Y", "C"),
            ("/", "*"),
        ]

        self.assertSequenceEqual(
            list(nodes.rebase_rules("foo", rules)),
            [
                ("X", "foo/A/B"),
                ("Y", "foo/C"),
                ("/", "foo/*"),
            ]
        )


class TestNode(unittest.TestCase):
    class FakeNode(nodes.Node):
        pass

    def setUp(self):
        self.node = self.FakeNode("foo")

    def test_rejects_slashes_in_argument(self):
        with self.assertRaisesRegex(ValueError,
                                    "invalid file or directory name"):
            self.FakeNode("foo/bar")

    def test_rejects_NUL_in_argument(self):
        with self.assertRaisesRegex(ValueError,
                                    "invalid file or directory name"):
            self.FakeNode("foo\0bar")

    def test_rejects_empty_argument(self):
        with self.assertRaisesRegex(ValueError,
                                    "name must be non-empty string"):
            self.FakeNode("")

    def test_rejects_tuple(self):
        with self.assertRaisesRegex(ValueError,
                                    "name must be non-empty string"):
            self.FakeNode(("", "bar"))

    def test_accept_some_file_name(self):
        files = [
            "foo",
            "füchen",
            "∀x∈X"
        ]

        for filename in files:
            node = self.FakeNode(filename)
            self.assertEqual(
                node.name,
                filename
            )

    def test_childmap(self):
        self.assertDictEqual(
            self.node.childmap(),
            {
            }
        )

    def test_iter_child_rules(self):
        self.node.evict("foo")
        self.node.evict("bar")

        foo_node = self.node.childmap()["foo"]
        bar_node = self.node.childmap()["bar"]

        with contextlib.ExitStack() as stack:
            foo_rules = stack.enter_context(
                unittest.mock.patch.object(foo_node, "iter_rules")
            )
            bar_rules = stack.enter_context(
                unittest.mock.patch.object(bar_node, "iter_rules")
            )
            chain = stack.enter_context(
                unittest.mock.patch("itertools.chain")
            )
            rebase_rules = stack.enter_context(
                unittest.mock.patch("fancysync.nodes.rebase_rules")
            )

            rules = self.node.iter_child_rules()

        self.assertSequenceEqual(
            chain.mock_calls,
            [
                unittest.mock.call(
                    bar_rules(),
                    foo_rules(),
                ),
            ]
        )

        self.assertSequenceEqual(
            rebase_rules.mock_calls,
            [
                unittest.mock.call(
                    self.node.name,
                    chain()
                )
            ]
        )

        self.assertEqual(
            rules,
            rebase_rules()
        )

    def test_evict(self):
        self.node.evict("bar")

        childmap = self.node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("bar", childmap)

        node = childmap["bar"]

        self.assertIsInstance(
            node,
            nodes.EvictNode
        )

        self.assertEqual(
            node.name,
            "bar"
        )

    def test_evict_path(self):
        self.node.evict("bar/baz")

        childmap = self.node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("bar", childmap)

        node = childmap["bar"]

        self.assertIsInstance(
            node,
            nodes.EvictNode
        )

        self.assertEqual(
            node.name,
            "bar"
        )

        childmap = node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("baz", childmap)

        node = childmap["baz"]

        self.assertIsInstance(
            node,
            nodes.EvictNode
        )

        self.assertEqual(
            node.name,
            "baz"
        )

    def test_include(self):
        self.node.include("bar")

        childmap = self.node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("bar", childmap)

        node = childmap["bar"]

        self.assertIsInstance(
            node,
            nodes.IncludeNode
        )

        self.assertEqual(
            node.name,
            "bar"
        )

    def test_include_path(self):
        self.node.include("bar/baz")

        childmap = self.node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("bar", childmap)

        node = childmap["bar"]

        self.assertIsInstance(
            node,
            nodes.EvictNode
        )

        self.assertEqual(
            node.name,
            "bar"
        )

        childmap = node.childmap()
        self.assertEqual(len(childmap), 1)
        self.assertIn("baz", childmap)

        node = childmap["baz"]

        self.assertIsInstance(
            node,
            nodes.IncludeNode
        )

        self.assertEqual(
            node.name,
            "baz"
        )

    def test_include_raises_on_conflict_with_evict(self):
        self.node.evict("bar")
        with self.assertRaisesRegex(ValueError,
                                    "conflicts with eviction rule"):
            self.node.include("bar")

        self.node.include("bar/baz")

    def test_evict_raises_on_conflict_with_include(self):
        self.node.include("bar")
        with self.assertRaisesRegex(ValueError,
                                    "conflicts with inclusion rule"):
            self.node.evict("bar")


class TestEvictNode(unittest.TestCase):
    def setUp(self):
        self.node = nodes.EvictNode("foo")

    def test_is_Node(self):
        self.assertTrue(issubclass(
            nodes.EvictNode,
            nodes.Node
        ))

    def test_iter_rules(self):
        self.assertSequenceEqual(
            list(self.node.iter_rules()),
            [
                ("-", self.node.name)
            ]
        )

    def tearDown(self):
        del self.node


class TestIncludeNode(unittest.TestCase):
    def setUp(self):
        self.node = nodes.IncludeNode("foo")

    def test_is_Node(self):
        self.assertTrue(issubclass(
            nodes.IncludeNode,
            nodes.Node
        ))

    def test_iter_rules(self):
        self.assertSequenceEqual(
            list(self.node.iter_rules()),
            [
                ("+", self.node.name)
            ]
        )

    def tearDown(self):
        del self.node


class TestTarget(unittest.TestCase):
    def setUp(self):
        self.src = "host:/source/directory/"
        self.dest = "/destination/directory/"
        self.target = nodes.Target(
            self.src,
            self.dest
        )

    def test_init_attributes(self):
        self.assertEqual(
            self.target.src,
            self.src
        )

        self.assertEqual(
            self.target.dest,
            self.dest
        )

    def test_base_filter_rules(self):
        self.assertSequenceEqual(
            [
            ],
            list(self.target.iter_filter_rules())
        )

    def test_evict(self):
        self.assertSequenceEqual(
            list(self.target.iter_nodes()),
            [
            ]
        )

        self.target.evict(["A", "B"])

    def tearDown(self):
        del self.target
