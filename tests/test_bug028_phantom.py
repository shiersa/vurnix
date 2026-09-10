"""BUG-028 复现/验收测试（test-author 独立产出，仅由 spec + 公开契约推导）。

实现者禁改本文件（恒态红线 §二6）；修订仅限已确认 spec 变更或夹具损坏经 reviewer 会签。
预期先红：0.3.1 phantom 通用化（声明依赖/布局/守卫/别名五路判定）未实现前，
AC1-AC4 各测试应因误报存在而失败；AC5 回归测试与 exit-0 契约应保持绿。

公开契约（FEAT-019 AC4）：`vurnix phantom <root>` 每行 `相对路径\t模块名`，
空输出 = 干净，exit 恒 0。

AC → 测试映射（BUG-028）
=============
AC1  声明依赖三源（声明名规范化 lower、-↔_ 后命中即非幻影）:
     test_ac1_pyproject_dependencies_and_optional_not_flagged
       （pyproject [project] dependencies + optional-dependencies 组，二合一）
     test_ac1_requirements_dir_dev_txt_not_flagged
     test_ac1_setup_py_install_requires_literal_not_flagged
AC2  布局（搜索路径扩为 root, root/src, root/tests）:
     test_ac2_src_layout_package_import_not_flagged
     test_ac2_tests_sibling_helper_package_not_flagged
AC3  守卫式 import 收集阶段跳过（同夹具裸 import 对照防修过头）:
     test_ac3_try_except_importerror_skipped_bare_sibling_still_flagged
     test_ac3_type_checking_attribute_block_skipped
AC4  常见 import名≠发行名 别名表:
     test_ac4_alias_declared_pyyaml_import_yaml_not_flagged
     test_ac4_alias_declared_pillow_import_pil_not_flagged
AC5  抓幻影能力不回退:
     test_ac5_invented_name_still_flagged_with_file_and_module
     test_ac5_declared_foo_bar_but_import_other_still_flagged
版本  0.3.1:
     test_version_is_0_3_1

W-8 实测追加的四处精修（R1-R4，spec 回填后追加的防回退钉，追加时精修已实现，
预期直接绿；非复现红测）:
R1   try/except ImportError 的 else 腿同属守卫:
     test_r1_else_leg_of_import_guard_skipped
R2   同文件同名传播（传播只限同文件，跨文件裸 import 仍标）:
     test_r2_same_file_same_name_propagation_other_file_still_flagged
R3   PEP 735 [dependency-groups] 纳入声明源:
     test_r3_pep735_dependency_groups_not_flagged
R4   声明文件向上搜索项目根 + docs/requirements*.txt 纳入:
     test_r4_upward_root_search_and_docs_requirements_not_flagged
"""

import os
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
# 全部用 tmp_path 现场构造合成项目，离线、确定性；模块名均为发明名，
# 保证宿主环境不可解析（排除「碰巧本机装了」的干扰）。


def _write(directory, name, text):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------- AC1 声明依赖三源 → 非幻影


def test_ac1_pyproject_dependencies_and_optional_not_flagged(tmp_path):
    # pyproject [project] dependencies 声明 foo-bar，optional-dependencies
    # 组内声明 extra-pkg；规范化（-↔_）后 import foo_bar / extra_pkg 均非幻影。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["foo-bar>=1"]\n'
        '\n'
        '[project.optional-dependencies]\n'
        'dev = ["extra-pkg>=2"]\n',
    )
    _write(work, "app.py", "import foo_bar\nimport extra_pkg\n")
    flagged, _, proc = run_phantom(work)
    assert "foo_bar" not in flagged, (
        f"pyproject dependencies 已声明 foo-bar，import foo_bar 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "extra_pkg" not in flagged, (
        f"optional-dependencies 组内已声明 extra-pkg，import extra_pkg "
        f"不得标为幻影；实际 stdout：{proc.stdout!r}"
    )


def test_ac1_requirements_dir_dev_txt_not_flagged(tmp_path):
    # requirements/ 目录下的 dev.txt 也是声明源（spec：requirements*.txt
    # 与 requirements/*.txt）。
    work = tmp_path / "proj"
    _write(work / "requirements", "dev.txt", "freezegun==1.4.0\n")
    _write(work, "app.py", "import freezegun\n")
    flagged, _, proc = run_phantom(work)
    assert "freezegun" not in flagged, (
        f"requirements/dev.txt 已声明 freezegun，不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac1_setup_py_install_requires_literal_not_flagged(tmp_path):
    # setup.py install_requires 字符串字面量（正则抽取，不执行代码）。
    work = tmp_path / "proj"
    _write(
        work,
        "setup.py",
        "from setuptools import setup\n"
        "\n"
        "setup(\n"
        '    name="fixture-proj",\n'
        '    install_requires=["charset_normalizer"],\n'
        ")\n",
    )
    _write(work, "app.py", "import charset_normalizer\n")
    flagged, _, proc = run_phantom(work)
    assert "charset_normalizer" not in flagged, (
        f"setup.py install_requires 已声明 charset_normalizer，不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------------------------------------- AC2 标准布局（src / tests）→ 非幻影


def test_ac2_src_layout_package_import_not_flagged(tmp_path):
    # src 布局是标准约定：src/mypkg 存在时，根下 import mypkg 非幻影。
    work = tmp_path / "proj"
    _write(work / "src" / "mypkg", "__init__.py", "VALUE = 1\n")
    _write(work, "main.py", "import mypkg\n")
    flagged, _, proc = run_phantom(work)
    assert "mypkg" not in flagged, (
        f"src/mypkg 存在，import mypkg 不得标为幻影（搜索路径应含 root/src）；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac2_tests_sibling_helper_package_not_flagged(tmp_path):
    # pytest tests/ 布局：tests/ 内兄弟包 helpers 对 tests/test_x.py 可解析。
    work = tmp_path / "proj"
    _write(work / "tests" / "helpers", "__init__.py", "TOKEN = 'x'\n")
    _write(
        work / "tests",
        "test_x.py",
        "import helpers\n"
        "\n"
        "\n"
        "def test_token():\n"
        "    assert helpers.TOKEN == 'x'\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "helpers" not in flagged, (
        f"tests/helpers 存在，tests/test_x.py 的 import helpers 不得标为幻影"
        f"（搜索路径应含 root/tests）；实际 stdout：{proc.stdout!r}"
    )


# --------------------------------------- AC3 守卫式 import 跳过 + 裸 import 对照


def test_ac3_try_except_importerror_skipped_bare_sibling_still_flagged(tmp_path):
    # try/except ImportError 守卫内的 import 收集阶段即跳过；
    # 同一夹具另一文件裸 import（无守卫、无声明）仍必须标——防修过头。
    work = tmp_path / "proj"
    _write(
        work,
        "guarded.py",
        "try:\n"
        "    import maybe_missing\n"
        "except ImportError:\n"
        "    maybe_missing = None\n",
    )
    _write(work, "bare.py", "import maybe_missing2\n")
    flagged, _, proc = run_phantom(work)
    assert "maybe_missing" not in flagged, (
        f"try/except ImportError 守卫内的 import 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "maybe_missing2" in flagged, (
        f"对照：裸 import maybe_missing2（无守卫无声明）仍必须标为幻影"
        f"（防修过头）；实际 stdout：{proc.stdout!r}"
    )


def test_ac3_type_checking_attribute_block_skipped(tmp_path):
    # if t.TYPE_CHECKING:（Attribute 形式）块内的 import 收集阶段即跳过。
    work = tmp_path / "proj"
    _write(
        work,
        "typed.py",
        "import typing as t\n"
        "\n"
        "if t.TYPE_CHECKING:\n"
        "    import maybe_typed_dep\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "maybe_typed_dep" not in flagged, (
        f"if t.TYPE_CHECKING: 块内的 import 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ------------------------------------------- AC4 import名≠发行名 别名表


def test_ac4_alias_declared_pyyaml_import_yaml_not_flagged(tmp_path):
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["pyyaml"]\n',
    )
    _write(work, "app.py", "import yaml\n")
    flagged, _, proc = run_phantom(work)
    assert "yaml" not in flagged, (
        f"已声明 pyyaml，别名表应使 import yaml 非幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac4_alias_declared_pillow_import_pil_not_flagged(tmp_path):
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["pillow>=10"]\n',
    )
    _write(work, "app.py", "import PIL\n")
    flagged, _, proc = run_phantom(work)
    assert "PIL" not in flagged, (
        f"已声明 pillow，别名表应使 import PIL 非幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# ----------------------------------------- AC5 抓幻影能力不回退（回归守卫）


def test_ac5_invented_name_still_flagged_with_file_and_module(tmp_path):
    # 纯发明名、无任何声明/守卫：必须标，且文件名与模块名都对。
    work = tmp_path / "proj"
    _write(work, "inventor.py", "import totally_invented_xyz\n")
    flagged, pairs, proc = run_phantom(work)
    assert ("inventor.py", "totally_invented_xyz") in pairs, (
        f"应有一行 'inventor.py\\ttotally_invented_xyz'，"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_ac5_declared_foo_bar_but_import_other_still_flagged(tmp_path):
    # 声明了 foo-bar，但代码 import 的是别名表外的另一个名字：仍必须标。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["foo-bar>=1"]\n',
    )
    _write(work, "app.py", "import completely_other\n")
    flagged, _, proc = run_phantom(work)
    assert "completely_other" in flagged, (
        f"completely_other 未声明、非别名、无守卫，仍必须标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


# --------------------------------- W-8 精修 R1-R4（防回退钉，预期直接绿）


def test_r1_else_leg_of_import_guard_skipped(tmp_path):
    # R1：try/except ImportError 的 else 腿同属守卫（requests help.py 的
    # `else: import OpenSSL` 形态），else 腿内的 import 不得标为幻影。
    work = tmp_path / "proj"
    _write(
        work,
        "guarded_else.py",
        "try:\n"
        "    import maybe_a\n"
        "except ImportError:\n"
        "    maybe_a = None\n"
        "else:\n"
        "    import maybe_a_extra\n",
    )
    flagged, _, proc = run_phantom(work)
    assert "maybe_a_extra" not in flagged, (
        f"R1：else 腿同属守卫，import maybe_a_extra 不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )
    assert "maybe_a" not in flagged, (
        f"R1 前置：try 块内的 import maybe_a 本就不得标；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_r2_same_file_same_name_propagation_other_file_still_flagged(tmp_path):
    # R2：某名在该文件任一守卫 import 出现过 → 该文件内其它同名 import
    # 视为同一可选性结构（requests compat.py 的 has_simplejson flag 形态）；
    # 对照：传播只限同文件，另一文件裸 import optmod 无守卫 → 该文件行仍标。
    work = tmp_path / "proj"
    _write(
        work,
        "compat_like.py",
        "has_x = False\n"
        "try:\n"
        "    import optmod\n"
        "    has_x = True\n"
        "except ImportError:\n"
        "    pass\n"
        "if has_x:\n"
        "    from optmod import thing\n",
    )
    _write(work, "bare_opt.py", "import optmod\n")
    flagged, pairs, proc = run_phantom(work)
    assert ("compat_like.py", "optmod") not in pairs, (
        f"R2：optmod 在 compat_like.py 内有守卫 import，同文件的 "
        f"from optmod import thing 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert ("bare_opt.py", "optmod") in pairs, (
        f"R2 对照：传播只限同文件，bare_opt.py 的裸 import optmod "
        f"仍必须标；实际 stdout：{proc.stdout!r}"
    )


def test_r3_pep735_dependency_groups_not_flagged(tmp_path):
    # R3：pyproject 顶层 PEP 735 [dependency-groups] 纳入声明源
    # （itsdangerous 形态）。
    work = tmp_path / "proj"
    _write(
        work,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        '\n'
        '[dependency-groups]\n'
        'tests = ["freezegun2"]\n',
    )
    _write(work, "app.py", "import freezegun2\n")
    flagged, _, proc = run_phantom(work)
    assert "freezegun2" not in flagged, (
        f"R3：[dependency-groups] 已声明 freezegun2，不得标为幻影；"
        f"实际 stdout：{proc.stdout!r}"
    )


def test_r4_upward_root_search_and_docs_requirements_not_flagged(tmp_path):
    # R4：对 <root>/src2 子树跑 phantom，声明文件向上搜索到项目根
    # （标记 = pyproject 等）仍可见；RTD 约定 docs/requirements*.txt 纳入。
    root = tmp_path / "proj"
    _write(
        root,
        "pyproject.toml",
        '[project]\n'
        'name = "fixture-proj"\n'
        'version = "0.0.1"\n'
        'dependencies = ["foo-bar>=1"]\n',
    )
    _write(root / "docs", "requirements.txt", "docdep==1.0\n")
    _write(
        root / "src2" / "pkg",
        "app.py",
        "import foo_bar\nimport docdep\n",
    )
    flagged, _, proc = run_phantom(root / "src2")
    assert "foo_bar" not in flagged, (
        f"R4：声明在上层 pyproject（向上搜索项目根应发现），"
        f"import foo_bar 不得标为幻影；实际 stdout：{proc.stdout!r}"
    )
    assert "docdep" not in flagged, (
        f"R4：docs/requirements.txt 已声明 docdep（RTD 约定纳入声明源），"
        f"不得标为幻影；实际 stdout：{proc.stdout!r}"
    )


# ------------------------------------------------------------------ 版本 0.3.1


def test_version_is_0_3_1():
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
    assert proc.stdout.strip() == "0.3.1", (
        f"__version__ 应为 0.3.1，实际 {proc.stdout.strip()!r}"
    )
