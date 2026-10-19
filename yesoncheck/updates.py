"""업데이트 확인 핵심: NAS·GitHub의 latest.json을 읽고 더 새 버전을 고름 (Qt 없음).

이 모듈은 파일 읽기와 HTTP 요청만 한다. 창을 띄우는 일, 로그를 남기는 일, 백그라운드 스레드로 옮기는 일은
부른 쪽(player_base 등)이 한다. NAS·GitHub 각각을 읽은 결과(SourceResult)는 "예상된 실패"(expected_problem
— 공유 설정을 아직 모름·NAS에 배포가 아직 없음·인터넷이 없음·GitHub에 아직 배포가 없음: 로그만)와 "오류"
(error — 그 밖의 모든 문제: 창에 그대로, 트레이스백 포함)를 구분해서 돌려준다. 오류를 삼키거나 다른 곳으로
저절로 바꾸지 않는다.

NAS: <공유 설정 폴더>/updates/latest.json. GitHub: <base_url>/latest/download/latest.json (기본 base_url은
GITHUB_RELEASES_URL, 시험은 YESONCHECK_UPDATE_URL로 바꿔 끼움). REST API는 쓰지 않는다.

requests는 read_github 안에서 불러온다 — 앱의 시작(main_window → player_update → 이 모듈)이 requests(약 80 ms, 처음 켤 때
200 ms 넘게)를 기다리지 않게. 확인은 뒤 스레드에서 돈다.
"""

import json
import os
import re
import traceback
from dataclasses import dataclass
from functools import total_ordering

MANIFEST_NAME = "latest.json"
NAS_DIR_NAME = "updates"
GITHUB_RELEASES_URL = "https://github.com/yesonsys03-web/yesoncheck/releases"
GITHUB_TIMEOUT_S = 10

_UPDATE_URL_ENV = "YESONCHECK_UPDATE_URL"
_UPDATE_URL_OFF = "off"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(\+[0-9a-f]{7}(\.dirty)?)?")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MANIFEST_FIELDS = ("version", "commit", "released", "notes", "files")
_SOURCES = ("NAS", "GitHub")


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    """버전 하나. 비교와 `==`는 (major, minor, patch)만 본다 — 커밋 꼬리(`+<7자리>`, 배포가 아닌 빌드,
    `.dirty` 가능)는 무시. `str()`은 `parse`에 넘긴 원문 그대로."""

    major: int
    minor: int
    patch: int
    text: str

    @classmethod
    def parse(cls, text: str) -> "Version":
        """`X.Y.Z` 또는 `X.Y.Z+<커밋 7자리 소문자 16진수>`(`.dirty` 가능)만 허용. 그 밖은 ValueError."""
        match = _VERSION_RE.fullmatch(text)
        if not match:
            raise ValueError(
                f"버전 형식이 아닙니다 (X.Y.Z 또는 X.Y.Z+커밋7자리[.dirty]여야 함): {text!r}"
            )
        major, minor, patch = (int(group) for group in match.group(1, 2, 3))
        return cls(major, minor, patch, text)

    def _key(self):
        return (self.major, self.minor, self.patch)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() == other._key()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._key() < other._key()

    def __hash__(self):
        return hash(self._key())

    def __str__(self):
        return self.text


@dataclass(frozen=True)
class FileEntry:
    """latest.json의 플랫폼별 배포 파일 한 항목."""

    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Manifest:
    """latest.json 하나. files: 플랫폼 키(windows·mac-x86_64·mac-arm64 등) → FileEntry."""

    version: Version
    commit: str
    released: str
    notes: str
    files: dict[str, FileEntry]


class ManifestError(ValueError):
    """latest.json 형식이 올바르지 않음 (무엇이 틀렸는지는 메시지에 한국어로)."""


def parse_manifest(data: bytes) -> Manifest:
    """latest.json의 바이트 → Manifest. 형식이 틀리면 ManifestError (무엇이 틀렸는지 한국어)."""
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"latest.json이 JSON 형식이 아닙니다: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"latest.json의 맨 위가 객체가 아닙니다: {type(payload).__name__}")
    missing = [name for name in _MANIFEST_FIELDS if name not in payload]
    if missing:
        raise ManifestError(f"latest.json에 다음 항목이 없습니다: {', '.join(missing)}")
    version_text, commit, released, notes, files = (payload[name] for name in _MANIFEST_FIELDS)
    for field_name, value in (
        ("version", version_text), ("commit", commit), ("released", released), ("notes", notes),
    ):
        if not isinstance(value, str):
            raise ManifestError(f"latest.json의 {field_name}이 문자열이 아닙니다: {value!r}")
    try:
        version = Version.parse(version_text)
    except ValueError as exc:
        raise ManifestError(f"latest.json의 version이 올바르지 않습니다: {exc}") from exc
    if not isinstance(files, dict):
        raise ManifestError(f"latest.json의 files가 객체가 아닙니다: {type(files).__name__}")
    parsed_files = {platform_key: _parse_file_entry(platform_key, entry) for platform_key, entry in files.items()}
    return Manifest(version, commit, released, notes, parsed_files)


def _parse_file_entry(platform_key: str, entry) -> FileEntry:
    if not isinstance(entry, dict):
        raise ManifestError(f"latest.json의 files.{platform_key}이 객체가 아닙니다: {type(entry).__name__}")
    name = entry.get("name")
    size = entry.get("size")
    sha256 = entry.get("sha256")
    if not isinstance(name, str) or not name:
        raise ManifestError(f"latest.json의 files.{platform_key}.name이 올바르지 않습니다: {name!r}")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ManifestError(f"latest.json의 files.{platform_key}.size가 양의 정수가 아닙니다: {size!r}")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise ManifestError(
            f"latest.json의 files.{platform_key}.sha256이 올바르지 않습니다 (소문자 64자리 16진수여야 함): {sha256!r}"
        )
    return FileEntry(name, size, sha256)


def github_base_url() -> str | None:
    """실제 GitHub 주소(GITHUB_RELEASES_URL). 시험용 환경 변수 YESONCHECK_UPDATE_URL이 있으면 그 값으로
    대신하고, 값이 "off"면 GitHub 확인을 안 함(None)."""
    override = os.environ.get(_UPDATE_URL_ENV)
    if override == _UPDATE_URL_OFF:
        return None
    return override or GITHUB_RELEASES_URL


@dataclass(frozen=True)
class SourceResult:
    """NAS 또는 GitHub에서 latest.json을 읽어 본 결과 — manifest·expected_problem·error 중 정확히 하나만 값.

    source: "NAS" 또는 "GitHub". location: 그 소스에서 받아 올 위치의 바탕(NAS는 updates 폴더, GitHub는
    base_url) — asset_location이 씀. expected_problem: 예상된 실패(studio 사용자에게는 로그만 남기면 됨 —
    예: 공유 설정을 아직 모름, NAS에 아직 배포가 없음, 인터넷이 없거나 시간 초과, GitHub에 아직 배포가 없음).
    error: 그 밖의 모든 문제 — 사용자 창에 그대로 보여 줘야 함(예외 글 전체 또는 트레이스백).
    """

    source: str
    location: str
    manifest: Manifest | None
    expected_problem: str | None
    error: str | None

    def __post_init__(self):
        if self.source not in _SOURCES:
            raise ValueError(f"source는 {_SOURCES} 중 하나여야 합니다: {self.source!r}")
        set_count = sum(value is not None for value in (self.manifest, self.expected_problem, self.error))
        if set_count != 1:
            raise ValueError(
                "SourceResult는 manifest·expected_problem·error 중 정확히 하나만 있어야 합니다: "
                f"manifest={self.manifest!r}, expected_problem={self.expected_problem!r}, error={self.error!r}"
            )


def read_nas(config_dir: str | None, platform_key: str) -> SourceResult:
    """NAS(공유 설정 폴더)의 updates/latest.json을 읽음.

    config_dir가 None이면 공유 설정 폴더를 아직 모름(expected_problem). updates 폴더나 latest.json이
    없으면 NAS에 아직 배포된 버전이 없음(expected_problem). 그 밖의 OSError·형식 오류·이 플랫폼용 항목이
    없으면 error. 예상 못 한 예외는 트레이스백째 error에 넣는다(삼키지 않음).
    """
    if config_dir is None:
        return SourceResult("NAS", "", None, "공유 설정 폴더를 아직 모름", None)
    updates_dir = os.path.join(config_dir, NAS_DIR_NAME)
    manifest_path = os.path.join(updates_dir, MANIFEST_NAME)
    try:
        try:
            with open(manifest_path, "rb") as fh:
                data = fh.read()
        except FileNotFoundError:
            return SourceResult(
                "NAS", updates_dir, None, f"NAS에 아직 배포된 버전이 없음 ({manifest_path})", None
            )
        manifest = parse_manifest(data)
        if platform_key not in manifest.files:
            return SourceResult(
                "NAS", updates_dir, None, None,
                f"이 컴퓨터용({platform_key}) 배포 파일 정보가 latest.json에 없음: {manifest_path}",
            )
        return SourceResult("NAS", updates_dir, manifest, None, None)
    except ManifestError as exc:
        return SourceResult("NAS", updates_dir, None, None, str(exc))
    except OSError as exc:
        return SourceResult("NAS", updates_dir, None, None, f"{type(exc).__name__}: {exc}")
    except Exception:
        return SourceResult("NAS", updates_dir, None, None, traceback.format_exc())


def read_github(base_url: str | None, platform_key: str, timeout_s: float = GITHUB_TIMEOUT_S) -> SourceResult:
    """GitHub Releases의 latest.json을 읽음 (`{base_url}/latest/download/latest.json`).

    base_url이 None이면 GitHub 확인을 안 함(설정이 꺼짐 — expected_problem). 연결이 안 되거나 시간
    초과면 expected_problem(인터넷 문제일 수 있음). 아직 배포가 없으면(404) expected_problem. SSL
    문제(먼저 검사 — ConnectionError의 하위 클래스)·그 밖의 HTTP 상태·형식 오류·이 플랫폼용 항목이 없으면
    error. 예상 못 한 예외는 트레이스백째 error에 넣는다.
    """
    if base_url is None:
        return SourceResult("GitHub", "", None, "GitHub 확인 안 함 (설정 꺼짐)", None)
    import requests  # 처음 쓸 때 (모듈 설명)

    url = f"{base_url}/latest/download/{MANIFEST_NAME}"
    try:
        response = requests.get(url, timeout=timeout_s)
    except requests.exceptions.SSLError as exc:
        return SourceResult("GitHub", base_url, None, None, f"GitHub 연결에 보안(SSL) 문제: {exc}")
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
        return SourceResult(
            "GitHub", base_url, None, f"GitHub에 닿지 못함 (인터넷 연결 없음 또는 시간 초과): {exc}", None,
        )
    except Exception:
        return SourceResult("GitHub", base_url, None, None, traceback.format_exc())
    try:
        if response.status_code == 404:
            return SourceResult("GitHub", base_url, None, "GitHub에 아직 배포된 버전이 없음", None)
        if response.status_code != 200:
            return SourceResult(
                "GitHub", base_url, None, None, f"GitHub 응답 오류: HTTP {response.status_code}"
            )
        manifest = parse_manifest(response.content)
        if platform_key not in manifest.files:
            return SourceResult(
                "GitHub", base_url, None, None,
                f"이 컴퓨터용({platform_key}) 배포 파일 정보가 latest.json에 없음",
            )
        return SourceResult("GitHub", base_url, manifest, None, None)
    except ManifestError as exc:
        return SourceResult("GitHub", base_url, None, None, str(exc))
    except Exception:
        return SourceResult("GitHub", base_url, None, None, traceback.format_exc())


@dataclass(frozen=True)
class Offer:
    """고른 업데이트: manifest·어느 소스에서 왔는지(result)·이 플랫폼용 배포 파일(entry)."""

    manifest: Manifest
    result: SourceResult
    entry: FileEntry


def choose_offer(current: Version, platform_key: str, results: list[SourceResult]) -> Offer | None:
    """results 중 current보다 새 버전이면서 이 플랫폼용 배포 파일이 있는 것 중 가장 새 버전을 고름.

    여럿이 같은 버전이면 NAS를 고름(설치가 빠르고 인터넷을 쓰지 않음). 고를 것이 없으면 None.
    """
    candidates = []
    for result in results:
        manifest = result.manifest
        if manifest is None:
            continue
        entry = manifest.files.get(platform_key)
        if entry is None or manifest.version <= current:
            continue
        candidates.append((result, manifest, entry))
    if not candidates:
        return None
    result, manifest, entry = max(candidates, key=lambda c: (c[1].version, 1 if c[0].source == "NAS" else 0))
    return Offer(manifest, result, entry)


def asset_location(result: SourceResult, manifest: Manifest, entry: FileEntry) -> str:
    """entry(배포 파일)를 받아 올 위치: NAS면 updates 폴더 안 경로, GitHub면 내려받기 주소."""
    if result.source == "NAS":
        return os.path.join(result.location, entry.name)
    if result.source == "GitHub":
        return f"{result.location}/download/v{manifest.version}/{entry.name}"
    raise ValueError(f"모르는 소스입니다: {result.source!r}")  # SourceResult가 이미 막지만, 방어적으로


@dataclass(frozen=True)
class CheckResult:
    """check()의 결과: 소스별 읽기 결과 전체(로그에 다 남길 수 있게)와 고른 업데이트(없으면 None)."""

    results: list[SourceResult]
    offer: Offer | None


def check(current: Version, platform_key: str, config_dir: str | None, base_url: str | None) -> CheckResult:
    """NAS·GitHub를 모두 읽고 더 새 버전을 고름."""
    results = [read_nas(config_dir, platform_key), read_github(base_url, platform_key)]
    return CheckResult(results, choose_offer(current, platform_key, results))
