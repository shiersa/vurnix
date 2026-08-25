"""FEAT-019 验收测试（test-author 独立产出，仅由 spec + 公开契约推导）。

实现者禁改本文件（恒态红线 §二6）；修订仅限已确认 spec 变更或夹具损坏经 reviewer 会签。

AC → 测试映射
=============
AC1  integrity snapshot|compare（反弱化守卫，delta 语义，py + js）:
     test_ac1_snapshot_outputs_json_signature
     test_ac1_compare_unchanged_with_preexisting_skip_exits_zero
     test_ac1_compare_strengthened_file_exits_zero
     test_ac1_integrity_detects_deleted_assert
     test_ac1_integrity_detects_added_skip
     test_ac1_integrity_detects_added_xfail
     test_ac1_integrity_detects_trivialized_assert
     test_ac1_integrity_detects_deleted_test_function
     test_ac1_js_compare_unchanged_exits_zero
     test_ac1_js_detects_deleted_expect
     test_ac1_compare_missing_args_exits_two
     test_ac1_compare_garbage_signature_exits_two
     test_ac1_snapshot_unparseable_source_exits_two
AC2  coverage（去重 + 非平凡计数，py + js）:
     test_ac2_coverage_counts_dedup_nontrivial
     test_ac2_coverage_trivial_only_is_zero
AC3  mutation mutants|run（确定性变异点 / score 与 --strict --threshold）:
     test_ac3_mutation_mutants_lists_points
     test_ac3_mutation_mutants_deterministic
     test_ac3_mutation_run_reports_score_default_exit_zero
     test_ac3_mutation_run_strict_below_threshold_nonzero
     test_ac3_mutation_run_strict_passes_when_tests_kill_mutants
AC4  phantom（幻影 import 清单，--deps，exit 恒 0）:
     test_ac4_phantom_lists_unresolvable_import
     test_ac4_phantom_deps_dir_resolves_import
     test_ac4_phantom_clean_root_empty_output_exit_zero
AC5  compile（按扩展名分发；语法错指名；缺工具链 SKIP 不假 pass）:
     test_ac5_compile_clean_dir_exits_zero
     test_ac5_compile_syntax_error_nonzero_and_names_file
     test_ac5_compile_missing_toolchain_reports_skip
AC6  gate（组合汇总，任一 BLOCK 非零退出）:
     test_ac6_gate_clean_dir_exits_zero_with_summary
     test_ac6_gate_block_causes_nonzero_and_block_label
AC7  打包卫生（零第三方运行时依赖）:
     test_ac7_pyproject_declares_no_runtime_dependencies
AC9  发布物无密钥/个人路径（grep 断言，内容项另行核销的机器可测部分）:
     test_ac9_release_files_contain_no_private_paths_or_secrets
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
REPO = TESTS_DIR.parent
SRC = REPO / "src"
FIX = TESTS_DIR / "fixtures"

PY_BASENAME = "test_sample.py"
JS_BASENAME = "sample.test.js"


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


def make_signature(tmp_path, fixture_name, basename):
    """对 before 夹具做 snapshot，把 stdout（JSON 签名）落盘为 before_sig.json。"""
    before_dir = tmp_path / "before"
    before_dir.mkdir(exist_ok=True)
    before = before_dir / basename
    shutil.copyfile(FIX / "integrity" / fixture_name, before)
    proc = run_cli("integrity", "snapshot", before)
    assert proc.returncode == 0, (
        f"snapshot 应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    sig_path = tmp_path / "before_sig.json"
    sig_path.write_text(proc.stdout)
    return sig_path


def compare_after(tmp_path, sig_path, fixture_name, basename):
    """把 after 夹具以同名 basename 落到独立目录后 compare。"""
    after_dir = tmp_path / "after"
    after_dir.mkdir(exist_ok=True)
    after = after_dir / basename
    shutil.copyfile(FIX / "integrity" / fixture_name, after)
    return run_cli("integrity", "compare", sig_path, after)


# ------------------------------------------------------------- AC1 integrity


def test_ac1_snapshot_outputs_json_signature(tmp_path):
    work = tmp_path / "w"
    work.mkdir()
    target = work / PY_BASENAME
    shutil.copyfile(FIX / "integrity" / "test_sample_before.py", target)
    proc = run_cli("integrity", "snapshot", target)
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    sig = json.loads(proc.stdout)
    assert sig, "签名 JSON 不应为空"


def test_ac1_compare_unchanged_with_preexisting_skip_exits_zero(tmp_path):
    # before 里本就带一个 @pytest.mark.skip —— delta 语义下不算新弱化
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(tmp_path, sig, "test_sample_before.py", PY_BASENAME)
    assert proc.returncode == 0, (
        f"未弱化应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_ac1_compare_strengthened_file_exits_zero(tmp_path):
    # 只新增测试函数（加强），不得误报为弱化
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(tmp_path, sig, "test_sample_added_test.py", PY_BASENAME)
    assert proc.returncode == 0, (
        f"加强不是弱化，应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def _assert_weakening_flagged(proc, hint_terms):
    assert proc.returncode == 1, (
        f"弱化应 exit 1，实际 {proc.returncode}；"
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    err = proc.stderr
    assert err.strip(), "弱化时 stderr 必须有说明"
    assert any(t.lower() in err.lower() for t in hint_terms), (
        f"stderr 说明应至少提及 {hint_terms} 之一，实际：{err!r}"
    )


def test_ac1_integrity_detects_deleted_assert(tmp_path):
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(tmp_path, sig, "test_sample_deleted_assert.py", PY_BASENAME)
    _assert_weakening_flagged(proc, ["test_alpha", "assert", "断言"])


def test_ac1_integrity_detects_added_skip(tmp_path):
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(tmp_path, sig, "test_sample_added_skip.py", PY_BASENAME)
    _assert_weakening_flagged(proc, ["test_beta", "skip"])


def test_ac1_integrity_detects_added_xfail(tmp_path):
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(tmp_path, sig, "test_sample_added_xfail.py", PY_BASENAME)
    _assert_weakening_flagged(proc, ["test_beta", "xfail"])


def test_ac1_integrity_detects_trivialized_assert(tmp_path):
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(
        tmp_path, sig, "test_sample_trivialized_assert.py", PY_BASENAME
    )
    _assert_weakening_flagged(proc, ["test_beta", "trivial", "assert", "恒真"])


def test_ac1_integrity_detects_deleted_test_function(tmp_path):
    sig = make_signature(tmp_path, "test_sample_before.py", PY_BASENAME)
    proc = compare_after(
        tmp_path, sig, "test_sample_deleted_function.py", PY_BASENAME
    )
    _assert_weakening_flagged(proc, ["test_beta", "delet", "miss", "删"])


def test_ac1_js_compare_unchanged_exits_zero(tmp_path):
    sig = make_signature(tmp_path, "sample_before.test.js", JS_BASENAME)
    proc = compare_after(tmp_path, sig, "sample_before.test.js", JS_BASENAME)
    assert proc.returncode == 0, (
        f"js 未弱化应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )


def test_ac1_js_detects_deleted_expect(tmp_path):
    sig = make_signature(tmp_path, "sample_before.test.js", JS_BASENAME)
    proc = compare_after(tmp_path, sig, "sample_deleted_expect.test.js", JS_BASENAME)
    assert proc.returncode == 1, (
        f"js 删断言应 exit 1，实际 {proc.returncode}；"
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert proc.stderr.strip(), "js 弱化时 stderr 必须有说明"


def _assert_usage_error_of_real_subcommand(proc):
    """exit 2 必须是 integrity 自身的用法/解析错，而非「integrity 不是合法子命令」。

    没有这条，stub 的 argparse invalid-choice（同为 exit 2）会让本测试假绿。
    """
    assert proc.returncode == 2, f"应 exit 2，实际 {proc.returncode}"
    assert "invalid choice" not in proc.stderr, (
        f"integrity 必须是已注册子命令，实际 stderr：{proc.stderr!r}"
    )


def test_ac1_compare_missing_args_exits_two(tmp_path):
    proc = run_cli("integrity", "compare", tmp_path / "only_one_arg.json")
    _assert_usage_error_of_real_subcommand(proc)


def test_ac1_compare_garbage_signature_exits_two(tmp_path):
    garbage = tmp_path / "before_sig.json"
    garbage.write_text("this is {{{ not json")
    after = tmp_path / PY_BASENAME
    shutil.copyfile(FIX / "integrity" / "test_sample_before.py", after)
    proc = run_cli("integrity", "compare", garbage, after)
    _assert_usage_error_of_real_subcommand(proc)


def test_ac1_snapshot_unparseable_source_exits_two(tmp_path):
    target = tmp_path / PY_BASENAME
    shutil.copyfile(FIX / "integrity" / "test_sample_unparseable.py", target)
    proc = run_cli("integrity", "snapshot", target)
    _assert_usage_error_of_real_subcommand(proc)


# -------------------------------------------------------------- AC2 coverage


def test_ac2_coverage_counts_dedup_nontrivial():
    # py: test_add 与 test_add_duplicate 同 body 折叠为 1；trivial/empty 不计；
    #     test_sub 计 1 → 2。js: test() + it() 各 1 → 2。合计 4。
    proc = run_cli("coverage", FIX / "coverage" / "counted")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    out = proc.stdout.strip()
    assert out, "coverage 应在 stdout 打印一个整数"
    assert int(out) == 4, f"期望 4（py 2 + js 2），实际输出 {out!r}"


def test_ac2_coverage_trivial_only_is_zero():
    proc = run_cli("coverage", FIX / "coverage" / "trivial_only")
    # FEAT-025 spec 变更: 计数 0 现为 UNPROVEN → exit 3（stdout 仍打印 0）
    assert proc.returncode == 3, f"stderr={proc.stderr!r}"
    out = proc.stdout.strip()
    assert out, "coverage 应在 stdout 打印一个整数"
    assert int(out) == 0, f"纯平凡测试应计 0，实际输出 {out!r}"


# -------------------------------------------------------------- AC3 mutation


def test_ac3_mutation_mutants_lists_points():
    proc = run_cli("mutation", "mutants", FIX / "mutation" / "calc.py")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout.strip(), "calc.py 含 + 与 > 运算符，变异点列表不应为空"


def test_ac3_mutation_mutants_deterministic():
    target = FIX / "mutation" / "calc.py"
    a = run_cli("mutation", "mutants", target)
    b = run_cli("mutation", "mutants", target)
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout.strip(), "变异点列表不应为空"
    assert a.stdout == b.stdout, "确定性变异点：两次运行输出必须逐字节一致"


def _copy_calc(tmp_path):
    target = tmp_path / "calc.py"
    shutil.copyfile(FIX / "mutation" / "calc.py", target)
    return target


def _score_reported(proc):
    out = all_output(proc)
    return bool(re.search(r"(?i)score", out) or re.search(r"\d+\s*/\s*\d+", out))


def test_ac3_mutation_run_reports_score_default_exit_zero(tmp_path):
    target = _copy_calc(tmp_path)
    # 测试命令恒 pass：杀不死任何变异体，但默认（无 --strict）仍 exit 0
    proc = run_cli(
        "mutation", "run", target, "--max", "10",
        "--", sys.executable, "-c", "pass",
    )
    assert proc.returncode == 0, (
        f"默认应 exit 0，实际 {proc.returncode}；stderr={proc.stderr!r}"
    )
    assert _score_reported(proc), (
        f"应报告 score=killed/total，实际输出：{all_output(proc)!r}"
    )


def test_ac3_mutation_run_strict_below_threshold_nonzero(tmp_path):
    target = _copy_calc(tmp_path)
    proc = run_cli(
        "mutation", "run", target, "--max", "10", "--strict", "--threshold", "0.5",
        "--", sys.executable, "-c", "pass",
    )
    assert proc.returncode != 0, "--strict 且 score(=0) < threshold 应非零退出"
    assert _score_reported(proc), (
        f"应报告 score=killed/total，实际输出：{all_output(proc)!r}"
    )


def test_ac3_mutation_run_strict_passes_when_tests_kill_mutants(tmp_path):
    target = _copy_calc(tmp_path)
    # 直接 exec 源文件文本，规避 pyc 缓存；行为全覆盖 → 变异体应被杀
    test_prog = (
        "import sys; "
        f"src = open({str(target)!r}).read(); ns = {{}}; "
        "exec(compile(src, 'calc.py', 'exec'), ns); "
        "ok = (ns['add'](2, 3) == 5 and ns['is_positive'](7) is True "
        "and ns['is_positive'](1) is True and ns['is_positive'](0) is False "
        "and ns['is_positive'](-7) is False); "
        "sys.exit(0 if ok else 1)"
    )
    proc = run_cli(
        "mutation", "run", target, "--max", "10", "--strict", "--threshold", "0.5",
        "--", sys.executable, "-c", test_prog,
    )
    assert proc.returncode == 0, (
        f"测试全杀变异体时 --strict 应 exit 0，实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )


# --------------------------------------------------------------- AC4 phantom


def _phantom_pairs(stdout):
    pairs = []
    for line in stdout.splitlines():
        if "\t" in line:
            rel, mod = line.split("\t", 1)
            pairs.append((rel, mod))
    return pairs


def test_ac4_phantom_lists_unresolvable_import():
    proc = run_cli("phantom", FIX / "phantom" / "with_ghost")
    assert proc.returncode == 0, "phantom 契约：exit 恒 0"
    pairs = _phantom_pairs(proc.stdout)
    assert ("app.py", "ghostlib") in pairs, (
        f"应有一行 'app.py\\tghostlib'，实际 stdout：{proc.stdout!r}"
    )
    flagged_modules = {m for _, m in pairs}
    assert not flagged_modules & {"os", "json", "sys", "helper"}, (
        f"stdlib 与本地可解析模块不得上榜，实际：{flagged_modules}"
    )


def test_ac4_phantom_deps_dir_resolves_import():
    proc = run_cli(
        "phantom", FIX / "phantom" / "with_ghost",
        "--deps", FIX / "phantom" / "deps",
    )
    assert proc.returncode == 0, "phantom 契约：exit 恒 0"
    assert proc.stdout.strip() == "", (
        f"ghostlib 在 --deps 内可解析，输出应为空，实际：{proc.stdout!r}"
    )


def test_ac4_phantom_clean_root_empty_output_exit_zero():
    proc = run_cli("phantom", FIX / "phantom" / "clean")
    assert proc.returncode == 0, "phantom 契约：exit 恒 0"
    assert proc.stdout.strip() == "", (
        f"干净目录输出应为空，实际：{proc.stdout!r}"
    )


# --------------------------------------------------------------- AC5 compile


def test_ac5_compile_clean_dir_exits_zero():
    proc = run_cli("compile", FIX / "compile" / "clean")
    assert proc.returncode == 0, (
        f"干净目录应 exit 0，实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )


def test_ac5_compile_syntax_error_nonzero_and_names_file():
    proc = run_cli("compile", FIX / "compile" / "bad")
    assert proc.returncode != 0, "含语法错误的 .py 应非零退出"
    assert "broken_syntax.py" in all_output(proc), (
        f"应指出出错文件 broken_syntax.py，实际输出：{all_output(proc)!r}"
    )


def test_ac5_compile_missing_toolchain_reports_skip(tmp_path):
    # PATH 指向空目录 → go 工具链不可见；目录里只有 .go 文件，
    # SKIP 字样必须出现（对该语言明确报 SKIP 而非 OK / 假 pass）
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir()
    proc = run_cli(
        "compile", FIX / "compile" / "go_only",
        env_overrides={"PATH": str(empty_bin)},
    )
    out = all_output(proc)
    assert "SKIP" in out, f"缺工具链必须显式报 SKIP，实际输出：{out!r}"
    assert "Traceback" not in out, f"缺工具链不应崩溃，实际输出：{out!r}"


# ------------------------------------------------------------------ AC6 gate


def test_ac6_gate_clean_dir_exits_zero_with_summary():
    proc = run_cli("gate", FIX / "gate" / "clean")
    assert proc.returncode == 0, (
        f"干净目录 gate 应 exit 0，实际 {proc.returncode}；"
        f"输出：{all_output(proc)!r}"
    )
    out = all_output(proc).lower()
    named = [
        k for k in ("compile", "phantom", "coverage", "mutation", "integrity")
        if k in out
    ]
    assert len(named) >= 2, (
        f"gate 应输出各检查器汇总（至少提及 2 个检查器名），实际：{all_output(proc)!r}"
    )


def test_ac6_gate_block_causes_nonzero_and_block_label():
    proc = run_cli("gate", FIX / "gate" / "blocked")
    assert proc.returncode != 0, "存在 BLOCK（语法错文件）时 gate 必须非零退出"
    assert "BLOCK" in all_output(proc), (
        f"汇总里应出现 BLOCK 字样，实际输出：{all_output(proc)!r}"
    )


# ------------------------------------------------------------- AC7 packaging


def test_ac7_pyproject_declares_no_runtime_dependencies():
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"].get("dependencies", [])
    assert deps == [], f"零第三方运行时依赖被违反：{deps}"


# --------------------------------------------------------------- AC9 hygiene


def test_ac9_release_files_contain_no_private_paths_or_secrets():
    # 发布物 = 源码包会带出去的东西；tests/ 不随 wheel 发布，不在扫描面
    patterns = re.compile(
        r"/Users/shiersa"          # 个人绝对路径
        r"|PrivateProject"         # 私有工作区路径
        r"|pypi-Ag[A-Za-z0-9_-]"   # PyPI API token 前缀
    )
    scan_targets = [
        REPO / "pyproject.toml",
        REPO / "README.md",
        REPO / "LICENSE",
        *sorted((REPO / "src").rglob("*.py")),
        *sorted(p for p in (REPO / "npm").rglob("*") if p.is_file()),
    ]
    offenders = []
    for path in scan_targets:
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if patterns.search(text):
            offenders.append(str(path.relative_to(REPO)))
    assert not offenders, f"发布物含私有路径/密钥引用：{offenders}"
