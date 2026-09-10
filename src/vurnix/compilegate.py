"""Thin compile gate: does the code even build? Dispatched by file extension.

A test suite can be green while a sibling file never compiles (nothing imports it), and a
"tests passed" claim on top of code that does not build is the cheapest kind of false
green. This runs the cheapest honest build check per language:

- Python: ``compile()`` every ``.py`` (syntax; no artifacts written, nothing executed)
- JS: ``node --check`` every ``.js/.mjs/.cjs``
- Go: ``go vet ./...`` (requires a ``go.mod`` for module context)
- Java: ``mvn -q -DskipTests compile`` when a ``pom.xml`` is present, else ``javac``

HONESTY RULE: a language whose toolchain is unavailable is reported ``SKIP`` with the
reason — never silently counted as OK. A check that cannot run is not a check that passed.

Usage::

    vurnix compile <dir>      # exit 0 = everything checked compiles; 1 = failures;
                              # 3 = UNPROVEN (skipped checks / no sources — nothing
                              # was actually proven); 2 = usage
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

_SKIP_DIRS = {'.deps', 'node_modules', '__pycache__', '.venv', 'venv', 'vendor', 'target',
              'site-packages', '.pw-browsers', 'dist', 'build'}
_TIMEOUT = 240


def _collect(root):
    py, js, ts, go, java = [], [], [], [], []
    for dp, dn, fn in os.walk(root):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS and not d.startswith('.')]
        for f in fn:
            p = os.path.join(dp, f)
            if f.endswith('.py'):
                py.append(p)
            elif f.endswith(('.js', '.mjs', '.cjs')):
                js.append(p)
            elif f.endswith(('.ts', '.tsx')) and not f.endswith(('.d.ts', '-d.ts')):
                # .d.ts / *-d.ts are ambient type declarations and tsd-style type tests —
                # no runtime code, not "unchecked source"
                ts.append(p)
            elif f.endswith('.go'):
                go.append(p)
            elif f.endswith('.java'):
                java.append(p)
    return sorted(py), sorted(js), sorted(ts), sorted(go), sorted(java)


def _javac_works():
    """which() alone lies on macOS: /usr/bin/javac exists as a stub that errors with
    'Unable to locate a Java Runtime' when no JDK is installed. Probe it for real."""
    if shutil.which('javac') is None:
        return False
    rc, _ = _run(['javac', '-version'])
    return rc == 0


def _run(cmd, cwd=None):
    """-> (rc, combined-output). rc 124 on timeout (reported as a failure, not a pass)."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT)
        return p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out after %ds" % _TIMEOUT


def check(root):
    """-> (report_lines, failure_count, skip_count). A SKIP is never counted as OK — the
    skip_count lets callers turn "checks that did not run" into an UNPROVEN verdict."""
    root = os.path.abspath(root)
    py, js, ts, go, java = _collect(root)
    lines = []
    failures = 0
    skips = 0

    if py:
        bad = []
        for f in py:
            try:
                compile(open(f, encoding='utf-8', errors='ignore').read(), f, 'exec')
            except SyntaxError as e:
                bad.append("  py FAIL %s: %s (line %s)" % (os.path.relpath(f, root), e.msg, e.lineno))
        if bad:
            lines.append("compile py: FAIL (%d of %d file(s))" % (len(bad), len(py)))
            lines.extend(bad)
            failures += len(bad)
        else:
            lines.append("compile py: OK (%d file(s))" % len(py))

    if js:
        if shutil.which('node') is None:
            lines.append("compile js: SKIP (node toolchain not found — %d file(s) NOT checked)" % len(js))
            skips += 1
        else:
            bad = []
            for f in js:
                rc, out = _run(['node', '--check', f])
                if rc == 124:
                    lines.append("compile js: SKIP (%s timed out — NOT checked)" % os.path.relpath(f, root))
                    skips += 1
                elif rc != 0:
                    bad.append("  js FAIL %s: %s" % (os.path.relpath(f, root), out.splitlines()[-1] if out else "rc=%d" % rc))
            if bad:
                lines.append("compile js: FAIL (%d of %d file(s))" % (len(bad), len(js)))
                lines.extend(bad)
                failures += len(bad)
            else:
                lines.append("compile js: OK (%d file(s))" % len(js))

    if ts:
        # TypeScript honestly needs the PROJECT'S compiler+config: per-file tsc without the
        # project's types would fail on every import (environment, not code).
        tsconfig = os.path.isfile(os.path.join(root, 'tsconfig.json'))
        if shutil.which('tsc') is None:
            lines.append("compile ts: SKIP (tsc/TypeScript compiler not found — %d file(s) NOT checked)" % len(ts))
            skips += 1
        elif not tsconfig:
            lines.append("compile ts: SKIP (no tsconfig.json — no project context for tsc; %d file(s) NOT checked)" % len(ts))
            skips += 1
        else:
            rc, out = _run(['tsc', '--noEmit', '-p', root], cwd=root)
            if rc == 124:
                lines.append("compile ts: SKIP (tsc timed out after %ds — %d file(s) NOT checked)" % (_TIMEOUT, len(ts)))
                skips += 1
            elif rc != 0:
                errs = [ln for ln in out.splitlines() if re.search(r'error TS\d+', ln)]
                # TS2307/TS2688/TS7016: cannot find module / type declarations — the
                # dependencies aren't installed here; that's the environment, not the code
                env_only = errs and all(re.search(r'error TS(2307|2688|7016)\b', ln) for ln in errs)
                if env_only:
                    lines.append("compile ts: SKIP (tsc only reports unresolvable modules — "
                                 "dependencies not installed here; %d file(s) NOT checked)" % len(ts))
                    skips += 1
                else:
                    lines.append("compile ts: FAIL (tsc --noEmit)")
                    for ln in (errs or out.splitlines())[:20]:
                        lines.append("  ts %s" % ln)
                    failures += 1
            else:
                lines.append("compile ts: OK (tsc, %d file(s))" % len(ts))

    if go:
        if shutil.which('go') is None:
            lines.append("compile go: SKIP (go toolchain not found — %d file(s) NOT checked)" % len(go))
            skips += 1
        elif not os.path.isfile(os.path.join(root, 'go.mod')):
            lines.append("compile go: SKIP (no go.mod — no module context to build in; %d file(s) NOT checked)" % len(go))
            skips += 1
        else:
            rc, out = _run(['go', 'vet', './...'], cwd=root)
            if rc == 124:
                # a vet run that never finished (usually fetching modules) proved nothing —
                # that is UNPROVEN, not a code failure
                lines.append("compile go: SKIP (go vet timed out after %ds — %d file(s) NOT checked)" % (_TIMEOUT, len(go)))
                skips += 1
            elif rc != 0:
                lines.append("compile go: FAIL")
                for ln in out.splitlines()[:20]:
                    lines.append("  go %s" % ln)
                failures += 1
            else:
                lines.append("compile go: OK (%d file(s))" % len(go))

    if java:
        pom = os.path.isfile(os.path.join(root, 'pom.xml'))
        if pom and shutil.which('mvn'):
            rc, out = _run(['mvn', '-q', '-DskipTests', 'compile'], cwd=root)
            if rc == 124:
                lines.append("compile java: SKIP (mvn timed out after %ds — %d file(s) NOT checked)" % (_TIMEOUT, len(java)))
                skips += 1
            elif rc != 0:
                lines.append("compile java: FAIL (mvn compile)")
                for ln in out.splitlines()[:20]:
                    lines.append("  java %s" % ln)
                failures += 1
            else:
                lines.append("compile java: OK (mvn, %d file(s))" % len(java))
        elif pom:
            # a Maven project without mvn: raw javac has no classpath, so every dependency
            # import "fails" — that verdict would be about the environment, not the code
            lines.append("compile java: SKIP (pom.xml present but no mvn — javac without a "
                         "classpath proves nothing; %d file(s) NOT checked)" % len(java))
            skips += 1
        elif os.path.isfile(os.path.join(root, 'build.gradle')) or \
                os.path.isfile(os.path.join(root, 'build.gradle.kts')):
            # same reasoning for Gradle projects: compiling outside the build tool proves nothing
            lines.append("compile java: SKIP (gradle project — compiling outside Gradle "
                         "proves nothing; %d file(s) NOT checked)" % len(java))
            skips += 1
        elif _javac_works():
            with tempfile.TemporaryDirectory() as tmp:
                rc, out = _run(['javac', '-d', tmp] + java)
            if rc == 124:
                lines.append("compile java: SKIP (javac timed out after %ds — %d file(s) NOT checked)" % (_TIMEOUT, len(java)))
                skips += 1
            elif rc != 0:
                lines.append("compile java: FAIL (javac)")
                for ln in out.splitlines()[:20]:
                    lines.append("  java %s" % ln)
                failures += 1
            else:
                lines.append("compile java: OK (javac, %d file(s))" % len(java))
        else:
            lines.append("compile java: SKIP (no working mvn/javac toolchain — %d file(s) NOT checked)" % len(java))
            skips += 1

    if not lines:
        lines.append("compile: SKIP (no source files found under %s — nothing to prove)" % root)
        skips += 1
    return lines, failures, skips


def run(args):
    if len(args) != 1:
        sys.stderr.write("usage: vurnix compile <dir>\n")
        return 2
    if not os.path.isdir(args[0]):
        sys.stderr.write("compile: not a directory: %s\n" % args[0])
        return 2
    lines, failures, skips = check(args[0])
    for ln in lines:
        print(ln)
    if failures:
        return 1
    if skips:
        print("compile: UNPROVEN — %d check(s) did not run; a check that cannot run "
              "is not a check that passed" % skips)
        return 3
    return 0
