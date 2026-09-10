"""Catch PHANTOM imports: a module the code references that exists nowhere.

Language models invent imports — ``from models import UrlRequest`` with no ``models.py``
anywhere and no such package. A syntax check passes (it is valid syntax); the failure
surfaces later as a cryptic install or import error. This makes it a clear, attributed
signal instead.

A phantom = a top-level absolutely-imported name that would be unresolvable in a CLEAN
environment after installing the project. "Resolvable" means any of:

- stdlib, or findable via ``find_spec`` on ``[<root>, <root>/src, <root>/tests, <deps-dir>]``
  (local modules, src/ layout, pytest-style test helpers, vendored deps);
- DECLARED as a dependency — pyproject ``[project]`` dependencies/optional-dependencies,
  ``requirements*.txt`` / ``requirements/*.txt``, ``setup.py`` install_requires/
  extras_require string literals, ``setup.cfg`` install_requires — matched on the
  normalized name, with a small alias table for the common import-name/distribution-name
  mismatches (``yaml``/pyyaml, ``PIL``/pillow, ...).

Imports guarded by ``try/except ImportError`` (either leg) or an ``if TYPE_CHECKING:``
block are deliberate optionality, not phantoms — they are skipped at collection.

The host's site-packages remain deliberately EXCLUDED: a package that happens to be
installed on the dev machine but is neither vendored nor declared is still flagged (it
would fail in a clean environment). Deterministic, stdlib only, no code executed
(``find_spec`` locates, never imports).

Known limit: an import name whose distribution name differs beyond normalization and the
alias table (and is neither vendored nor installed under root) is still flagged.

Usage::

    vurnix phantom <root> [--deps <dir>]      # deps defaults to <root>/.deps
        -> one "<relfile>\\t<module>" line per (file, phantom-import) pair;
           empty output = clean. exit code always 0 (this is a signal, not a gate —
           `vurnix gate` turns findings into a BLOCK).
"""

import ast
import configparser
import importlib.util
import os
import re
import sys

# stdlib names. sys.stdlib_module_names exists on 3.10+ (this package requires >=3.10).
_STD = set(getattr(sys, 'stdlib_module_names', set())) | {'__future__'}

_SKIP_DIRS = {'.deps', '.pw-browsers', '__pycache__', '.venv', 'node_modules', 'site-packages'}
# test runners and packaging tools commonly present in the runtime without being vendored
# or declared — excluding these avoids false phantoms on test files and setup.py.
_PREINSTALLED = {'pytest', 'pytest_asyncio', '_pytest', 'py', 'setuptools', 'pip', 'wheel'}
# platform-runtime namespaces that exist only inside their interpreter (Pyodide/Emscripten)
_PLATFORM_RUNTIME = {'js', 'pyodide', 'micropip'}

# Common import-name -> distribution-name mismatches (normalization can't bridge these).
_ALIASES = {
    'PIL': 'pillow', 'cv2': 'opencv-python', 'yaml': 'pyyaml', 'sklearn': 'scikit-learn',
    'bs4': 'beautifulsoup4', 'dateutil': 'python-dateutil', 'dotenv': 'python-dotenv',
    'attr': 'attrs', 'OpenSSL': 'pyopenssl', 'jwt': 'pyjwt', 'docx': 'python-docx',
    'magic': 'python-magic',
}

# leading distribution name in a requirement string ("foo-bar[extra]>=1.0 ; ..." -> foo-bar)
_REQ_NAME = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)')


def _norm(name):
    return name.lower().replace('-', '_')


def _names_from_req_lines(lines):
    out = set()
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith(('#', '-')):        # comments, -r/-e/--options
            continue
        m = _REQ_NAME.match(ln)
        if m:
            out.add(_norm(m.group(1)))
    return out


def _deps_from_pyproject(path):
    try:
        import tomllib
        with open(path, 'rb') as f:
            data = tomllib.load(f)
        proj = data.get('project', {})
        reqs = list(proj.get('dependencies', []))
        for group in proj.get('optional-dependencies', {}).values():
            reqs.extend(group)
        # PEP 735 [dependency-groups] (top-level table); {include-group: ...} dicts skipped
        for group in data.get('dependency-groups', {}).values():
            reqs.extend(item for item in group if isinstance(item, str))
        # poetry: table KEYS are the distribution names ("python" is the interpreter pin)
        poetry = data.get('tool', {}).get('poetry', {})
        for table in (poetry.get('dependencies', {}), poetry.get('dev-dependencies', {})):
            reqs.extend(k for k in table if k.lower() != 'python')
        for group in poetry.get('group', {}).values():
            reqs.extend(k for k in group.get('dependencies', {}) if k.lower() != 'python')
        return _names_from_req_lines(reqs)
    except Exception:
        # py3.10 (no tomllib) or malformed toml: scan quoted strings as requirement
        # candidates. Over-matching is harmless here — it can only mark a name declared.
        try:
            text = open(path, encoding='utf-8', errors='ignore').read()
        except OSError:
            return set()
        return _names_from_req_lines(m.group(1) for m in re.finditer(r'["\']([^"\']+)["\']', text))


def _deps_from_setup_py(path):
    try:
        text = open(path, encoding='utf-8', errors='ignore').read()
    except OSError:
        return set()
    regions = re.findall(r'install_requires\s*=\s*\[(.*?)\]', text, re.S)
    regions += re.findall(r'extras_require\s*=\s*\{(.*?)\}', text, re.S)
    reqs = []
    for region in regions:
        reqs += re.findall(r'["\']([^"\']+)["\']', region)
    return _names_from_req_lines(reqs)


def _deps_from_setup_cfg(path):
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding='utf-8')
    except (configparser.Error, OSError, UnicodeDecodeError):
        return set()
    reqs = []
    if cp.has_option('options', 'install_requires'):
        reqs += cp.get('options', 'install_requires').splitlines()
    if cp.has_section('options.extras_require'):
        for _, v in cp.items('options.extras_require'):
            reqs += v.splitlines()
    return _names_from_req_lines(reqs)


_DECL_MARKERS = ('pyproject.toml', 'setup.py', 'setup.cfg', 'requirements.txt', '.git')


def _declaration_base(root):
    """Nearest ancestor (incl. root) carrying dependency-declaration files — so gating a
    subtree (src/, app/) still sees the project's declarations, the way pytest/ruff find
    their config upward. Falls back to root."""
    cur = os.path.abspath(root)
    for _ in range(12):
        if any(os.path.exists(os.path.join(cur, m)) for m in _DECL_MARKERS):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.abspath(root)


def declared_deps(root):
    """Normalized distribution names the project declares (pyproject / requirements
    files / setup.py / setup.cfg, discovered at the nearest declaring ancestor). A
    declared dependency is not a phantom: it would be installed in any clean
    environment that installs the project."""
    out = set()
    root = _declaration_base(root)
    pp = os.path.join(root, 'pyproject.toml')
    if os.path.isfile(pp):
        out |= _deps_from_pyproject(pp)
    sp = os.path.join(root, 'setup.py')
    if os.path.isfile(sp):
        out |= _deps_from_setup_py(sp)
    sc = os.path.join(root, 'setup.cfg')
    if os.path.isfile(sc):
        out |= _deps_from_setup_cfg(sc)
    req_files = []
    try:
        req_files += [os.path.join(root, f) for f in os.listdir(root)
                      if f.startswith('requirements') and f.endswith('.txt')]
    except OSError:
        pass
    for sub in ('requirements', 'docs'):                      # requirements/ dir; RTD-style docs/requirements*.txt
        subdir = os.path.join(root, sub)
        if os.path.isdir(subdir):
            try:
                req_files += [os.path.join(subdir, f) for f in os.listdir(subdir)
                              if f.endswith('.txt') and (sub == 'requirements' or f.startswith('requirements'))]
            except OSError:
                pass
    for rf in req_files:
        try:
            out |= _names_from_req_lines(open(rf, encoding='utf-8', errors='ignore').readlines())
        except OSError:
            continue
    return out


def _catches_import_error(handler_type):
    """Does this except-clause type catch ImportError? (bare except / Exception count)."""
    if handler_type is None:
        return True
    if isinstance(handler_type, ast.Tuple):
        return any(_catches_import_error(e) for e in handler_type.elts)
    name = getattr(handler_type, 'id', None) or getattr(handler_type, 'attr', None)
    return name in {'ImportError', 'ModuleNotFoundError', 'Exception', 'BaseException'}


def _is_type_checking(test):
    """`if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` / `if t.TYPE_CHECKING:`."""
    return (isinstance(test, ast.Name) and test.id == 'TYPE_CHECKING') or \
           (isinstance(test, ast.Attribute) and test.attr == 'TYPE_CHECKING')


def _is_env_conditional(test):
    """`if sys.version_info >= (3, 11):` / `if sys.platform == "emscripten":` — both
    branches are environment-conditional optionality (the leg that doesn't run here may
    be the one that runs elsewhere), so imports in either leg are not phantoms."""
    return any(isinstance(n, ast.Attribute) and n.attr in ('version_info', 'platform')
               for n in ast.walk(test))


def _collect_imports(tree):
    """-> (live, guarded) lists of top-level names from absolute imports. Guarded = inside
    a try whose handlers catch ImportError — body, handler AND else legs all belong to the
    same optionality dance (`else:` runs only when the try-import succeeded). Imports in an
    `if TYPE_CHECKING:` body are typing-only and collected nowhere."""
    live, guarded = [], []
    def emit(node, g):
        sink = guarded if g else live
        if isinstance(node, ast.Import):
            for a in node.names:
                sink.append(a.name.split('.')[0])
        elif node.level == 0 and node.module:
            sink.append(node.module.split('.')[0])
    def visit(node, g):
        if isinstance(node, ast.Try) and any(_catches_import_error(h.type) for h in node.handlers):
            for child in node.body + node.handlers + node.orelse:
                visit(child, True)
            for child in node.finalbody:
                visit(child, g)
            return
        if isinstance(node, ast.If) and _is_type_checking(node.test):
            for child in node.orelse:
                visit(child, g)
            return
        if isinstance(node, ast.If) and _is_env_conditional(node.test):
            for child in node.body + node.orelse:
                visit(child, True)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            emit(node, g)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, g)
    visit(tree, False)
    return live, guarded


def imported_names(root):
    """-> {top_level_module_name: [relfile, ...]} for live absolute imports. A name that is
    guard-imported anywhere in the SAME file makes its other imports in that file part of
    the same optionality dance (`has_x = False; try: import x ...; if has_x: from x import y`)."""
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
            live, guarded = _collect_imports(tree)
            gset = set(guarded)
            for name in live:
                if name in gset:
                    continue
                names.setdefault(name, []).append(rel)
    return names


def resolvable(name, search):
    """Findable as an isolated test runtime would: stdlib, OR on the search paths only.
    Excludes host site-packages so a host-only, undeclared package is still caught."""
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


def _declared_matches(name, declared):
    """Normalized-name match, plus the classic prefix/suffix families the ecosystem uses
    for import-name/distribution-name pairs (socks/pysocks, markdown_it/markdown-it-py)."""
    n = _norm(name)
    if n in declared:
        return True
    return any(form in declared for form in ('py' + n, n + '_py', n + '_python', 'python_' + n))


def _file_base(file_dir, outer_base, cache):
    """Nearest declaring ancestor of file_dir, never above outer_base — so a nested
    sub-project (examples/tutorial with its own pyproject) resolves against ITSELF."""
    chain = []
    cur = file_dir
    found = outer_base
    while True:
        if cur in cache:
            found = cache[cur]
            break
        chain.append(cur)
        if cur == outer_base or len(chain) > 24:
            break
        if any(os.path.exists(os.path.join(cur, m)) for m in _DECL_MARKERS if m != '.git'):
            found = cur
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for d in chain:
        cache[d] = found
    return found


def find_phantoms(root, deps):
    root = os.path.abspath(root)
    outer_base = _declaration_base(root)
    base_cache, decl_cache, search_cache = {}, {}, {}

    def base_info(base):
        if base not in decl_cache:
            decl_cache[base] = declared_deps(base)
            # src/ layout and pytest-style tests/ helpers are standard, local-by-convention paths.
            search_cache[base] = [base, os.path.join(base, 'src'), os.path.join(base, 'tests')]
        return decl_cache[base], search_cache[base]

    outer_declared, outer_search = base_info(outer_base)
    # the scanned root itself always anchors resolution (a fixture/subdir scanned directly
    # may sit below its declaration base — its own local modules must still resolve)
    root_search = [root, os.path.join(root, 'src'), os.path.join(root, 'tests')]
    # the base's basename is treated as local (`from app.x import ...` inside app/): we hunt
    # INVENTED sibling modules (models/db/state/...), not package-layout issues.
    skip = _PREINSTALLED | _PLATFORM_RUNTIME | {os.path.basename(root.rstrip('/')), os.path.basename(outer_base)}
    out = []
    for name, files in sorted(imported_names(root).items()):
        if name in skip:
            continue
        for rel in sorted(set(files)):
            file_dir = os.path.dirname(os.path.join(root, rel))
            base = _file_base(file_dir, outer_base, base_cache)
            declared, search = base_info(base)
            # file_dir itself: Python puts the running script's own directory on sys.path,
            # and test fixtures/example apps rely on exactly that
            if resolvable(name, [file_dir] + root_search + search + outer_search + [deps]):
                continue
            if _declared_matches(name, declared | outer_declared):
                continue
            if name in _ALIASES and _norm(_ALIASES[name]) in (declared | outer_declared):
                continue
            if name == os.path.basename(base):
                continue
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
