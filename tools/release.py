"""배포 도구 — "배포해줘"에서 이 Mac이 실행 (Claude가 실행하고 기다리기는 Claude가 직접, 사용자는 바뀐 점만 확인).

  prepare   확인(gh 로그인·깨끗한 작업 폴더·커밋이 origin/main에 있음·커밋에 tools/write_build_info.py·NAS에 쓸 수
            있음) → 번호 → 바뀐 점을 메시지로 주석 태그 vX.Y.Z → 푸시 → 그 태그의 CI 실행 id·주소를 JSON 한 줄로
            (실행을 기다리지 않음 — 세 빌드는 30분 넘게 걸림)
  publish   CI의 job별 성공 확인 → artifact 받기(파일 이름이 이미 Release 이름) → latest.json → 초안 Release
            (파일 4개, 노트 = 태그 메시지) → 공개·"latest"(--draft-only면 초안 그대로) → NAS 복사 → JSON 한 줄 보고
  nas-sync  Release 파일을 받아 latest.json과 대조한 뒤 NAS에 다시 복사 (GitHub에는 공개됐는데 NAS 복사가 실패했을 때)
  abort     원격·로컬 태그와 초안 Release를 지움 (CI가 실패했을 때 — 번호는 다음 배포가 다시 씀). 공개된 Release면 거부

NAS 위치: <공유 설정 폴더>/updates (shared_config.configured_config_dir()). 설치 파일을 먼저(임시 이름 → sha256 확인 →
이름 바꾸기), latest.json을 맨 마지막에 바꿔 넣어 앱이 반쯤 복사된 파일을 보지 않게 하고, 지금·바로 전 버전만 남깁니다.
외부 명령(git·gh)은 모두 run() 하나를 거치고, 실패하면 명령·출력 전부와 함께 멈춥니다 (오류를 삼키지 않음).

사용법: python tools/release.py prepare --notes-file F [--minor | --version X.Y.Z] [--commit REF] [--allow-branch]
        python tools/release.py publish vX.Y.Z [--draft-only --nas-dir DIR] [--without-arm64]
        python tools/release.py nas-sync vX.Y.Z [--nas-dir DIR]
        python tools/release.py abort vX.Y.Z
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from yesoncheck import shared_config, updates  # noqa: E402

REPO = "yesonsys03-web/yesoncheck"  # updates.GITHUB_RELEASES_URL의 저장소 (시험이 같은지 확인)
WORKFLOW = "windows-build.yml"
PLATFORM_KEYS = ("windows", "mac-x86_64", "mac-arm64")
# Release 파일 이름 · CI artifact 이름 · CI job 이름 ({}는 X.Y.Z — 태그 빌드는 artifact 안 파일이 이미 Release 이름)
ASSET_TEMPLATES = {
    "windows": "YesonCheck_Setup_{}.exe",
    "mac-x86_64": "YesonCheck_Autocut_Intel_{}.dmg",
    "mac-arm64": "YesonCheck_Autocut_AppleSilicon_{}.dmg",
}
ARTIFACT_TEMPLATES = {
    "windows": "YesonCheck_Setup_Windows_{}",
    "mac-x86_64": "YesonCheck_Autocut_Intel_{}",
    "mac-arm64": "YesonCheck_Autocut_AppleSilicon_{}",
}
JOB_NAMES = {"windows": "build", "mac-x86_64": "mac (Intel)", "mac-arm64": "mac (AppleSilicon)"}
VERSION_FILE = "tools/write_build_info.py"  # 이 파일이 든 커밋(1.1.0 이후)만 앱이 자기 버전을 앎 → 배포 가능
MAIN_REF = "origin/main"
FILE_MODE = 0o644  # Windows PC의 NAS 계정은 이 Mac과 달라 모두 읽을 수 있어야 함 (쓰기는 이 Mac만)
DIR_MODE = 0o755
RUN_POLL_TRIES = 12  # 태그를 푸시한 뒤 CI 실행이 보일 때까지 약 1분
RUN_POLL_S = 5
RELEASE_LIST_LIMIT = "100"

_RELEASE_TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
_RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+")
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_ASSET_PATTERNS = [
    re.compile(re.escape(before) + r"(\d+\.\d+\.\d+)" + re.escape(after))
    for before, after in (template.split("{}") for template in ASSET_TEMPLATES.values())
]


class ReleaseError(RuntimeError):
    """배포를 멈춰야 하는 문제 (무엇이 왜 문제인지와 다음에 할 일을 한국어로)."""


class CommandError(RuntimeError):
    """외부 명령이 0이 아닌 종료 코드로 끝남 — 명령·종료 코드·표준 출력·표준 오류 전부가 메시지에."""


def log(message):
    print(f"[release] {message}", file=sys.stderr, flush=True)  # 표준 출력은 결과 JSON 한 줄만


def run(cmd: list[str], cwd=None) -> str:
    """외부 명령 하나를 실행하고 표준 출력을 돌려줌. 실패(종료 코드 ≠ 0)하면 명령과 출력 전부로 CommandError.
    입력은 닫음(gh가 묻는 창에서 멈추지 않고 실패하게)."""
    log("$ " + shlex.join(cmd))
    result = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise CommandError(
            f"명령 실패 (종료 코드 {result.returncode}, 폴더 {cwd or os.getcwd()}): {shlex.join(cmd)}\n"
            f"[표준 출력]\n{result.stdout}\n[표준 오류]\n{result.stderr}"
        )
    return result.stdout


def git(*args):
    return run(["git", *args], cwd=ROOT)


def gh(*args):
    return run(["gh", *args, "--repo", REPO], cwd=ROOT)


# ── 순수 함수 ───────────────────────────────────────────────────────────────


def _check_release_version(version):
    if not isinstance(version, str) or not _RELEASE_VERSION.fullmatch(version):
        raise ValueError(f"배포 버전은 X.Y.Z 모양이어야 합니다: {version!r}")


def next_version(tags: list[str], minor: bool) -> str:
    """다음 배포 번호: 가장 큰 vX.Y.Z 태그에서 끝자리 +1 (minor면 가운데 +1·끝 0). 배포 태그가 없으면 1.1.0.
    크기는 숫자로 비교 (1.1.10 > 1.1.9), vX.Y.Z 모양이 아닌 태그는 버림."""
    numbers = [tuple(int(n) for n in m.groups()) for m in map(_RELEASE_TAG.fullmatch, tags) if m]
    if not numbers:
        return "1.1.0"
    major, middle, last = max(numbers)
    return f"{major}.{middle + 1}.0" if minor else f"{major}.{middle}.{last + 1}"


def asset_names(version: str) -> dict[str, str]:
    """플랫폼 키 → Release 파일 이름."""
    _check_release_version(version)
    return {key: template.format(version) for key, template in ASSET_TEMPLATES.items()}


def _asset_version(name):
    """Release 파일 이름이면 그 버전 X.Y.Z, 아니면 None."""
    for pattern in _ASSET_PATTERNS:
        match = pattern.fullmatch(name)
        if match:
            return match.group(1)
    return None


def _hash_file(path):
    """(sha256 소문자 16진수, 크기)."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def now_iso():
    """latest.json의 released: 지금 시각, 이 Mac의 시간대, 초까지 (예: 2026-10-25T10:00:00+09:00)."""
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def make_manifest(version: str, commit: str, released: str, notes: str, files: dict[str, str]) -> bytes:
    """latest.json의 바이트. files: 플랫폼 키 → 파일 경로 (파일 이름은 Release 이름 그대로여야 함), sha256·크기를 계산.
    만든 것을 앱이 쓰는 parse_manifest로 스스로 검사."""
    _check_release_version(version)
    if not isinstance(commit, str) or not _FULL_SHA.fullmatch(commit):
        raise ValueError(f"커밋이 40자리 16진수가 아닙니다: {commit!r}")
    if not files:
        raise ValueError("latest.json에 넣을 설치 파일이 없습니다")
    unknown = sorted(set(files) - set(PLATFORM_KEYS))
    if unknown:
        raise ValueError(f"모르는 플랫폼 키: {', '.join(unknown)} (가능: {', '.join(PLATFORM_KEYS)})")
    names = asset_names(version)
    entries = {}
    for key in PLATFORM_KEYS:
        if key not in files:
            continue
        path = files[key]
        if os.path.basename(path) != names[key]:
            raise ValueError(f"{key} 파일 이름이 Release 이름({names[key]})이 아닙니다: {path}")
        sha256, size = _hash_file(path)
        entries[key] = {"name": names[key], "size": size, "sha256": sha256}
    payload = {"version": version, "commit": commit, "released": released, "notes": notes, "files": entries}
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    parsed = updates.parse_manifest(data)
    if str(parsed.version) != version or sorted(parsed.files) != sorted(entries):
        raise ValueError(f"만든 latest.json을 다시 읽은 값이 다릅니다: {parsed}")
    return data


# ── NAS ─────────────────────────────────────────────────────────────────────


def default_nas_dir():
    """<공유 설정 폴더>/updates — 앱(updates.read_nas)이 읽는 곳."""
    config_dir = shared_config.configured_config_dir()
    if not config_dir:
        raise ReleaseError("공유 설정 폴더를 모릅니다 (이 컴퓨터에 공유 설정 폴더가 정해져 있지 않음)")
    return os.path.join(config_dir, updates.NAS_DIR_NAME)


def check_nas_writable(nas_dir):
    """NAS 폴더(아직 없으면 그 위 폴더 — 처음 복사 때 만듦)에 파일을 써서 권한을 바꾸고 지워 봄. 안 되면 멈춤."""
    if os.path.exists(nas_dir) and not os.path.isdir(nas_dir):
        raise ReleaseError(f"NAS 위치가 폴더가 아닙니다: {nas_dir}")
    target = nas_dir if os.path.isdir(nas_dir) else os.path.dirname(nas_dir)
    if not os.path.isdir(target):
        raise ReleaseError(f"NAS 폴더를 열 수 없습니다 (NAS 연결을 확인하세요): {target}")
    probe = os.path.join(target, f".release_write_check_{os.getpid()}.tmp")
    try:
        with open(probe, "wb") as fh:
            fh.write(b"yesoncheck release write check\n")
        os.chmod(probe, FILE_MODE)
    except OSError as exc:
        raise ReleaseError(f"NAS 폴더에 쓸 수 없습니다: {target}\n{type(exc).__name__}: {exc}") from exc
    finally:
        if os.path.exists(probe):
            os.remove(probe)


def _check_entry(path, key, entry):
    """파일이 latest.json 항목(크기·sha256)과 같은지. 다르면 ReleaseError."""
    sha256, size = _hash_file(path)
    if (sha256, size) != (entry.sha256, entry.size):
        raise ReleaseError(
            f"{key} 파일이 latest.json과 다릅니다: {path}\n"
            f"  latest.json: 크기 {entry.size}, sha256 {entry.sha256}\n  파일: 크기 {size}, sha256 {sha256}"
        )


def _nas_versions(nas_dir):
    """NAS 폴더에 있는 Release 파일들의 버전."""
    found = (_asset_version(entry.name) for entry in os.scandir(nas_dir) if entry.is_file(follow_symlinks=False))
    return {updates.Version.parse(v) for v in found if v}


def sync_to_nas(files: dict[str, str], manifest: bytes, nas_dir: str) -> None:
    """설치 파일들과 latest.json을 NAS 폴더에 넣음.

    1) 받은 파일이 모두 latest.json과 같은지 먼저 확인, NAS의 latest.json이 더 새 버전이면 거부 (아무것도 안 씀)
    2) 설치 파일마다 <이름>.tmp로 쓰고 다시 읽어 sha256·크기 확인 → 권한 0644 → os.replace (폴더는 0755)
    3) latest.json을 .tmp로 쓰고 확인 → 권한 0644 → os.replace — 맨 마지막 (앱은 다 들어간 파일만 봄)
    4) prune_nas: 지금 버전과 그 바로 전 버전(NAS에 있는 것 중 지금보다 작은 가장 큰 번호)만 남김
    """
    parsed = updates.parse_manifest(manifest)
    if set(files) != set(parsed.files):
        raise ReleaseError(
            f"복사할 파일의 플랫폼({', '.join(sorted(files))})이 latest.json의 플랫폼"
            f"({', '.join(sorted(parsed.files))})과 다릅니다"
        )
    for key, path in files.items():
        entry = parsed.files[key]
        if os.path.basename(path) != entry.name:
            raise ReleaseError(f"{key} 파일 이름이 latest.json의 이름({entry.name})과 다릅니다: {path}")
        _check_entry(path, key, entry)
    manifest_path = os.path.join(nas_dir, updates.MANIFEST_NAME)
    if os.path.exists(manifest_path):
        with open(manifest_path, "rb") as fh:
            current = updates.parse_manifest(fh.read())
        if current.version > parsed.version:
            raise ReleaseError(
                f"NAS의 latest.json이 더 새 버전({current.version})입니다 — {parsed.version}을 넣지 않음: {manifest_path}"
            )

    if not os.path.isdir(nas_dir):
        os.mkdir(nas_dir)  # updates 폴더만 만듦 (공유 설정 폴더는 만들지 않음 — 없으면 여기서 실패)
    os.chmod(nas_dir, DIR_MODE)
    for key in (k for k in PLATFORM_KEYS if k in files):
        entry = parsed.files[key]
        final = os.path.join(nas_dir, entry.name)
        partial = final + ".tmp"
        log(f"NAS에 복사: {entry.name} ({entry.size} 바이트)")
        shutil.copyfile(files[key], partial)
        try:
            _check_entry(partial, key, entry)
        except ReleaseError:
            os.remove(partial)
            raise
        os.chmod(partial, FILE_MODE)  # 이름을 바꾸기 전에 → 다른 계정이 못 읽는 순간이 없음
        os.replace(partial, final)
    partial = manifest_path + ".tmp"
    with open(partial, "wb") as fh:
        fh.write(manifest)
    with open(partial, "rb") as fh:
        if fh.read() != manifest:
            raise ReleaseError(f"NAS에 쓴 latest.json을 다시 읽은 내용이 다릅니다: {partial}")
    os.chmod(partial, FILE_MODE)
    os.replace(partial, manifest_path)
    log(f"NAS latest.json → {parsed.version}: {manifest_path}")

    older = [v for v in _nas_versions(nas_dir) if v < parsed.version]
    keep = {str(parsed.version)} | ({str(max(older))} if older else set())
    removed = prune_nas(nas_dir, keep)
    log(f"NAS 정리: 남김 {', '.join(sorted(keep))} · 지움 {len(removed)}개 {[os.path.basename(p) for p in removed]}")


def prune_nas(nas_dir: str, keep: set[str]) -> list[str]:
    """이름에 버전이 든 Release 설치 파일 중 keep(버전 X.Y.Z들)에 없는 것만 지움 (지운 경로 목록).
    latest.json·.tmp·그 밖의 파일과 폴더는 건드리지 않음."""
    removed = []
    for entry in sorted(os.scandir(nas_dir), key=lambda e: e.name):
        version = _asset_version(entry.name)
        if version is None or version in keep or not entry.is_file(follow_symlinks=False):
            continue
        os.remove(entry.path)
        removed.append(entry.path)
    return removed


# ── git·gh ──────────────────────────────────────────────────────────────────


def parse_tag(tag):
    """vX.Y.Z → X.Y.Z (다른 모양이면 ReleaseError)."""
    if not _RELEASE_TAG.fullmatch(tag):
        raise ReleaseError(f"태그는 vX.Y.Z 모양이어야 합니다: {tag!r}")
    return tag[1:]


def remote_tags():
    """origin의 태그 이름들."""
    lines = git("ls-remote", "--tags", "--refs", "origin").splitlines()
    return [line.split("\t", 1)[1].removeprefix("refs/tags/") for line in lines if "\t" in line]


def tag_runs(tag):
    """그 태그로 실행된 빌드 워크플로들 (가장 새것 먼저)."""
    runs = json.loads(gh("run", "list", "--workflow", WORKFLOW, "--branch", tag, "--json", "databaseId,url,headSha"))
    return sorted(runs, key=lambda r: r["databaseId"], reverse=True)


def find_release(tag):
    """그 태그의 Release(초안 포함) {"tagName", "isDraft", …}, 없으면 None."""
    rows = json.loads(gh("release", "list", "--json", "tagName,isDraft,isLatest", "--limit", RELEASE_LIST_LIMIT))
    matches = [row for row in rows if row["tagName"] == tag]
    return matches[0] if matches else None


def check_arm64_omittable():
    """--without-arm64: 공개된 마지막 Release의 latest.json에 mac-arm64가 있으면 거부 (실리콘이 한 번 배포된 뒤로는
    세 빌드 모두 있어야 함 — 설계 10장 15). 공개된 Release가 없으면 허용."""
    rows = json.loads(gh("release", "list", "--exclude-drafts", "--json", "tagName,isLatest",
                         "--limit", RELEASE_LIST_LIMIT))
    if not rows:
        log("공개된 Release가 없음 → mac-arm64 없이 배포 가능")
        return
    latest = [row["tagName"] for row in rows if row["isLatest"]]
    if len(latest) != 1:
        raise ReleaseError(f"공개된 Release 중 'latest'가 하나가 아닙니다: {rows}")
    previous = updates.parse_manifest(
        gh("release", "download", latest[0], "-p", updates.MANIFEST_NAME, "-O", "-").encode("utf-8"))
    if "mac-arm64" in previous.files:
        raise ReleaseError(
            f"이전 배포({latest[0]})의 latest.json에 mac-arm64가 있습니다 — 그 뒤로는 Apple Silicon 빌드 없이 배포할 수 "
            "없습니다 (--without-arm64 거부). mac (AppleSilicon) job을 고친 뒤 다시 배포하세요."
        )


def check_jobs(run_id, keys):
    """실행의 job별 결과: keys의 job이 모두 끝나고 성공했는지. 아니면 job 상태 전부와 함께 ReleaseError."""
    view = json.loads(gh("run", "view", str(run_id), "--json", "status,conclusion,jobs,url"))
    jobs = {job["name"]: job for job in view["jobs"]}
    states = ", ".join(f"{job['name']}={job['status']}/{job['conclusion'] or '-'}" for job in view["jobs"])
    bad = []
    for key in keys:
        job = jobs.get(JOB_NAMES[key])
        if job is None or job["status"] != "completed" or job["conclusion"] != "success":
            bad.append(JOB_NAMES[key])
    if bad:
        raise ReleaseError(
            f"CI 실행 {run_id}에서 성공하지 않은 job: {', '.join(bad)} (전체: {states}). 실패면 abort, 아직 도는 중이면 "
            "끝난 뒤 다시. 첫 배포에서 Apple Silicon만 막히면 --without-arm64."
        )
    log(f"CI 실행 {run_id}: {states}")


def tag_notes(tag):
    """주석 태그의 메시지(= 바뀐 점 = Release 노트·latest.json notes)와 커밋."""
    if git("cat-file", "-t", tag).strip() != "tag":
        raise ReleaseError(f"{tag}가 주석 태그가 아닙니다 (바뀐 점이 없음) — prepare가 만든 태그만 배포합니다")
    commit = git("rev-parse", "--verify", f"{tag}^{{commit}}").strip()
    notes = git("tag", "-l", "--format=%(contents)", tag).strip()
    if not notes:
        raise ReleaseError(f"{tag}의 태그 메시지(바뀐 점)가 비어 있습니다")
    return commit, notes


def print_result(result):
    print(json.dumps(result, ensure_ascii=False), flush=True)


# ── 명령 ────────────────────────────────────────────────────────────────────


def cmd_prepare(args):
    with open(args.notes_file, encoding="utf-8") as fh:
        if not fh.read().strip():
            raise ReleaseError(f"바뀐 점 파일이 비어 있습니다: {args.notes_file}")
    nas_dir = args.nas_dir or default_nas_dir()
    ref = args.commit or ("HEAD" if args.allow_branch else MAIN_REF)

    run(["gh", "auth", "status", "--hostname", "github.com"], cwd=ROOT)
    dirty = git("status", "--porcelain")
    if dirty.strip():
        raise ReleaseError(f"작업 폴더에 커밋 안 된 변경이 있습니다:\n{dirty}")
    git("fetch", "origin")
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if args.allow_branch:
        log(f"--allow-branch: {MAIN_REF}에 있는지 확인하지 않음 (예행연습만)")
    elif git("merge-base", commit, MAIN_REF).strip() != commit:
        raise ReleaseError(f"커밋 {commit} ({ref})이 {MAIN_REF}에 없습니다 — main에 합친 커밋만 배포합니다")
    try:
        git("cat-file", "-e", f"{commit}:{VERSION_FILE}")
    except CommandError as exc:
        raise ReleaseError(
            f"커밋 {commit} ({ref})에 {VERSION_FILE}이 없습니다 — 앱이 자기 버전을 아는 커밋(1.1.0 이후)만 배포·되돌리기할 수 "
            "있습니다"
        ) from exc
    check_nas_writable(nas_dir)

    tags = remote_tags()
    version = args.version or next_version(tags, args.minor)
    tag = f"v{version}"
    if tag in tags:
        raise ReleaseError(f"origin에 이미 {tag} 태그가 있습니다")
    before = {r["databaseId"] for r in tag_runs(tag)}  # 같은 번호를 지우고 다시 쓴 경우의 옛 실행은 빼려고
    git("tag", "-a", tag, "-F", args.notes_file, "--cleanup=whitespace", commit)
    try:
        git("push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
    except CommandError as exc:
        raise ReleaseError(f"태그 {tag} 푸시 실패 — 로컬 태그가 남아 있음: 다시 하기 전에 abort {tag}") from exc
    log(f"태그 {tag} 푸시 ({commit}) → CI 실행을 찾는 중")
    for attempt in range(RUN_POLL_TRIES):
        new = [r for r in tag_runs(tag) if r["headSha"] == commit and r["databaseId"] not in before]
        if new:
            print_result({"version": version, "tag": tag, "commit": commit, "run_id": new[0]["databaseId"],
                          "run_url": new[0]["url"]})
            return
        if attempt + 1 < RUN_POLL_TRIES:
            time.sleep(RUN_POLL_S)
    raise ReleaseError(
        f"태그 {tag}를 푸시했지만 {RUN_POLL_TRIES * RUN_POLL_S}초 안에 {WORKFLOW} 실행이 보이지 않습니다 — Actions 화면을 "
        f"확인하고, 그만두려면 abort {tag}"
    )


def cmd_publish(args):
    started = time.monotonic()
    version = parse_tag(args.tag)
    tag = args.tag
    nas_dir = args.nas_dir or default_nas_dir()
    check_nas_writable(nas_dir)  # GitHub에 공개하기 전에 (NAS만 실패하는 일을 줄임)
    commit, notes = tag_notes(tag)
    existing = find_release(tag)
    if existing is not None and not existing["isDraft"]:
        raise ReleaseError(f"{tag} Release가 이미 공개돼 있습니다 — NAS만 다시 하려면 nas-sync {tag}")
    keys = [k for k in PLATFORM_KEYS if not (args.without_arm64 and k == "mac-arm64")]
    if args.without_arm64:
        check_arm64_omittable()
    runs = [r for r in tag_runs(tag) if r["headSha"] == commit]
    if not runs:
        raise ReleaseError(f"{tag} ({commit})의 {WORKFLOW} 실행이 없습니다")
    run_id = runs[0]["databaseId"]
    check_jobs(run_id, keys)

    names = asset_names(version)
    with tempfile.TemporaryDirectory(prefix="yc_release_") as work:
        files = {}
        for key in keys:
            artifact = ARTIFACT_TEMPLATES[key].format(version)
            folder = os.path.join(work, artifact)
            gh("run", "download", str(run_id), "-n", artifact, "-D", folder)
            path = os.path.join(folder, names[key])
            if not os.path.isfile(path):
                found = [os.path.relpath(os.path.join(d, f), work) for d, _, fs in os.walk(folder) for f in fs]
                raise ReleaseError(f"artifact {artifact}에 {names[key]}이 없습니다 (받은 것: {found})")
            files[key] = path
        manifest = make_manifest(version, commit, now_iso(), notes, files)
        manifest_path = os.path.join(work, updates.MANIFEST_NAME)
        with open(manifest_path, "wb") as fh:
            fh.write(manifest)
        notes_path = os.path.join(work, "notes.md")
        with open(notes_path, "w", encoding="utf-8") as fh:
            fh.write(notes + "\n")

        if existing is not None:
            log(f"지난번 초안 {tag}를 지우고 다시 만듦 (태그는 그대로)")
            gh("release", "delete", tag, "--yes")
        gh("release", "create", tag, "--draft", "--verify-tag", "--title", tag, "--notes-file", notes_path,
           *(files[k] for k in keys), manifest_path)
        if not args.draft_only:
            gh("release", "edit", tag, "--draft=false", "--latest")
        view = json.loads(gh("release", "view", tag, "--json", "isDraft,url,assets"))
        uploaded = {asset["name"]: asset["size"] for asset in view["assets"]}
        expected = {os.path.basename(p): os.path.getsize(p) for p in [*files.values(), manifest_path]}
        if uploaded != expected or view["isDraft"] != args.draft_only:
            raise ReleaseError(f"{tag} Release가 예상과 다릅니다: 올라간 파일 {uploaded}, 예상 {expected}, "
                               f"초안 {view['isDraft']} (예상 {args.draft_only})")
        state = "초안" if args.draft_only else "공개"
        log(f"{tag} Release {state}: {view['url']}")
        try:
            sync_to_nas(files, manifest, nas_dir)
        except Exception as exc:
            again = f"nas-sync {tag}" + (f" --nas-dir {shlex.quote(nas_dir)}" if args.nas_dir else "")
            raise ReleaseError(f"GitHub Release({state})는 됐지만 NAS 복사가 실패했습니다: {nas_dir} — NAS만 다시: {again}") \
                from exc
    print_result({"version": version, "tag": tag, "commit": commit, "release_url": view["url"],
                  "draft": args.draft_only, "files": {k: names[k] for k in keys}, "nas_dir": nas_dir,
                  "elapsed_s": round(time.monotonic() - started)})


def cmd_nas_sync(args):
    version = parse_tag(args.tag)
    tag = args.tag
    existing = find_release(tag)
    if existing is None:
        raise ReleaseError(f"{tag} Release가 없습니다")
    if existing["isDraft"] and not args.nas_dir:
        raise ReleaseError(f"{tag}는 아직 초안 Release입니다 — 실제 NAS에는 공개된 Release만 (시험이면 --nas-dir)")
    nas_dir = args.nas_dir or default_nas_dir()
    check_nas_writable(nas_dir)
    with tempfile.TemporaryDirectory(prefix="yc_release_") as work:
        gh("release", "download", tag, "-D", work, "-p", updates.MANIFEST_NAME)
        with open(os.path.join(work, updates.MANIFEST_NAME), "rb") as fh:
            manifest = fh.read()
        parsed = updates.parse_manifest(manifest)
        if str(parsed.version) != version:
            raise ReleaseError(f"{tag} Release의 latest.json 버전이 {parsed.version}입니다")
        patterns = [arg for entry in parsed.files.values() for arg in ("-p", entry.name)]
        gh("release", "download", tag, "-D", work, *patterns)
        files = {key: os.path.join(work, entry.name) for key, entry in parsed.files.items()}
        sync_to_nas(files, manifest, nas_dir)  # 받은 파일을 latest.json과 먼저 대조
    print_result({"version": version, "tag": tag, "files": {k: e.name for k, e in parsed.files.items()},
                  "nas_dir": nas_dir})


def cmd_abort(args):
    parse_tag(args.tag)
    tag = args.tag
    existing = find_release(tag)
    if existing is not None and not existing["isDraft"]:
        raise ReleaseError(f"{tag} Release가 이미 공개돼 있어 지우지 않습니다 — 되돌리려면 예전 커밋으로 새 번호를 배포하세요")
    removed = []
    if existing is not None:
        gh("release", "delete", tag, "--yes")
        removed.append("초안 Release")
    if git("ls-remote", "--tags", "origin", f"refs/tags/{tag}").strip():
        git("push", "origin", f":refs/tags/{tag}")
        removed.append("원격 태그")
    if git("tag", "-l", tag).strip():
        git("tag", "-d", tag)
        removed.append("로컬 태그")
    print_result({"tag": tag, "removed": removed})


def main(argv=None):
    parser = argparse.ArgumentParser(description="배포 도구: 태그 → CI 세 빌드 → GitHub Release → NAS")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="확인 → 번호 → 주석 태그 푸시 → CI 실행 id·주소 JSON 한 줄")
    prepare.add_argument("--notes-file", required=True, help="바뀐 점 (쉬운 한국어, 내부 정보 없이 — 퍼블릭)")
    number = prepare.add_mutually_exclusive_group()
    number.add_argument("--minor", action="store_true", help="큰 변경: 가운데 +1·끝 0")
    number.add_argument("--version", help="이 번호 X.Y.Z로 (예행연습의 버리는 번호 등)")
    prepare.add_argument("--commit", help=f"배포할 커밋 (기본 {MAIN_REF}, --allow-branch면 HEAD; 되돌리기는 예: v1.1.1)")
    prepare.add_argument("--allow-branch", action="store_true", help=f"{MAIN_REF}에 없는 커밋도 (예행연습만)")
    prepare.add_argument("--nas-dir", help="쓸 수 있는지 확인할 NAS 폴더 (기본 <공유 설정 폴더>/updates)")

    publish = commands.add_parser("publish", help="CI 성공 확인 → Release(초안 → 공개) → NAS 복사")
    publish.add_argument("tag", help="vX.Y.Z")
    publish.add_argument("--draft-only", action="store_true", help="초안 Release만 (공개·latest 안 함, --nas-dir 필요)")
    publish.add_argument("--nas-dir", help="복사할 NAS 폴더 (기본 <공유 설정 폴더>/updates)")
    publish.add_argument("--without-arm64", action="store_true",
                         help="Apple Silicon 없이 (이전 배포에 mac-arm64가 없을 때만)")

    nas_sync = commands.add_parser("nas-sync", help="Release 파일을 받아 NAS에 다시 복사")
    nas_sync.add_argument("tag", help="vX.Y.Z")
    nas_sync.add_argument("--nas-dir", help="복사할 NAS 폴더 (기본 <공유 설정 폴더>/updates)")

    abort = commands.add_parser("abort", help="원격·로컬 태그와 초안 Release 지우기 (공개된 Release면 거부)")
    abort.add_argument("tag", help="vX.Y.Z")

    args = parser.parse_args(argv)
    if args.command == "prepare" and args.version is not None and not _RELEASE_VERSION.fullmatch(args.version):
        parser.error(f"--version은 X.Y.Z 모양이어야 합니다: {args.version!r}")
    if args.command == "publish" and args.draft_only and not args.nas_dir:
        parser.error("--draft-only는 --nas-dir와 함께만 (초안 버전을 실제 NAS에 올리지 않게)")
    {"prepare": cmd_prepare, "publish": cmd_publish, "nas-sync": cmd_nas_sync, "abort": cmd_abort}[args.command](args)


if __name__ == "__main__":
    main()
