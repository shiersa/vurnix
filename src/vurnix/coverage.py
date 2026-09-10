"""Honest test-count floor: count DISTINCT, NON-TRIVIAL test functions.

A naive "at least N test functions" floor is gameable: an agent can pad with N copies of
the same easy test, or N ``assert True`` bodies, and clear the floor with near-zero real
coverage. This counter is honest — a test function counts ONLY if:

1. it carries a REAL assertion — an ``assert`` whose condition is not a bare constant
   (``assert True``, ``assert 1``, ``assert "x"``), or a ``pytest.raises(...)`` context; AND
2. its (normalized) body is DISTINCT — identical bodies (copy-paste padding) collapse to one.

Python is counted by AST; JS (``*.test.js`` / ``*.spec.js``), Go (``*_test.go``) and Java
(JUnit ``@Test``) by regex with the same two rules. A project is normally single-language,
so all four counts are summed (the other languages contribute 0). Deterministic, stdlib only.

Usage::

    vurnix coverage <dir>     # prints ONE integer: the qualifying distinct count
                              # exit 0 = counted >0, 3 = counted 0 (UNPROVEN: nothing
                              # verified is not a pass), 2 = usage
"""

import ast
import hashlib
import os
import re
import sys


def _find_test_files(root):
    out = []
    for dp, dn, fn in os.walk(root):
        if os.sep + ".deps" in dp or "__pycache__" in dp or os.sep + "site-packages" in dp:
            continue
        for f in fn:
            if (f.startswith("test_") and f.endswith(".py")) or f.endswith("_test.py"):
                out.append(os.path.join(dp, f))
    return out


def _has_real_check(fn):
    """A test counts only if it makes at least one non-trivial assertion / expects a raise."""
    for n in ast.walk(fn):
        if isinstance(n, ast.Assert):
            # `assert <constant>` (True / 1 / "x" / ...) proves nothing → trivial; anything else counts
            if not isinstance(n.test, ast.Constant):
                return True
        elif isinstance(n, ast.Call):
            name = getattr(n.func, "attr", None) or getattr(n.func, "id", None)
            if name == "raises":            # pytest.raises(...) / raises(...)
                return True
    return False


def _body_key(fn):
    """Normalized body fingerprint (ignores the def name + line numbers) so copy-paste duplicates
    collapse. Two tests that differ in any statement/value hash differently → counted separately."""
    try:
        dump = ast.dump(ast.Module(body=fn.body, type_ignores=[]), annotate_fields=False)
    except TypeError:                        # py<3.8 Module signature
        dump = ast.dump(ast.Module(body=fn.body))
    return hashlib.md5(dump.encode("utf-8")).hexdigest()


def count(root):
    seen = set()
    n = 0
    for path in _find_test_files(root):
        try:
            tree = ast.parse(open(path, encoding="utf-8").read())
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                if not _has_real_check(node):
                    continue
                key = _body_key(node)
                if key in seen:
                    continue
                seen.add(key)
                n += 1
    return n


_JS_TEST = re.compile(r"""\b(?:test|it)\s*\(\s*(['"`])(?P<name>(?:\\.|(?!\1).)*?)\1""", re.S)
# one match per assertion: `assert.X(` / `assert(` / `expect(` — covers node:assert, node:test t.assert, chai/jest.
_JS_ASSERT = re.compile(r"\bassert\s*[.(]|\bexpect\s*\(")


def _find_js_test_files(root):
    """*.test.js / *.spec.js anywhere, plus plain .js under a top-level test/ or tests/
    directory (the mocha convention — express-style suites live in test/*.js). Non-test
    helpers swept up by the directory rule are harmless: only assertion-bearing
    test()/it() blocks are counted anyway."""
    out = []
    root = os.path.abspath(root)
    for dp, dn, fn in os.walk(root):
        if os.sep + "node_modules" in dp or os.sep + ".deps" in dp:
            continue
        rel = os.path.relpath(dp, root)
        top = rel.split(os.sep)[0]
        for f in fn:
            if f.endswith(".test.js") or f.endswith(".spec.js") or \
                    (f.endswith(".js") and top in ("test", "tests")):
                out.append(os.path.join(dp, f))
    return out


def count_js(root):
    """Regex analogue of count() for JS: distinct, assertion-bearing test('...')/it('...') blocks."""
    seen = set()
    n = 0
    for path in _find_js_test_files(root):
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        marks = [(m.start(), m.end(), m.group("name")) for m in _JS_TEST.finditer(src)]
        for i, (_s, e, _name) in enumerate(marks):
            body = src[e:marks[i + 1][0]] if i + 1 < len(marks) else src[e:]
            if not _JS_ASSERT.search(body):        # no real assertion in this test's body → trivial
                continue
            key = hashlib.md5(re.sub(r"\s+", "", body).encode("utf-8")).hexdigest()  # collapse copy-paste
            if key in seen:
                continue
            seen.add(key)
            n += 1
    return n


# Go: `func TestXxx(t *testing.T) {` is a test; it counts only if its body carries a real
# check (t.Error*/t.Fatal*/t.Fail*). Distinct by normalized body (copy-paste padding collapses).
_GO_TEST = re.compile(r"\bfunc\s+(Test\w+)\s*\(\s*\w+\s+\*testing\.T\s*\)\s*\{")
_GO_ASSERT = re.compile(r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b")


def _find_go_test_files(root):
    out = []
    for dp, dn, fn in os.walk(root):
        if os.sep + ".deps" in dp or os.sep + "vendor" in dp:
            continue
        for f in fn:
            if f.endswith("_test.go"):
                out.append(os.path.join(dp, f))
    return out


def _match_brace(src, open_idx):
    """Index just past the '}' matching the '{' at open_idx (naive: ignores braces in strings/comments —
    fine for counting test boundaries). Returns len(src) if unbalanced."""
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(src)


def count_go(root):
    seen = set()
    n = 0
    for path in _find_go_test_files(root):
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in _GO_TEST.finditer(src):
            body = src[m.end() - 1:_match_brace(src, m.end() - 1)]
            if not _GO_ASSERT.search(body):
                continue
            key = hashlib.md5(re.sub(r"\s+", "", body).encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            n += 1
    return n


# Java: a `@Test`-annotated method counts only if its body carries a JUnit assertion
# (assert*/fail). Distinct by normalized body. Test files live under src/test/java (or *Test.java).
_JAVA_TEST = re.compile(r"@Test\b[^\{;]*?\bvoid\s+\w+\s*\([^)]*\)[^\{;]*\{")
_JAVA_ASSERT = re.compile(r"\b(?:assertEquals|assertTrue|assertFalse|assertNotNull|assertNull|assertThrows"
                          r"|assertSame|assertNotSame|assertArrayEquals|assertLinesMatch|assertIterableEquals|fail)\b")


def _find_java_test_files(root):
    out = []
    for dp, dn, fn in os.walk(root):
        if os.sep + "target" in dp or os.sep + ".deps" in dp:
            continue
        for f in fn:
            if f.endswith("Test.java") or f.endswith("Tests.java") or (os.sep + "test" + os.sep) in dp and f.endswith(".java"):
                out.append(os.path.join(dp, f))
    return out


def count_java(root):
    seen = set()
    n = 0
    for path in set(_find_java_test_files(root)):
        try:
            src = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for m in _JAVA_TEST.finditer(src):
            body = src[m.end() - 1:_match_brace(src, m.end() - 1)]
            if not _JAVA_ASSERT.search(body):
                continue
            key = hashlib.md5(re.sub(r"\s+", "", body).encode("utf-8")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            n += 1
    return n


def count_all(root):
    return count(root) + count_js(root) + count_go(root) + count_java(root)


def run(args):
    if len(args) != 1 or not os.path.isdir(args[0]):
        sys.stderr.write("usage: vurnix coverage <dir>\n")
        return 2
    n = count_all(args[0])
    print(n)
    return 0 if n else 3
