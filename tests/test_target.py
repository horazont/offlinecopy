import contextlib
import os.path
import unittest
import unittest.mock

import offlinecopy_impl.target as target


class Testrebase_rules(unittest.TestCase):
    def test_add_prefix(self):
        rules = [
            ("X", "A/B"),
            ("Y", "C"),
            ("/", "*"),
            ("F", None)
        ]

        self.assertSequenceEqual(
            list(target.rebase_rules("foo", rules)),
            [
                ("X", "foo/A/B"),
                ("Y", "foo/C"),
                ("/", "foo/*"),
                ("F", "foo"),
            ]
        )


class Testpath_split(unittest.TestCase):
    def test_splits_deep_paths(self):
        self.assertEqual(
            ("A", "B", "C"),
            target.path_split(os.path.join("A", "B", "C")),
        )

    def test_split_root_path(self):
        self.assertEqual(
            ("A", "B", "C"),
            target.path_split("/A/B/C/"),
        )


class TestNode(unittest.TestCase):
    def setUp(self):
        self.n1 = target.Node()
        self.n2 = target.Node(parent=self.n1)
        self.n1.childmap["foo"] = self.n2
        self.n3 = target.Node(parent=self.n2)
        self.n2.childmap["bar"] = self.n3

        self.n1.state = target.State.INCLUDED
        self.n2.state = target.State.EVICTED

    def test_get_state(self):
        self.assertEqual(
            self.n3.get_state(),
            target.State.EVICTED
        )
        self.assertEqual(
            self.n2.get_state(),
            target.State.EVICTED
        )
        self.assertEqual(
            self.n1.get_state(),
            target.State.INCLUDED
        )

    def test_get_node(self):
        self.assertEqual(
            self.n1.get_node("foo/bar"),
            (self.n3, ()),
        )

        self.assertEqual(
            self.n1.get_node("foo/bar/baz"),
            (self.n3, ("baz",)),
        )

        self.assertEqual(
            self.n1.get_node("foo/bar/"),
            (self.n3, ()),
        )

        self.assertEqual(
            self.n1.get_node("bar/"),
            (self.n1, ("bar",)),
        )

        self.assertEqual(
            self.n1.get_node("foo/"),
            (self.n2, ()),
        )

        self.assertEqual(
            self.n1.get_node(""),
            (self.n1, ()),
        )

        self.assertEqual(
            self.n1.get_node("/"),
            (self.n1, ()),
        )

    def test_ensure_node(self):
        self.assertIs(
            self.n1.ensure_node("foo/bar/"),
            self.n3
        )

        new_node = self.n1.ensure_node("foo/bar/baz")
        self.assertIs(new_node.parent, self.n3)
        self.assertIs(self.n3.childmap["baz"], new_node)

        new_node = self.n1.ensure_node("bar/baz")
        parent_node = new_node.parent
        self.assertIs(parent_node.parent, self.n1)
        self.assertIs(self.n1.childmap["bar"], parent_node)
        self.assertIs(new_node.parent, parent_node)
        self.assertIs(parent_node.childmap["baz"], new_node)

    def test_prune_includes_in_included(self):
        nroot = target.Node()
        n1 = target.Node(parent=nroot)
        nroot.childmap["foo"] = n1
        n1.state = target.State.INCLUDED

        nroot.prune()
        self.assertNotIn("foo", nroot.childmap)

    def test_prune_evictions_in_evicted(self):
        nroot = target.Node()
        n1 = target.Node(parent=nroot)
        nroot.childmap["foo"] = n1
        n1.state = target.State.EVICTED
        n2 = target.Node(parent=n1)
        n1.childmap["bar"] = n2
        n2.state = target.State.EVICTED

        nroot.prune()
        self.assertIn("foo", nroot.childmap)
        self.assertNotIn("bar", nroot.childmap["foo"].childmap)

    def test_clear(self):
        self.n1.clear()
        self.assertIsNone(self.n1.state)
        self.assertDictEqual(self.n1.childmap, {})


class TestTarget(unittest.TestCase):
    def setUp(self):
        self.src = "host:/source/directory/"
        self.dest = "/destination/directory/"
        self.target = target.Target(
            self.src,
            self.dest
        )
        self.target.include("/")

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
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("A/B")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("-", "A/B"),
            ]
        )

        self.assertIs(
            self.target.get_state("A"),
            target.State.INCLUDED
        )

        self.assertIs(
            self.target.get_state("A/B"),
            target.State.EVICTED
        )

        self.assertIs(
            self.target.get_state("A/B/C"),
            target.State.EVICTED
        )

    def test_include_included_root_is_noop(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.include("A")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

    def test_evict_root(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("-", "*"),
            ]
        )

    def test_evict_inside_evicted_is_noop(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("A")
        self.target.evict("A/B/")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("-", "A")
            ]
        )

    def test_include_sub_evicted(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("A")
        self.target.include("A/B")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("+", "A/B"),
                ("-", "A/*"),
            ]
        )

    def test_include_deep_sub_evicted(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("A")
        self.target.include("A/B/C")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("+", "A/B/C"),
                ("-", "A/B/*"),
                ("+", "A/B"),
                ("-", "A/*"),
            ]
        )

    def test_complex(self):
        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
            ]
        )

        self.target.evict("A")
        self.target.include("A/B/C")
        self.target.evict("A/B/C/D")
        self.target.include("A/E")

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("-", "A/B/C/D"),
                ("+", "A/B/C"),
                ("-", "A/B/*"),
                ("+", "A/B"),
                ("+", "A/E"),
                ("-", "A/*"),
            ]
        )

    def test_iter_flat_nodes(self):
        self.assertSequenceEqual(
            list(self.target.iter_flat_nodes()),
            [
                (target.State.INCLUDED, ""),
            ]
        )

        self.target.evict("A")
        self.target.include("A/B/C")
        self.target.evict("A/B/C/D")
        self.target.include("A/E")

        self.assertSequenceEqual(
            list(self.target.iter_flat_nodes()),
            [
                (target.State.INCLUDED, ""),
                (target.State.EVICTED, "A"),
                (target.State.INCLUDED, "A/B/C"),
                (target.State.EVICTED, "A/B/C/D"),
                (target.State.INCLUDED, "A/E"),
            ]
        )

    def test_iter_flat_nodes_evicted_root(self):
        self.assertSequenceEqual(
            list(self.target.iter_flat_nodes()),
            [
                (target.State.INCLUDED, ""),
            ]
        )

        self.target.evict("")
        self.target.include("A/B/C")
        self.target.evict("A/B/C/D")
        self.target.include("A/E")

        self.assertSequenceEqual(
            list(self.target.iter_flat_nodes()),
            [
                (target.State.EVICTED, ""),
                (target.State.INCLUDED, "A/B/C"),
                (target.State.EVICTED, "A/B/C/D"),
                (target.State.INCLUDED, "A/E"),
            ]
        )

    def test_from_flat_nodes(self):
        self.target.from_flat_nodes([
            (target.State.EVICTED, "A"),
            (target.State.INCLUDED, "A/B/C"),
            (target.State.EVICTED, "A/B/C/D"),
            (target.State.INCLUDED, "A/E"),
        ])

        self.assertSequenceEqual(
            list(self.target.iter_flat_nodes()),
            [
                (target.State.EVICTED, "A"),
                (target.State.INCLUDED, "A/B/C"),
                (target.State.EVICTED, "A/B/C/D"),
                (target.State.INCLUDED, "A/E"),
            ]
        )

        self.assertSequenceEqual(
            list(self.target.iter_filter_rules()),
            [
                ("-", "A/B/C/D"),
                ("+", "A/B/C"),
                ("-", "A/B/*"),
                ("+", "A/B"),
                ("+", "A/E"),
                ("-", "A/*"),
            ]
        )

    def tearDown(self):
        del self.target
