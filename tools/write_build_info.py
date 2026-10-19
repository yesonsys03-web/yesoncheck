"""빌드 정보(build_info.json: 버전·커밋·빌드 시각·플랫폼)를 만듭니다 — spec이 앱에 넣고 yesoncheck/build_info.py가 읽음.

build_app.sh(Mac)와 CI(Windows)가 PyInstaller 앞에 빌드 환경의 파이썬으로 실행합니다 (platform_key는 이 파이썬 기준).
버전: HEAD에 vX.Y.Z 태그가 있고 작업 폴더가 깨끗하면 X.Y.Z(배포판), 아니면 <HEAD에서 닿는 가장 큰 vX.Y.Z>+<커밋 7자리>
(태그가 없으면 0.0.0, 커밋 안 된 변경이 있으면 끝에 .dirty). git이 실패하면 기본값 없이 멈춥니다.
표준 출력: 파일 이름에 붙일 file_tag 한 줄 (배포판이면 X.Y.Z, 아니면 커밋 7자리).

사용법: python tools/write_build_info.py --out build/build_info.json [--version X.Y.Z]
"""

import argparse
import dataclasses
import datetime
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from yesoncheck import build_info  # noqa: E402

RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _release_numbers(tags):
    """vX.Y.Z 모양의 태그만 (X, Y, Z) 숫자로 (vfoo·v1.2·release-1 등은 버림)."""
    return [tuple(int(n) for n in m.groups()) for m in map(RELEASE_TAG.match, tags) if m]


def compute_version(tags_at_head, reachable_tags, sha, dirty):
    """git 상태로 버전을 정함: 깨끗한 작업 폴더의 HEAD에 vX.Y.Z가 있으면 "X.Y.Z" (여럿이면 가장 큰 것),
    아니면 "<닿는 가장 큰 vX.Y.Z 또는 0.0.0>+<커밋 7자리>" (+ dirty면 ".dirty"). 크기는 숫자로 비교 (1.1.10 > 1.1.9)."""
    if not FULL_SHA.match(sha):
        raise ValueError(f"커밋이 40자리 16진수가 아닙니다: {sha!r}")
    at_head = _release_numbers(tags_at_head)
    if at_head and not dirty:
        return "%d.%d.%d" % max(at_head)
    base = max(_release_numbers(reachable_tags), default=(0, 0, 0))
    return "%d.%d.%d+%s%s" % (*base, sha[:7], ".dirty" if dirty else "")


def file_tag(version, sha):
    """파일 이름에 붙일 꼬리: 배포판이면 버전 X.Y.Z, 아니면 커밋 7자리."""
    return version if RELEASE_VERSION.match(version) else sha[:7]


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 실패 (종료 코드 {result.returncode}, 폴더 {ROOT}):\n{result.stderr}")
    return result.stdout


def _same_dir(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def main(argv=None):
    parser = argparse.ArgumentParser(description="빌드 정보(build_info.json)를 만들고 file_tag를 한 줄 출력")
    parser.add_argument("--out", required=True, help="쓸 파일 (보통 build/build_info.json)")
    parser.add_argument("--version", help="git 대신 이 버전 X.Y.Z를 씀")
    args = parser.parse_args(argv)
    if args.version is not None and not RELEASE_VERSION.match(args.version):
        parser.error(f"--version은 X.Y.Z 모양이어야 합니다: {args.version!r}")

    # 이 폴더 자체가 저장소여야 함: 상위 폴더의 다른 저장소 커밋으로 버전을 정하지 않게
    toplevel = git("rev-parse", "--show-toplevel").strip()
    if not _same_dir(toplevel, ROOT):
        raise RuntimeError(f"이 폴더가 git 저장소의 맨 위가 아닙니다: {ROOT} (git 저장소 맨 위: {toplevel})")
    sha = git("rev-parse", "HEAD").strip()
    if args.version is not None:
        version = args.version
    else:
        dirty = bool(git("status", "--porcelain").strip())
        version = compute_version(git("tag", "--points-at", "HEAD").split(), git("tag", "--merged", "HEAD").split(),
                                  sha, dirty)
    info = build_info.BuildInfo(
        version=version,
        commit=sha,
        built=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        platform_key=build_info.platform_key(),
    )
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(dataclasses.asdict(info), fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"[write_build_info] {args.out}: {info}", file=sys.stderr)  # 표준 출력은 file_tag 한 줄만
    print(file_tag(version, sha))


if __name__ == "__main__":
    main()
