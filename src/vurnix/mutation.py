"""Mutation testing: measure test STRENGTH (do the tests actually catch bugs?).

Complements the anti-weakening guard (which only stops tests getting *weaker*): mutate the
implementation, run the tests — a mutant the tests still PASS on "survived" and marks a
test gap. SIGNAL by default (report + exit 0); ``--strict --threshold P`` fails when the
mutation score < P. Pure stdlib AST mutator — no mutmut/cosmic-ray dependency.

Two UNPROVEN conditions (exit 3, never a pass): the un-mutated baseline test command
already fails (a red baseline "kills" every mutant — the score would be a lie), and zero
mutants generated (nothing measured).

Usage::

    vurnix mutation mutants <file>
        # list the mutants it would generate (deterministic, no test run)
    vurnix mutation run <dir_or_file> [--max N] [--strict --threshold P] -- <test-cmd...>
        # for each mutant: apply -> run <test-cmd> (in cwd) -> restore. rc!=0 = killed,
        # rc==0 = survived. reports score = killed/total. --max bounds the run.

Python operators (one mutant per site): comparison (== <-> !=, < <-> >=, > <-> <=),
identity (is <-> is not), boolean (and <-> or), arithmetic (+ <-> -, * <-> /) on BinOp and
AugAssign, boolean constants (True <-> False), numeric constants (n -> n+1: status codes /
lengths / boundaries), and ``return <expr>`` -> ``return None`` (catches tests that never
check the returned value). JS/Go/Java are C-family: mutated by regex over a copy with
strings/comments masked, using conservative high-signal operators only.
"""

import ast
import os
import re
import subprocess
import sys

_CMP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt, ast.Gt: ast.LtE, ast.LtE: ast.Gt,
        ast.Is: ast.IsNot, ast.IsNot: ast.Is}
_BOOL = {ast.And: ast.Or, ast.Or: ast.And}
_BIN = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.Div, ast.Div: ast.Mult}
_NAME = {ast.Eq: '==', ast.NotEq: '!=', ast.Lt: '<', ast.GtE: '>=', ast.Gt: '>', ast.LtE: '<=',
         ast.Is: 'is', ast.IsNot: 'is not',
         ast.And: 'and', ast.Or: 'or', ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.Div: '/'}


def generate_mutants(src):
    """Return [(description, mutated_source)], one per mutation site. Deterministic. Mutates the tree
    in place, unparses, then reverts — so each mutant differs from the original at exactly one node."""
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                sw = _CMP.get(type(op))
                if not sw:
                    continue
                node.ops[i] = sw()
                out.append(("line %d: %s -> %s" % (getattr(node, 'lineno', 0), _NAME[type(op)], _NAME[sw]),
                            ast.unparse(tree)))
                node.ops[i] = op
        elif isinstance(node, ast.BoolOp):
            sw = _BOOL.get(type(node.op))
            if sw:
                orig = node.op
                node.op = sw()
                out.append(("line %d: %s -> %s" % (getattr(node, 'lineno', 0), _NAME[type(orig)], _NAME[sw]),
                            ast.unparse(tree)))
                node.op = orig
        elif isinstance(node, ast.BinOp):
            sw = _BIN.get(type(node.op))
            if sw:
                orig = node.op
                node.op = sw()
                out.append(("line %d: %s -> %s" % (getattr(node, 'lineno', 0), _NAME[type(orig)], _NAME[sw]),
                            ast.unparse(tree)))
                node.op = orig
        elif isinstance(node, ast.AugAssign) and type(node.op) in _BIN:
            orig = node.op
            node.op = _BIN[type(orig)]()
            out.append(("line %d: %s= -> %s=" % (getattr(node, 'lineno', 0), _NAME[type(orig)], _NAME[type(node.op)]),
                        ast.unparse(tree)))
            node.op = orig
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            orig = node.value
            node.value = not orig
            out.append(("line %d: %s -> %s" % (getattr(node, 'lineno', 0), orig, not orig), ast.unparse(tree)))
            node.value = orig
        elif isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            # numeric literal n -> n+1: catches status codes / lengths / boundaries a shallow test misses
            # (e.g. asserts 200 but code returns 201; range(6) -> range(7) -> 7-char code)
            orig = node.value
            node.value = orig + 1
            out.append(("line %d: %r -> %r" % (getattr(node, 'lineno', 0), orig, orig + 1), ast.unparse(tree)))
            node.value = orig
        elif isinstance(node, ast.Return) and node.value is not None \
                and not (isinstance(node.value, ast.Constant) and node.value.value is None):
            # return <expr> -> return None: catches tests that never check the returned value
            orig = node.value
            node.value = ast.Constant(value=None)
            out.append(("line %d: return <expr> -> return None" % getattr(node, 'lineno', 0), ast.unparse(tree)))
            node.value = orig
    return out


# ---- C-family mutation (JS/Go/Java) — no stdlib AST for these, so regex over a copy with
# strings/comments MASKED (equal-length filler) to avoid mutating operators inside a URL/regex/comment.
# CONSERVATIVE, high-signal, low-false-survivor operators only: comparisons, &&/||, true/false, n->n+1.
# Arithmetic (+ - * /) and `return x -> null` are SKIPPED: `/` collides with regex literals and a
# void handler's `return` is an equivalent mutant (false survivor -> false BLOCK). A mutant that
# breaks the syntax just fails the test run => counted killed (the safe direction). ----
def _mask_c_family(src):
    """Return src with the CONTENTS of string literals (' " `) and comments (// , /* */) replaced by 'X'
    (delimiters + newlines preserved, length unchanged) so operator sites are found only in real code."""
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] != "\n":
                    out[j] = "X"
                j += 1
            i = j + 1
        elif c == "/" and i + 1 < n and src[i + 1] == "/":
            j = i + 2
            while j < n and src[j] != "\n":
                out[j] = "X"
                j += 1
            i = j
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            j = i + 2
            while j < n and not (src[j] == "*" and j + 1 < n and src[j + 1] == "/"):
                if src[j] != "\n":
                    out[j] = "X"
                j += 1
            i = j + 2
        else:
            i += 1
    return "".join(out)


# alternation ordered longest-first so `===` wins over `==`; finditer is non-overlapping
_C_OP_RE = re.compile(r"===|!==|==|!=|<=|>=|&&|\|\||<|>|\btrue\b|\bfalse\b|\b\d+\b")
_C_SWAP = {"===": "!==", "!==": "===", "==": "!=", "!=": "==",
           "<=": ">", ">=": "<", "<": ">=", ">": "<=",
           "&&": "||", "||": "&&", "true": "false", "false": "true"}


def generate_c_family_mutants(src):
    masked = _mask_c_family(src)
    out = []
    for m in _C_OP_RE.finditer(masked):
        tok = m.group(0)
        s, e = m.start(), m.end()
        if tok in ("<", ">"):
            # skip arrow `=>` and any `<=/>=/=>` neighbourhood (a broken arrow is just noise)
            if s > 0 and masked[s - 1] == "=":
                continue
            if e < len(masked) and masked[e] == "=":
                continue
        if tok.isdigit():
            rep = str(int(tok) + 1)
            label = "%s -> %s" % (tok, rep)
        else:
            rep = _C_SWAP[tok]
            label = "%s -> %s" % (tok, rep)
        line = src.count("\n", 0, s) + 1
        out.append(("line %d: %s" % (line, label), src[:s] + rep + src[e:]))
    return out


def generate_mutants_for(src, path):
    # Go/Java are C-family: same operator tokens (== != < > <= >= && || true false) and the same
    # string/comment masking as JS, so the regex mutator applies verbatim.
    if path and path.endswith((".js", ".jsx", ".mjs", ".cjs", ".ts", ".go", ".java")):
        return generate_c_family_mutants(src)
    return generate_mutants(src)


def _impl_files(target):
    if os.path.isfile(target):
        return [target]
    files = []
    for root, _, names in os.walk(target):
        if '/.deps' in root or root.endswith('/.deps') or '__pycache__' in root or '/node_modules' in root:
            continue
        for n in names:
            if n.endswith('.py') and not n.startswith('test_') and not n.endswith('_test.py') and n != 'conftest.py':
                files.append(os.path.join(root, n))
            elif (n.endswith('.js') or n.endswith('.mjs') or n.endswith('.cjs')) \
                    and not n.endswith('.test.js') and not n.endswith('.spec.js') and n != 'conftest.js':
                files.append(os.path.join(root, n))
            elif n.endswith('.go') and not n.endswith('_test.go') and '/vendor/' not in root:
                files.append(os.path.join(root, n))
            elif n.endswith('.java') and not n.endswith('Test.java') and not n.endswith('Tests.java') \
                    and (os.sep + 'test' + os.sep) not in root and (os.sep + 'target' + os.sep) not in root:
                files.append(os.path.join(root, n))
    return sorted(files)


def run_mode(target, test_cmd, max_mutants, strict, threshold):
    # A red baseline makes every mutant look "killed" — the score would be a lie. Measure
    # only from green; anything else is UNPROVEN (exit 3), not a pass.
    baseline_rc = subprocess.call(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if baseline_rc != 0:
        sys.stderr.write("mutation: UNPROVEN — baseline test command fails before any "
                         "mutation (rc=%d); kill rate is unmeasurable on a red baseline\n" % baseline_rc)
        return 3
    killed = survived = 0
    survivors = []
    stop = False
    for f in _impl_files(target):
        try:
            with open(f, encoding='utf-8') as fh:
                src = fh.read()
            muts = generate_mutants_for(src, f)
        except (OSError, SyntaxError):
            continue
        for desc, msrc in muts:
            if max_mutants and (killed + survived) >= max_mutants:
                stop = True
                break
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write(msrc)
            try:
                rc = subprocess.call(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            finally:
                with open(f, 'w', encoding='utf-8') as fh:
                    fh.write(src)                       # ALWAYS restore
            if rc != 0:
                killed += 1
            else:
                survived += 1
                survivors.append("%s %s" % (f, desc))
        if stop:
            break
    total = killed + survived
    if total == 0:
        sys.stderr.write("mutation: UNPROVEN — 0 mutants generated; test strength was "
                         "not measured (unmeasured is not passing)\n")
        return 3
    score = killed / total
    sys.stderr.write("mutation: %d/%d killed — score %.0f%%%s\n"
                     % (killed, total, 100 * score, " (bounded by --max)" if stop else ""))
    if survivors:
        sys.stderr.write("SURVIVED (tests did NOT catch these mutations — test-strength gaps):\n")
        for s in survivors:
            sys.stderr.write("  - %s\n" % s)
    if strict and total and score < threshold:
        sys.stderr.write("mutation: FAIL — score %.0f%% < threshold %.0f%% (--strict)\n" % (100 * score, 100 * threshold))
        return 1
    return 0


def run(args):
    if len(args) >= 2 and args[0] == "mutants":
        try:
            with open(args[1], encoding='utf-8') as f:
                muts = generate_mutants_for(f.read(), args[1])
        except (OSError, SyntaxError) as e:
            sys.stderr.write("mutation: cannot read/parse %s: %s\n" % (args[1], e))
            return 2
        for desc, _ in muts:
            print("MUTANT %s" % desc)
        sys.stderr.write("mutation: %d mutant(s)\n" % len(muts))
        return 0
    if len(args) >= 2 and args[0] == "run" and "--" in args:
        sep = args.index("--")
        opts, test_cmd = args[1:sep], args[sep + 1:]
        if not test_cmd or not opts:
            sys.stderr.write("error: usage: vurnix mutation run <dir> [--max N] [--strict --threshold P] -- <test-cmd...>\n")
            return 2
        target = opts[0]
        max_mutants = int(opts[opts.index("--max") + 1]) if "--max" in opts else 50
        strict = "--strict" in opts
        threshold = float(opts[opts.index("--threshold") + 1]) if "--threshold" in opts else 0.0
        return run_mode(target, test_cmd, max_mutants, strict, threshold)
    sys.stderr.write("usage: vurnix mutation mutants <file> | run <dir> [--max N] "
                     "[--strict --threshold P] -- <test-cmd...>\n")
    return 2
