"""Catch PHANTOM imports: a module the code references that exists nowhere.

Language models invent imports — ``from models import UrlRequest`` with no ``models.py``
anywhere and no such package. A syntax check passes (it is valid syntax); the failure
surfaces later as a cryptic install or import error. This makes it a clear, attributed
signal instead.

A phantom = a top-level absolutely-imported name that is UNRESOLVABLE the way an isolated
test runtime would resolve it: it is neither stdlib nor findable via ``find_spec`` on
``[<root>, <deps-dir>]``. The host's site-packages are deliberately EXCLUDED so a package
that happens to be installed on the dev machine but is NOT vendored into the deps dir is
still flagged (it would fail in a clean environment). Deterministic, stdlib only, no code
executed (``find_spec`` locates, never imports).

Usage::

    vurnix phantom <root> [--deps <dir>]      # deps defaults to <root>/.deps
        -> one "<relfile>\\t<module>" line per (file, phantom-import) pair;
           empty output = clean. exit code always 0 (this is a signal, not a gate —
           `vurnix gate` turns findings into a BLOCK).
"""

import ast
import importlib.util
import os
import sys

# stdlib names. sys.stdlib_module_names exists on 3.10+ (this package requires >=3.10).
_STD = set(getattr(sys, 'stdlib_module_names', set())) | {'__future__'}

_SKIP_DIRS = {'.deps', '.pw-browsers', '__pycache__', '.venv', 'node_modules', 'site-packages'}
# test runners commonly present in the runtime without being vendored into deps —
# excluding these avoids false phantoms on test files.
_PREINSTALLED = {'pytest', 'pytest_asyncio', '_pytest', 'py'}


def imported_names(root):
    """-> {top_level_module_name: [relfile, ...]} for absolute imports (level 0) across the tree."""
    names = {}
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS]
        for f in fn:
            if not f.endswith('.py'):
                continue
            path = os.path.join(dp, f)
            try:
                tree = ast.parse(open(path, encoding='utf-8', errors='ignore').read())
            except (OSError, SyntaxError):
                continue
            rel = os.path.relpath(path, root)
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        names.setdefault(a.name.split('.')[0], []).append(rel)
                elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                    names.setdefault(n.module.split('.')[0], []).append(rel)
    return names


def resolvable(name, search):
    """Findable as an isolated test runtime would: stdlib, OR on [root, deps] only.
    Excludes host site-packages so a host-only package is still caught."""
    if name in _STD:
        return True
    old = sys.path
    sys.path = search
    try:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
            return False
    finally:
        sys.path = old
        importlib.invalidate_caches()


def find_phantoms(root, deps):
    search = [root, deps]
    # the root's basename is treated as local (`from app.x import ...` inside app/): we hunt
    # INVENTED sibling modules (models/db/state/...), not package-layout issues — those are a
    # different failure class that the test run itself surfaces.
    skip = _PREINSTALLED | {os.path.basename(root.rstrip('/'))}
    out = []
    for name, files in sorted(imported_names(root).items()):
        if name in skip or resolvable(name, search):
            continue
        for rel in sorted(set(files)):
            out.append((rel, name))
    return out


def run(args):
    nonflag = [a for a in args if not a.startswith('--')]
    if not nonflag:
        sys.stderr.write("usage: vurnix phantom <root> [--deps <dir>]\n")
        return 0
    root = os.path.abspath(nonflag[0])
    if '--deps' in args and args.index('--deps') + 1 < len(args):
        deps = args[args.index('--deps') + 1]
    else:
        deps = os.path.join(root, '.deps')
    if not os.path.isdir(root):
        return 0
    for rel, name in find_phantoms(root, deps):
        print("%s\t%s" % (rel, name))
    return 0
