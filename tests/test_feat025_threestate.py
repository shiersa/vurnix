"""FEAT-025 P1 验收测试（test-author 独立产出，仅由 spec + 公开契约推导）。

实现者禁改本文件（恒态红线 §二6）；修订仅限已确认 spec 变更或夹具损坏经 reviewer 会签。
预期先红：0.3.0 三态判决（PASS/BLOCK/UNPROVEN）未实现前，本文件多数断言应失败。

AC → 测试映射（FEAT-025 P1，AC7 属 P2 不在本文件）
=============
AC1  判决枚举全局契约（PASS=0 / BLOCK=1 / usage=2 / UNPROVEN=3；
     fail-dominant：BLOCK > UNPROVEN > PASS）:
     test_ac1_gate_block_dominates_unproven
     test_ac1_usage_error_still_exits_two
     （0 与 3 的逐命令取值由下方 AC2-AC5 各测试共同钉死）
AC2  coverage 三态（计数 0 → 3 且 stdout 仍打印 0；>0 → 0；参数错误 → 2）:
     test_ac2_coverage_zero_count_exits_three_stdout_still_zero
     test_ac2_coverage_positive_count_exits_zero
     test_ac2_coverage_nonexistent_dir_usage_exits_two
AC3  compile 三态（FAIL → 1；无 FAIL 但有 SKIP / 无源文件 → 3 + UNPROVEN 字样）:
     test_ac3_compile_fail_exits_exactly_one
     test_ac3_compile_missing_toolchain_skip_exits_three_unproven
     test_ac3_compile_no_source_files_exits_three_unproven
AC4  mutation run 三态（mutant 总数 0 → 3；未变异基线红 → 3）:
     test_ac4_mutation_zero_mutants_exits_three
     test_ac4_mutation_red_baseline_exits_three
AC5  gate 三态（BLOCK → 1；compile SKIP/无源 或 测试计数 0 → RESULT: UNPROVEN
     + 逐条原因 + 3；全证 → RESULT: PASS + 0）:
     test_ac5_gate_zero_tests_unproven_exit_three
     test_ac5_gate_compile_all_skip_unproven_exit_three
     test_ac5_gate_all_proven_prints_result_pass_exit_zero
AC6  版本与文档（__version__ = 0.3.0；info 与 README 写明 0/1/2/3 契约与口号）:
     test_ac6_version_is_0_3_0
     test_ac6_info_documents_threestate_contract
     test_ac6_readme_documents_threestate_contract
"""

import os
import re
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent
SRC = REPO / "src"


# ---------------------------------------------------------------- CLI helpers


def run_cli(*args, cwd=None, env_overrides=None, timeout=180):
    """契约约定的调用方式：sys.executable -m vurnix.cli，PYTHONPATH 指向 src。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "vurnix.cli", *[str(a) for a in args]],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO),
        env=env,
        timeout=timeout,
    )


def all_output(proc):
    return proc.stdout + proc.stderr


# ------------------------------------------------------------ fixture builders
# 全部用临时目录现场构造，不依赖网络；「缺工具链」用 PATH 裁剪模拟。


def _write(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


GOOD_PY_MODULE = "def add(a, b):\n    return a + b\n"

BROKEN_PY_MODULE = "def broken(:\n    return oops\n"

REAL_PY_TEST = (
    "def test_add():\n"
    "    assert 1 + 1 == 2\n"
    "\n"
    "\n"
    "def test_sub():\n"
    "    assert 5 - 3 == 2\n"
)

REAL_JS_TEST = (
    "test('multiplies numbers', () => {\n"
    "  expect(2 * 3).toBe(6);\n"
    "});\n"
)

GO_MAIN = "package main\n\nfunc main() {}\n"

# + 与 > 运算符保证存在变异点（FEAT-019 AC3 公开契约同款形状）
MUTABLE_PY_MODULE = (
    "def add(a, b):\n"
    "    return a + b\n"
    "\n"
    "\n"
    "def is_positive(x):\n"
    "    return x > 0\n"
)


def _empty_path_env(tmp_path):
    """PATH 裁剪法：指向一个空目录，外部工具链（go/node/…）全部不可见。"""
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir(exist_ok=True)
    return {"PATH": str(empty_bin)}


# ----------------------------------------------------------- AC1 判决枚举契约


def test_ac1_gate_block_dominates_unproven(tmp_path):
    # 同一目录同时命中 BLOCK（语法错 → compile FAIL）与 UNPROVEN（零测试）：
    # fail-dominant 要求最终判决 = BLOCK，exit 必须是 1 而非 3。
    work = tmp_path / "both"
    _write(work, "broken_syntax.py", BROKEN_PY_MODULE)
    proc = run_cli("gate", work)
    assert proc.returncode == 1, (
        f"BLOCK 必须压过 UNPROVEN（BLOCK > UNPROVEN > PASS），应 exit 1，"
        f"实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert "BLOCK" in all_output(proc), (
        f"汇总里应出现 BLOCK 字样，实际输出：{all_output(proc)!r}"
    )


def test_ac1_usage_error_still_exits_two():
    # usage=2 与 UNPROVEN=3 必须互斥：缺必要参数是用法错，不得挪用 3。
    proc = run_cli("gate")
    assert proc.returncode == 2, (
        f"缺目录参数应 exit 2（usage），实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


# -------------------------------------------------------------- AC2 coverage


def test_ac2_coverage_zero_count_exits_three_stdout_still_zero(tmp_path):
    # 有源文件但零测试：计数 0 → exit 3，stdout 仍打印 0。
    work = tmp_path / "no_tests"
    _write(work, "mod.py", GOOD_PY_MODULE)
    proc = run_cli("coverage", work)
    assert proc.returncode == 3, (
        f"计数 0 应 exit 3（UNPROVEN），实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )
    out = proc.stdout.strip()
    assert out, "coverage 应在 stdout 打印一个整数"
    assert int(out.splitlines()[0]) == 0, (
        f"exit 3 时 stdout 仍应打印 0，实际输出 {proc.stdout!r}"
    )


def test_ac2_coverage_positive_count_exits_zero(tmp_path):
    work = tmp_path / "with_tests"
    _write(work, "test_math.py", REAL_PY_TEST)
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"计数 >0 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    out = proc.stdout.strip()
    assert out and int(out.splitlines()[0]) >= 1, (
        f"两个真实断言测试应计数 ≥1，实际输出 {proc.stdout!r}"
    )


def test_ac2_coverage_nonexistent_dir_usage_exits_two(tmp_path):
    # 修现行「打印 0 返回 0」缺陷：参数错误（目录不存在）→ exit 2。
    proc = run_cli("coverage", tmp_path / "does_not_exist")
    assert proc.returncode == 2, (
        f"目录不存在是参数错误，应 exit 2，实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


# --------------------------------------------------------------- AC3 compile


def test_ac3_compile_fail_exits_exactly_one(tmp_path):
    work = tmp_path / "bad"
    _write(work, "broken_syntax.py", BROKEN_PY_MODULE)
    proc = run_cli("compile", work)
    assert proc.returncode == 1, (
        f"任一 FAIL 应 exit 1（BLOCK），实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


def test_ac3_compile_missing_toolchain_skip_exits_three_unproven(tmp_path):
    # 仅 .go 文件 + PATH 裁剪：无 FAIL 但存在 SKIP → exit 3 且输出含 UNPROVEN。
    work = tmp_path / "go_only"
    _write(work, "main.go", GO_MAIN)
    proc = run_cli("compile", work, env_overrides=_empty_path_env(tmp_path))
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"缺工具链（SKIP，无 FAIL）应 exit 3，实际 {proc.returncode}；"
        f"输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"输出必须含 UNPROVEN 字样，实际：{out!r}"
    assert "Traceback" not in out, f"缺工具链不应崩溃，实际输出：{out!r}"


def test_ac3_compile_no_source_files_exits_three_unproven(tmp_path):
    # 目录无任何可编译源文件（仅 .txt）→ 什么都没查过 = UNPROVEN。
    work = tmp_path / "no_sources"
    _write(work, "notes.txt", "no source files here\n")
    proc = run_cli("compile", work)
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"无源文件应 exit 3，实际 {proc.returncode}；输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"输出必须含 UNPROVEN 字样，实际：{out!r}"


# ---------------------------------------------------------- AC4 mutation run


def test_ac4_mutation_zero_mutants_exits_three(tmp_path):
    # 空 .py 文件 = 必然零变异点；废除现行 total=0 时 score=1.0 → exit 0。
    target = tmp_path / "empty_module.py"
    target.write_text("", encoding="utf-8")
    proc = run_cli(
        "mutation", "run", target, "--max", "10",
        "--", sys.executable, "-c", "pass",
    )
    assert proc.returncode == 3, (
        f"mutant 总数 0 应 exit 3（UNPROVEN），实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


def test_ac4_mutation_red_baseline_exits_three(tmp_path):
    # 变异前未变异基线必须先跑：test-cmd 必然非零退出 → 基线红 → exit 3。
    target = _write(tmp_path / "src", "calc.py", MUTABLE_PY_MODULE)
    mutants = run_cli("mutation", "mutants", target)
    assert mutants.returncode == 0 and mutants.stdout.strip(), (
        "前置守卫：+ 与 > 应产生非空变异点列表（FEAT-019 公开契约），"
        f"实际输出：{mutants.stdout!r}"
    )
    proc = run_cli(
        "mutation", "run", target, "--max", "10",
        "--", sys.executable, "-c", "raise SystemExit(1)",
    )
    assert proc.returncode == 3, (
        f"基线已红（无法度量杀伤）应 exit 3，实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


# ------------------------------------------------------------------ AC5 gate


def _unproven_reason_lines(out):
    """RESULT 行之外、提及 UNPROVEN 成因的行（逐条原因契约）。"""
    return [
        line for line in out.splitlines()
        if "RESULT:" not in line and line.strip()
        and re.search(r"(?i)unproven|coverage|tests?|compile|skip", line)
    ]


def test_ac5_gate_zero_tests_unproven_exit_three(tmp_path):
    # 有源文件、compile 可查、但测试计数 0 → RESULT: UNPROVEN + 原因 + exit 3。
    work = tmp_path / "no_tests"
    _write(work, "mod.py", GOOD_PY_MODULE)
    proc = run_cli("gate", work)
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"零测试目录 gate 应 exit 3，实际 {proc.returncode}；输出：{out!r}"
    )
    assert "RESULT: UNPROVEN" in out, (
        f"应打印 'RESULT: UNPROVEN'，实际输出：{out!r}"
    )
    reasons = _unproven_reason_lines(out)
    assert reasons, f"UNPROVEN 必须带逐条原因行，实际输出：{out!r}"


def test_ac5_gate_compile_all_skip_unproven_exit_three(tmp_path):
    # 仅 .js（含真实断言测试，coverage >0）+ PATH 裁剪 → compile 全 SKIP →
    # RESULT: UNPROVEN + exit 3（原因应指向 compile/SKIP 而非测试计数）。
    work = tmp_path / "js_only"
    _write(work, "sample.test.js", REAL_JS_TEST)
    proc = run_cli("gate", work, env_overrides=_empty_path_env(tmp_path))
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"compile 全 SKIP 的 gate 应 exit 3，实际 {proc.returncode}；"
        f"输出：{out!r}"
    )
    assert "RESULT: UNPROVEN" in out, (
        f"应打印 'RESULT: UNPROVEN'，实际输出：{out!r}"
    )
    assert re.search(r"(?i)compile|skip", out), (
        f"原因应提及 compile/SKIP，实际输出：{out!r}"
    )


def test_ac5_gate_all_proven_prints_result_pass_exit_zero(tmp_path):
    # 全证路径：py 源 + 真实断言测试，compile 无 SKIP → RESULT: PASS + exit 0。
    work = tmp_path / "proven"
    _write(work, "calc.py", GOOD_PY_MODULE)
    _write(
        work,
        "test_calc.py",
        "from calc import add\n"
        "\n"
        "\n"
        "def test_add():\n"
        "    assert add(2, 3) == 5\n"
        "\n"
        "\n"
        "def test_add_negative():\n"
        "    assert add(-1, -2) == -3\n",
    )
    proc = run_cli("gate", work)
    out = all_output(proc)
    assert proc.returncode == 0, (
        f"全证目录 gate 应 exit 0，实际 {proc.returncode}；输出：{out!r}"
    )
    assert "RESULT: PASS" in out, (
        f"应打印 'RESULT: PASS'，实际输出：{out!r}"
    )


# ------------------------------------------------------------ AC6 版本与文档


def test_ac6_version_is_0_3_0():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", "import vurnix; print(vurnix.__version__)"],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout.strip() == "0.3.0", (
        f"__version__ 应为 0.3.0，实际 {proc.stdout.strip()!r}"
    )


def test_ac6_info_documents_threestate_contract():
    proc = run_cli("info")
    assert proc.returncode == 0, (
        f"info 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    out = all_output(proc)
    for token in ("UNPROVEN", "BLOCK", "PASS"):
        assert token in out, f"info 应写明三态判决（缺 {token}）：{out!r}"
    assert "3" in out, f"info 应写明 UNPROVEN=exit 3 的契约：{out!r}"
    # 口号按两段核心子串断言，避免连接符（—/-）排版差异造成脆断
    assert "a check that cannot run" in out, f"info 应含口号前半句：{out!r}"
    assert "enforced by exit code" in out, f"info 应含口号后半句：{out!r}"


def test_ac6_readme_documents_threestate_contract():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "UNPROVEN" in readme, "README 应写明 UNPROVEN 判决"
    assert "a check that cannot run" in readme, "README 应含口号前半句"
    assert "enforced by exit code" in readme, "README 应含口号后半句"
