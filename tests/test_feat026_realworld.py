"""FEAT-026 七失败类 A-G 复现/验收测试（test-author 独立产出，仅由 spec + 公开契约推导）。

实现者禁改本文件（恒态红线 §二6）；修订仅限已确认 spec 变更或夹具损坏经 reviewer 会签。
预期先红：真实仓扫描定型的失败类 A-E、G 修复未实现前，各类主测试应因
「误报存在 / 测试计数为 0 / 判决错位」而失败；各对照（控制）测试应保持绿。

公开契约沿用：
- phantom（FEAT-019 AC4）：`vurnix phantom <root>` 每行 `相对路径\t模块名`，空输出=干净，exit 恒 0
- coverage（FEAT-025 AC2）：stdout 首行打印整数计数；>0 → exit 0；0 → exit 3
- compile（FEAT-025 AC3）：FAIL → 1；无 FAIL 但有 SKIP → 3 + 输出含 UNPROVEN
- gate（FEAT-025 AC5）：全证 → `RESULT: PASS` + 0；不可证 → `RESULT: UNPROVEN` + 3

失败类 → 测试映射（FEAT-026「失败类定型」A-G）
=============
A  poetry 声明源（[tool.poetry.dependencies] / [tool.poetry.group.*.dependencies]，
   键即发行名，python 键跳过）:
     test_a_poetry_dependencies_and_group_dev_not_flagged        （预期红）
     test_a_poetry_python_key_produces_no_side_effect            （对照，预期绿）
B  嵌套子项目（每个 .py 按文件就近向上找声明基底，本地搜索路径与声明依赖均按该基底解析）:
     test_b_nested_subproject_resolved_by_nearest_base           （预期红）
     test_b_nested_control_invented_still_flagged                （对照，预期绿）
C  版本/平台条件守卫（if 测试式含 sys.version_info / sys.platform → 两分支均视为可选性结构）:
     test_c_sys_version_info_guard_both_branches_not_flagged     （预期红）
     test_c_sys_platform_guard_not_flagged_bare_control_flagged  （半红：守卫断言红，对照绿）
D  别名规则化（声明名 d 匹配 import 名 i 当 d∈{i, py+i, i+_py, i+_python, python_+i}，规范化后）:
     test_d_py_prefix_and_py_suffix_forms_not_flagged            （预期红）
     test_d_prefix_rule_is_full_composition_not_substring        （对照，预期绿）
E  JS mocha 布局（顶层 test|tests/ 目录下 plain .js 纳入测试识别）:
     test_e_mocha_plain_js_under_test_dir_counted                （预期红）
     test_e_gate_mocha_layout_not_unproven                       （预期红；依赖宿主 node）
F  编译超时=UNPROVEN（rc=124 记 SKIP 入 unproven 而非 FAIL）:
     【跳过自动化测试】F 类由实现内部 rc=124 路径覆盖。红测不可行：无法离线确定性
     构造 240s 编译超时（人工造超时 = 夹具自身不确定且拖慢全量回归），交由真实仓
     gin（go vet 拉依赖超时）复验核销（FEAT-026 AC2 真实仓复验环节）。
G  java 工具链诚实判定（有 pom 无 mvn → SKIP；javac 存在但 -version 失败 → SKIP）:
     test_g_java_pom_without_toolchain_skip_unproven             （红绿以实测为准）
     注：「宿主 javac 为 macOS 无 JDK stub（存在但 -version 失败）」情形无法离线
     确定性模拟（依赖宿主装机状态），该分支交真实仓 spring-petclinic 复验核销。

实测追加的两处精修（H/I，防回退钉，追加时精修已实现，预期直接绿；非复现红测）:
H  脚本目录语义（importer 文件自身所在目录参与解析；仅限该目录，不向别处放行）:
     test_h_importer_own_directory_participates_in_resolution
I  平台运行时内建（js/pyodide/micropip 为 Pyodide/Emscripten 运行时命名空间，
   策展表放行；表外相近名不放行）:
     test_i_pyodide_runtime_builtins_not_flagged_control_flagged

夹具备注（reviewer 会签依据）:
- D 类任务原型「声明 markdown-it-py2 → import markdown_it2」不满足 spec D 规则集
  （i+_py = markdown_it2_py ≠ markdown_it_py2，规范化后无一形式命中），红测将永不可绿；
  按 spec 规则改用发明名「markdown-it2-py」（d 规范化 = markdown_it2_py = i+_py，命中
  _py 后缀形式），保持任务意图（_py 后缀规则 + 发明名离线确定性）。
"""

import os
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


# ------------------------------------------------------------ fixture builders
# 全部用 tmp_path 现场构造合成项目，离线、确定性；依赖名均为发明名，
# 保证宿主环境不可解析（排除「碰巧本机装了」的干扰）。


def _write(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _python_only_path_env(tmp_path):
    """PATH 裁剪法：只含指向本解释器的 python/python3，无 mvn/javac/node/go。"""
    bin_dir = tmp_path / "pyonly-bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("python", "python3"):
        link = bin_dir / name
        if not link.exists():
            os.symlink(sys.executable, link)
    return {"PATH": str(bin_dir)}


# ---------------------------------------------- A poetry 声明源（rich/tinydb 类）


POETRY_ONLY_PYPROJECT = (
    "[tool.poetry]\n"
    'name = "fixture-poetry"\n'
    'version = "0.0.1"\n'
    "\n"
    "[tool.poetry.dependencies]\n"
    'python = "^3.10"\n'
    'pygments2 = "^1.0"\n'
    "\n"
    "[tool.poetry.group.dev.dependencies]\n"
    'devtool9 = "^2.0"\n'
)


def test_a_poetry_dependencies_and_group_dev_not_flagged(tmp_path):
    # pyproject 只有 [tool.poetry] 区（无 [project]）：
    # [tool.poetry.dependencies] 的键 pygments2 与
    # [tool.poetry.group.dev.dependencies] 的键 devtool9 均是声明依赖。
    work = tmp_path / "proj"
    _write(work, "pyproject.toml", POETRY_ONLY_PYPROJECT)
    _write(work, "app.py", "import pygments2\nimport devtool9\n")
    flagged, _, proc = run_phantom(work)
    assert "pygments2" not in flagged, (
        f"A：[tool.poetry.dependencies] 已声明 pygments2（键即发行名），"
        f"import pygments2 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "devtool9" not in flagged, (
        f"A：[tool.poetry.group.dev.dependencies] 已声明 devtool9，"
        f"import devtool9 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )


def test_a_poetry_python_key_produces_no_side_effect(tmp_path):
    # 对照（防修过头）：python 键是解释器约束不是依赖，必须跳过——
    # 它不得把 `import python` 洗白；同夹具纯发明名仍必须标。
    work = tmp_path / "proj"
    _write(work, "pyproject.toml", POETRY_ONLY_PYPROJECT)
    _write(work, "misuse.py", "import python\n")
    _write(work, "inventor.py", "import poetry_invented55\n")
    flagged, _, proc = run_phantom(work)
    assert "python" in flagged, (
        f"A 对照：python 键应被跳过，不得使 import python 通过"
        f"（非声明、非本地、非 stdlib 模块）；实际 stdout：{proc.stdout!r}"
    )
    assert "poetry_invented55" in flagged, (
        f"A 对照：纯发明名 poetry_invented55 仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------------------------------- B 嵌套子项目（flask examples / pytest doc 类）


def _build_nested_fixture(tmp_path):
    root = tmp_path / "proj"
    _write(
        root,
        "pyproject.toml",
        "[project]\n"
        'name = "fixture-root"\n'
        'version = "0.0.1"\n'
        'dependencies = ["rootdep7>=1"]\n',
    )
    _write(root, "app_root.py", "import rootdep7\n")
    tutorial = root / "examples" / "tutorial"
    _write(
        tutorial,
        "pyproject.toml",
        "[project]\n"
        'name = "flaskr9"\n'
        'version = "0.0.1"\n'
        'dependencies = ["exdep8>=1"]\n',
    )
    _write(tutorial / "src" / "flaskr9", "__init__.py", "VALUE = 1\n")
    _write(
        tutorial,
        "app.py",
        "import flaskr9\nimport exdep8\nimport invented77\n",
    )
    return root


def test_b_nested_subproject_resolved_by_nearest_base(tmp_path):
    # 对夹具根跑 phantom：examples/tutorial/ 有自己的 pyproject（就近基底），
    # 其 app.py 的 import 按该基底解析——flaskr9 由 base/src 本地解析、
    # exdep8 由 base 声明解析；根下文件按根基底解析 rootdep7。
    root = _build_nested_fixture(tmp_path)
    flagged, _, proc = run_phantom(root)
    assert "flaskr9" not in flagged, (
        f"B：examples/tutorial/src/flaskr9 存在且就近基底为 examples/tutorial，"
        f"import flaskr9 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "exdep8" not in flagged, (
        f"B：examples/tutorial/pyproject.toml 已声明 exdep8（就近基底声明），"
        f"import exdep8 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "rootdep7" not in flagged, (
        f"B：根 pyproject 已声明 rootdep7，根下 import rootdep7 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_b_nested_control_invented_still_flagged(tmp_path):
    # 对照（防修过头）：就近基底解析不是放行嵌套目录——
    # examples/tutorial/app.py 里的纯发明名 invented77 仍必须标。
    root = _build_nested_fixture(tmp_path)
    flagged, pairs, proc = run_phantom(root)
    assert "invented77" in flagged, (
        f"B 对照：invented77 未声明、非本地、无守卫，仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert any(rel.endswith("app.py") and mod == "invented77" for rel, mod in pairs), (
        f"B 对照：invented77 的报告行应指向 examples/tutorial/app.py；"
        f"实际 pairs：{pairs!r}"
    )


# --------------------- C 版本/平台条件守卫（click/attrs/urllib3 类）


def test_c_sys_version_info_guard_both_branches_not_flagged(tmp_path):
    # if 测试式含 sys.version_info → 两分支均视为可选性结构：
    # else 分支的 typing_extensions 不得标（click 3.11 分支形态）。
    work = tmp_path / "proj"
    _write(
        work,
        "compat.py",
        "import sys\n"
        "\n"
        "if sys.version_info >= (3, 11):\n"
        "    from typing import Self\n"
        "else:\n"
        "    from typing_extensions import Self\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "typing_extensions" not in flagged, (
        f"C：sys.version_info 条件守卫的 else 分支属可选性结构，"
        f"from typing_extensions import Self 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_c_sys_platform_guard_not_flagged_bare_control_flagged(tmp_path):
    # if 测试式含 sys.platform → 分支内 import 视为可选性结构（urllib3
    # pyodide 形态）；对照：同夹具另一文件裸 import 仍必须标——防修过头。
    work = tmp_path / "proj"
    _write(
        work,
        "platform_only.py",
        "import sys\n"
        "\n"
        'if sys.platform == "emscripten":\n'
        "    import pyodide9\n",
    )
    _write(work, "bare.py", "import unguarded88\n")
    flagged, _, proc = run_phantom(work)
    assert "pyodide9" not in flagged, (
        f"C：sys.platform 条件守卫内的 import pyodide9 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "unguarded88" in flagged, (
        f"C 对照：裸 import unguarded88（无守卫无声明）仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------------------------- D 别名规则化（pysocks/markdown-it-py 类）


def test_d_py_prefix_and_py_suffix_forms_not_flagged(tmp_path):
    # 规则集（规范化后）：d ∈ {i, py+i, i+_py, i+_python, python_+i}。
    # py 前缀形式：声明 pysocks9 = py + socks9 → import socks9 不标；
    # _py 后缀形式：声明 markdown-it2-py（规范化 markdown_it2_py =
    # markdown_it2 + _py）→ import markdown_it2 不标。
    # （夹具名较任务原型有一处 spec 对齐修正，见文件头「夹具备注」。）
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        "[project]\n"
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["pysocks9", "markdown-it2-py"]\n',
    )
    _write(work, "app.py", "import socks9\nimport markdown_it2\n")
    flagged, _, proc = run_phantom(work)
    assert "socks9" not in flagged, (
        f"D：已声明 pysocks9（= py + socks9，py 前缀形式），"
        f"import socks9 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "markdown_it2" not in flagged, (
        f"D：已声明 markdown-it2-py（规范化 = markdown_it2 + _py，"
        f"_py 后缀形式），import markdown_it2 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_d_prefix_rule_is_full_composition_not_substring(tmp_path):
    # 对照（防修过头）：规则是「全名 + 前后缀」的精确合成，不是子串放行——
    # 声明 pyx 只能放行 import pyx / import x（py+x）之类，
    # 绝不能放行 import pyxq（pyx 只是 pyxq 的前缀子串）。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        "[project]\n"
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["pyx"]\n',
    )
    _write(work, "app.py", "import pyxq\n")
    flagged, _, proc = run_phantom(work)
    assert "pyxq" in flagged, (
        f"D 对照：声明 pyx 不得放行 import pyxq（子串≠合成形式，"
        f"pyxq ∉ 由 pyx 可导出的任一形式），仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ----------------------------------- E JS mocha 布局（express 类假 UNPROVEN）


MOCHA_PLAIN_JS_TEST = (
    "const assert = require('assert');\n"
    "\n"
    "describe('routes', () => {\n"
    "  it('adds numbers', () => {\n"
    "    assert.strictEqual(2 + 3, 5);\n"
    "  });\n"
    "  it('keeps element order', () => {\n"
    "    assert.ok([1, 2].indexOf(2) === 1);\n"
    "  });\n"
    "  it('joins path segments', () => {\n"
    "    assert.strictEqual(['a', 'b'].join('-'), 'a-b');\n"
    "  });\n"
    "});\n"
)

GOOD_JS_MODULE = (
    "function add(a, b) {\n"
    "  return a + b;\n"
    "}\n"
    "\n"
    "module.exports = { add };\n"
)


def _build_mocha_fixture(tmp_path):
    work = tmp_path / "proj"
    _write(work, "lib.js", GOOD_JS_MODULE)  # 可过 compile 的源文件
    # mocha 约定：顶层 test/ 目录下的 plain .js（非 *.test.js 后缀）
    _write(work / "test", "routes.js", MOCHA_PLAIN_JS_TEST)
    return work


def test_e_mocha_plain_js_under_test_dir_counted(tmp_path):
    # 顶层 test/ 目录下 plain .js 的 it() 断言测试应纳入测试识别：
    # coverage 计数 >0 且 exit 0（现行仅认 *.test.js → 计 0 → exit 3 = 红）。
    work = _build_mocha_fixture(tmp_path)
    proc = run_cli("coverage", work)
    assert proc.returncode == 0, (
        f"E：mocha test/ 布局下三个去重非平凡 it() 测试应使 coverage "
        f"exit 0，实际 {proc.returncode}；输出：{all_output(proc)!r}"
    )
    out = proc.stdout.strip()
    assert out and int(out.splitlines()[0]) > 0, (
        f"E：coverage 计数应 >0，实际 stdout：{proc.stdout!r}"
    )


@pytest.mark.skipif(
    shutil.which("node") is None,
    reason="宿主无 node：E 类 gate 断言的 compile 腿无法离线证明",
)
def test_e_gate_mocha_layout_not_unproven(tmp_path):
    # 同夹具过 gate：宿主有 node → compile 腿可证；测试识别修复后
    # 不得再因「零测试」判 UNPROVEN → RESULT: PASS + exit 0。
    work = _build_mocha_fixture(tmp_path)
    proc = run_cli("gate", work)
    out = all_output(proc)
    assert proc.returncode == 0, (
        f"E：mocha 布局夹具（可编译 js + test/ 下真实断言测试）gate 应 "
        f"exit 0，实际 {proc.returncode}；输出：{out!r}"
    )
    assert "RESULT: PASS" in out, (
        f"E：应打印 'RESULT: PASS'（不得再因零测试 UNPROVEN），"
        f"实际输出：{out!r}"
    )


# --------------- F 编译超时=UNPROVEN：无自动化测试，理由见文件头映射表 ---------------


# ----------------------- G java 工具链诚实判定（spring-petclinic 类）


def test_g_java_pom_without_toolchain_skip_unproven(tmp_path):
    # 有 pom.xml + .java 源，PATH 裁剪到只含 python（无 mvn/javac）：
    # java 必须被诚实承认并 SKIP（而非 FAIL、也非无声无息），
    # compile 判 UNPROVEN → exit 3。
    # 「javac 存在但 -version 失败（macOS 无 JDK stub）」分支无法离线
    # 确定性模拟，交真实仓 spring-petclinic 复验核销。
    work = tmp_path / "proj"
    _write(
        work,
        "pom.xml",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "  <modelVersion>4.0.0</modelVersion>\n"
        "  <groupId>com.example</groupId>\n"
        "  <artifactId>fixture-java</artifactId>\n"
        "  <version>0.0.1</version>\n"
        "</project>\n",
    )
    _write(
        work / "src",
        "Main.java",
        "public class Main {\n"
        "    public static void main(String[] args) {\n"
        '        System.out.println("ok");\n'
        "    }\n"
        "}\n",
    )
    proc = run_cli(
        "compile", work, env_overrides=_python_only_path_env(tmp_path)
    )
    out = all_output(proc)
    assert proc.returncode == 3, (
        f"G：有 pom 无 mvn/javac 应判 UNPROVEN（exit 3）而非 FAIL(1)/PASS(0)，"
        f"实际 {proc.returncode}；输出：{out!r}"
    )
    assert "SKIP" in out, (
        f"G：java 源必须被诚实承认为 SKIP（不可无声跳过或记 FAIL）；"
        f"实际输出：{out!r}"
    )
    assert "UNPROVEN" in out, f"G：输出必须含 UNPROVEN 字样，实际：{out!r}"
    assert "Traceback" not in out, f"G：缺工具链不应崩溃，实际输出：{out!r}"


# ------------------- H 脚本目录语义（防回退钉，追加时已实现，预期直接绿）


def test_h_importer_own_directory_participates_in_resolution(tmp_path):
    # H：importer 文件自身所在目录参与解析——tests/sub/runner.py 与
    # tests/sub/fixture_pkg9 同目录 → 对 root 跑 phantom 不标该行；
    # 对照：root/other.py 不同目录（fixture_pkg9 亦不在 root / root/src /
    # root/tests 顶层）→ 该行仍标。同名模块跨文件两判，按 pairs 逐行断言。
    root = tmp_path / "proj"
    _write(root / "tests" / "sub" / "fixture_pkg9", "__init__.py", "VALUE = 1\n")
    _write(root / "tests" / "sub", "runner.py", "import fixture_pkg9\n")
    _write(root, "other.py", "import fixture_pkg9\n")
    flagged, pairs, proc = run_phantom(root)
    assert not any(
        rel.endswith("runner.py") and mod == "fixture_pkg9" for rel, mod in pairs
    ), (
        f"H：runner.py 与 fixture_pkg9 同目录（脚本目录语义），"
        f"其 import fixture_pkg9 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert ("other.py", "fixture_pkg9") in pairs, (
        f"H 对照：脚本目录语义只对 importer 自身目录生效，root/other.py "
        f"的 import fixture_pkg9 仍必须标；实际 stdout：{proc.stdout!r}"
    )


# ----------------- I 平台运行时内建（防回退钉，追加时已实现，预期直接绿）


def test_i_pyodide_runtime_builtins_not_flagged_control_flagged(tmp_path):
    # I：js / pyodide / micropip 是 Pyodide/Emscripten 运行时命名空间
    # （策展表），裸 import（无声明无守卫）不得标；
    # 对照：表外相近发明名 js_invented9 仍必须标——防策展表变前缀放行。
    work = tmp_path / "proj"
    _write(
        work,
        "wasm_app.py",
        "import js\nimport pyodide\nimport micropip\n",
    )
    _write(work, "bare.py", "import js_invented9\n")
    flagged, _, proc = run_phantom(work)
    for mod in ("js", "pyodide", "micropip"):
        assert mod not in flagged, (
            f"I：{mod} 属平台运行时内建策展表，裸 import 不得标为幻影；"
            f"实际 stdout：{proc.stdout!r}"
        )
    assert "js_invented9" in flagged, (
        f"I 对照：js_invented9 不在策展表、未声明、无守卫，仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
