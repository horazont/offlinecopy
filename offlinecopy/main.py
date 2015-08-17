import argparse
import configparser
import contextlib
import os.path
import shutil
import subprocess
import sys
import tempfile

from enum import Enum

import lxml.etree

import xdg.BaseDirectory

from . import config, target


def get_targets_path():
    return os.path.join(
        xdg.BaseDirectory.save_config_path("fancysync"),
        "targets.xml"
    )


@contextlib.contextmanager
def FilterFile(t):
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        try:
            for mode, rule in t.iter_filter_rules():
                print("{} /{}".format(mode, rule), file=f)
            f.close()
            yield f.name
        finally:
            os.unlink(f.name)


def resync(t, dry_run=False):
    cmd = ["rsync", "-raHEAXSP", "--delete"]

    with FilterFile(t) as name:
        cmd.extend(["--filter", ". {}".format(name)])
        cmd.append(t.src + "/")
        cmd.append(t.dest + "/")
        if dry_run:
            apply_dry_run_mode(cmd, dry_run)
        subprocess.check_call(cmd)


def backsync(t, dry_run=False):
    cmd = ["rsync", "-raHEAXSP", "--delete"]

    with FilterFile(t) as name:
        cmd.extend(["--filter", ". {}".format(name)])
        cmd.append(t.dest + "/")
        cmd.append(t.src + "/")
        if dry_run:
            apply_dry_run_mode(cmd, dry_run)
        subprocess.check_call(cmd)


def read_config(f):
    parser = configparser.ConfigParser()
    parser.read_file(f)

    return parser


def read_targets(path):
    try:
        f = open(path, "rb")
    except FileNotFoundError:
        targets = config.E.targets()
    else:
        with f:
            targets = lxml.etree.parse(f).getroot()

    return list(config.load_targets(targets))


def write_targets(path, targets):
    root = config.E.targets()
    config.save_targets(root, targets)
    data = lxml.etree.tostring(root, encoding="utf-8")

    with open(path, "wb") as f:
        f.write(data)


def get_target_from_path(targets, path):
    for target in targets:
        target_dest = os.path.realpath(target.dest)
        if path.startswith(target_dest):
            return target, path[len(target_dest):]
    return None, None


def cmdfunc_add(args, cfg, targets):
    dest = os.path.realpath(args.dest)

    for t in targets:
        target_dest = os.path.realpath(t.dest)
        if target_dest.startswith(dest) or dest.startswith(target_dest):
            print("the destination is already covered by another target")
            sys.exit(1)

    new_target = target.Target(args.source, dest)
    targets.append(new_target)

    write_targets(get_targets_path(), targets)


def cmdfunc_remove(args, cfg, targets):
    dest = os.path.realpath(args.dest).rstrip("/")

    for target in targets:
        target_dest = os.path.realpath(args.dest).rstrip("/")
        if target_dest == dest:
            break
    else:
        print("no target matching path: {}".format(dest),
              file=sys.stderr)
        sys.exit(1)

    targets.remove(target)

    write_targets(get_targets_path(), targets)


def cmdfunc_evict(args, cfg, targets):
    path = os.path.realpath(args.path)
    t, relpath = get_target_from_path(targets, path)

    if t is None:
        print("no target holds {}".format(path), file=sys.stderr)
        sys.exit(1)

    state = t.get_state(relpath)
    if state == target.State.EVICTED:
        print("already evicted: {}".format(relpath), file=sys.stderr)
        sys.exit(1)

    t.evict(relpath)
    t.prune()

    write_targets(get_targets_path(), targets)

    if args.delete:
        shutil.rmtree(path)


def cmdfunc_include(args, cfg, targets):
    path = os.path.realpath(args.path)
    t, relpath = get_target_from_path(targets, path)
    if t is None:
        print("not target holds {}".format(path), file=sys.stderr)
        sys.exit(1)

    state = t.get_state(relpath)
    if state == target.State.INCLUDED:
        print("already included: {}".format(relpath), file=sys.stderr)
        sys.exit(1)

    t.include(relpath)
    t.prune()

    write_targets(get_targets_path(), targets)


def cmdfunc_backsync(args, cfg, targets):
    selection = {os.path.realpath(path) for path in args.targets}
    if not selection:
        matched_targets = list(targets)
    else:
        matched_targets = []
        for t in targets:
            target_dest = os.path.realpath(t.dest)
            if target_dest in selection:
                matched_targets.append(t)
                selection.remove(target_dest)

        if selection:
            for path in selection:
                print("no matching target for paths:", file=sys.stderr)
                print("  {}".format(path), file=sys.stderr)
                sys.exit(1)

    for t in matched_targets:
        backsync(t, args.dry_run)


def cmdfunc_resync(args, cfg, targets):
    selection = {os.path.realpath(path) for path in args.targets}
    if not selection and not args.map_none_to_all:
        print("no target selected (did you mean --all?)", file=sys.stderr)
        sys.exit(1)
    elif not selection:
        matched_targets = list(targets)
    else:
        matched_targets = []
        for t in targets:
            target_dest = os.path.realpath(t.dest)
            if target_dest in selection:
                matched_targets.append(t)
                selection.remove(target_dest)

        if selection:
            for path in selection:
                print("no matching target for paths:", file=sys.stderr)
                print("  {}".format(path), file=sys.stderr)
                sys.exit(1)

    for t in matched_targets:
        resync(t, args.dry_run)


def cmdfunc_list(args, cfg, targets):
    for target in targets:
        print("{} => {}".format(target.src, target.dest))
        for state, path in target.iter_filter_rules():
            print("  {} {}".format(state, path))


class DryRunMode(Enum):
    LOCAL = "local"
    RSYNC = "rsync"


def apply_dry_run_mode(args, mode):
    args.insert(*{
        DryRunMode.LOCAL: (0, "echo"),
        DryRunMode.RSYNC: (1, "--dry-run"),
    }[mode])


def dry_run_argument(parser):
    parser.add_argument(
        "-n", "--dry-run",
        nargs="?",
        type=DryRunMode,
        default=False,
        const=DryRunMode.LOCAL,
        dest="dry_run",
        help="Perform a dry run instead of a actual run. The optional argument"
        " specifies the dry-run mode. With `local', the rsync commands are"
        " printed, but not executed. With `rsync', rsync gets passed the"
        " --dry-run argument."
    )


def main():
    parser = argparse.ArgumentParser(
        description="""\
fancysync allows to selectively pick directories which are synchronized with a
remote target (or possibly another directory)."""
    )

    subparsers = parser.add_subparsers(metavar="command")

    cmd_add = subparsers.add_parser(
        "add",
        help="Add a new synchronization target"
    )
    cmd_add.add_argument(
        "source",
        metavar="SOURCE",
        help="URL for the source of the target"
    )
    cmd_add.add_argument(
        "dest",
        metavar="DEST",
        help="Path for the destination of the target. This must not be within"
        " another target"
    )
    cmd_add.set_defaults(cmd=cmdfunc_add)

    cmd_remove = subparsers.add_parser(
        "remove",
        help="Remove an existing synchronization target",
        description="""\
Removes the target from the bookkeeping. This does not delete any files."""
    )
    cmd_remove.add_argument(
        "dest",
        metavar="DEST",
        help="Remove the target with the given destination directory"
    )
    cmd_remove.set_defaults(cmd=cmdfunc_remove)

    cmd_evict = subparsers.add_parser(
        "evict",
        help="Evict a directory from synchronization",
        description="""\
This excludes the file or directory (and in the case of an directory,
any of its contents) from synchronisation."""
    )
    cmd_evict.add_argument(
        "path",
        metavar="PATH",
        help="Path to the node to exclude"
    )
    cmd_evict.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete the file or directory after evicting"
    )
    cmd_evict.set_defaults(cmd=cmdfunc_evict)

    cmd_include = subparsers.add_parser(
        "include",
        help="(Re-)include a previously evicted (sub-)directory"
    )
    cmd_include.add_argument(
        "path",
        metavar="PATH",
        help="Path to the node to include"
    )
    cmd_include.set_defaults(cmd=cmdfunc_include)

    cmd_backsync = subparsers.add_parser(
        "backsync",
        help="Transfer one or more targets to their source",
        description="""\
Synchronize all matching targets to their source. This is done with
--delete, so that files deleted locally are propagated back to the origin.
If you do not want that behaviour, use the evict subcommand to mark directories
which are just deleted locally and whose deletion shall not propagate back to
the source."""
    )
    cmd_backsync.add_argument(
        "targets",
        metavar="PATH",
        nargs="*",
        help="Zero or more target destination directiories. If none is given, "
        "all targets are synced back"
    )
    dry_run_argument(cmd_backsync)
    cmd_backsync.set_defaults(cmd=cmdfunc_backsync)

    cmd_resync = subparsers.add_parser(
        "resync",
        help="Transfer one or more targets from their source",
        description="""\
Any matched target is re-transmitted from the source; the existing contents
which are not evicted are removed from the destination."""
    )
    cmd_resync.add_argument(
        "--all",
        action="store_true",
        dest="map_none_to_all",
        default=False,
        help="If and only if this switch is given, supplying no targets is"
        " valid and is equivalent to specifying *all* registered targets."
    )
    cmd_resync.add_argument(
        "targets",
        metavar="PATH",
        nargs="*",
        help="One or more target destination directories."
    )
    dry_run_argument(cmd_resync)
    cmd_resync.set_defaults(cmd=cmdfunc_resync)

    cmd_status = subparsers.add_parser(
        "list",
        help="List all targets"
    )
    cmd_status.set_defaults(cmd=cmdfunc_list)

    args = parser.parse_args()

    if not hasattr(args, "cmd"):
        print("no command selected", file=sys.stderr)
        sys.exit(1)

    config = configparser.ConfigParser()

    targets = read_targets(get_targets_path())

    args.cmd(args, config, targets)
