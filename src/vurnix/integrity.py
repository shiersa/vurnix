"""Anti-weakening test guard.

An AI coding agent asked to "make the tests pass" can do it the dishonest way: delete a
failing assert, add ``@pytest.mark.skip`` / ``xfail``, turn an assert always-true, or drop
the whole test function. This guard catches that deterministically — no model in the loop.

Usage::

    vurnix integrity snapshot <test_file>                  # prints a JSON signature
    vurnix integrity compare  <before_sig.json> <after_test_file>

Exit codes for ``compare``: 0 = not weakened (asserts / test functions preserved, no new
skip/xfail/always-true), 1 = WEAKENED (reasons on stderr), 2 = usage / unparseable input.

Delta-based: a skip or always-true assert that was ALREADY in the before-snapshot is fine —
only a NEW one, or a DROP in asserts / test functions, flags weakening. A genuine spec
change that legitimately removes a test is the caller's decision to allow; this guard only
reports the mechanical fact. Pure AST for Python; JS/Go/Java signatures are regex-computed
with the same shape, dispatched on the test file's extension. Stdlib only.
"""

import ast
import json
import re
import sys


def signature(src):
    tree = ast.parse(src)
    sig = {"asserts": 0, "test_funcs": 0, "skips": 0, "xfails": 0, "alwaystrue": 0,
           "test_names": []}
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            sig["asserts"] += 1
            t = node.test
            if isinstance(t, ast.Constant) and bool(t.value):     # assert True / assert 1 / assert "x"
                sig["alwaystrue"] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                sig["test_funcs"] += 1
                names.add(node.name)
        elif isinstance(node, ast.Attribute):                     # pytest.mark.skip / .xfail / pytest.skip()
            if node.attr == "xfail":
                sig["xfails"] += 1
            elif node.attr in ("skip", "skipif"):
                sig["skips"] += 1
        elif isinstance(node, ast.Name):
            if node.id == "xfail":
                sig["xfails"] += 1
            elif node.id in ("skip", "skipif"):
                sig["skips"] += 1
    sig["test_names"] = sorted(names)
    return sig


# count one per assertion: `assert.X(` / `assert(` / `expect(` (NOT the `require('node:assert')` line,
# and not double-counting the method name after `assert.`). Covers node:assert, node:test t.assert, chai/jest expect.
_JS_ASSERT = re.compile(r"\bassert\s*[.(]|\bexpect\s*\(")
# test('x', ...) / it('x', ...) — and their skipped/todo/only variants (still test declarations)
_JS_TESTFN = re.compile(r"\b(?:test|it)\s*(?:\.\s*(?:skip|todo|only|concurrent)\s*)?\(")
_JS_TESTNAME = re.compile(r"""\b(?:test|it)\s*(?:\.\s*\w+\s*)?\(\s*(['"`])(?P<name>(?:\\.|(?!\1).)*?)\1""", re.S)
_JS_SKIP = re.compile(r"\b(?:test|it|describe)\s*\.\s*skip\b|\bskip\s*:\s*true\b")
_JS_TODO = re.compile(r"\b(?:test|it)\s*\.\s*todo\b|\btodo\s*:\s*true\b")
# always-true assertions that prove nothing
_JS_ALWAYSTRUE = re.compile(
    r"assert\s*\(\s*true\s*\)|assert\.ok\s*\(\s*true\s*\)|assert\.strictEqual\s*\(\s*true\s*,\s*true\s*\)"
    r"|expect\s*\(\s*true\s*\)\s*\.\s*to"
)


def js_signature(src):
    return {
        "asserts": len(_JS_ASSERT.findall(src)),
        "test_funcs": len(_JS_TESTFN.findall(src)),
        "skips": len(_JS_SKIP.findall(src)),
        "xfails": len(_JS_TODO.findall(src)),
        "alwaystrue": len(_JS_ALWAYSTRUE.findall(src)),
        "test_names": sorted({m.group("name") for m in _JS_TESTNAME.finditer(src)}),
    }


# Go: asserts = t.Error*/t.Fatal*/t.Fail*; test funcs = func TestXxx; skips = t.Skip*. Go has no
# xfail/`assert True` idiom (a weakened test that swaps t.Fatalf for t.Logf just drops an assert
# -> caught by the asserts-dropped delta).
_GO_ASSERT_SIG = re.compile(r"\bt\.(?:Error|Errorf|Fatal|Fatalf|Fail|FailNow)\b")
_GO_TESTFN_SIG = re.compile(r"\bfunc\s+(Test\w+)\s*\(")
_GO_SKIP_SIG = re.compile(r"\bt\.(?:Skip|Skipf|SkipNow)\b")


def go_signature(src):
    return {
        "asserts": len(_GO_ASSERT_SIG.findall(src)),
        "test_funcs": len(_GO_TESTFN_SIG.findall(src)),
        "skips": len(_GO_SKIP_SIG.findall(src)),
        "xfails": 0,
        "alwaystrue": 0,
        "test_names": sorted(set(_GO_TESTFN_SIG.findall(src))),
    }


# Java: asserts = JUnit assert*/fail; test funcs = @Test methods; skips = @Disabled/assume*.
_JAVA_ASSERT_SIG = re.compile(r"\b(?:assertEquals|assertTrue|assertFalse|assertNotNull|assertNull|assertThrows"
                              r"|assertSame|assertNotSame|assertArrayEquals|assertLinesMatch|assertIterableEquals|fail)\b")
_JAVA_TESTFN_SIG = re.compile(r"@Test\b")
_JAVA_TESTNAME_SIG = re.compile(r"@Test\b[^\{;]*?\bvoid\s+(\w+)\s*\(")
_JAVA_SKIP_SIG = re.compile(r"@Disabled\b|\bassumeTrue\b|\bassumeFalse\b")


def java_signature(src):
    return {
        "asserts": len(_JAVA_ASSERT_SIG.findall(src)),
        "test_funcs": len(_JAVA_TESTFN_SIG.findall(src)),
        "skips": len(_JAVA_SKIP_SIG.findall(src)),
        "xfails": 0,
        "alwaystrue": 0,
        "test_names": sorted(set(_JAVA_TESTNAME_SIG.findall(src))),
    }


def signature_for(path, src):
    """Pick the regex signature by test-file extension (JS / Go / Java), else the Python AST signature."""
    if path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
        return js_signature(src)
    if path.endswith(".go"):
        return go_signature(src)
    if path.endswith(".java"):
        return java_signature(src)
    return signature(src)


def weakening_reasons(before, after):
    r = []
    if after["asserts"] < before["asserts"]:
        r.append("asserts dropped %d -> %d" % (before["asserts"], after["asserts"]))
    if after["test_funcs"] < before["test_funcs"]:
        missing = sorted(set(before.get("test_names", [])) - set(after.get("test_names", [])))
        which = (": %s" % ", ".join(missing)) if missing else ""
        r.append("test function(s) deleted/missing%s (%d -> %d)"
                 % (which, before["test_funcs"], after["test_funcs"]))
    if after["skips"] > before["skips"]:
        r.append("new skip/skipif added (%d -> %d)" % (before["skips"], after["skips"]))
    if after["xfails"] > before["xfails"]:
        r.append("new xfail added (%d -> %d)" % (before["xfails"], after["xfails"]))
    if after["alwaystrue"] > before["alwaystrue"]:
        r.append("new always-true assert (%d -> %d)" % (before["alwaystrue"], after["alwaystrue"]))
    return r


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run(args):
    if len(args) >= 2 and args[0] == "snapshot":
        try:
            print(json.dumps(signature_for(args[1], _read(args[1]))))
        except (OSError, SyntaxError, ValueError) as e:
            sys.stderr.write("integrity: cannot snapshot %s: %s\n" % (args[1], e))
            return 2
        return 0
    if len(args) >= 3 and args[0] == "compare":
        try:
            before = json.loads(_read(args[1]))
            after = signature_for(args[2], _read(args[2]))
        except (OSError, SyntaxError, ValueError) as e:
            sys.stderr.write("integrity: compare failed: %s\n" % e)
            return 2
        reasons = weakening_reasons(before, after)
        if reasons:
            for r in reasons:
                sys.stderr.write("WEAKENED: %s\n" % r)
            sys.stderr.write("integrity: test file WEAKENED — do NOT count this round as fixed.\n")
            return 1
        sys.stderr.write("integrity: OK — tests not weakened (asserts=%d, test_funcs=%d).\n"
                         % (after["asserts"], after["test_funcs"]))
        return 0
    sys.stderr.write("usage: vurnix integrity snapshot <file> | compare <before.json> <after_file>\n")
    return 2
