#!/usr/bin/env python3
"""VideoPlayer 믹스인 간 self 결합 스냅샷·비교 (읽기 전용 정적 분석 — 소스를 import/실행하지 않음, PyQt5 없이 돈다).

사용 (같은 Python으로 스냅샷과 비교를 해야 함 — 본문 해시가 ast 모양에 따라 Python 버전마다 다름):
  mixin_coupling.py snapshot -o FILE [--root DIR] [--qt-names FILE]
      작업 트리를 분석해 FILE에 JSON으로 씀. 기준을 정할 때(리팩토링 전)와 비교할 때(작업마다) 같은 도구.
  mixin_coupling.py compare --baseline FILE [--allow DIFF_FILE] [--root DIR] [--qt-names FILE]
      지금 작업 트리를 baseline과 견줌. 차이가 없으면 "차이 없음"을 출력하고 종료 0, 있으면 차이를 나열하고 종료 1.
      baseline을 읽을 수 없거나 Python 버전이 다르면 종료 2.

- 분석 대상: main_window.py의 `class VideoPlayer(...)`에서 시작해 패키지 안에서 정의된 기반 클래스를 재귀로 찾아 C3 순서
  (MRO)로 늘어놓고, 클래스마다 메서드 목록·self.X 쓰기/읽기/호출, getattr/hasattr/setattr 문자열 접근, self.__dict__ 접근,
  super() 호출을 모은다. 믹스인 파일·클래스가 늘어도 그대로 다시 돌릴 수 있다. OCRReviewDialog·OCRTimelineWidget과
  플레이어 밖 모듈(app·smoke_test·default_app·video_widget)이 플레이어에 닿는 이름도 모은다.
- 스냅샷의 "normalized"는 파일·클래스·줄 번호에 무관한 요약 — compare는 이것만 견준다. 메서드를 다른 믹스인으로 옮기기만
  하면 같고(함수 본문 해시의 다중집합, MRO에서 이기는 구현, super() 대상 구현, self 이름 사용 횟수), 본문이 바뀌거나 메서드가
  사라지거나 super() 대상이 바뀌면 다르다. "mro"(VideoPlayer·VideoPlayerBase·OCRReviewDialog의 클래스 이름 순서, 맨 끝은 Qt
  기반 클래스)도 들어 있어 믹스인을 더하거나 순서를 바꾸면 차이로 나온다.
- 차이의 한 줄은 `<항목> - <없어진 것>` / `<항목> + <생긴 것>` / `<항목> ~ <이름>: <전> → <후>` 모양.
- --allow DIFF_FILE: 그 작업에서 일어나리라 미리 적은 차이 목록. 한 줄에 차이 한 줄의 모양(`*`는 아무 글자나)을 쓰고, 빈 줄과
  `#` 줄은 무시. 차이가 모두 목록에 있고 목록의 줄이 모두 실제 차이에 쓰였을 때만 통과(허용만 했고 나타나지 않은 차이도 실패).
- Qt 이름 목록(qt_names.json, 이 폴더에 있음): Qt에서 물려받은 이름을 가르는 데만 씀. PyQt5가 바뀌면 PyQt5가 있는 환경에서
  다음으로 다시 뽑는다 (도구 자체는 PyQt5를 import하지 않음):
    python -I -c "import json; from PyQt5.QtWidgets import QMainWindow, QDialog; json.dump({'QMainWindow': sorted(dir(QMainWindow)), 'QDialog': sorted(dir(QDialog))}, open('tools/refactor_checks/qt_names.json', 'w'), indent=1, sort_keys=True)"
"""
import argparse
import ast
import collections
import hashlib
import json
import os
import re
import sys

PKG_NAME = "yesoncheck"
DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_QT_NAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qt_names.json")
SHORT = {  # 보고서용 짧은 이름 (없으면 클래스 이름)
    "PlayerUpdateMixin": "update", "PlayerAnnotationsMixin": "annotations", "PlayerSidebarMixin": "sidebar",
    "PlayerPlaybackMixin": "playback", "VideoPlayerBase": "base",
}
DYN_FUNCS = ("getattr", "hasattr", "setattr", "delattr")


# ---------------------------------------------------------------- 파싱·클래스 찾기
_TREES = {}


def parse(path):
    if path not in _TREES:
        with open(path, encoding="utf-8") as fh:
            _TREES[path] = ast.parse(fh.read(), filename=path)
    return _TREES[path]


def module_file(pkg_dir, module):
    """'yesoncheck.player_base' / '.player_base' → 파일 경로 (패키지 밖이면 None)"""
    if module.startswith("."):
        module = PKG_NAME + module
    if not module.startswith(PKG_NAME + "."):
        return None
    path = os.path.join(pkg_dir, *module.split(".")[1:]) + ".py"
    return path if os.path.exists(path) else None


def find_class_in(path, name):
    for node in parse(path).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    return None


def resolve_class(pkg_dir, path, name):
    """path 모듈에서 보이는 이름 name의 클래스 정의 (같은 모듈 또는 from-import). 패키지 밖이면 None."""
    cls = find_class_in(path, name)
    if cls is not None:
        return path, cls
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            mod = ("." * node.level + node.module) if node.level else node.module
            for alias in node.names:
                if (alias.asname or alias.name) == name:
                    target = module_file(pkg_dir, mod)
                    if target:
                        return resolve_class(pkg_dir, target, alias.name)
    return None


def c3(cls_key, bases_of):
    seqs = [[cls_key]] + [c3(b, bases_of) for b in bases_of[cls_key]] + [list(bases_of[cls_key])]
    seqs = [s[:] for s in seqs if s]
    out = []
    while seqs:
        for s in seqs:
            head = s[0]
            if not any(head in t[1:] for t in seqs):
                break
        else:
            raise TypeError("C3 실패")
        out.append(head)
        seqs = [t for t in ([x for x in t if x != head] for t in seqs) if t]
    return out


def discover(pkg_dir, path, name, include_root, externals=False):
    """path의 클래스 name과 (패키지 안) 기반 클래스들을 MRO 순서로: [(label, 파일이름, 클래스이름, ClassDef)]
    externals=True면 패키지 밖 기반 클래스(Qt 등)도 이름만 끼워 넣음 (파일이름 "", ClassDef None) — MRO 기록용"""
    found, bases_of = {}, {}

    def visit(p, n):
        key = (os.path.basename(p), n)
        if key in found:
            return key
        _, cls = resolve_class(pkg_dir, p, n)
        found[key] = cls
        bases_of[key] = []
        for b in cls.bases:
            r = resolve_class(pkg_dir, p, b.id) if isinstance(b, ast.Name) else None
            if r:
                bases_of[key].append(visit(r[0], r[1].name))
            elif externals:
                ext = ("", ast.unparse(b))
                found[ext], bases_of[ext] = None, []
                bases_of[key].append(ext)
        return key

    root = visit(path, name)
    return [(SHORT.get(n, n), f, n, found[(f, n)]) for f, n in c3(root, bases_of) if include_root or (f, n) != root]


def discover_player(pkg_dir):
    """VideoPlayer의 (패키지 안) 기반 클래스들 (VideoPlayer 자신은 몸체가 비어 있어 뺌)"""
    return discover(pkg_dir, os.path.join(pkg_dir, "main_window.py"), "VideoPlayer", include_root=False)


def find_class_anywhere(pkg_dir, name):
    for fname in sorted(os.listdir(pkg_dir)):
        if fname.endswith(".py"):
            cls = find_class_in(os.path.join(pkg_dir, fname), name)
            if cls is not None:
                return fname, cls
    raise LookupError(name)


# ---------------------------------------------------------------- 클래스 멤버·self 접근
def decorator_names(fn):
    return [ast.unparse(d.func if isinstance(d, ast.Call) else d) for d in fn.decorator_list]


def member_kind(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        decs = decorator_names(node)
        if "property" in decs:
            return "property"
        if any(d.endswith((".setter", ".deleter")) for d in decs):
            return "property_setter"
        if "staticmethod" in decs:
            return "staticmethod"
        if "classmethod" in decs:
            return "classmethod"
        return "method"
    return None


def class_members(cls):
    """클래스 몸체에서 직접 정의된 이름: {name: [(kind, lineno)]}"""
    members = collections.defaultdict(list)
    for node in cls.body:
        kind = member_kind(node)
        if kind:
            members[node.name].append((kind, node.lineno))
        elif isinstance(node, ast.Assign):
            is_signal = isinstance(node.value, ast.Call) and ast.unparse(node.value.func).endswith(("pyqtSignal", "Signal"))
            for t in node.targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        members[n.id].append(("signal" if is_signal else "classattr", node.lineno))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            members[node.target.id].append(("classattr", node.lineno))
    return members


def body_hash(node):
    return hashlib.sha1(ast.dump(node, include_attributes=False).encode()).hexdigest()[:12]


def member_node(cls, name):
    """클래스 몸체에서 name을 정의하는 마지막 노드 (같은 이름이 둘이면 나중 것이 이김)"""
    hit = None
    for n in cls.body:
        if getattr(n, "name", None) == name:
            hit = n
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(x, ast.Name) and x.id == name for t in targets for x in ast.walk(t)):
                hit = n
    return hit


class SelfVisitor(ast.NodeVisitor):
    """메서드 하나에서 receiver(self/cls).X의 쓰기·읽기·호출, getattr/hasattr/setattr 문자열 접근,
    self.__dict__.setdefault("X"), super().X() 를 모은다.
    - 중첩 함수/람다는 receiver 이름을 매개변수로 다시 쓰지 않는 한 같은 self (클로저 콜백)로 보되,
      '지금 바로 부르는 호출'(direct_calls, __init__ 도달 계산용)에서는 뺀다.
    - 중첩 클래스는 건너뛴다."""

    def __init__(self, recv, method, sink):
        self.recv, self.method, self.sink = recv, method, sink
        self.call_funcs, self.aug_targets = set(), set()
        self.deferred = 0
        self.direct_calls = set()

    def _is_recv(self, node):
        return isinstance(node, ast.Name) and node.id == self.recv

    def _shadowed(self, args):
        names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
        names += [a.arg for a in (args.vararg, args.kwarg) if a]
        return self.recv in names

    def visit_FunctionDef(self, node):
        for d in node.decorator_list:
            self.visit(d)
        if self._shadowed(node.args):
            return
        self.deferred += 1
        for stmt in node.body:
            self.visit(stmt)
        self.deferred -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node):
        if self._shadowed(node.args):
            return
        self.deferred += 1
        self.visit(node.body)
        self.deferred -= 1

    def visit_ClassDef(self, node):
        self.sink["nested_classes"].append((self.method, node.lineno, node.name))

    def visit_AugAssign(self, node):
        self.aug_targets.add(id(node.target))
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            self.call_funcs.add(id(f))
            if isinstance(f.value, ast.Call) and isinstance(f.value.func, ast.Name) and f.value.func.id == "super":
                self.sink["super_calls"].append((self.method, node.lineno, f.attr))
            # self.__dict__.setdefault("X", ...)
            if (isinstance(f.value, ast.Attribute) and f.value.attr == "__dict__" and self._is_recv(f.value.value)
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                name = node.args[0].value
                if f.attr in ("setdefault", "update", "__setitem__"):
                    self.sink["stores"][name].append((self.method, node.lineno, "dict_" + f.attr))
                self.sink["loads"][name].append((self.method, node.lineno, "dict_" + f.attr))
        if isinstance(f, ast.Name) and f.id in DYN_FUNCS and node.args and self._is_recv(node.args[0]):
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                bucket = "stores" if f.id in ("setattr", "delattr") else "loads"
                self.sink[bucket][node.args[1].value].append((self.method, node.lineno, f.id))
            else:
                self.sink["dynamic"].append((self.method, node.lineno, ast.unparse(node)[:120]))
        if isinstance(f, ast.Name) and f.id == "vars" and node.args and self._is_recv(node.args[0]):
            self.sink["dynamic"].append((self.method, node.lineno, ast.unparse(node)[:120]))
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if self._is_recv(node.value):
            name = node.attr
            if name in ("__dict__", "__class__"):
                self.sink["dynamic"].append((self.method, node.lineno, f"{self.recv}.{name}"))
            if isinstance(node.ctx, ast.Store):
                how = "augassign" if id(node) in self.aug_targets else "assign"
                self.sink["stores"][name].append((self.method, node.lineno, how))
                if how == "augassign":
                    self.sink["loads"][name].append((self.method, node.lineno, "read"))
            elif isinstance(node.ctx, ast.Del):
                self.sink["stores"][name].append((self.method, node.lineno, "del"))
            else:
                how = "call" if id(node) in self.call_funcs else "read"
                self.sink["loads"][name].append((self.method, node.lineno, how))
                if how == "call" and not self.deferred:
                    self.direct_calls.add(name)
        self.generic_visit(node)


def new_sink():
    return {"stores": collections.defaultdict(list), "loads": collections.defaultdict(list),
            "super_calls": [], "dynamic": [], "nested_classes": []}


def analyze_class(cls):
    sink = new_sink()
    calls_by_method = collections.defaultdict(set)
    stores_by_method = collections.defaultdict(set)
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or member_kind(node) == "staticmethod":
            continue
        args = node.args.posonlyargs + node.args.args
        if not args:
            continue
        local = new_sink()
        v = SelfVisitor(args[0].arg, node.name, local)
        for stmt in node.body:
            v.visit(stmt)
        for k in ("stores", "loads"):
            for name, sites in local[k].items():
                sink[k][name].extend(sites)
        for k in ("super_calls", "dynamic", "nested_classes"):
            sink[k].extend(local[k])
        calls_by_method[node.name] |= v.direct_calls
        stores_by_method[node.name] |= set(local["stores"])
    return sink, calls_by_method, stores_by_method


# ---------------------------------------------------------------- 다른 객체(부모·다이얼로그) 접근
class AliasVisitor(ast.NodeVisitor):
    """source(node)가 참인 식(예: self.parent(), self.ocr_review_dialog)과 그 식을 받은 지역 이름(별칭)의
    .X / getattr(·,'X') / hasattr(·,'X') / setattr(·,'X')를 기록. sticky 이름은 다시 할당돼도 별칭 유지."""

    def __init__(self, source, method, out, seed_aliases=(), sticky=()):
        self.source, self.method, self.out = source, method, out
        self.aliases, self.sticky = set(seed_aliases), set(sticky)
        self.call_funcs = set()

    def _is_target(self, node):
        return (isinstance(node, ast.Name) and node.id in self.aliases) or self.source(node)

    def _derived(self, value):  # parent = parent.parent() (부모 사슬 걷기)
        return (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and value.func.attr in ("parent", "parentWidget") and self._is_target(value.func.value))

    def visit_Assign(self, node):
        self.visit(node.value)
        is_src = self._is_target(node.value)
        for t in node.targets:
            if isinstance(t, ast.Name):
                if is_src:
                    self.aliases.add(t.id)
                elif t.id in self.aliases and t.id not in self.sticky and not self._derived(node.value):
                    self.aliases.discard(t.id)
            self.visit(t)

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute):
            self.call_funcs.add(id(f))
        if isinstance(f, ast.Name) and f.id in ("getattr", "hasattr", "setattr") and node.args and self._is_target(node.args[0]):
            ok = len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
            self.out.append((self.method, node.lineno, node.args[1].value if ok else "<dynamic>", f.id))
        self.generic_visit(node)

    def visit_Attribute(self, node):
        if self._is_target(node.value):
            how = "assign" if isinstance(node.ctx, ast.Store) else ("call" if id(node) in self.call_funcs else "read")
            self.out.append((self.method, node.lineno, node.attr, how))
        self.generic_visit(node)


def alias_scan(cls, source_factory, seed=None):
    out = []
    for node in cls.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args.posonlyargs + node.args.args
            v = AliasVisitor(source_factory(args[0].arg if args else "self"), node.name, out, seed(node) if seed else ())
            for stmt in node.body:
                v.visit(stmt)
    return out


def self_attr_source(attr_names):
    def factory(recv):
        return lambda n: (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                          and n.value.id == recv and n.attr in attr_names)
    return factory


def self_call_source(call_names):
    def factory(recv):
        return lambda n: (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                          and isinstance(n.func.value, ast.Name) and n.func.value.id == recv
                          and n.func.attr in call_names and not n.args)
    return factory


# ---------------------------------------------------------------- 추출
def build_snapshot(root, qt_path):
    """root의 작업 트리를 분석해 스냅샷(JSON으로 쓸 수 있는 dict)을 돌려줌"""
    pkg = os.path.join(root, PKG_NAME)
    with open(qt_path, encoding="utf-8") as fh:
        qt = json.load(fh)
    qt_main, qt_dialog = set(qt["QMainWindow"]), set(qt["QDialog"])

    player = discover_player(pkg)
    keys = [label for label, _, _, _ in player]
    cls_nodes = {label: cls for label, _, _, cls in player}
    result = {"meta": {"python": "%d.%d" % sys.version_info[:2]}, "mro": keys, "classes": {}}
    C = result["classes"]
    for label, fname, cname, cls in player:
        sink, calls_by_method, stores_by_method = analyze_class(cls)
        C[label] = {
            "file": fname, "class": cname, "lines": [cls.lineno, cls.end_lineno],
            "members": dict(sorted(class_members(cls).items())),
            "stores": dict(sorted(sink["stores"].items())), "loads": dict(sorted(sink["loads"].items())),
            "super_calls": sink["super_calls"], "dynamic": sink["dynamic"], "nested_classes": sink["nested_classes"],
            "calls_by_method": {k: sorted(v) for k, v in sorted(calls_by_method.items())},
            "stores_by_method": {k: sorted(v) for k, v in sorted(stores_by_method.items())},
        }

    member_def = {k: set(C[k]["members"]) for k in keys}
    kinds = lambda k, n: {x[0] for x in C[k]["members"].get(n, [])}
    method_like = {k: {n for n in member_def[k] if kinds(k, n) & {"method", "staticmethod", "classmethod"}} for k in keys}
    prop_like = {k: {n for n in member_def[k] if kinds(k, n) & {"property", "property_setter"}} for k in keys}
    classattr_like = {k: {n for n in member_def[k] if kinds(k, n) & {"classattr", "signal"}} for k in keys}
    store_def = {k: set(C[k]["stores"]) for k in keys}
    defines = {k: member_def[k] | store_def[k] for k in keys}

    def resolve(name):  # MRO에서 멤버(메서드·속성·클래스 속성)를 처음 가진 클래스
        return next((k for k in keys if name in member_def[k]), None)

    def owner_of(name, qt_names):
        o = resolve(name)
        if o:
            return o
        st = [k for k in keys if name in store_def[k]]
        return ("attr:" + ",".join(st)) if st else ("Qt" if name in qt_names else "UNDEFINED")

    # __init__ 도달 메서드 (지금 바로 부르는 self.X()만, MRO로 해석)
    init_owner = resolve("__init__")
    reach, stack = set(), [(init_owner, "__init__")]
    while stack:
        k, m = stack.pop()
        if (k, m) in reach:
            continue
        reach.add((k, m))
        for callee in C[k]["calls_by_method"].get(m, []):
            o = resolve(callee)
            if o and callee in method_like[o]:
                stack.append((o, callee))
    init_stores = set().union(*(set(C[k]["stores_by_method"].get(m, [])) for k, m in reach))
    result["init_reachable_methods"] = sorted(f"{k}.{m}" for k, m in reach)
    result["init_stored_attrs"] = sorted(init_stores)

    # 클래스별 (a)(b)(c)(d)
    per = {}
    for k in keys:
        b, c, d, undefined, qt_inh = {}, {}, {}, {}, {}
        for name, sites in C[k]["loads"].items():
            if name in defines[k]:
                continue
            others = [o for o in keys if o != k and name in defines[o]]
            meth_owners = [o for o in others if name in method_like[o]]
            if meth_owners:
                c[name] = {"owners": meth_owners, "sites": len(sites),
                           "calls": sum(s[2] == "call" for s in sites), "refs": sum(s[2] != "call" for s in sites)}
            elif others:
                guarded_methods = {s[0] for s in sites if s[2] in ("getattr", "hasattr")}
                b[name] = {"owners": others, "sites": len(sites),
                           "unguarded_methods": sorted({s[0] for s in sites} - guarded_methods),
                           "kind": "property" if any(name in prop_like[o] for o in others) else
                                   ("classattr" if any(name in classattr_like[o] for o in others) else "instance")}
            elif name in qt_main:
                qt_inh[name] = len(sites)
            else:
                undefined[name] = sites
        for name in sorted(store_def[k]):
            others = [o for o in keys if o != k and (name in store_def[o] or name in classattr_like[o])]
            if others:
                d[name] = {"others": others, "sites": len(C[k]["stores"][name])}
        per[k] = {"a_members": sorted(member_def[k]), "a_instance_attrs": sorted(store_def[k] - member_def[k]),
                  "b_reads_foreign": dict(sorted(b.items())), "c_calls_foreign": dict(sorted(c.items())),
                  "d_shared_writes": d, "undefined": dict(sorted(undefined.items())), "qt_inherited": dict(sorted(qt_inh.items()))}
    result["per_class"] = per

    # 의존 행렬 user -> definer: [서로 다른 이름 수, 사용 지점 수]
    matrix = {k: {o: [0, 0] for o in keys} for k in keys}
    for k in keys:
        for bucket in ("b_reads_foreign", "c_calls_foreign"):
            for name, info in per[k][bucket].items():
                for o in info["owners"]:
                    matrix[k][o][0] += 1
                    matrix[k][o][1] += info["sites"]
    result["matrix"] = matrix

    # 멤버 이름 충돌 (둘 이상 클래스) — effective = MRO에서 이기는 쪽
    collisions = {}
    for name in sorted(set().union(*member_def.values())):
        owners = [k for k in keys if name in member_def[k]]
        if len(owners) > 1:
            collisions[name] = {"owners": [(o, C[o]["members"][name]) for o in owners], "effective": owners[0],
                                "calls_super": [o for o in owners if any(s[0] == name and s[2] == name for s in C[o]["super_calls"])]}
    result["collisions"] = collisions
    result["duplicate_in_class"] = {k: {n: v for n, v in C[k]["members"].items()
                                        if len([x for x in v if x[0] != "property_setter"]) > 1} for k in keys}
    result["qt_overrides"] = {n: [k for k in keys if n in member_def[k]]
                              for n in sorted(set().union(*member_def.values())) if n in qt_main and not n.startswith("__")}
    result["attr_vs_method"] = {n: {"methods": [k for k in keys if n in method_like[k] | prop_like[k]],
                                    "stores": [k for k in keys if n in store_def[k]]}
                                for n in sorted(set().union(*store_def.values()))
                                if any(n in method_like[k] | prop_like[k] for k in keys)}
    result["attr_vs_qt"] = {n: [k for k in keys if n in store_def[k]]
                            for n in sorted(set().union(*store_def.values())) if n in qt_main}
    result["classattr_shadowed_by_instance"] = {n: {"classattr": [k for k in keys if n in classattr_like[k]],
                                                    "stores": [k for k in keys if n in store_def[k]]}
                                                for n in sorted(set().union(*classattr_like.values()))
                                                if any(n in store_def[k] for k in keys)}

    # 지연 생성(=__init__ 도달 메서드에서 쓰지 않음) 속성을 다른 파일이 읽는 경우
    lazy = {}
    for k in keys:
        for name, info in per[k]["b_reads_foreign"].items():
            if info["kind"] == "instance" and name not in init_stores:
                lazy.setdefault(name, {"owners": info["owners"], "readers": {}})["readers"][k] = {
                    "sites": info["sites"], "unguarded_methods": info["unguarded_methods"]}
    result["lazy_cross_reads"] = lazy

    hot = collections.defaultdict(lambda: {"users": set(), "sites": 0, "owners": set()})
    for k in keys:
        for bucket in ("b_reads_foreign", "c_calls_foreign"):
            for name, info in per[k][bucket].items():
                hot[name]["users"].add(k)
                hot[name]["sites"] += info["sites"]
                hot[name]["owners"].update(info["owners"])
    result["hotspots"] = sorted(({"name": n, "users": sorted(v["users"]), "owners": sorted(v["owners"]), "sites": v["sites"]}
                                 for n, v in hot.items()), key=lambda x: (-len(x["users"]), -x["sites"], x["name"]))

    # 문자열로 된 self 속성 이름 (예: RUNNING_JOB_ATTRS → getattr(self, attr))
    all_store = set().union(*store_def.values())
    string_refs = {}
    for k in keys:
        recorded = {(s[1], n) for n, ss in C[k]["loads"].items() for s in ss if s[2] in ("getattr", "hasattr") or s[2].startswith("dict_")}
        recorded |= {(s[1], n) for n, ss in C[k]["stores"].items() for s in ss if s[2] in ("setattr", "delattr")}
        for n in ast.walk(cls_nodes[k]):
            if (isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in all_store
                    and (n.lineno, n.value) not in recorded and n.value.isidentifier() and "_" in n.value):
                string_refs.setdefault(k, []).append((n.lineno, n.value, [o for o in keys if n.value in store_def[o]]))
    result["string_refs"] = string_refs

    # ---- OCRReviewDialog ↔ 플레이어, 타임라인 → 다이얼로그
    rv_file, rv = find_class_anywhere(pkg, "OCRReviewDialog")
    tl_file, tl = find_class_anywhere(pkg, "OCRTimelineWidget")
    rv_members = class_members(rv)
    rv_sink, _, _ = analyze_class(rv)
    rv_defined = set(rv_members) | set(rv_sink["stores"])
    result["review"] = {"file": rv_file, "lines": [rv.lineno, rv.end_lineno],
                        "duplicate_members": {n: v for n, v in rv_members.items() if len(v) > 1},
                        "super_calls": rv_sink["super_calls"],
                        "undefined": {n: s for n, s in rv_sink["loads"].items() if n not in rv_defined and n not in qt_dialog}}
    init_seed = lambda fn: {"parent"} if fn.name == "__init__" else set()
    result["dialog_to_player"] = [(m, l, n, h, owner_of(n, qt_main)) for m, l, n, h in
                                  alias_scan(rv, self_call_source({"parent", "parentWidget", "window"}), seed=init_seed)]
    dlg_owner = lambda n: "review" if n in rv_defined else ("Qt" if n in qt_dialog else "UNDEFINED")
    result["player_to_dialog"] = [(k, m, l, n, h, dlg_owner(n)) for k in keys
                                  for m, l, n, h in alias_scan(cls_nodes[k], self_attr_source({"ocr_review_dialog"}))]
    result["timeline_to_dialog"] = [(m, l, n, h, dlg_owner(n)) for m, l, n, h in
                                    alias_scan(tl, self_attr_source({"_parent_dialog"}))]

    # ---- 플레이어 밖 모듈의 플레이어 접근 (app.py·smoke_test.py의 player, default_app.py의 parent, video_widget.py의 부모 걷기)
    external = set()
    for fname, seed_names, parent_walk in [("app.py", {"player"}, False), ("smoke_test.py", {"player"}, False),
                                            ("default_app.py", {"parent"}, False), ("video_widget.py", set(), True)]:
        path = os.path.join(pkg, fname)
        if not os.path.exists(path):
            continue
        for fn in ast.walk(parse(path)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            out = []
            if parent_walk:
                recv = fn.args.args[0].arg if fn.args.args else "self"
                v = AliasVisitor(self_call_source({"parent", "parentWidget", "window"})(recv), fn.name, out)
            else:
                names = {x.id for x in ast.walk(fn) if isinstance(x, ast.Name)} | {a.arg for a in fn.args.args}
                seeds = seed_names & names
                if not seeds:
                    continue
                v = AliasVisitor(lambda n: False, fn.name, out, seeds, sticky=seeds)
            for stmt in fn.body:
                v.visit(stmt)
            for m, l, n, h in out:
                if not (parent_walk and n in ("parent", "parentWidget")):
                    external.add((fname, l, n, h, owner_of(n, qt_main)))  # 중첩 함수 중복 방문은 집합으로 제거
    result["external_access"] = sorted(external)

    # ---- 파일·클래스·줄 번호에 무관한 정규화 요약 (compare용)
    use = collections.defaultdict(collections.Counter)
    for k in keys:
        for name, sites in C[k]["loads"].items():
            for s in sites:
                use[name][s[2]] += 1
        for name, sites in C[k]["stores"].items():
            for s in sites:
                use[name]["w:" + s[2]] += 1
    effective = {}
    for name in sorted(set().union(*member_def.values())):
        o = resolve(name)
        effective[name] = {"kinds": sorted(kinds(o, name)), "body": body_hash(member_node(cls_nodes[o], name))}
    shadowed = {name: sorted(body_hash(member_node(cls_nodes[o], name)) for o, _ in info["owners"][1:])
                for name, info in collisions.items()}
    # 패키지 전체의 함수 몸체 다중집합 (모듈 함수 + 클래스 메서드, 중첩 함수는 바깥 함수에 포함) — '옮기기만'이면 같아야 함
    bodies, index = collections.Counter(), collections.defaultdict(list)
    for fname in sorted(os.listdir(pkg)):
        if not fname.endswith(".py"):
            continue
        tree = parse(os.path.join(pkg, fname))
        for top in tree.body:
            fns = [(top.name, top)] if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            if isinstance(top, ast.ClassDef):
                fns = [(f"{top.name}.{n.name}", n) for n in top.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for qual, fn in fns:
                h = body_hash(fn)
                bodies[h] += 1
                index[h].append(f"{fname}:{qual}")
    result["function_index"] = dict(index)
    # OCRReviewDialog도 같은 방식: 자신 + (패키지 안) 기반 클래스들의 MRO에서 이기는 구현·super 대상·self 이름 사용
    rv_chain = discover(pkg, os.path.join(pkg, rv_file), "OCRReviewDialog", include_root=True)
    rv_keys = [n for _, _, n, _ in rv_chain]
    rv_nodes = {n: c for _, _, n, c in rv_chain}
    rv_mem = {n: set(class_members(c)) for n, c in rv_nodes.items()}
    rv_effective, rv_super, rv_use = {}, set(), collections.defaultdict(collections.Counter)
    for name in sorted(set().union(*rv_mem.values())):
        o = next(k for k in rv_keys if name in rv_mem[k])
        rv_effective[name] = body_hash(member_node(rv_nodes[o], name))
    for i, k in enumerate(rv_keys):
        sk, _, _ = analyze_class(rv_nodes[k])
        for m, _, t in sk["super_calls"]:
            nxt = next((o for o in rv_keys[i + 1:] if t in rv_mem[o]), None)
            rv_super.add((m, t, body_hash(member_node(rv_nodes[nxt], t)) if nxt else "Qt"))
        for bucket, prefix in (("loads", ""), ("stores", "w:")):
            for name, sites in sk[bucket].items():
                for st in sites:
                    rv_use[name][prefix + st[2]] += 1

    # super().t() 가 MRO에서 실제로 닿는 구현 (부르는 클래스 다음부터 찾음; 없으면 Qt 기반 클래스)
    super_targets = set()
    for i, k in enumerate(keys):
        for m, _, t in C[k]["super_calls"]:
            nxt = next((o for o in keys[i + 1:] if t in member_def[o]), None)
            super_targets.add((m, t, body_hash(member_node(cls_nodes[nxt], t)) if nxt else "Qt"))
    # 클래스 이름으로 된 MRO (패키지 밖 기반 클래스는 이름만) — 믹스인을 더하거나 순서를 바꾸면 차이로 드러남
    base_file, _ = find_class_anywhere(pkg, "VideoPlayerBase")
    class_mro = {}
    for name, path in (("VideoPlayer", os.path.join(pkg, "main_window.py")),
                       ("VideoPlayerBase", os.path.join(pkg, base_file)),
                       ("OCRReviewDialog", os.path.join(pkg, rv_file))):
        class_mro[name] = [n for _, _, n, _ in discover(pkg, path, name, include_root=True, externals=True)]
    result["normalized"] = {
        "mro": class_mro,
        "function_bodies": sorted(bodies.items()),
        "super_targets": sorted(super_targets),
        "self_name_use": {n: dict(sorted(c.items())) for n, c in sorted(use.items())},
        "effective_members": effective,
        "shadowed_members": shadowed,
        "super_calls": sorted({(m, t) for k in keys for m, _, t in C[k]["super_calls"]}),
        "undefined": sorted({n for k in keys for n in per[k]["undefined"]}),
        "dynamic": sorted({d for k in keys for _, _, d in C[k]["dynamic"]}),
        "string_refs": sorted({s[1] for v in string_refs.values() for s in v}),
        "init_stored_attrs": result["init_stored_attrs"],
        "dialog_to_player": sorted(collections.Counter((n, h) for _, _, n, h, _ in result["dialog_to_player"]).items()),
        "player_to_dialog": sorted(collections.Counter((n, h) for _, _, _, n, h, _ in result["player_to_dialog"]).items()),
        "timeline_to_dialog": sorted(collections.Counter((n, h) for _, _, n, h, _ in result["timeline_to_dialog"]).items()),
        "review_effective_members": rv_effective,
        "review_super_targets": sorted(rv_super),
        "review_self_name_use": {n: dict(sorted(c.items())) for n, c in sorted(rv_use.items())},
        "external_access": sorted(collections.Counter((f, n, h) for f, _, n, h, _ in result["external_access"]).items()),
    }

    return json.loads(dump_snapshot(result))  # 파일에서 읽은 것과 같은 모양(튜플 → 리스트 등)으로 돌려줌


def dump_snapshot(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=True, default=list) + "\n"


# ---------------------------------------------------------------- 비교
def entry_text(key, sign, item):
    return f"{key} {sign} {json.dumps(item, ensure_ascii=False, sort_keys=True)}"


def diff_entries(before, after, index):
    """normalized 둘의 차이: [(항목, [차이 한 줄, ...])] — 항목 순서대로, 같은 항목은 빈 목록"""
    for side in (before, after):  # 함수 해시 옆에 어느 함수였는지 붙여 읽기 쉽게
        side["function_bodies"] = [[h, n, index.get(h, ["?"])[:3]] for h, n in side.get("function_bodies", [])]
    dumps = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True)
    result = []
    for key in sorted(set(before) | set(after)):
        x, y = before.get(key), after.get(key)
        lines = []
        if x != y:
            if isinstance(x, dict) and isinstance(y, dict):
                lines = [f"{key} ~ {n}: {dumps(x.get(n))} → {dumps(y.get(n))}" for n in sorted(set(x) | set(y)) if x.get(n) != y.get(n)]
            else:
                xs = {dumps(i) for i in (x or [])}
                ys = {dumps(i) for i in (y or [])}
                lines = [f"{key} - {i}" for i in sorted(xs - ys)] + [f"{key} + {i}" for i in sorted(ys - xs)]
            if not lines:  # 모양이 달라 위 방법으로 줄이 안 나올 때도 차이를 숨기지 않음
                lines = [f"{key} ~ {dumps(x)} → {dumps(y)}"]
        result.append((key, lines))
    return result


def read_allow(path):
    """허용 목록 파일: 줄마다 차이 한 줄의 모양 (`*`만 아무 글자나, 나머지는 글자 그대로) → [(줄, 정규식)]"""
    patterns = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#"):
                patterns.append((line, re.compile(".*".join(re.escape(part) for part in line.split("*")), re.S)))
    return patterns


def compare(baseline, current, allow_path=None):
    """baseline·current: 스냅샷 dict. 차이를 출력하고 종료 코드(0 같음/허용만, 1 차이)를 돌려줌"""
    index = {**baseline.get("function_index", {}), **current.get("function_index", {})}
    groups = diff_entries(baseline["normalized"], current["normalized"], index)
    patterns = read_allow(allow_path) if allow_path else []
    used = set()

    def allowed(line):
        hits = [p for p, rx in patterns if rx.fullmatch(line)]
        used.update(hits)
        return bool(hits)

    total = denied = 0
    for key, lines in groups:
        if not lines:
            print(f"[같음] {key}")
            continue
        print(f"[다름] {key}")
        for line in lines:
            total += 1
            ok = allowed(line)
            denied += not ok
            print(f"    {'(허용) ' if ok else ''}{line}")
    unused = [p for p, _ in patterns if p not in used]
    if unused:
        print(f"나타나지 않은 허용 {len(unused)}개 (예상한 차이가 일어나지 않았음):")
        for p in unused:
            print(f"    {p}")
    if denied:
        print(f"허용되지 않은 차이 {denied}개" if allow_path else f"차이 {denied}개")
    elif not total and not unused:
        print("차이 없음")
    elif not unused:
        print(f"허용된 차이만 있음 ({total}개)")
    return 1 if denied or unused else 0


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description="VideoPlayer 믹스인 결합 스냅샷·비교 (정적 분석, 읽기 전용)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("snapshot", "작업 트리를 분석해 스냅샷 파일을 씀"), ("compare", "지금 작업 트리를 baseline 스냅샷과 견줌")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--root", default=DEFAULT_ROOT, help="저장소 루트 (yesoncheck/가 있는 곳, 기본: 이 도구가 든 저장소)")
        p.add_argument("--qt-names", default=DEFAULT_QT_NAMES, help="Qt에서 물려받은 이름 목록 JSON (기본: 이 폴더의 qt_names.json)")
        if name == "snapshot":
            p.add_argument("-o", "--output", required=True, help="스냅샷을 쓸 JSON 파일")
        else:
            p.add_argument("--baseline", required=True, help="견줄 기준 스냅샷 JSON 파일")
            p.add_argument("--allow", metavar="DIFF_FILE", help="허용할 차이 목록 파일 (모듈 설명 참조)")
    args = parser.parse_args(argv)

    if args.command == "compare" and not os.path.isfile(args.baseline):
        fail(f"baseline 파일이 없음: {args.baseline}")
    snapshot = build_snapshot(os.path.abspath(args.root), args.qt_names)
    if args.command == "snapshot":
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(dump_snapshot(snapshot))
        print("ok", args.output, "MRO:", " → ".join(snapshot["normalized"]["mro"]["VideoPlayer"]))
        return 0

    with open(args.baseline, encoding="utf-8") as fh:
        baseline = json.load(fh)
    made_with = baseline.get("meta", {}).get("python")
    if made_with != snapshot["meta"]["python"]:
        fail(f"baseline은 Python {made_with}로 뜬 것인데 지금은 {snapshot['meta']['python']} — "
             "본문 해시가 Python 버전마다 달라 견줄 수 없음 (같은 Python으로 다시 스냅샷)")
    return compare(baseline, snapshot, args.allow)


if __name__ == "__main__":
    sys.exit(main())
