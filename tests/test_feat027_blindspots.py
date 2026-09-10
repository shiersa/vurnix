"""FEAT-027 盲区修复红测试（test-author 独立产出，仅由 spec + 公开契约推导）。

实现者禁改本文件（恒态红线 §二6）；修订仅限已确认 spec 变更或夹具损坏经 reviewer 会签。
预期先红：样本盲区（Django/unittest、TypeScript、Gradle、conda）修复未实现前，
各主测试应因「计数为 0 / 输出 no source files / 缺 gradle 归属 / 幻影误报」而失败；
各对照（控制）测试应保持绿。

公开契约沿用（同 test_feat025 / test_feat026）：
- phantom（FEAT-019 AC4）：`vurnix phantom <root>` 每行 `相对路径\t模块名`，空输出=干净，exit 恒 0
- coverage（FEAT-025 AC2）：stdout 首行打印整数计数；>0 → exit 0；0 → exit 3
- compile（FEAT-025 AC3）：FAIL → 1；无 FAIL 但有 SKIP / 无源文件 → 3 + 输出含 UNPROVEN

AC → 测试映射（FEAT-027）
=============
AC1 Django/unittest（tests.py 纳入发现；self.assert*/self.fail = 真实断言）:
     test_ac1_django_tests_py_assert_equal_counted            （预期红：现行计 0）
     test_ac1_django_tests_py_self_fail_counted               （预期红：现行计 0）
     test_ac1_trivial_self_assert_and_setup_not_counted       （对照，预期绿：
       只含 self.assertTrue(True)（纯常量参数）与 self.setUp() 的测试函数不计数）
AC2 TypeScript 测试识别（*.test.ts 及顶层 tests/ 下 plain .ts）:
     test_ac2_jest_dot_test_dot_ts_counted                    （预期红：现行计 0）
     test_ac2_plain_ts_under_tests_dir_counted                （预期红：现行计 0）
AC3 TypeScript 编译诚实判定（.ts 纳入源收集；无 tsc → SKIP 计入 UNPROVEN）:
     test_ac3_ts_source_collected_no_toolchain_skip           （预期红：现行走
       「no source files」空判而非对 ts 的诚实 SKIP）
     test_ac3_node_present_compiler_absent_still_skip         （预期红；skipif 无 node：
       有 tsconfig.json、PATH 有 node 无 tsc → tsc 探活失败仍 SKIP+3）
     注：「宿主有 tsc + tsconfig → `tsc --noEmit -p`；rc=124→SKIP；TS2307 族
     （未装依赖）→ SKIP；其余错误 → FAIL」依宿主装机状态，无法离线确定性构造，
     交真实仓 hono 复验核销（spec 第二轮样本环节）。
AC4 Gradle 诚实 SKIP（build.gradle 存在 → 同「有 pom 无 mvn」逻辑，绝不 FAIL）:
     test_ac4_gradle_layout_java_skip_never_fail              （预期红：现行 SKIP 行
       只提 mvn/javac，不提及 gradle 这一真实构建系统 = 归属不诚实）
AC5 conda 声明源（environment.yml dependencies 及 `- pip:` 子列表）:
     test_ac5_conda_environment_yml_deps_not_flagged          （预期红：现行误报）
     test_ac5_conda_control_invented_still_flagged            （对照，预期绿）
AC6 回归：不新增文件级断言——由全量跑保证（写作时既有基线 79 项全绿，以实跑为准）；
     「平凡断言判定不被 unittest 改动弱化」由 AC1 对照钉死（self.assertTrue(True)
     纯常量参数 = 平凡，与裸 assert True 同判）；版本类测试勿新增（下限钉已在
     test_feat025 AC6（≥0.3.0）与 test_bug028（≥0.3.1），0.3.2 精确值属发布相位核验）。

第二轮实测追加 R2a-d（spec 回填节；防回退钉，追加时精修已实现，预期直接绿；
非复现红测——先例同 test_feat026 的 H/I）:
R2a 声明文件名泛化（根目录任意 *requirements*.txt，otel 现场）:
     test_r2a_requirements_variant_files_are_declaration_sources
R2b 命名空间包规则（声明名 = import名 + `_` 前缀族；囊括原 _py/_python 后缀规则）:
     test_r2b_namespace_prefix_family_resolves_control_not_substring
R2c 别名补条（rest_framework→djangorestframework；google→(protobuf|…) 元组任一命中）:
     test_r2c_alias_rest_framework_and_tuple_alias_google_not_flagged
R2d TS 源排除 .d.ts / *-d.ts（纯类型声明与 tsd 类型测试非运行时源码，commander 现场）:
     test_r2d_declaration_ts_excluded_compile_clean      （skipif 无 node）
     test_r2d_declaration_ts_fixture_gate_pass           （skipif 无 node）

夹具备注（reviewer 会签依据）:
- AC1 基类均在夹具内自定义（TestCase / ApiTestBase），不导入 django——识别不得
  依赖 django 可导入，且不得依赖基类恰好名为 TestCase。
- AC3 两测的红因主锚是「输出不得再含 no source files」（黑盒实测现行输出原文）；
  toolchain 归属断言用 (?i)tsc|typescript，测试名/夹具目录名刻意避开 tsc 子串，
  防 tmp 路径回显造成假绿。
- AC4 的 gradle 归属断言依据黑盒实测：现行 java SKIP 行不回显夹具路径，
  故「gradle」字样只能来自实现的真实归属输出。
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


def _phantom_pairs(stdout):
    """FEAT-019 公开契约：每行 `相对路径\\t模块名`。"""
    pairs = []
    for line in stdout.splitlines():
        if "\t" in line:
            rel, mod = line.split("\t", 1)
            pairs.append((rel, mod))
    return pairs


def run_phantom(root):
    """跑 phantom 并顺带断言 exit 恒 0 契约；返回 (被标模块集合, pairs, proc)。"""
    proc = run_cli("phantom", root)
    assert proc.returncode == 0, (
        f"phantom 契约：exit 恒 0，实际 {proc.returncode}；"
        f"stderr={proc.stderr!r}"
    )
    pairs = _phantom_pairs(proc.stdout)
    return {m for _, m in pairs}, pairs, proc


def _coverage_count(proc):
    """FEAT-025 公开契约：coverage stdout 首行是整数计数。"""
    out = proc.stdout.strip()
    assert out, f"coverage 应在 stdout 首行打印整数计数，实际 {proc.stdout!r}"
    return int(out.splitlines()[0])


# ------------------------------------------------------------ fixture builders
# 全部用 tmp_path 现场构造合成项目，离线、确定性；依赖名均为发明名，
# 保证宿主环境不可解析；「缺工具链」用 PATH 裁剪模拟。


def _write(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _empty_path_env(tmp_path):
    """PATH 全裁剪：指向空目录，外部工具链（mvn/javac/gradle/node/…）全不可见。"""
    empty_bin = tmp_path / "emptybin"
    empty_bin.mkdir(exist_ok=True)
    return {"PATH": str(empty_bin)}


def _python_only_path_env(tmp_path):
    """PATH 裁剪法：只含指向本解释器的 python/python3，无 node/tsc/mvn/javac。"""
    bin_dir = tmp_path / "pyonly-bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("python", "python3"):
        link = bin_dir / name
        if not link.exists():
            os.symlink(sys.executable, link)
    return {"PATH": str(bin_dir)}


def _node_no_tsc_path_env(tmp_path):
    """PATH 裁剪法：python/python3 + 宿主 node，唯独没有 tsc。"""
    bin_dir = tmp_path / "node-bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("python", "python3"):
        link = bin_dir / name
        if not link.exists():
            os.symlink(sys.executable, link)
    node = shutil.which("node")
    assert node, "调用方须先 skipif 无 node"
    link = bin_dir / "node"
    if not link.exists():
        os.symlink(node, link)
    return {"PATH": str(bin_dir)}


# ------------------- AC1 Django/unittest（django-realworld-example-app 类）


DJANGO_STYLE_TESTS_PY = (
    "class TestCase:\n"
    '    """本地自定义基类：不导入 django（识别不得依赖 django 可导入）。"""\n'
    "\n"
    "\n"
    "class CalcTests(TestCase):\n"
    "    def test_addition(self):\n"
    "        self.assertEqual(1 + 1, 2)\n"
    "\n"
    "    def test_subtraction(self):\n"
    "        self.assertEqual(5 - 3, 2)\n"
)


def test_ac1_django_tests_py_assert_equal_counted(tmp_path):
    # Django 命名惯例：测试文件名是 tests.py（非 test_*.py/*_test.py）。
    # TestCase 类 + self.assertEqual(1 + 1, 2)（表达式参数，非纯常量）
    # = 真实断言 → 计数 ≥1、exit 0（现行不发现 tests.py → 计 0 → exit 3 = 红）。
    work = tmp_path / "app"
    _write(work, "tests.py", DJANGO_STYLE_TESTS_PY)
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"AC1：tests.py（Django 命名）内 TestCase 风格真实断言测试应使 "
        f"coverage exit 0，实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert _coverage_count(proc) >= 1, (
        f"AC1：self.assertEqual(1 + 1, 2) 是真实断言，计数应 ≥1，"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac1_django_tests_py_self_fail_counted(tmp_path):
    # self.fail("boom") 形式（unittest 全家）也算真实断言；
    # 基类用自定义名 ApiTestBase——识别不得依赖基类恰好名为 TestCase。
    work = tmp_path / "app"
    _write(
        work,
        "tests.py",
        "class ApiTestBase:\n"
        "    pass\n"
        "\n"
        "\n"
        "class GuardTests(ApiTestBase):\n"
        "    def test_unreachable_branch(self):\n"
        '        self.fail("boom")\n',
    )
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"AC1：self.fail(...) 是真实断言（unittest 全家），coverage 应 "
        f"exit 0，实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert _coverage_count(proc) >= 1, (
        f"AC1：含 self.fail('boom') 的测试应计数 ≥1，"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac1_trivial_self_assert_and_setup_not_counted(tmp_path):
    # 对照（防修过头，亦是 AC6 反弱化钉）：
    # self.assertTrue(True)（参数为纯常量）与裸 assert True 同判 = 平凡；
    # self.setUp() 是非断言方法调用，不算断言。
    # 只含这两者的测试函数不计数 → 计 0、exit 3。
    work = tmp_path / "app"
    _write(
        work,
        "tests.py",
        "class TestCase:\n"
        "    pass\n"
        "\n"
        "\n"
        "class TrivialTests(TestCase):\n"
        "    def setUp(self):\n"
        "        self.ready = True\n"
        "\n"
        "    def test_looks_busy_but_proves_nothing(self):\n"
        "        self.setUp()\n"
        "        self.assertTrue(True)\n",
    )
    proc = run_cli("coverage", work)
    assert proc.returncode == 3, (
        f"AC1 对照：只含纯常量断言与 setUp 调用的测试不计数，应 exit 3，"
        f"实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert _coverage_count(proc) == 0, (
        f"AC1 对照：self.assertTrue(True) + self.setUp() = 平凡，计数应为 0，"
        f"实际 stdout：{proc.stdout!r}"
    )


# --------------------------- AC2 TypeScript 测试识别（hono 类假 UNPROVEN）


def test_ac2_jest_dot_test_dot_ts_counted(tmp_path):
    # *.test.ts 应纳入测试识别（复用 JS 正则，TS 类型注解语法兼容）：
    # jest 风格 test()+expect() → 计数 ≥1、exit 0（现行计 0 → exit 3 = 红）。
    work = tmp_path / "web"
    _write(
        work,
        "add.test.ts",
        "const limit: number = 2;  // TS 类型注解——复用的 JS 正则须语法兼容\n"
        "\n"
        "test('adds numbers', () => {\n"
        "  expect(1 + 1).toBe(2);\n"
        "});\n",
    )
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"AC2：add.test.ts 内 jest 风格真实断言测试应使 coverage exit 0，"
        f"实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert _coverage_count(proc) >= 1, (
        f"AC2：test('x', ...) + expect(1+1).toBe(2) 应计数 ≥1，"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac2_plain_ts_under_tests_dir_counted(tmp_path):
    # 顶层 tests/ 目录下的 plain .ts（非 *.test.ts 后缀，mocha 布局）
    # 也应纳入：it() + assert 调用 → 计数 ≥1、exit 0。
    work = tmp_path / "web"
    _write(
        work / "tests",
        "routes.ts",
        "const assert = require('assert');\n"
        "\n"
        "describe('routes', () => {\n"
        "  it('adds numbers', () => {\n"
        "    assert.strictEqual(2 + 3, 5);\n"
        "  });\n"
        "  it('keeps element order', () => {\n"
        "    assert.ok([1, 2].indexOf(2) === 1);\n"
        "  });\n"
        "});\n",
    )
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"AC2：顶层 tests/ 下 plain .ts 的 it()+assert 测试应使 coverage "
        f"exit 0，实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    assert _coverage_count(proc) >= 1, (
        f"AC2：tests/routes.ts 两个真实断言 it() 应计数 ≥1，"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------------------- AC3 TypeScript 编译诚实判定（hono 类「隐形源」）


TS_SOURCE = (
    "export function add(a: number, b: number): number {\n"
    "  return a + b;\n"
    "}\n"
)


def test_ac3_ts_source_collected_no_toolchain_skip(tmp_path):
    # 仅 .ts 源文件目录 + PATH 裁剪（无 node/tsc）：.ts 必须纳入源收集并被
    # 诚实承认为 SKIP（exit 3 + UNPROVEN），而不是被当成「no source files」
    # 的空目录（现行输出原文含 no source files = 红因主锚）。
    work = tmp_path / "web"
    _write(work, "math.ts", TS_SOURCE)
    proc = run_cli(
        "compile", work, env_overrides=_python_only_path_env(tmp_path)
    )
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"AC3：ts 源无 tsc 应判 UNPROVEN（exit 3）而非 FAIL(1)/PASS(0)，"
        f"实际 {proc.returncode}；输出：{out!r}"
    )
    assert "no source files" not in out, (
        f"AC3：.ts 已是源文件，不得再走「no source files」空判；"
        f"实际输出：{out!r}"
    )
    assert "SKIP" in out, (
        f"AC3：无 tsc 时 ts 源必须被诚实承认为 SKIP；实际输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"AC3：输出必须含 UNPROVEN 字样，实际：{out!r}"
    assert re.search(r"(?i)tsc|typescript", out), (
        f"AC3：SKIP 归属应指向 ts/tsc（说清哪条腿没跑），实际输出：{out!r}"
    )
    assert "Traceback" not in out, f"AC3：缺工具链不应崩溃，实际输出：{out!r}"


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="宿主无 node：无法构造「PATH 有 node 无 tsc」的探活失败环境",
)
def test_ac3_node_present_compiler_absent_still_skip(tmp_path):
    # 同夹具 + tsconfig.json，PATH 有 node 但无 tsc：tsc 探活失败 →
    # 仍 SKIP + exit 3（node 在场不等于 ts 可编译，绝不 FAIL、不空判）。
    # 「宿主有 tsc：tsc --noEmit -p / rc=124→SKIP / TS2307 族→SKIP / 其余→FAIL」
    # 依宿主装机状态，交真实仓 hono 复验核销。
    work = tmp_path / "web"
    _write(work, "math.ts", TS_SOURCE)
    _write(
        work,
        "tsconfig.json",
        '{\n  "compilerOptions": {\n    "strict": true\n  }\n}\n',
    )
    proc = run_cli(
        "compile", work, env_overrides=_node_no_tsc_path_env(tmp_path)
    )
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"AC3：有 tsconfig、有 node、无 tsc → 探活失败应 SKIP（exit 3），"
        f"实际 {proc.returncode}；输出：{out!r}"
    )
    assert "no source files" not in out, (
        f"AC3：.ts + tsconfig.json 的项目不得判「no source files」；"
        f"实际输出：{out!r}"
    )
    assert "SKIP" in out, (
        f"AC3：tsc 缺席必须诚实 SKIP（而非 FAIL/PASS/空判）；实际输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"AC3：输出必须含 UNPROVEN 字样，实际：{out!r}"
    assert "Traceback" not in out, f"AC3：缺 tsc 不应崩溃，实际输出：{out!r}"


# ----------------------------- AC4 Gradle 诚实 SKIP（junit5 类）


def test_ac4_gradle_layout_java_skip_never_fail(tmp_path):
    # build.gradle + java 源，PATH 全裁剪：同「有 pom 无 mvn」逻辑——
    # 裸 javac 无 classpath 证明不了任何东西 → SKIP + exit 3，绝不 FAIL；
    # 且 SKIP 归属必须提及 gradle（现行只提 mvn/javac，不认 gradle 工程 = 红）。
    # 黑盒实测：现行 java SKIP 行不回显夹具路径，「gradle」字样只能来自实现输出。
    work = tmp_path / "app"
    _write(work, "build.gradle", 'plugins { id "java" }\n')
    _write(
        work / "src",
        "Main.java",
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("ok");\n'
        "    }\n"
        "}\n",
    )
    proc = run_cli("compile", work, env_overrides=_empty_path_env(tmp_path))
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"AC4：gradle 工程缺工具链应判 UNPROVEN（exit 3），绝不 FAIL(1)，"
        f"实际 {proc.returncode}；输出：{out!r}"
    )
    assert "SKIP" in out, (
        f"AC4：java 源必须被诚实承认为 SKIP；实际输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"AC4：输出必须含 UNPROVEN 字样，实际：{out!r}"
    assert re.search(r"(?i)gradle", out), (
        f"AC4：SKIP 归属应提及 gradle（承认这是 gradle 工程、说明为何不裸编），"
        f"实际输出：{out!r}"
    )
    assert "FAIL" not in out, (
        f"AC4：build.gradle 存在时绝不 FAIL（无 classpath 的裸 javac 不构成"
        f"证据）；实际输出：{out!r}"
    )
    assert "Traceback" not in out, f"AC4：缺工具链不应崩溃，实际输出：{out!r}"


# --------------------- AC5 conda environment.yml 声明源（geopandas 类）


CONDA_ENV_YML = (
    "name: fixture-env\n"
    "dependencies:\n"
    "  - condadep7\n"
    "  - pip:\n"
    "    - pipdep8>=1\n"
)


def test_ac5_conda_environment_yml_deps_not_flagged(tmp_path):
    # environment.yml 的 dependencies 列表（含 `- pip:` 子列表）是声明源：
    # import condadep7 / import pipdep8 均不得标为幻影（行级解析，无 yaml 依赖）。
    work = tmp_path / "proj"
    _write(work, "environment.yml", CONDA_ENV_YML)
    _write(work, "app.py", "import condadep7\nimport pipdep8\n")
    flagged, _, proc = run_phantom(work)
    assert "condadep7" not in flagged, (
        f"AC5：environment.yml dependencies 已声明 condadep7，"
        f"import condadep7 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "pipdep8" not in flagged, (
        f"AC5：environment.yml 的 `- pip:` 子列表已声明 pipdep8>=1，"
        f"import pipdep8 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )


def test_ac5_conda_control_invented_still_flagged(tmp_path):
    # 对照（防修过头）：environment.yml 在场不是放行全目录——
    # 未声明的纯发明名 conda_invented9 仍必须标。
    work = tmp_path / "proj"
    _write(work, "environment.yml", CONDA_ENV_YML)
    _write(work, "app.py", "import condadep7\nimport conda_invented9\n")
    flagged, _, proc = run_phantom(work)
    assert "conda_invented9" in flagged, (
        f"AC5 对照：conda_invented9 未声明、非本地、无守卫，仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ============== 第二轮实测追加 R2a-d（防回退钉，预期直接绿） ==============


# ---------------- R2a 声明文件名泛化：根目录 *requirements*.txt（otel 现场）


def test_r2a_requirements_variant_files_are_declaration_sources(tmp_path):
    # dev-requirements.txt / docs-requirements.txt 形态也是声明源；
    # 对照内嵌：同夹具纯发明名仍必须标——泛化的是文件名，不是放行全目录。
    work = tmp_path / "proj"
    _write(work, "dev-requirements.txt", "devreq9>=1\n")
    _write(work, "docs-requirements.txt", "docsreq8\n")
    _write(
        work,
        "app.py",
        "import devreq9\nimport docsreq8\nimport reqs_invented5\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "devreq9" not in flagged, (
        f"R2a：根目录 dev-requirements.txt 已声明 devreq9，"
        f"import devreq9 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "docsreq8" not in flagged, (
        f"R2a：根目录 docs-requirements.txt 已声明 docsreq8，"
        f"import docsreq8 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "reqs_invented5" in flagged, (
        f"R2a 对照：reqs_invented5 未在任何 *requirements*.txt 声明，"
        f"仍必须标为幻影；实际 stdout：{proc.stdout!r}"
    )


# ------------- R2b 命名空间包规则：声明名 = import名 + `_` 前缀族（otel 现场）


def test_r2b_namespace_prefix_family_resolves_control_not_substring(tmp_path):
    # 声明 opentelemetry2-api（规范化 opentelemetry2_api = opentelemetry2 + _api）
    # → import opentelemetry2 可解析（命名空间前缀族）；
    # 对照：声明 foo2bar（foo2 与 bar 之间无 `_` 连接）不得放行 import foo2——
    # 规则是「下划线边界的前缀」，不是任意子串。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        "[project]\n"
        'name = "fixture-ns"\n'
        'version = "0.0.1"\n'
        'dependencies = ["opentelemetry2-api", "foo2bar"]\n',
    )
    _write(work, "app.py", "import opentelemetry2\nimport foo2\n")
    flagged, _, proc = run_phantom(work)
    assert "opentelemetry2" not in flagged, (
        f"R2b：已声明 opentelemetry2-api（= opentelemetry2 + `_` 前缀族），"
        f"import opentelemetry2 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "foo2" in flagged, (
        f"R2b 对照：声明 foo2bar 无下划线连接（foo2bar ≠ foo2 + `_` + …），"
        f"不得放行 import foo2，仍必须标为幻影；实际 stdout：{proc.stdout!r}"
    )


# ---------- R2c 别名补条：djangorestframework / protobuf 元组别名（实测现场）


def test_r2c_alias_rest_framework_and_tuple_alias_google_not_flagged(tmp_path):
    # 别名表补条：import rest_framework ← 声明 djangorestframework；
    # import google ← 声明 (protobuf|googleapis-common-protos) 元组任一命中
    # （本夹具声明 protobuf 即命中）。
    # 对照内嵌：同夹具纯发明名仍必须标——别名表不是全局放行。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        "[project]\n"
        'name = "fixture-alias"\n'
        'version = "0.0.1"\n'
        'dependencies = ["djangorestframework", "protobuf"]\n',
    )
    _write(
        work,
        "app.py",
        "import rest_framework\nimport google\nimport alias_invented4\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "rest_framework" not in flagged, (
        f"R2c：已声明 djangorestframework（别名表 rest_framework→"
        f"djangorestframework），import rest_framework 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "google" not in flagged, (
        f"R2c：已声明 protobuf（元组别名 google→(protobuf|googleapis-common-"
        f"protos) 任一命中），import google 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "alias_invented4" in flagged, (
        f"R2c 对照：alias_invented4 不在别名表、未声明，仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------- R2d TS 源排除 .d.ts / *-d.ts（纯类型声明非运行时源码，commander 现场）


def _build_declaration_ts_fixture(tmp_path):
    """可过的 .js + 真实 .test.js 测试 + 两个纯类型声明文件。

    声明文件内容故意用 TS-only 语法（declare / 泛型）：若实现错误地把
    .d.ts/*-d.ts 并入 js/ts 运行时源收集，要么走 ts 腿 SKIP（无 tsc）、
    要么走 js 腿语法 FAIL——两个方向都会被下方断言抓住。
    """
    work = tmp_path / "pkg"
    _write(
        work,
        "lib.js",
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
        "\n"
        "module.exports = { add };\n",
    )
    _write(
        work,
        "lib.test.js",
        "test('adds numbers', () => {\n"
        "  expect(2 + 3).toBe(5);\n"
        "});\n",
    )
    _write(
        work,
        "types.d.ts",
        "export declare function add(a: number, b: number): number;\n",
    )
    _write(
        work,
        "index.test-d.ts",
        "import { expectType } from 'tsd';\n"
        "\n"
        "declare const total: number;\n"
        "expectType<number>(total);\n",
    )
    return work


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="宿主无 node：js 腿无法离线证明，.d.ts 排除断言失去 PASS 基底",
)
def test_r2d_declaration_ts_excluded_compile_clean(tmp_path):
    # PATH 有 node 无 tsc：.d.ts / *-d.ts 被排除出源收集 → compile 不得
    # 因 ts 判 SKIP/UNPROVEN（输出不含 "compile ts"），js 腿全证 → exit 0。
    work = _build_declaration_ts_fixture(tmp_path)
    proc = run_cli(
        "compile", work, env_overrides=_node_no_tsc_path_env(tmp_path)
    )
    out = all_output(proc)
    assert proc.returncode == 0, (
        f"R2d：纯类型声明文件被排除后仅剩可过的 js 源，compile 应 exit 0，"
        f"实际 {proc.returncode}；输出：{out!r}"
    )
    assert "compile ts" not in out, (
        f"R2d：.d.ts/*-d.ts 非运行时源码，不得触发 ts 腿"
        f"（输出不得含 'compile ts'）；实际输出：{out!r}"
    )
    assert "UNPROVEN" not in out, (
        f"R2d：不得因声明文件判 UNPROVEN；实际输出：{out!r}"
    )
    assert "Traceback" not in out, f"R2d：不应崩溃，实际输出：{out!r}"


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="宿主无 node：js 腿无法离线证明，gate 必然 UNPROVEN 与本钉无关",
)
def test_r2d_declaration_ts_fixture_gate_pass(tmp_path):
    # 同夹具过 gate：真实 .test.js 断言测试（coverage >0）+ 可过 js 源 +
    # 被排除的声明文件 → RESULT: PASS + exit 0（commander 形态不再假 UNPROVEN）。
    work = _build_declaration_ts_fixture(tmp_path)
    proc = run_cli(
        "gate", work, env_overrides=_node_no_tsc_path_env(tmp_path)
    )
    out = all_output(proc)
    assert proc.returncode == 0, (
        f"R2d：声明文件夹具 gate 应 exit 0，实际 {proc.returncode}；"
        f"输出：{out!r}"
    )
    assert "RESULT: PASS" in out, (
        f"R2d：应打印 'RESULT: PASS'（.d.ts 不得把判决拖成 UNPROVEN），"
        f"实际输出：{out!r}"
    )
