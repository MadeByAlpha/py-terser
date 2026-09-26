from __future__ import annotations

import argparse
import os
import sys

import terser
from alpha93.progression import TqdmReporter

from .._pipeline.mangler.util import preserved_names
from ..exceptions import UnbeneficialMinificationError
from ._argparse import arguments_from_model, normalize_bool_flags
from ._argv import TerserArguments, TerserParsedArguments, parse_preserve

STDIN = '-'

def main(argv: list[str] | None = None):
    """
    examples:
      # Minifying stdin to stdout
      terser -

      # Minifying a file to stdout
      terser example.py

      # Minifying a file and writing to a different file
      terser example.py --output example.min.py

      # Minifying a file in place
      terser example.py --in-place

      # Minifying all *.py files in a directory
      terser src/ --in-place

      # Minifying a directory to a separate output directory
      terser src/ --output build/

      # Minifying multiple paths in place
      terser file1.py file2.py src/ --in-place
    """

    args = _argv(argv)

    # for single files
    if (paths_size := len(args.path)) <= 1 and (not paths_size or (p := next(iter(args.path))) == STDIN or os.path.isfile(p)):
        if not paths_size or next(iter(args.path)) == STDIN:
            path = "<stdin>"
            source: str = sys.stdin.read()
        else:
            path = next(iter(args.path))
            source_: str
            with open(path, 'r') as f:
                source_ = f.read()
            source = source_

        try:
            mangling = args.mangling_options
            minified = terser.minify(
                source,
                args.transform_options,
                path,
                preserve_shebang=args.preserve_shebang,
                prefer_single_line=args.prefer_single_line,
                hoist_literals=mangling.hoist_literals,
                rename_locals=mangling.rename_locals,
                preserve_locals=sorted(preserved_names(path, parse_preserve(mangling.preserve_locals))),
                rename_globals=mangling.rename_globals,
                preserve_globals=sorted(preserved_names(path, parse_preserve(mangling.preserve_globals))),
            )
        except UnbeneficialMinificationError:
            # Use original source when minification isn't beneficial
            minified = source

        if destination := args.output_options.output or (args.output_options.in_place and path):
            with open(destination, 'w') as f:
                f.write(minified)
        else:
            sys.stdout.write(minified)
        return

    # Directories and multiple paths are minified as a project (whole-project name
    # resolution/linking), so route them separately.
    from functools import partial

    import anyio

    with TqdmReporter() as reporter:
        anyio.run(partial(terser.minify_project,
            args.transform_options,
            args.path,
            reporter,
            __import__("anyio").Path(output) if (output := args.output_options.output) else None,
            workers=args.workers,
            hoist_literals=args.mangling_options.hoist_literals,
            rename_locals=args.mangling_options.rename_locals,
            preserve_locals=parse_preserve(args.mangling_options.preserve_locals),
            rename_globals=args.mangling_options.rename_globals,
            preserve_globals=parse_preserve(args.mangling_options.preserve_globals),
            rename_modules=args.mangling_options.rename_modules,
            preserve_modules=args.mangling_options.preserve_modules,
            entry=args.entry,
        ))
    return


def _argv(argv: list[str] | None = None) -> TerserParsedArguments:
    python_minifier = __import__("terser")
    parser = argparse.ArgumentParser("terser", None, python_minifier.__doc__, main.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    #parser.add_argument("--help", "-h", action="help")
    parser.add_argument("-v", "--version", action="version", version=python_minifier.version)

    parser.add_argument(
        'path',
        nargs='+',
        type=str,
        help='The source file or directory to minify. Use "-" to read from stdin. Directories are recursively searched for ".py" files to minify. May be used multiple times',
    )

    arguments_from_model(parser, TerserArguments)
    args = TerserParsedArguments.from_argparse(parser.parse_args(normalize_bool_flags(parser, sys.argv[1:] if argv is None else argv)))

    # Handle some invalid argument combinations
    if '-' in args.path and len(args.path) != 1:
        sys.stderr.write('error: multiple path arguments, reading from stdin not allowed\n')
        sys.exit(1)
    if '-' in args.path and args.output_options.in_place:
        sys.stderr.write('error: reading from stdin, --in-place is not valid\n')
        sys.exit(1)
    if len(args.path) > 1 and not (args.output_options.in_place or args.output_options.output):
        sys.stderr.write('error: multiple path arguments, --in-place or --output required\n')
        sys.exit(1)
    if len(args.path) == 1 and os.path.isdir(p := next(iter(args.path))) and not (args.output_options.in_place or args.output_options.output):
        sys.stderr.write('error: path ' + p + ' is a directory, --in-place or --output required\n')
        sys.exit(1)
    #if not is_project_mode(args) and (args.mangling_options.rename_globals or args.mangling_options.preserve_globals):
    #    sys.stderr.write('error: --rename-globals/--preserve-globals require a directory, multiple paths, or --in-place, since global renaming needs whole-project linking\n')
    #    sys.exit(1)
    if (
        len(args.path) <= 1 and (not args.path or os.path.isfile(next(iter(args.path))))
        and (args.entry or args.mangling_options.rename_modules or args.mangling_options.preserve_modules)
    ):
        sys.stderr.write('error: --entry/--rename-modules/--preserve-modules require a directory or multiple paths, since these need whole-project linking\n')
        sys.exit(1)
    if args.mangling_options.rename_modules and not args.output_options.output:
        sys.stderr.write('error: --rename-modules requires --output, since renamed files can\'t be written back in-place\n')
        sys.exit(1)

    return args
