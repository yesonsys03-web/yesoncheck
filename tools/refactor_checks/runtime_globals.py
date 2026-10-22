#!/usr/bin/env python3
"""yesoncheck 모듈의 모든 함수·메서드가 쓰는 모듈 전역 이름(LOAD_GLOBAL)이 풀리는지 확인 (import만, 창은 만들지 않음).

사용: runtime_globals.py [--root DIR] [-o REPORT.json]
  풀리지 않는 이름이 없으면 "unresolved: 0"을 출력하고 종료 0, 있으면 (함수, 이름)을 나열하고 종료 1.
  yesoncheck 아래 모듈을 모두 import하므로(PyQt5·TensorFlow 포함) 개발 환경의 Python으로 돌릴 것. 창은 만들지 않도록
  QT_QPA_PLATFORM=offscreen을 설정하고 .pyc도 쓰지 않는다. import에 실패하는 모듈은 숨기지 않고 예외를 그대로 낸다.

- 함수(중첩 함수·람다·컴프리헨션 포함)의 바이트코드에서 LOAD_GLOBAL 이름을 모아, 그 함수의 __globals__ 또는 builtins에
  있는지 본다 → 코드를 다른 파일로 옮기면서 import를 빠뜨려 드물게 도는 분기에서만 터질 NameError를 import 시점에 잡는다.
  새 모듈이 생겨도 yesoncheck 폴더에 있으면 저절로 훑는다.
- -o REPORT.json에는 함수별 사용 전역 이름과, tests/가 monkeypatch.setattr(모듈, "이름", …)로 바꾸는 모듈 전역을 어느
  함수가 읽는지 적는다 → 그 함수는 그 모듈에 남아야 시험이 그대로 통한다 (옮기면 시험의 patch 대상도 함께 옮겨야 함).
"""
import argparse
import builtins
import dis
import importlib
import inspect
import json
import os
import pkgutil
import re
import sys
import types

# 창을 만들지 않고, 도구가 소스 옆에 .pyc를 남기지 않게 (yesoncheck를 import하기 전에)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.dont_write_bytecode = True

PKG_NAME = "yesoncheck"
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_MODULE_ALIASES = {"sidebar_module": "player_sidebar"}  # 시험이 `import yesoncheck.player_sidebar as sidebar_module`로 쓰는 이름


def code_globals(code):
    names = set()
    for ins in dis.get_instructions(code):
        if ins.opname == "LOAD_GLOBAL":
            names.add(ins.argval)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names |= code_globals(const)
    return names


def unwrap(obj):
    """staticmethod·classmethod·functools 래퍼를 벗겨 안의 함수를 돌려줌 (함수가 아니면 그대로)"""
    if isinstance(obj, (staticmethod, classmethod)):
        obj = obj.__func__
    return inspect.unwrap(obj)


def functions_of(namespace, prefix, module_name, seen):
    """namespace(모듈 또는 클래스의 __dict__)에서 이 모듈이 정의한 함수·메서드·프로퍼티: (키, 함수) — 중첩 클래스도 따라감"""
    for name, obj in list(namespace.items()):
        obj = unwrap(obj)
        if isinstance(obj, property):
            for part, fn in (("fget", obj.fget), ("fset", obj.fset), ("fdel", obj.fdel)):
                if fn is not None:
                    yield f"{prefix}{name}.{part}", fn
        elif inspect.isfunction(obj):
            if obj.__module__ == module_name:  # `from .x import f`로 들어온 것은 x에서 훑음
                yield f"{prefix}{name}", obj
        elif inspect.isclass(obj) and obj.__module__ == module_name and id(obj) not in seen:
            seen.add(id(obj))
            yield from functions_of(vars(obj), f"{prefix}{name}.", module_name, seen)


def scan(root):
    sys.path.insert(0, root)
    pkg = importlib.import_module(PKG_NAME)
    report = {"unresolved": [], "uses": {}, "modules": []}
    for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
        module = importlib.import_module(f"{PKG_NAME}.{info.name}")
        report["modules"].append(info.name)
        for key, fn in functions_of(vars(module), f"{module.__name__}.", module.__name__, set()):
            used = code_globals(fn.__code__)
            report["uses"][key] = sorted(used)
            report["unresolved"].extend((key, n) for n in sorted(used) if n not in fn.__globals__ and not hasattr(builtins, n))
    return report


def test_patched_globals(root, report):
    """tests/가 monkeypatch.setattr로 바꾸는 yesoncheck 모듈 전역 → 그것을 읽는 함수"""
    modules = "|".join(sorted(report["modules"]))
    object_names = "|".join(sorted(set(report["modules"]) | set(TEST_MODULE_ALIASES)))
    patch_re = re.compile(rf'setattr\(\s*(?:yesoncheck\.)?({object_names})\s*,\s*"(\w+)"')  # setattr(player_base, "NAME", …)
    str_re = re.compile(rf'setattr\(\s*"yesoncheck\.({modules})\.(\w+)')  # setattr("yesoncheck.player_base.NAME", …)
    targets = set()
    tests = os.path.join(root, "tests")
    for fname in sorted(os.listdir(tests)) if os.path.isdir(tests) else []:
        if fname.endswith(".py"):
            with open(os.path.join(tests, fname), encoding="utf-8") as fh:
                text = fh.read()
            for m in patch_re.finditer(text):
                targets.add((TEST_MODULE_ALIASES.get(m.group(1), m.group(1)), m.group(2), fname))
            for m in str_re.finditer(text):
                targets.add((m.group(1), m.group(2), fname))
    pinned = {}
    for mod, name, tfile in sorted(targets):
        users = [k for k, g in report["uses"].items() if k.startswith(f"{PKG_NAME}.{mod}.") and name in g]
        pinned.setdefault(f"{mod}.{name}", {"tests": [], "functions": users})["tests"].append(tfile)
    return pinned


def main(argv=None):
    parser = argparse.ArgumentParser(description="yesoncheck 모듈 함수의 모듈 전역 이름이 풀리는지 확인")
    parser.add_argument("--root", default=DEFAULT_ROOT, help="저장소 루트 (yesoncheck/가 있는 곳, 기본: 이 도구가 든 저장소)")
    parser.add_argument("-o", "--output", help="함수별 사용 전역 이름 등을 담은 JSON 보고서를 쓸 파일")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.root)
    report = scan(root)
    report["test_patched_globals"] = test_patched_globals(root, report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=1, sort_keys=True)
            fh.write("\n")

    print(f"unresolved: {len(report['unresolved'])}  functions: {len(report['uses'])}  modules: {len(report['modules'])}")
    for key, name in report["unresolved"]:
        print(f"    {key}: {name}")
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    sys.exit(main())
