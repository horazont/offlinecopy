import argparse
import configparser
import contextlib
import os.path
import pathlib
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

    cmd.extend(cfg.rsync_options)

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

        dest_path = str(t.dest)
        if t.dest.is_dir():
            dest_path += "/"

        if revert:
            cmd.append(t.src)
            cmd.append(dest_path)
        else:
            cmd.append(dest_path)
            cmd.append(t.src)

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


def validate_targets(targets):
    for target in targets:
        if target.dest.is_dir() and not target.src.endswith("/"):
            print("warning: directory target {!r} uses non-directory source"
                  " {!r}".format(
                      str(target.dest),
                      target.src),
                  file=sys.stderr)


def write_targets(path, targets):
    validate_targets(targets)

    root = config.E.targets()
    config.save_targets(root, targets)
    data = lxml.etree.tostring(root, encoding="utf-8")

    with open(path, "wb") as f:
        f.write(data)


def get_target_from_path(targets, path):
    for target in targets:
        target_dest = target.dest.resolve()
        if target_dest in path.parents or target_dest == path:
            return target, str(path)[len(str(target_dest)):]
    return None, None


def get_target_by_path(targets, path):
    for target in targets:
        target_dest = target.dest.resolve()
        if target_dest == path:
            return target


def cmdfunc_add(args, cfg, targets):
    dest = pathlib.Path(args.dest).resolve()
    parents = list(dest.parents)

    for t in targets:
        target_dest = t.dest.resolve()
        if target_dest in parents or dest == target_dest:
            print("error: the destination is already covered by another target"
                  ": {}".format(t.dest), file=sys.stderr)
            sys.exit(1)
        if dest in target_dest.parents:
            print("error: the destination is parent of another target"
                  ": {}".format(t.dest), file=sys.stderr)
            sys.exit(1)

    if dest.is_dir() and not args.source.endswith("/"):
        args.source += "/"

    new_target = target.Target(args.source, dest)
    targets.append(new_target)

    write_targets(get_targets_path(), targets)


def cmdfunc_remove(args, cfg, targets):
    dest = pathlib.Path(args.dest).resolve()
    target = get_target_by_path(targets, dest)
    if target is None:
        print("error: {!r} is not a target".format(str(dest)),
              file=sys.stderr)
        return 1

    targets.remove(target)

    write_targets(get_targets_path(), targets)


def cmdfunc_exclude(args, cfg, targets):
    path = pathlib.Path(args.path).resolve()
    t, relpath = get_target_from_path(targets, path)

    if t is None:
        print("error: {!r} is not inside a target".format(str(path)),
              file=sys.stderr)
        sys.exit(1)

    state = t.get_state(relpath)
    if state == target.State.EVICTED:
        print("error: already excluded: {!r}".format(relpath),
              file=sys.stderr)
        sys.exit(1)

    t.evict(relpath)
    t.prune()

    write_targets(get_targets_path(), targets)

    if args.evict:
        shutil.rmtree(path)


def cmdfunc_include(args, cfg, targets):
    path = pathlib.Path(args.path)
    try:
        path = path.resolve()
    except FileNotFoundError:
        pass

    t, relpath = get_target_from_path(targets, path)
    if t is None:
        print("error: {!r} is not in any target".format(str(path)),
              file=sys.stderr)
        sys.exit(1)

    state = t.get_state(relpath)
    if state == target.State.INCLUDED:
        print("error: {!r} is already included".format(relpath),
              file=sys.stderr)
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

    all_targets = frozenset(targets)
    selection = {pathlib.Path(path).resolve() for path in args.targets}

    if not selection:
        matched_targets = set(targets)
    else:
        matched_targets = set()
        for t in targets:
            target_dest = pathlib.Path(t.dest).resolve()
            if target_dest in selection:
                matched_targets.add(t)
                selection.remove(target_dest)

        if selection:
            for path in selection:
                print("error: no matching target for paths:", file=sys.stderr)
                print("  {!r}".format(str(path)), file=sys.stderr)
                sys.exit(1)

    if args.not_:
        matched_targets = all_targets - matched_targets

    if not matched_targets:
        print("note: no targets selected", file=sys.stderr)
        sys.exit(1)

    matched_targets = sorted(matched_targets,
                             key=lambda target: target.dest)

    for t in matched_targets:
        if args.verbosity > 0:
            print("pushing target {!r}".format(str(t.dest)))
        rsync_target(cfg, t,
                     additional_args=args.rsync_opts,
                     dry_run=args.dry_run,
                     revert=False,
                     verbosity=args.verbosity)


def cmdfunc_revert(args, cfg, targets):
    selection = {pathlib.Path(path).resolve() for path in args.targets}

    if not selection and not args.map_none_to_all:
        print("error: no target selected (did you mean --all?)",
              file=sys.stderr)
        sys.exit(1)
    elif not selection:
        matched_targets = list(targets)
    else:
        matched_targets = []
        for t in targets:
            target_dest = t.dest.resolve()
            if target_dest in selection:
                matched_targets.append(t)
                selection.remove(target_dest)

        if selection:
            for path in selection:
                print("error: no matching target for paths:", file=sys.stderr)
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
        dest_path = target.dest
        if dest_path.is_dir():
            dest_path = str(dest_path) + "/"
        print("{} => {}".format(target.src, dest_path))
        for state, path in target.iter_filter_rules():
            print("  {} {}".format(state, path))


def cmdfunc_set_source(args, cfg, targets):
    path = pathlib.Path(args.target).resolve()
    target = get_target_by_path(targets, path)
    if not target:
        print("error: {!r} is not a target".format(str(path)),
              file=sys.stderr)
        return 1

    target.src = args.source

    write_targets(get_targets_path(), targets)


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
        help="Add a new synchronization target",
        description="""\
        Add a synchronization target. A synchronization target consists of a
        remote source (using standard scp/rsync syntax like `user@host:/path')
        and a destination (a local path). Inside each target, files and
        directories can be included and excluded individually using the include
        and exclude subcommands. Adding a target does not transfer any files
        from or to the source. New targets are created so that their root is
        excluded and you can summon the whole target or individual parts using
        the summon subcommand."""
    )
    cmd_add.add_argument(
        "source",
        metavar="SOURCE",
        help="URL for the source of the target"
    )
    cmd_add.add_argument(
        "dest",
        metavar="DEST",
        help="""\
        Path for the destination of the target. This must not be within another
        target (see include/exclude for excluding or including specific parts
        of a target). The path is automatically canonicalized (i.e. symlinks
        and relative paths are resolved)."""
    )
    cmd_add.set_defaults(cmd=cmdfunc_add)

    cmd_remove = subparsers.add_parser(
        "remove",
        help="Remove an existing synchronization target",
        description="""\
        Removes the target from the bookkeeping. This does not delete any
        files, but all include/exclude state is gone."""
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
        help="(Re-)include a previously evicted (sub-)directory",
        description="""\
        The include command marks a path for being included into the
        synchronization process. This does not transfer any files from or to
        the source. Use summon if you want to prime the included directory
        with remote contents and see summon --help for advantages of using
        summon over include + revert."""
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
        --delete, so that files deleted locally are propagated back to the
        origin. If you do not want that behaviour, use the exclude subcommand
        to mark directories which are just deleted locally and whose deletion
        shall not propagate back to the source."""
    )
    cmd_push.add_argument(
        "--diff",
        action="store_true",
        default=False,
        help="Equivalent to `--dry-run rsync' and `-v`, i.e. shows the diff to"
        " the remote."
    )
    cmd_push.add_argument(
        "--not",
        dest="not_",
        action="store_true",
        default=False,
        help="Invert selection of targets (i.e. specify targets *not* to push "
        "instead of targets to push)."
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
        Any matched target is re-transmitted from the source; the existing
        contents which are not evicted are removed from the destination. This
        is a potentially dangerous operation which is why you have to name all
        targets explicitly or use --all if you want to apply it to all
        targets."""
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

    cmd_set_source = subparsers.add_parser(
        "set-source",
        help="Change the source of a target",
        description="""\
        Set the remote source of a target to a different path. No
        synchronization happens during this command."""
    )
    cmd_set_source.add_argument(
        "target",
        metavar="PATH",
        help="Path identifying the target locally."
    )
    cmd_set_source.add_argument(
        "source",
        metavar="SOURCE",
        help="New source for the target. The same rules as for the add"
        " subcommand apply.",
    )
    cmd_set_source.set_defaults(cmd=cmdfunc_set_source)

    cmd_status = subparsers.add_parser(
        "status",
        aliases=["list"],
        help="Show the target configuration"
    )
    cmd_status.set_defaults(cmd=cmdfunc_list)

    args = parser.parse_args()

    if not hasattr(args, "cmd"):
        print("no command selected", file=sys.stderr)
        sys.exit(1)

    cfg = config.Config(read_config(get_config_path()))
    targets = read_targets(get_targets_path())

    try:
        sys.exit(args.cmd(args, cfg, targets) or 0)
    except OSError as exc:
        print(exc)
        sys.exit(1)
