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
        xdg.BaseDirectory.save_config_path("offlinecopy"),
        "targets.xml"
    )


def get_config_path():
    return os.path.join(
        xdg.BaseDirectory.save_config_path("offlinecopy"),
        "config.ini"
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


def rsync_invocation_base(cfg, verbosity=0, delete=True):
    cmd = ["rsync", "-raHEAXS", "--protect-args"]

    options = cfg.get("offlinecopy", "rsync-options", fallback="").strip()
    if options:
        cmd.append(options)

    if delete:
        cmd.append("--delete")

    if verbosity >= 1:
        cmd.append("-v")
        cmd.append("--itemize-changes")

    if verbosity <= 2:
        cmd.append("--progress")

    return cmd


def rsync_target(cfg, t,
                 additional_args=[],
                 verbosity=0,
                 revert=False,
                 dry_run=False,
                 delete=True):
    cmd = rsync_invocation_base(cfg,
                                verbosity=verbosity,
                                delete=delete)

    with FilterFile(t) as name:
        cmd.extend(["--filter", ". {}".format(name)])
        cmd.extend(additional_args)
        if revert:
            cmd.append(t.src + "/")
            cmd.append(t.dest + "/")
        else:
            cmd.append(t.dest + "/")
            cmd.append(t.src + "/")

        if dry_run:
            apply_dry_run_mode(cmd, dry_run)

        subprocess.check_call(cmd)


def read_config(path):
    parser = configparser.ConfigParser()
    try:
        f = open(path, "r")
    except FileNotFoundError:
        pass
    else:
        with f:
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


def cmdfunc_exclude(args, cfg, targets):
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

    if args.evict:
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

    if args.summon:
        cmd = rsync_invocation_base(cfg,
                                    verbosity=args.verbosity,
                                    delete=False)
        if args.dry_run:
            apply_dry_run_mode(cmd, args.dry_run)

        cmd.extend(args.rsync_opts)
        cmd.append("--ignore-existing")

        cmd.append(os.path.join(t.src, relpath[1:])+"/")
        cmd.append(os.path.join(t.dest, relpath[1:])+"/")

        subprocess.check_call(cmd)

    if not args.dry_run:
        write_targets(get_targets_path(), targets)


def cmdfunc_push(args, cfg, targets):
    if args.diff:
        args.dry_run = DryRunMode.RSYNC
        args.verbosity = 1

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
        rsync_target(cfg, t,
                     additional_args=args.rsync_opts,
                     dry_run=args.dry_run,
                     revert=False,
                     verbosity=args.verbosity)


def cmdfunc_revert(args, cfg, targets):
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
        rsync_target(cfg, t,
                     additional_args=args.rsync_opts,
                     dry_run=args.dry_run,
                     revert=True,
                     verbosity=args.verbosity)


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


def rsync_opts_argument(parser):
    parser.add_argument(
        "--rsync",
        dest="rsync_opts",
        action="append",
        default=[],
        metavar="OPTION",
        help="Options to use in calls to rsync during this command and only"
        " during this command. They are not saved in the configuration. Make"
        " sure to use --rsync=OPTION syntax to pass options starting with `-'."
    )


def main():
    parser = argparse.ArgumentParser(
        description="""\
offlinecopy allows to selectively pick directories which are synchronized with a
remote target (or possibly another directory)."""
    )

    parser.add_argument(
        "-v",
        help="Increase verbosity (up to -vvv)",
        action="count",
        default=0,
        dest="verbosity",
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

    cmd_exclude = subparsers.add_parser(
        "exclude",
        help="Exclude a directory from synchronization",
        description="""\
This excludes the file or directory (and in the case of an directory,
any of its contents) from synchronisation."""
    )
    cmd_exclude.add_argument(
        "path",
        metavar="PATH",
        help="Path to the node to exclude"
    )
    cmd_exclude.add_argument(
        "--evict", "--delete",
        action="store_true",
        default=False,
        help="Delete the file or directory after evicting"
    )
    cmd_exclude.set_defaults(cmd=cmdfunc_exclude)

    cmd_include = subparsers.add_parser(
        "include",
        help="(Re-)include a previously evicted (sub-)directory"
    )
    cmd_include.add_argument(
        "path",
        metavar="PATH",
        help="Path to the node to include"
    )
    dry_run_argument(cmd_include)
    rsync_opts_argument(cmd_include)
    cmd_include.set_defaults(cmd=cmdfunc_include, summon=False)

    cmd_summon = subparsers.add_parser(
        "summon",
        help="(Re-)include and copy a directory to the local file system",
        description="""\
        When summoning, the files from the source are transferred to the local
        file system. Using summon has three advantages over using include and
        revert: first, other directories inside the target are not affected;
        second, when summoning, local files are not deleted or overwritten in
        favour of remote files; third, the directory is only marked as included
        after a successful transfer has taken place."""
    )
    cmd_summon.add_argument(
        "path",
        metavar="PATH",
        help="Path to the node to include"
    )
    dry_run_argument(cmd_summon)
    rsync_opts_argument(cmd_summon)
    cmd_summon.set_defaults(cmd=cmdfunc_include, summon=True)

    cmd_push = subparsers.add_parser(
        "push",
        help="Transfer one or more targets to their source",
        description="""\
Synchronize all matching targets to their source. This is done with
--delete, so that files deleted locally are propagated back to the origin.
If you do not want that behaviour, use the evict subcommand to mark directories
which are just deleted locally and whose deletion shall not propagate back to
the source."""
    )
    cmd_push.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Equivalent to `--dry-run rsync' and `-v`, i.e. shows the diff to"
        " the remote."
    )
    cmd_push.add_argument(
        "targets",
        metavar="PATH",
        nargs="*",
        help="Zero or more target destination directiories. If none is given, "
        "all targets are synced back"
    )
    dry_run_argument(cmd_push)
    rsync_opts_argument(cmd_push)
    cmd_push.set_defaults(cmd=cmdfunc_push)

    cmd_revert = subparsers.add_parser(
        "revert",
        help="Transfer one or more targets from their source",
        description="""\
Any matched target is re-transmitted from the source; the existing contents
which are not evicted are removed from the destination."""
    )
    cmd_revert.add_argument(
        "--all",
        action="store_true",
        dest="map_none_to_all",
        default=False,
        help="If and only if this switch is given, supplying no targets is"
        " valid and is equivalent to specifying *all* registered targets."
    )
    cmd_revert.add_argument(
        "targets",
        metavar="PATH",
        nargs="*",
        help="One or more target destination directories."
    )
    dry_run_argument(cmd_revert)
    rsync_opts_argument(cmd_revert)
    cmd_revert.set_defaults(cmd=cmdfunc_revert)

    cmd_status = subparsers.add_parser(
        "list",
        help="List all targets"
    )
    cmd_status.set_defaults(cmd=cmdfunc_list)

    args = parser.parse_args()

    if not hasattr(args, "cmd"):
        print("no command selected", file=sys.stderr)
        sys.exit(1)

    config = read_config(get_config_path())
    targets = read_targets(get_targets_path())

    args.cmd(args, config, targets)
