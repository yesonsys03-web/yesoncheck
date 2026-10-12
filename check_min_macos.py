"""빌드된 .app 번들 안의 모든 Mach-O 바이너리를 검사합니다.

- 목표 아키텍처(x86_64 / arm64) 슬라이스가 있는지
- 요구 최소 macOS 버전(minos)이 앱 Info.plist의 LSMinimumSystemVersion 이하인지
- 대상 컴퓨터에 없을 경로(/usr/local, /opt/homebrew 등)의 dylib를 참조하지 않는지
- @rpath·@loader_path·@executable_path 참조가 번들 안의 실제 파일을 가리키는지
- 심볼릭 링크가 번들 밖을 가리키거나 끊어져 있지 않은지

사용법: python check_min_macos.py <앱 번들> <아키텍처>
예:     python check_min_macos.py dist/YesonCheck_Autocut_Intel.app x86_64
문제가 하나라도 있으면 목록을 출력하고 종료 코드 1로 끝납니다.
"""

import os
import plistlib
import sys

from macholib.MachO import MachO
from macholib.mach_o import (
    LC_BUILD_VERSION,
    LC_LOAD_DYLIB,
    LC_LOAD_UPWARD_DYLIB,
    LC_LOAD_WEAK_DYLIB,
    LC_REEXPORT_DYLIB,
    LC_RPATH,
    LC_VERSION_MIN_MACOSX,
)
from macholib.util import is_platform_file

CPU_TYPES = {"x86_64": 0x01000007, "arm64": 0x0100000C}
DYLIB_COMMANDS = (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LOAD_UPWARD_DYLIB)
SYSTEM_PREFIXES = ("/usr/lib/", "/System/Library/")
# macholib이 인식하지 못하는 64비트 fat 형식 → 건너뛰지 않고 실패로 알림
FAT_MAGIC_64 = (b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca")


def decode_version(value):
    """Mach-O 버전 인코딩(xxxx.yy.zz)을 (major, minor) 튜플로 변환합니다."""
    return (value >> 16, (value >> 8) & 0xFF)


def c_string(data):
    return data.split(b"\x00", 1)[0].decode("utf-8", "replace")


def read_macho(path, cputype):
    """목표 아키텍처 헤더의 (minos, [(명령, dylib)], [rpath])를 읽습니다. 슬라이스가 없으면 None."""
    headers = [h for h in MachO(path).headers if h.header.cputype == cputype]
    if not headers:
        return None
    minos, dylibs, rpaths = None, [], []
    for lc, cmd, data in headers[0].commands:
        if lc.cmd == LC_BUILD_VERSION:
            minos = decode_version(cmd.minos)
        elif lc.cmd == LC_VERSION_MIN_MACOSX:
            minos = decode_version(cmd.version)
        elif lc.cmd in DYLIB_COMMANDS:
            dylibs.append((lc.cmd, c_string(data)))
        elif lc.cmd == LC_RPATH:
            rpaths.append(c_string(data))
    return minos, dylibs, rpaths


def expand(path, loader_dir, exec_dir):
    if path.startswith("@loader_path"):
        return loader_dir + path[len("@loader_path"):]
    if path.startswith("@executable_path"):
        return exec_dir + path[len("@executable_path"):]
    return path


def resolves_in_bundle(ref, loader_dir, exec_dir, rpaths, bundle_real):
    """dyld 방식으로 참조를 풀어 번들 안의 실제 파일이 있는지 확인합니다."""
    if ref.startswith("@rpath/"):
        candidates = [os.path.join(expand(r, loader_dir, exec_dir), ref[len("@rpath/"):]) for r in rpaths]
    else:
        candidates = [expand(ref, loader_dir, exec_dir)]
    for candidate in candidates:
        real = os.path.realpath(os.path.normpath(candidate))
        if os.path.isfile(real) and real.startswith(bundle_real + os.sep):
            return True
    return False


def check_file(path, cputype, max_version, exec_dir, exec_rpaths, bundle_real):
    """파일 하나를 검사해 (minos, 문제 목록)을 반환합니다."""
    info = read_macho(path, cputype)
    if info is None:
        return None, ["목표 아키텍처 슬라이스 없음"]
    minos, dylibs, rpaths = info

    problems = []
    loader_dir = os.path.dirname(path)
    for command, dylib in dylibs:
        if dylib.startswith(SYSTEM_PREFIXES):
            continue
        if not dylib.startswith("@"):
            problems.append(f"외부 dylib 참조: {dylib}")
            continue
        # 로더 자신의 rpath + 메인 실행 파일의 rpath (dyld가 로드 체인의 rpath를 함께 씀)
        if resolves_in_bundle(dylib, loader_dir, exec_dir, rpaths + exec_rpaths, bundle_real):
            continue
        if command == LC_LOAD_WEAK_DYLIB:
            continue  # weak 참조는 없어도 로드됨
        problems.append(f"번들 안에서 찾을 수 없는 참조: {dylib}")

    if minos is not None and minos > max_version:
        problems.append(f"최소 macOS {minos[0]}.{minos[1]} 필요")
    return minos, problems


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    bundle, arch = sys.argv[1], sys.argv[2]
    cputype = CPU_TYPES[arch]
    bundle_real = os.path.realpath(bundle)
    with open(os.path.join(bundle, "Contents", "Info.plist"), "rb") as fh:
        plist = plistlib.load(fh)
    min_macos = plist["LSMinimumSystemVersion"]
    max_version = tuple(int(p) for p in min_macos.split("."))[:2]

    # onefile 빌드는 라이브러리가 실행 파일 안에 압축돼 있어 검사할 수 없음
    frameworks = os.path.join(bundle, "Contents", "Frameworks")
    if not any(
        is_platform_file(os.path.join(root, name))
        for root, _dirs, files in os.walk(frameworks)
        for name in files
    ):
        print(f"Contents/Frameworks에 바이너리가 없습니다. onedir 모드로 빌드됐는지 확인하세요: {frameworks}")
        return 1

    exec_dir = os.path.join(bundle_real, "Contents", "MacOS")
    exec_info = read_macho(os.path.join(exec_dir, plist["CFBundleExecutable"]), cputype)
    exec_rpaths = exec_info[2] if exec_info else []

    checked = 0
    failures = []
    no_version = []
    for root, dirs, files in os.walk(bundle):
        for name in dirs + files:
            path = os.path.join(root, name)
            rel = os.path.relpath(path, bundle)
            if os.path.islink(path):
                target = os.path.realpath(path)
                if not os.path.exists(target):
                    failures.append(f"{rel}: 끊어진 심볼릭 링크")
                elif not target.startswith(bundle_real + os.sep):
                    failures.append(f"{rel}: 번들 밖을 가리키는 심볼릭 링크 → {target}")
                continue
            if name in dirs:
                continue
            with open(path, "rb") as fh:
                if fh.read(4) in FAT_MAGIC_64:
                    failures.append(f"{rel}: FAT64 형식은 검사할 수 없음 (직접 확인 필요)")
                    continue
            if not is_platform_file(path):
                continue
            checked += 1
            minos, problems = check_file(os.path.realpath(path), cputype, max_version, exec_dir, exec_rpaths, bundle_real)
            for problem in problems:
                failures.append(f"{rel}: {problem}")
            if minos is None and not problems:
                no_version.append(rel)

    print(f"Mach-O {checked}개 검사 (아키텍처 {arch}, 최소 macOS {min_macos})")
    if no_version:
        print(f"버전 정보가 없는 파일 {len(no_version)}개 (오래된 툴체인 빌드, 참고용):")
        for rel in no_version:
            print(f"  {rel}")
    if failures:
        print(f"문제 {len(failures)}건:")
        for line in failures:
            print(f"  {line}")
        return 1
    print("통과: 모든 바이너리가 조건을 만족합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
