"""배포 도구(tools/release.py): 번호 계산·Release 파일 이름·latest.json·NAS 복사 순서와 정리, 그리고 prepare·publish·
nas-sync·abort가 부르는 명령의 차례 (가짜 run — GitHub·실제 NAS에 닿지 않음)."""

import hashlib
import importlib.util
import json
import os
import re
import stat
import sys

import pytest

from tests.conftest import ROOT
from yesoncheck import updates
from yesoncheck.updates import parse_manifest

TOOL = os.path.join(ROOT, "tools", "release.py")


def load_tool():
    """tools/release.py를 모듈로 불러옴 (tools는 패키지가 아니므로 파일 경로로)."""
    spec = importlib.util.spec_from_file_location("release_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load_tool()
next_version = release.next_version
asset_names = release.asset_names
make_manifest = release.make_manifest
sync_to_nas = release.sync_to_nas
prune_nas = release.prune_nas

SHA = "c" * 40
OLD_SHA = "d" * 40
RELEASED = "2026-10-25T10:00:00+09:00"
NOTES = "새로고침이 바뀐 영상의 썸네일도 다시 만듦\n# 이 줄도 그대로"
ALL_KEYS = ["windows", "mac-x86_64", "mac-arm64"]
ARTIFACT_PREFIX = {
    "windows": "YesonCheck_Setup_Windows_",
    "mac-x86_64": "YesonCheck_Autocut_Intel_",
    "mac-arm64": "YesonCheck_Autocut_AppleSilicon_",
}


def sha256_of(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def asset_bytes(version, key):
    return f"{key} 설치 파일 {version}\n".encode("utf-8") * 50


def files_in(folder, version="1.1.1", keys=ALL_KEYS):
    """folder에 Release 이름의 가짜 설치 파일들을 만들고 {플랫폼 키: 경로}."""
    os.makedirs(folder, exist_ok=True)
    files = {}
    for key in keys:
        path = os.path.join(str(folder), asset_names(version)[key])
        with open(path, "wb") as fh:
            fh.write(asset_bytes(version, key))
        files[key] = path
    return files


def touch_assets(folder, version):
    for name in asset_names(version).values():
        with open(os.path.join(str(folder), name), "wb") as fh:
            fh.write(b"x")


def record_replace_order(monkeypatch):
    """os.replace의 대상 경로를 부른 차례대로 기록 (실제 바꾸기는 그대로)."""
    order = []
    original = os.replace

    def recording(src, dst, *args, **kwargs):
        order.append(os.fspath(dst))
        return original(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", recording)
    return order


# ── 순수 함수 ───────────────────────────────────────────────────────────────


def test_next_version():
    assert next_version([], False) == "1.1.0"
    assert next_version(["v1.1.0", "v1.1.9", "v1.1.10", "vfoo"], False) == "1.1.11"
    assert next_version(["v1.1.3"], True) == "1.2.0"


def test_next_version_ignores_non_release_tags():
    assert next_version(["v1.2", "release-1", "v1.1.0-rc1", "1.5.0"], False) == "1.1.0"
    assert next_version(["v2.0.0", "v1.9.9"], True) == "2.1.0"


def test_asset_names():
    assert asset_names("1.1.1") == {"windows": "YesonCheck_Setup_1.1.1.exe",
                                    "mac-x86_64": "YesonCheck_Autocut_Intel_1.1.1.dmg",
                                    "mac-arm64": "YesonCheck_Autocut_AppleSilicon_1.1.1.dmg"}


@pytest.mark.parametrize("bad", ["v1.1.1", "1.1", "1.1.1+0f4d3d7", ""])
def test_asset_names_rejects_non_release_version(bad):
    with pytest.raises(ValueError, match="X.Y.Z"):
        asset_names(bad)


def test_repo_matches_app_update_url():
    """배포 도구가 Release를 만드는 저장소 = 앱이 latest.json을 읽는 저장소."""
    assert updates.GITHUB_RELEASES_URL == f"https://github.com/{release.REPO}/releases"


def test_make_manifest_roundtrip(tmp_path):
    m = parse_manifest(make_manifest("1.1.1", "c" * 40, "2026-10-25T10:00:00+09:00", "바뀐 점", files_in(tmp_path)))
    assert m.files["windows"].sha256 == sha256_of(tmp_path / "YesonCheck_Setup_1.1.1.exe")
    assert str(m.version) == "1.1.1" and m.commit == "c" * 40 and m.notes == "바뀐 점"
    assert m.released == "2026-10-25T10:00:00+09:00"
    for key, name in asset_names("1.1.1").items():
        assert m.files[key].name == name
        assert m.files[key].size == os.path.getsize(tmp_path / name)
        assert m.files[key].sha256 == sha256_of(tmp_path / name)


def test_make_manifest_is_utf8_json_in_platform_order(tmp_path):
    data = make_manifest("1.1.1", SHA, RELEASED, NOTES, files_in(tmp_path))
    payload = json.loads(data.decode("utf-8"))
    assert list(payload) == ["version", "commit", "released", "notes", "files"]
    assert list(payload["files"]) == ALL_KEYS
    assert "새로고침" in data.decode("utf-8")  # 한국어가 \uXXXX가 아니라 그대로 (사람이 읽는 파일)


def test_make_manifest_without_arm64(tmp_path):
    m = parse_manifest(make_manifest("1.1.1", SHA, RELEASED, NOTES, files_in(tmp_path, keys=ALL_KEYS[:2])))
    assert sorted(m.files) == ["mac-x86_64", "windows"]


def test_make_manifest_rejects_wrong_name_key_commit_version(tmp_path):
    files = files_in(tmp_path)
    wrong_name = dict(files, windows=files["mac-x86_64"])
    with pytest.raises(ValueError, match="windows"):
        make_manifest("1.1.1", SHA, RELEASED, NOTES, wrong_name)
    with pytest.raises(ValueError, match="linux"):
        make_manifest("1.1.1", SHA, RELEASED, NOTES, dict(files, linux=files["windows"]))
    with pytest.raises(ValueError, match="커밋"):
        make_manifest("1.1.1", "c" * 7, RELEASED, NOTES, files)
    with pytest.raises(ValueError, match="X.Y.Z"):
        make_manifest("1.1.1+0f4d3d7", SHA, RELEASED, NOTES, files)
    with pytest.raises(ValueError, match="파일"):
        make_manifest("1.1.1", SHA, RELEASED, NOTES, {})


def test_now_iso_has_local_offset_and_seconds():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", release.now_iso())


# ── NAS 복사·정리 ───────────────────────────────────────────────────────────


def test_sync_writes_manifest_last(tmp_path, monkeypatch):
    files = files_in(tmp_path)
    manifest = make_manifest("1.1.1", SHA, RELEASED, NOTES, files)
    order = record_replace_order(monkeypatch)
    sync_to_nas(files, manifest, str(tmp_path / "nas"))
    assert order[-1].endswith("latest.json") and len(order) == 4
    assert not list((tmp_path / "nas").glob("*.tmp"))
    nas = tmp_path / "nas"
    assert (nas / "latest.json").read_bytes() == manifest
    for key, path in files.items():
        assert sha256_of(nas / os.path.basename(path)) == parse_manifest(manifest).files[key].sha256


@pytest.mark.skipif(sys.platform == "win32", reason="Windows는 권한 비트가 없음 (읽기 전용 표시만)")
def test_sync_makes_files_readable_by_all(tmp_path, monkeypatch):
    previous = os.umask(0o077)  # 다른 계정이 못 읽게 만드는 umask여도
    try:
        files = files_in(tmp_path)
        sync_to_nas(files, make_manifest("1.1.1", SHA, RELEASED, NOTES, files), str(tmp_path / "nas"))
    finally:
        os.umask(previous)
    nas = tmp_path / "nas"
    assert stat.S_IMODE(os.stat(nas).st_mode) == 0o755
    for entry in nas.iterdir():
        assert stat.S_IMODE(os.stat(entry).st_mode) == 0o644, entry.name


def test_sync_rejects_source_not_matching_manifest(tmp_path):
    files = files_in(tmp_path)
    manifest = make_manifest("1.1.1", SHA, RELEASED, NOTES, files)
    with open(files["mac-arm64"], "ab") as fh:
        fh.write(b"!")
    with pytest.raises(release.ReleaseError, match="mac-arm64"):
        sync_to_nas(files, manifest, str(tmp_path / "nas"))
    assert not (tmp_path / "nas").exists()  # 맞지 않으면 NAS에 아무것도 쓰지 않음


def test_sync_rejects_files_not_in_manifest(tmp_path):
    files = files_in(tmp_path)
    manifest = make_manifest("1.1.1", SHA, RELEASED, NOTES, {k: files[k] for k in ALL_KEYS[:2]})
    with pytest.raises(release.ReleaseError, match="플랫폼"):
        sync_to_nas(files, manifest, str(tmp_path / "nas"))


def test_sync_refuses_older_version_than_nas(tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    newer_files = files_in(tmp_path / "new", "1.1.5")
    newer = make_manifest("1.1.5", SHA, RELEASED, NOTES, newer_files)
    (nas / "latest.json").write_bytes(newer)
    touch_assets(nas, "1.1.5")
    files = files_in(tmp_path / "old", "1.1.3")
    with pytest.raises(release.ReleaseError, match="1.1.5"):
        sync_to_nas(files, make_manifest("1.1.3", SHA, RELEASED, NOTES, files), str(nas))
    assert (nas / "latest.json").read_bytes() == newer
    assert sorted(p.name for p in nas.iterdir()) == sorted(["latest.json", *asset_names("1.1.5").values()])


def test_sync_keeps_current_and_previous(tmp_path):
    nas = tmp_path / "nas"
    nas.mkdir()
    for v in ["1.1.0", "1.1.1"]:
        touch_assets(nas, v)
    previous = make_manifest("1.1.1", OLD_SHA, RELEASED, NOTES, files_in(tmp_path / "s1", "1.1.1"))
    (nas / "latest.json").write_bytes(previous)
    (nas / "YesonCheck_Setup_1.1.2.exe.tmp").write_bytes(b"half")  # 지난번 중간에 멈춘 복사 → 덮어씀
    files = files_in(tmp_path / "s2", "1.1.2")
    sync_to_nas(files, make_manifest("1.1.2", SHA, RELEASED, NOTES, files), str(nas))
    expected = ["latest.json", *asset_names("1.1.1").values(), *asset_names("1.1.2").values()]
    assert sorted(p.name for p in nas.iterdir()) == sorted(expected)
    assert str(parse_manifest((nas / "latest.json").read_bytes()).version) == "1.1.2"


def test_sync_same_version_again_keeps_previous(tmp_path):
    """NAS만 다시(nas-sync)로 같은 버전을 또 넣어도 바로 전 버전은 남음."""
    nas = tmp_path / "nas"
    old = files_in(tmp_path / "s1", "1.1.1")
    sync_to_nas(old, make_manifest("1.1.1", OLD_SHA, RELEASED, NOTES, old), str(nas))
    new = files_in(tmp_path / "s2", "1.1.2")
    manifest = make_manifest("1.1.2", SHA, RELEASED, NOTES, new)
    sync_to_nas(new, manifest, str(nas))
    sync_to_nas(new, manifest, str(nas))
    expected = ["latest.json", *asset_names("1.1.1").values(), *asset_names("1.1.2").values()]
    assert sorted(p.name for p in nas.iterdir()) == sorted(expected)


def test_prune_keeps_current_and_previous(tmp_path):
    for v in ["1.1.0", "1.1.1", "1.1.2"]: touch_assets(tmp_path, v)
    (tmp_path / "latest.json").write_bytes(b"{}")
    (tmp_path / "메모.txt").write_text("x", encoding="utf-8")
    removed = prune_nas(str(tmp_path), {"1.1.1", "1.1.2"})
    assert sorted(os.path.basename(p) for p in removed) == sorted(asset_names("1.1.0").values())
    assert (tmp_path / "latest.json").exists() and (tmp_path / "메모.txt").exists()  # 버전 든 설치 파일만 지움


def test_prune_leaves_lookalikes(tmp_path):
    names = ["YesonCheck_Setup_1.1.0.exe.tmp", "YesonCheck_Setup_latest.exe", "YesonCheck_Setup_1.1.0.exe.bak",
             "old_YesonCheck_Setup_1.1.0.exe", "YesonCheck_Autocut_Intel_1.1.0.zip"]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "YesonCheck_Setup_1.0.0.exe").mkdir()  # 폴더는 지우지 않음
    assert prune_nas(str(tmp_path), {"1.1.2"}) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(names + ["YesonCheck_Setup_1.0.0.exe"])


def test_default_nas_dir_is_updates_under_shared_config(tmp_path, monkeypatch):
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(tmp_path))
    assert release.default_nas_dir() == os.path.join(str(tmp_path), updates.NAS_DIR_NAME)


def test_check_nas_writable(tmp_path):
    release.check_nas_writable(str(tmp_path / "updates"))  # 아직 없으면 그 위 폴더에 써 봄
    (tmp_path / "updates").mkdir()
    release.check_nas_writable(str(tmp_path / "updates"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["updates"]  # 써 본 파일은 지움
    assert list((tmp_path / "updates").iterdir()) == []
    with pytest.raises(release.ReleaseError, match="NAS"):
        release.check_nas_writable(str(tmp_path / "없는 폴더" / "updates"))


# ── run: 외부 명령 하나의 길 ─────────────────────────────────────────────────


# 자식 파이썬은 UTF-8 바이트를 직접 씀 (Windows 콘솔 인코딩과 상관없이 — git·gh의 출력은 UTF-8)
def test_run_returns_stdout():
    code = "import sys; sys.stdout.buffer.write('안녕\\n'.encode('utf-8'))"
    assert release.run([sys.executable, "-c", code]) == "안녕\n"


def test_run_raises_with_command_and_all_output():
    code = ("import sys; sys.stdout.buffer.write('표준 출력 글\\n'.encode('utf-8')); "
            "sys.stderr.buffer.write('표준 오류 글\\n'.encode('utf-8')); sys.exit(3)")
    with pytest.raises(release.CommandError) as info:
        release.run([sys.executable, "-c", code])
    text = str(info.value)
    assert "종료 코드 3" in text and "표준 출력 글" in text and "표준 오류 글" in text and "sys.exit(3)" in text


# ── 명령의 차례 (가짜 run) ──────────────────────────────────────────────────


class FakeRun:
    """run 대신: 부른 명령을 기록하고, 명령 앞부분이 맞는 첫 응답을 돌려줌.

    응답: 문자열 → 그대로, 리스트 → 부를 때마다 앞에서 하나씩, 함수 → 함수(cmd)의 값, 예외 → 던짐.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd, cwd=None):
        cmd = list(cmd)
        self.calls.append(cmd)
        for prefix, result in self.responses:
            if tuple(cmd[:len(prefix)]) == prefix:
                if isinstance(result, list):
                    assert result, f"응답을 다 썼는데 또 부름: {cmd}"
                    result = result.pop(0)
                if isinstance(result, BaseException):
                    raise result
                return result(cmd) if callable(result) else result
        raise AssertionError(f"예상 못 한 명령: {cmd}")

    def kinds(self):
        return [" ".join(cmd[:3]) for cmd in self.calls]

    def find(self, *prefix):
        return [cmd for cmd in self.calls if tuple(cmd[:len(prefix)]) == prefix]


def install(monkeypatch, responses):
    fake = FakeRun(responses)
    monkeypatch.setattr(release, "run", fake)
    monkeypatch.setattr(release, "RUN_POLL_S", 0)
    monkeypatch.setattr(release, "now_iso", lambda: RELEASED)
    return fake


def runs_json(*runs):
    return json.dumps([{"databaseId": run_id, "url": f"https://example.invalid/runs/{run_id}", "headSha": sha}
                       for run_id, sha in runs])


def prepare_responses(overrides=()):
    responses = {
        ("gh", "auth", "status"): "",
        ("git", "status", "--porcelain"): "",
        ("git", "fetch", "origin"): "",
        ("git", "rev-parse", "--verify"): SHA + "\n",
        ("git", "merge-base"): SHA + "\n",
        ("git", "cat-file", "-e"): "",
        ("git", "ls-remote", "--tags"): f"{OLD_SHA}\trefs/tags/v1.1.0\n{OLD_SHA}\trefs/tags/v1.1.9\n",
        # 푸시 전 1번(옛 실행만), 푸시 뒤: 아직 없음 → 새 실행
        ("gh", "run", "list"): [runs_json((5, SHA)), runs_json((5, SHA)), runs_json((9, SHA), (5, SHA))],
        ("git", "tag", "-a"): "",
        ("git", "push", "origin"): "",
    }
    responses.update(dict(overrides))
    return list(responses.items())


@pytest.fixture
def notes_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text(NOTES + "\n", encoding="utf-8")
    return str(path)


def test_prepare_sequence_and_json_line(monkeypatch, tmp_path, notes_file, capsys):
    fake = install(monkeypatch, prepare_responses())
    release.main(["prepare", "--notes-file", notes_file, "--nas-dir", str(tmp_path / "nas")])
    assert fake.kinds() == [
        "gh auth status", "git status --porcelain", "git fetch origin", "git rev-parse --verify",
        "git merge-base " + SHA, "git cat-file -e", "git ls-remote --tags",
        "gh run list", "git tag -a", "git push origin", "gh run list", "gh run list",
    ]
    assert fake.find("git", "rev-parse")[0][-1] == "origin/main^{commit}"  # 기본은 origin/main의 최신
    assert fake.find("git", "merge-base")[0] == ["git", "merge-base", SHA, "origin/main"]
    assert fake.find("git", "cat-file")[0] == ["git", "cat-file", "-e", f"{SHA}:tools/write_build_info.py"]
    tag_cmd = fake.find("git", "tag", "-a")[0]
    assert tag_cmd[3] == "v1.1.10" and tag_cmd[-1] == SHA
    assert tag_cmd[tag_cmd.index("-F") + 1] == notes_file and "--cleanup=whitespace" in tag_cmd
    assert fake.find("git", "push")[0] == ["git", "push", "origin", "refs/tags/v1.1.10:refs/tags/v1.1.10"]
    run_list = fake.find("gh", "run", "list")[0]
    assert run_list[run_list.index("--branch") + 1] == "v1.1.10"
    assert run_list[run_list.index("--json") + 1] == "databaseId,url,headSha"
    out = capsys.readouterr().out
    assert out.count("\n") == 1  # 표준 출력은 JSON 한 줄뿐
    assert json.loads(out) == {"version": "1.1.10", "tag": "v1.1.10", "commit": SHA, "run_id": 9,
                               "run_url": "https://example.invalid/runs/9"}


def test_prepare_minor_and_explicit_version(monkeypatch, tmp_path, notes_file, capsys):
    fake = install(monkeypatch, prepare_responses())
    release.main(["prepare", "--notes-file", notes_file, "--minor", "--nas-dir", str(tmp_path)])
    assert fake.find("git", "tag", "-a")[0][3] == "v1.2.0"
    capsys.readouterr()
    fake = install(monkeypatch, prepare_responses())
    release.main(["prepare", "--notes-file", notes_file, "--version", "0.9.0", "--nas-dir", str(tmp_path)])
    assert fake.find("git", "tag", "-a")[0][3] == "v0.9.0"
    assert json.loads(capsys.readouterr().out)["version"] == "0.9.0"


def test_prepare_refuses_existing_version(monkeypatch, tmp_path, notes_file):
    fake = install(monkeypatch, prepare_responses())
    with pytest.raises(release.ReleaseError, match="v1.1.9"):
        release.main(["prepare", "--notes-file", notes_file, "--version", "1.1.9", "--nas-dir", str(tmp_path)])
    assert not fake.find("git", "tag") and not fake.find("git", "push")


def test_prepare_refuses_dirty_tree(monkeypatch, tmp_path, notes_file):
    fake = install(monkeypatch, prepare_responses({("git", "status", "--porcelain"): " M yesoncheck/app.py\n"}))
    with pytest.raises(release.ReleaseError, match="yesoncheck/app.py"):
        release.main(["prepare", "--notes-file", notes_file, "--nas-dir", str(tmp_path)])
    assert not fake.find("git", "tag") and not fake.find("git", "push")


def test_prepare_refuses_commit_not_on_main(monkeypatch, tmp_path, notes_file):
    fake = install(monkeypatch, prepare_responses({("git", "merge-base"): OLD_SHA + "\n"}))
    with pytest.raises(release.ReleaseError, match="origin/main"):
        release.main(["prepare", "--notes-file", notes_file, "--commit", "auto_update", "--nas-dir", str(tmp_path)])
    assert fake.find("git", "rev-parse")[0][-1] == "auto_update^{commit}"
    assert not fake.find("git", "tag") and not fake.find("git", "push")


def test_prepare_allow_branch_uses_head_and_skips_main_check(monkeypatch, tmp_path, notes_file, capsys):
    fake = install(monkeypatch, prepare_responses())
    release.main(["prepare", "--notes-file", notes_file, "--version", "0.9.0", "--allow-branch",
                  "--nas-dir", str(tmp_path)])
    assert fake.find("git", "rev-parse")[0][-1] == "HEAD^{commit}"
    assert not fake.find("git", "merge-base")
    assert json.loads(capsys.readouterr().out)["tag"] == "v0.9.0"


def test_prepare_refuses_commit_before_this_feature(monkeypatch, tmp_path, notes_file):
    missing = release.CommandError("명령 실패 (종료 코드 128): git cat-file -e …")
    fake = install(monkeypatch, prepare_responses({("git", "cat-file", "-e"): missing}))
    with pytest.raises(release.ReleaseError, match="write_build_info.py") as info:
        release.main(["prepare", "--notes-file", notes_file, "--commit", "v1.0.0", "--nas-dir", str(tmp_path)])
    assert info.value.__cause__ is missing  # git의 출력도 함께 보임
    assert not fake.find("git", "tag") and not fake.find("git", "push")


def test_prepare_refuses_unwritable_nas(monkeypatch, tmp_path, notes_file):
    fake = install(monkeypatch, prepare_responses())
    with pytest.raises(release.ReleaseError, match="NAS"):
        release.main(["prepare", "--notes-file", notes_file, "--nas-dir", str(tmp_path / "없음" / "updates")])
    assert not fake.find("git", "tag") and not fake.find("git", "push")


def test_prepare_refuses_empty_notes(monkeypatch, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text(" \n\n", encoding="utf-8")
    fake = install(monkeypatch, prepare_responses())
    with pytest.raises(release.ReleaseError, match="바뀐 점"):
        release.main(["prepare", "--notes-file", str(empty), "--nas-dir", str(tmp_path)])
    assert not fake.find("git", "tag")


def test_prepare_errors_when_run_never_appears(monkeypatch, tmp_path, notes_file):
    old_only = [runs_json((5, SHA))] * (1 + release.RUN_POLL_TRIES)  # 같은 커밋의 옛 실행은 그 태그의 실행이 아님
    install(monkeypatch, prepare_responses({("gh", "run", "list"): old_only}))
    with pytest.raises(release.ReleaseError, match="abort v1.1.10"):
        release.main(["prepare", "--notes-file", notes_file, "--nas-dir", str(tmp_path)])


def test_prepare_stops_when_push_fails(monkeypatch, tmp_path, notes_file):
    failed = release.CommandError("명령 실패 (종료 코드 1): git push …")
    fake = install(monkeypatch, prepare_responses({("git", "push", "origin"): failed}))
    with pytest.raises(release.ReleaseError, match="abort v1.1.10") as info:  # 남은 로컬 태그를 지우는 방법
        release.main(["prepare", "--notes-file", notes_file, "--nas-dir", str(tmp_path)])
    assert info.value.__cause__ is failed
    assert fake.kinds()[-1] == "git push origin"


def test_prepare_rejects_minor_with_version(monkeypatch, tmp_path, notes_file):
    install(monkeypatch, prepare_responses())
    with pytest.raises(SystemExit):
        release.main(["prepare", "--notes-file", notes_file, "--minor", "--version", "1.2.0"])


# publish ───────────────────────────────────────────────────────────────────


def artifact_asset(name):
    """artifact 이름 → (플랫폼 키, 버전) (워크플로가 만드는 이름 그대로)."""
    for key, prefix in ARTIFACT_PREFIX.items():
        if name.startswith(prefix):
            return key, name[len(prefix):]
    raise AssertionError(f"모르는 artifact: {name}")


def fake_run_download(cmd):
    """gh run download <id> -n <artifact> -D <폴더> → 폴더에 Release 이름의 파일 하나."""
    key, version = artifact_asset(cmd[cmd.index("-n") + 1])
    folder = cmd[cmd.index("-D") + 1]
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, asset_names(version)[key]), "wb") as fh:
        fh.write(asset_bytes(version, key))
    return ""


class FakeReleases:
    """gh release list·create·edit·view·delete 흉내 — 한 태그의 Release 하나."""

    def __init__(self, existing=None, published=()):
        self.release = existing  # None 또는 {"isDraft": bool, "assets": [...]}
        self.published = list(published)  # 이전에 공개된 Release: [(태그, latest.json 바이트)]
        self.created = None

    def list(self, cmd):
        rows = [{"tagName": tag, "isDraft": False, "isLatest": i == 0} for i, (tag, _) in enumerate(self.published)]
        if self.release is not None:
            rows.insert(0, {"tagName": self.release["tag"], "isDraft": self.release["isDraft"], "isLatest": False})
        if "--exclude-drafts" in cmd:
            rows = [row for row in rows if not row["isDraft"]]
        return json.dumps(rows)

    def create(self, cmd):
        assert self.release is None, "Release가 이미 있는데 또 만듦"
        notes_path = cmd[cmd.index("--notes-file") + 1]
        assets = [arg for arg in cmd[4:] if os.path.isfile(arg) and arg != notes_path]
        with open(notes_path, encoding="utf-8") as fh:
            notes = fh.read()
        manifest = next(a for a in assets if os.path.basename(a) == "latest.json")
        with open(manifest, "rb") as fh:
            manifest_bytes = fh.read()
        self.created = {"cmd": cmd, "notes": notes, "manifest": manifest_bytes,
                        "assets": {os.path.basename(a): os.path.getsize(a) for a in assets}}
        self.release = {"tag": cmd[3], "isDraft": "--draft" in cmd, "assets": self.created["assets"]}
        return "https://example.invalid/releases/tag/" + cmd[3] + "\n"

    def edit(self, cmd):
        assert "--draft=false" in cmd and "--latest" in cmd
        self.release["isDraft"] = False
        return ""

    def view(self, cmd):
        return json.dumps({"isDraft": self.release["isDraft"], "url": "https://example.invalid/releases/tag/v1.1.2",
                           "assets": [{"name": n, "size": s} for n, s in self.release["assets"].items()]})

    def delete(self, cmd):
        assert self.release is not None and self.release["isDraft"]
        self.release = None
        return ""

    def download(self, cmd):
        tag = cmd[3]
        data = dict(self.published)[tag]
        assert cmd[cmd.index("-p") + 1] == "latest.json" and cmd[cmd.index("-O") + 1] == "-"
        return data.decode("utf-8")


def jobs_json(**conclusions):
    names = {"windows": "build", "mac_x86_64": "mac (Intel)", "mac_arm64": "mac (AppleSilicon)"}
    jobs = []
    for key, name in names.items():
        conclusion = conclusions.get(key, "success")
        jobs.append({"name": name, "status": "in_progress" if conclusion == "" else "completed",
                     "conclusion": conclusion})
    return json.dumps({"status": "completed", "conclusion": "success", "jobs": jobs})


def publish_responses(releases, overrides=()):
    responses = {
        ("git", "cat-file", "-t"): "tag\n",
        ("git", "rev-parse"): SHA + "\n",
        ("git", "tag", "-l"): NOTES + "\n\n",
        ("gh", "release", "list"): releases.list,
        ("gh", "run", "list"): runs_json((9, SHA), (5, OLD_SHA), (3, SHA)),
        ("gh", "run", "view"): jobs_json(),
        ("gh", "run", "download"): fake_run_download,
        ("gh", "release", "delete"): releases.delete,
        ("gh", "release", "create"): releases.create,
        ("gh", "release", "edit"): releases.edit,
        ("gh", "release", "view"): releases.view,
        ("gh", "release", "download"): releases.download,
    }
    responses.update(dict(overrides))
    return list(responses.items())


def record_sync(monkeypatch, fake):
    """sync_to_nas가 불린 때를 명령 기록 사이에 표시 (실제 복사는 그대로)."""
    original = release.sync_to_nas

    def recording(files, manifest, nas_dir):
        fake.calls.append(["<sync_to_nas>", nas_dir])
        return original(files, manifest, nas_dir)

    monkeypatch.setattr(release, "sync_to_nas", recording)


def test_publish_draft_only_sequence(monkeypatch, tmp_path, capsys):
    releases = FakeReleases()
    fake = install(monkeypatch, publish_responses(releases))
    record_sync(monkeypatch, fake)
    nas = tmp_path / "nas"
    release.main(["publish", "v1.1.2", "--draft-only", "--nas-dir", str(nas)])
    assert fake.kinds() == [
        "git cat-file -t", "git rev-parse --verify", "git tag -l", "gh release list",
        "gh run list", "gh run view", "gh run download", "gh run download", "gh run download",
        "gh release create", "gh release view", "<sync_to_nas> " + str(nas),
    ]
    assert fake.find("git", "rev-parse")[0][-1] == "v1.1.2^{commit}"
    assert fake.find("gh", "run", "view")[0][3] == "9"  # 같은 커밋의 실행 중 가장 새것
    assert {c[3] for c in fake.find("gh", "run", "download")} == {"9"}
    assert [c[c.index("-n") + 1] for c in fake.find("gh", "run", "download")] == [
        "YesonCheck_Setup_Windows_1.1.2", "YesonCheck_Autocut_Intel_1.1.2", "YesonCheck_Autocut_AppleSilicon_1.1.2"]
    create = releases.created["cmd"]
    assert "--draft" in create and "--verify-tag" in create and "--latest" not in create
    assert create[create.index("--title") + 1] == "v1.1.2"
    assert releases.created["notes"].strip() == NOTES  # Release 노트 = 태그 메시지
    assert sorted(releases.created["assets"]) == sorted([*asset_names("1.1.2").values(), "latest.json"])
    manifest = parse_manifest(releases.created["manifest"])
    assert str(manifest.version) == "1.1.2" and manifest.commit == SHA and manifest.notes == NOTES
    assert manifest.released == RELEASED and sorted(manifest.files) == sorted(ALL_KEYS)
    assert releases.release["isDraft"] is True and not fake.find("gh", "release", "edit")
    assert (nas / "latest.json").read_bytes() == releases.created["manifest"]
    for entry in manifest.files.values():
        assert sha256_of(nas / entry.name) == entry.sha256
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == "1.1.2" and report["draft"] is True and report["nas_dir"] == str(nas)


def test_publish_publishes_before_nas_copy(monkeypatch, tmp_path, capsys):
    releases = FakeReleases()
    fake = install(monkeypatch, publish_responses(releases))
    record_sync(monkeypatch, fake)
    nas = tmp_path / "nas"
    release.main(["publish", "v1.1.2", "--nas-dir", str(nas)])
    assert fake.kinds()[-4:] == ["gh release create", "gh release edit", "gh release view", "<sync_to_nas> " + str(nas)]
    assert fake.find("gh", "release", "edit")[0][3:6] == ["v1.1.2", "--draft=false", "--latest"]
    assert releases.release["isDraft"] is False
    assert json.loads(capsys.readouterr().out)["draft"] is False


def test_publish_default_nas_dir_is_shared_config_updates(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(tmp_path))
    install(monkeypatch, publish_responses(FakeReleases()))
    release.main(["publish", "v1.1.2"])
    assert (tmp_path / "updates" / "latest.json").exists()
    assert json.loads(capsys.readouterr().out)["nas_dir"] == str(tmp_path / "updates")


def test_publish_nas_failure_after_publishing_says_nas_sync(monkeypatch, tmp_path):
    install(monkeypatch, publish_responses(FakeReleases()))

    def broken(files, manifest, nas_dir):
        raise PermissionError(13, "쓰기 권한 없음", nas_dir)

    monkeypatch.setattr(release, "sync_to_nas", broken)
    with pytest.raises(release.ReleaseError, match="nas-sync v1.1.2") as info:
        release.main(["publish", "v1.1.2", "--nas-dir", str(tmp_path)])
    assert isinstance(info.value.__cause__, PermissionError)


def test_publish_draft_only_requires_nas_dir(monkeypatch):
    install(monkeypatch, publish_responses(FakeReleases()))
    with pytest.raises(SystemExit):
        release.main(["publish", "v1.1.2", "--draft-only"])


@pytest.mark.parametrize("conclusions", [{"windows": "failure"}, {"mac_x86_64": "cancelled"}, {"mac_arm64": ""}])
def test_publish_refuses_unsuccessful_job(monkeypatch, tmp_path, conclusions):
    releases = FakeReleases()
    fake = install(monkeypatch, publish_responses(releases, {("gh", "run", "view"): jobs_json(**conclusions)}))
    with pytest.raises(release.ReleaseError, match="성공하지 않"):
        release.main(["publish", "v1.1.2", "--nas-dir", str(tmp_path / "nas")])
    assert not fake.find("gh", "run", "download") and releases.created is None
    assert not (tmp_path / "nas").exists()


def test_publish_refuses_missing_run(monkeypatch, tmp_path):
    fake = install(monkeypatch, publish_responses(FakeReleases(), {("gh", "run", "list"): runs_json((5, OLD_SHA))}))
    with pytest.raises(release.ReleaseError, match="v1.1.2"):
        release.main(["publish", "v1.1.2", "--nas-dir", str(tmp_path)])
    assert not fake.find("gh", "run", "download")


def test_publish_refuses_lightweight_tag(monkeypatch, tmp_path):
    install(monkeypatch, publish_responses(FakeReleases(), {("git", "cat-file", "-t"): "commit\n"}))
    with pytest.raises(release.ReleaseError, match="주석 태그"):
        release.main(["publish", "v1.1.2", "--nas-dir", str(tmp_path)])


def test_publish_refuses_already_published(monkeypatch, tmp_path):
    releases = FakeReleases(existing={"tag": "v1.1.2", "isDraft": False, "assets": {}})
    fake = install(monkeypatch, publish_responses(releases))
    with pytest.raises(release.ReleaseError, match="nas-sync"):
        release.main(["publish", "v1.1.2", "--nas-dir", str(tmp_path)])
    assert not fake.find("gh", "run", "download")


def test_publish_replaces_existing_draft(monkeypatch, tmp_path, capsys):
    releases = FakeReleases(existing={"tag": "v1.1.2", "isDraft": True, "assets": {"old.dmg": 1}})
    fake = install(monkeypatch, publish_responses(releases))
    release.main(["publish", "v1.1.2", "--draft-only", "--nas-dir", str(tmp_path / "nas")])
    kinds = fake.kinds()
    assert kinds.index("gh release delete") < kinds.index("gh release create")
    delete = fake.find("gh", "release", "delete")[0]
    assert "--yes" in delete and "--cleanup-tag" not in delete  # 태그는 남김
    assert "old.dmg" not in releases.release["assets"]


def test_publish_without_arm64_first_time(monkeypatch, tmp_path, capsys):
    releases = FakeReleases()  # 이전 Release 없음
    fake = install(monkeypatch, publish_responses(releases, {("gh", "run", "view"): jobs_json(mac_arm64="failure")}))
    release.main(["publish", "v1.1.2", "--without-arm64", "--nas-dir", str(tmp_path / "nas")])
    assert [c[c.index("-n") + 1] for c in fake.find("gh", "run", "download")] == [
        "YesonCheck_Setup_Windows_1.1.2", "YesonCheck_Autocut_Intel_1.1.2"]
    assert sorted(releases.created["assets"]) == sorted(
        ["YesonCheck_Setup_1.1.2.exe", "YesonCheck_Autocut_Intel_1.1.2.dmg", "latest.json"])
    assert sorted(parse_manifest(releases.created["manifest"]).files) == ["mac-x86_64", "windows"]
    assert sorted(p.name for p in (tmp_path / "nas").iterdir()) == sorted(
        ["YesonCheck_Setup_1.1.2.exe", "YesonCheck_Autocut_Intel_1.1.2.dmg", "latest.json"])


def test_publish_without_arm64_allowed_when_previous_had_none(monkeypatch, tmp_path, capsys):
    previous = make_manifest("1.1.0", OLD_SHA, RELEASED, NOTES, files_in(tmp_path / "p", "1.1.0", ALL_KEYS[:2]))
    releases = FakeReleases(published=[("v1.1.0", previous)])
    fake = install(monkeypatch, publish_responses(releases))
    release.main(["publish", "v1.1.2", "--without-arm64", "--nas-dir", str(tmp_path / "nas")])
    assert fake.find("gh", "release", "download")[0][3] == "v1.1.0"
    assert sorted(parse_manifest(releases.created["manifest"]).files) == ["mac-x86_64", "windows"]


def test_publish_without_arm64_refused_after_arm64_was_released(monkeypatch, tmp_path):
    previous = make_manifest("1.1.1", OLD_SHA, RELEASED, NOTES, files_in(tmp_path / "p", "1.1.1"))
    releases = FakeReleases(published=[("v1.1.1", previous)])
    fake = install(monkeypatch, publish_responses(releases))
    with pytest.raises(release.ReleaseError, match="mac-arm64"):
        release.main(["publish", "v1.1.2", "--without-arm64", "--nas-dir", str(tmp_path / "nas")])
    assert not fake.find("gh", "run", "download") and releases.created is None


# nas-sync ──────────────────────────────────────────────────────────────────


def nas_sync_responses(tmp_path, manifest_version="1.1.2", is_draft=False):
    source = files_in(tmp_path / "release_files", "1.1.2")
    manifest = make_manifest(manifest_version, SHA, RELEASED, NOTES, source) if manifest_version == "1.1.2" else \
        make_manifest(manifest_version, SHA, RELEASED, NOTES, files_in(tmp_path / "other", manifest_version))

    def download(cmd):
        """gh release download <태그> -D <폴더> -p <이름> … → 폴더에 그 Release 파일들."""
        folder = cmd[cmd.index("-D") + 1]
        for name in (cmd[i + 1] for i, arg in enumerate(cmd) if arg == "-p"):
            if name == "latest.json":
                data = manifest
            else:
                with open(os.path.join(str(tmp_path / "release_files"), name), "rb") as fh:
                    data = fh.read()
            with open(os.path.join(folder, name), "wb") as fh:
                fh.write(data)
        return ""

    rows = json.dumps([{"tagName": "v1.1.2", "isDraft": is_draft, "isLatest": not is_draft}])
    return manifest, [(("gh", "release", "list"), rows), (("gh", "release", "download"), download)]


def test_nas_sync_downloads_checks_and_copies(monkeypatch, tmp_path, capsys):
    manifest, responses = nas_sync_responses(tmp_path)
    fake = install(monkeypatch, responses)
    record_sync(monkeypatch, fake)
    nas = tmp_path / "nas"
    release.main(["nas-sync", "v1.1.2", "--nas-dir", str(nas)])
    assert fake.kinds() == ["gh release list", "gh release download", "gh release download",
                            "<sync_to_nas> " + str(nas)]
    first, second = fake.find("gh", "release", "download")
    assert first[3] == "v1.1.2" and first[first.index("-p") + 1] == "latest.json"
    assert sorted(second[i + 1] for i, a in enumerate(second) if a == "-p") == sorted(asset_names("1.1.2").values())
    assert (nas / "latest.json").read_bytes() == manifest
    assert json.loads(capsys.readouterr().out)["nas_dir"] == str(nas)


def test_nas_sync_refuses_manifest_of_other_version(monkeypatch, tmp_path):
    _, responses = nas_sync_responses(tmp_path, manifest_version="1.1.1")
    install(monkeypatch, responses)
    with pytest.raises(release.ReleaseError, match="1.1.1"):
        release.main(["nas-sync", "v1.1.2", "--nas-dir", str(tmp_path / "nas")])
    assert not (tmp_path / "nas").exists()


def test_nas_sync_of_draft_needs_explicit_nas_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("YESONCHECK_CONFIG_DIR", str(tmp_path))
    _, responses = nas_sync_responses(tmp_path, is_draft=True)
    install(monkeypatch, responses)
    with pytest.raises(release.ReleaseError, match="초안"):
        release.main(["nas-sync", "v1.1.2"])
    assert not (tmp_path / "updates").exists()


def test_nas_sync_refuses_missing_release(monkeypatch, tmp_path):
    install(monkeypatch, [(("gh", "release", "list"), "[]")])
    with pytest.raises(release.ReleaseError, match="v1.1.2"):
        release.main(["nas-sync", "v1.1.2", "--nas-dir", str(tmp_path)])


# abort ─────────────────────────────────────────────────────────────────────


def abort_responses(release_rows, remote_tag=True, local_tag=True):
    return [
        (("gh", "release", "list"), json.dumps(release_rows)),
        (("gh", "release", "delete"), ""),
        (("git", "ls-remote", "--tags"), f"{OLD_SHA}\trefs/tags/v0.9.0\n" if remote_tag else ""),
        (("git", "push", "origin"), ""),
        (("git", "tag", "-l"), "v0.9.0\n" if local_tag else ""),
        (("git", "tag", "-d"), ""),
    ]


def test_abort_deletes_draft_remote_and_local_tag(monkeypatch, capsys):
    fake = install(monkeypatch, abort_responses([{"tagName": "v0.9.0", "isDraft": True, "isLatest": False}]))
    release.main(["abort", "v0.9.0"])
    assert fake.kinds() == ["gh release list", "gh release delete", "git ls-remote --tags", "git push origin",
                            "git tag -l", "git tag -d"]
    assert fake.find("gh", "release", "delete")[0][3] == "v0.9.0"
    assert fake.find("git", "ls-remote")[0][-1] == "refs/tags/v0.9.0"
    assert fake.find("git", "push")[0] == ["git", "push", "origin", ":refs/tags/v0.9.0"]
    assert fake.find("git", "tag", "-d")[0] == ["git", "tag", "-d", "v0.9.0"]
    assert json.loads(capsys.readouterr().out)["removed"] == ["초안 Release", "원격 태그", "로컬 태그"]


def test_abort_without_release_or_remote_tag(monkeypatch, capsys):
    fake = install(monkeypatch, abort_responses([{"tagName": "v1.1.0", "isDraft": False, "isLatest": True}],
                                                remote_tag=False))
    release.main(["abort", "v0.9.0"])
    assert fake.kinds() == ["gh release list", "git ls-remote --tags", "git tag -l", "git tag -d"]
    assert json.loads(capsys.readouterr().out)["removed"] == ["로컬 태그"]


def test_abort_refuses_published_release(monkeypatch):
    fake = install(monkeypatch, abort_responses([{"tagName": "v0.9.0", "isDraft": False, "isLatest": True}]))
    with pytest.raises(release.ReleaseError, match="공개"):
        release.main(["abort", "v0.9.0"])
    assert fake.kinds() == ["gh release list"]  # 아무것도 지우지 않음


@pytest.mark.parametrize("command", [["abort", "1.1.0"], ["publish", "v1.1"], ["nas-sync", "v1.1.0+0f4d3d7"]])
def test_commands_reject_bad_tag(monkeypatch, command):
    fake = install(monkeypatch, [])
    with pytest.raises(release.ReleaseError, match="vX.Y.Z"):
        release.main(command)
    assert fake.calls == []
