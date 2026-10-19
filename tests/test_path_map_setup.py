import contextlib
import json
import os
import stat
import threading
import time
import unicodedata
from types import SimpleNamespace

import pytest

from yesoncheck import path_map_setup as pms
from yesoncheck import paths
from yesoncheck.path_map_setup import Candidate, PairChoice, Proposal, Share


def dirs(*items):
    """주어진 폴더와 그 위 폴더들(공유 루트 \\\\서버\\공유까지)이 열리는 가짜 is_dir (대소문자 무시)."""
    keys = set()
    for item in items:
        parts = [part for part in item[2:].split("\\") if part]
        for n in range(2, len(parts) + 1):
            keys.add(("\\\\" + "\\".join(parts[:n])).casefold())
    return lambda path: path.casefold() in keys


S_USA2 = Share("\\\\203.0.113.3\\usadata2", ["Y:"])
S_COLOR = Share("\\\\203.0.113.19\\colordata", ["Z:"])
EXIST = {"_안내": ["x"], "version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\203.0.113.3\\usadata2"]}]}


def test_unc_key_ignores_case_slash_and_normalization():
    nfd = unicodedata.normalize("NFD", "\\\\NAS\\자료\\")
    assert paths.unc_key("//nas/자료") == paths.unc_key(nfd)


def test_connected_shares_groups_letters_and_reports_problems():
    remotes = {"X:": "\\\\nas\\data", "Y:": "\\\\NAS\\Data\\"}

    def resolve(drive):
        if drive == "W:":
            raise paths.PathMapError("W: 드라이브의 연결 정보를 읽지 못했습니다 (WNetGetConnectionW 오류 1203)")
        return remotes.get(drive)

    shares, problems = pms.connected_shares(resolve)
    assert [(s.unc, s.drives) for s in shares] == [("\\\\nas\\data", ["X:", "Y:"])]
    assert problems == ["W: — W: 드라이브의 연결 정보를 읽지 못했습니다 (WNetGetConnectionW 오류 1203)"]


def test_deepest_match_wins():
    is_dir = dirs("\\\\203.0.113.3\\usadata2\\Disney\\KOTH", "\\\\203.0.113.19\\colordata\\KOTH")
    proposal = pms.propose_mapping({"KOTH": "/usadata2/Disney/KOTH"}, [S_USA2, S_COLOR], is_dir)
    assert [(p.mac_prefix, [c.unc for c in p.candidates]) for p in proposal.pairs] == [
        ("/usadata2", ["\\\\203.0.113.3\\usadata2"])
    ]
    assert proposal.pairs[0].candidates[0].works == ["KOTH"]
    assert proposal.unmatched == {}


def test_same_depth_two_shares_is_ambiguous_and_prefers_name_match():
    other = Share("\\\\backup\\mirror", ["M:"])
    is_dir = dirs("\\\\backup\\mirror\\FLORIDA", "\\\\203.0.113.19\\colordata\\FLORIDA")
    proposal = pms.propose_mapping({"FL_Animatic": "/Volumes/colordata/FLORIDA"}, [other, S_COLOR], is_dir)
    (pair,) = proposal.pairs
    assert pair.mac_prefix == "/Volumes/colordata" and pair.ambiguous
    assert [c.unc for c in pair.candidates] == ["\\\\203.0.113.19\\colordata", "\\\\backup\\mirror"]


def test_share_root_alone_is_not_evidence_and_unmatched_reported():
    proposal = pms.propose_mapping({"KOTH": "/usadata2/KOTH"}, [S_USA2], dirs("\\\\203.0.113.3\\usadata2"))
    assert proposal.pairs == []
    assert proposal.unmatched == {"KOTH": "/usadata2/KOTH"}


def test_trailing_slash_firmlink_and_hangul():
    nfd = unicodedata.normalize("NFD", "HH99_시즌_자료")
    s4 = Share("\\\\203.0.113.14\\usadata4", ["U:"])
    is_dir = dirs(
        "\\\\203.0.113.19\\colordata\\Hazbin_Hotel\\HH99_시즌_자료",
        "\\\\203.0.113.14\\usadata4\\BentoBox_Data\\BB_New",
    )
    works = {
        "HH": f"/System/Volumes/Data/Volumes/colordata/Hazbin_Hotel/{nfd}",
        "BB": "/Users/studio01/Desktop/usadata4/BentoBox_Data/BB_New/",
    }
    proposal = pms.propose_mapping(works, [S_COLOR, s4], is_dir)
    assert {p.mac_prefix: p.candidates[0].unc for p in proposal.pairs} == {
        "/Volumes/colordata": "\\\\203.0.113.19\\colordata",
        "/Users/studio01/Desktop/usadata4": "\\\\203.0.113.14\\usadata4",
    }


def test_each_folder_checked_once():
    calls = []

    def is_dir(path):
        calls.append(path.casefold())
        return path.casefold() == S_USA2.unc.casefold()  # 공유 루트만 열림 → 작품 폴더도 확인함

    pms.propose_mapping({"A": "/usadata2/X/A", "B": "/usadata2/X/A"}, [S_USA2], is_dir)
    assert len(calls) > 1
    assert len(calls) == len(set(calls))


def test_progress_cancel():
    with pytest.raises(pms.SetupCancelled):
        pms.propose_mapping({"A": "/usadata2/A"}, [S_USA2], dirs("\\\\203.0.113.3\\usadata2"),
                            progress=lambda done, total: False)


def test_unreachable_share_skipped_once_and_reported():
    """서버가 꺼진(기억만 된) 드라이브: 루트를 한 번만 열어 보고 건너뜀 (작품마다 SMB 시간 초과를 기다리지 않음)."""
    dead = Share("\\\\localhost\\yc_fake_dead", ["X:", "W:"])
    calls = []
    alive = dirs("\\\\203.0.113.3\\usadata2\\KOTH", "\\\\203.0.113.3\\usadata2\\FLORIDA")

    def is_dir(path):
        calls.append(path.casefold())
        return alive(path)

    progress = []
    proposal = pms.propose_mapping(
        {"KOTH": "/usadata2/KOTH", "FL": "/usadata2/FLORIDA"}, [dead, S_USA2], is_dir,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert [c for c in calls if c.startswith(dead.unc.casefold())] == [dead.unc.casefold()]
    assert [(p.mac_prefix, [c.unc for c in p.candidates]) for p in proposal.pairs] == [
        ("/usadata2", [S_USA2.unc])
    ]
    assert proposal.pairs[0].candidates[0].works == ["FL", "KOTH"]
    assert len(proposal.share_problems) == 1
    problem = proposal.share_problems[0]
    assert "X:, W:" in problem and dead.unc in problem and "열리지 않음" in problem
    assert progress and progress[-1][0] == progress[-1][1]  # 진행 표시는 끝까지 감
    assert all(done <= total for done, total in progress)


def test_find_config_dirs_both_layouts():
    usa_db = Share("\\\\203.0.113.3\\USA_DB", ["U:"])
    data = Share("\\\\203.0.113.3\\data", ["D:"])
    files = {
        "\\\\203.0.113.3\\usa_db\\test_jn\\.yesoncheck\\work_paths.json",
        "\\\\203.0.113.3\\data\\usa_db\\test_jn\\.yesoncheck\\work_paths.json",
    }
    found = pms.find_config_dirs([usa_db, data], is_file=lambda p: p.casefold() in files)
    assert found == [
        "\\\\203.0.113.3\\USA_DB\\test_jn\\.yesoncheck",
        "\\\\203.0.113.3\\data\\USA_DB\\test_jn\\.yesoncheck",
    ]


def test_find_config_dirs_requires_work_paths():
    assert pms.find_config_dirs([Share("\\\\s\\x", ["X:"])], is_file=lambda p: False) == []


def test_find_config_dirs_probes_shares_concurrently_in_share_order():
    """공유마다 동시에 확인 → 전체 시간은 가장 느린 공유 정도 (합이 아님). 결과 순서는 공유 순서 그대로.

    a는 짧은 뒷부분에서 찾음(두 번 확인 → 가장 늦게 끝남), b·d는 긴 뒷부분에서 바로 찾음, c는 없음(두 번 확인).
    """
    a, b, c, d = (Share(f"\\\\srv\\{name}", [f"{name.upper()}:"]) for name in "abcd")
    files = {
        "\\\\srv\\a\\test_jn\\.yesoncheck\\work_paths.json",
        "\\\\srv\\b\\usa_db\\test_jn\\.yesoncheck\\work_paths.json",
        "\\\\srv\\d\\usa_db\\test_jn\\.yesoncheck\\work_paths.json",
    }
    lock = threading.Lock()
    active = {"now": 0, "max": 0}
    calls = []

    def slow_is_file(path):
        with lock:
            active["now"] += 1
            active["max"] = max(active["max"], active["now"])
            calls.append(path)
        time.sleep(0.3)
        with lock:
            active["now"] -= 1
        return path.casefold() in files

    started = time.monotonic()
    found = pms.find_config_dirs([a, b, c, d], is_file=slow_is_file)
    elapsed = time.monotonic() - started
    assert found == [
        "\\\\srv\\a\\test_jn\\.yesoncheck",
        "\\\\srv\\b\\USA_DB\\test_jn\\.yesoncheck",
        "\\\\srv\\d\\USA_DB\\test_jn\\.yesoncheck",
    ]
    assert len(calls) == 6  # a 2번, b 1번, c 2번, d 1번 → 차례로 하면 1.8초
    assert active["max"] >= 2  # 실제로 겹쳐 실행됨
    # 차례로 한 시간(0.3초 × 확인 수)의 80%보다 짧음 — 동시에 하면 약 0.6초. 고정 한계(1.2초)는 바쁜 시험 기계에서 넘었음
    sequential = 0.3 * len(calls)
    assert elapsed < 0.8 * sequential, f"{elapsed:.2f}초 (차례로 하면 {sequential:.1f}초, 동시에 하면 약 0.6초)"


def test_find_config_dirs_uses_daemon_threads():
    """공유 확인 스레드는 daemon — 서버가 꺼진 공유를 확인하는 중에 앱을 닫아도 프로세스가 그 확인을 기다리지 않음."""
    daemons = []

    def is_file(path):
        daemons.append(threading.current_thread().daemon)
        return False

    assert pms.find_config_dirs([Share("\\\\s\\x", ["X:"]), Share("\\\\s\\y", ["Y:"])], is_file=is_file) == []
    assert daemons and all(daemons)


def test_find_config_dirs_raises_probe_errors():
    def broken(path):
        raise OSError("확인 실패 (가짜 재현)")

    with pytest.raises(OSError, match="가짜 재현"):
        pms.find_config_dirs([Share("\\\\s\\x", ["X:"]), Share("\\\\s\\y", ["Y:"])], is_file=broken)


def test_merge_keeps_existing_adds_new_and_alias():
    merged = pms.merge_path_map(EXIST, [
        ("/usadata2", "\\\\NAS3\\usadata2"),
        ("/Volumes/colordata", "\\\\203.0.113.19\\colordata"),
    ])
    assert merged["_안내"] == ["x"]
    assert merged["shares"] == [
        {"mac": "/usadata2", "windows": ["\\\\203.0.113.3\\usadata2", "\\\\NAS3\\usadata2"]},
        {"mac": "/Volumes/colordata", "windows": ["\\\\203.0.113.19\\colordata"]},
    ]
    assert EXIST["shares"][0]["windows"] == ["\\\\203.0.113.3\\usadata2"]  # 원본은 그대로


def test_merge_same_alias_not_duplicated():
    assert pms.merge_path_map(EXIST, [("/usadata2", "//203.0.113.3/USADATA2/")]) == EXIST


def test_merge_invalid_result_raises():
    existing = {"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\s\\x"]}]}
    with pytest.raises(paths.PathMapError, match="번째 항목에도 있습니다"):
        pms.merge_path_map(existing, [("/b", "\\\\s\\x")])


def test_has_additions():
    proposal = Proposal(
        pairs=[PairChoice("/usadata2", [Candidate("/usadata2", "\\\\203.0.113.3\\usadata2", ["Y:"], ["KOTH"])])],
        unmatched={}, shares=[S_USA2],
    )
    assert not pms.has_additions(EXIST, proposal)
    assert pms.has_additions(None, proposal)
    assert not pms.has_additions(EXIST, Proposal(pairs=[], unmatched={}, shares=[]))


NAS_C = "\\\\nas\\colordata"
S_NAS_C = Share(NAS_C, ["Z:"])


def two_prefixes_one_share():
    """Mac이 같은 공유를 두 번째로 연결하면 /Volumes/colordata-1이 됨 → 같은 UNC가 두 Mac 앞부분에 맞음."""
    return Proposal(
        pairs=[
            PairChoice("/Volumes/colordata", [Candidate("/Volumes/colordata", NAS_C, ["Z:"], ["KOTH"])]),
            PairChoice("/Volumes/colordata-1", [
                Candidate("/Volumes/colordata-1", NAS_C, ["Z:"], ["FLORIDA", "FL_Animatic"]),
            ]),
        ],
        unmatched={}, shares=[S_NAS_C],
    )


def test_ordered_default_choices_most_works_first():
    proposal = two_prefixes_one_share()
    assert proposal.ordered_default_choices() == [("/Volumes/colordata-1", NAS_C), ("/Volumes/colordata", NAS_C)]


def test_split_mergeable_two_prefixes_claim_one_unc():
    ok, rejected = pms.split_mergeable(None, two_prefixes_one_share().ordered_default_choices())
    assert ok == [("/Volumes/colordata-1", NAS_C)]
    assert len(rejected) == 1
    mac, unc, reason = rejected[0]
    assert (mac, unc) == ("/Volumes/colordata", NAS_C)
    assert "/Volumes/colordata-1" in reason and "같은 경로로 맞추세요" in reason


def test_split_mergeable_unc_already_used_by_existing_entry():
    existing = {"version": 1, "shares": [{"mac": "/Volumes/colordata", "windows": [NAS_C]}]}
    choices = [("/usadata2", "\\\\203.0.113.3\\usadata2"), ("/Volumes/colordata-1", "//NAS/ColorData")]
    ok, rejected = pms.split_mergeable(existing, choices)
    assert ok == [("/usadata2", "\\\\203.0.113.3\\usadata2")]  # 주어진 순서 유지
    assert [(mac, unc) for mac, unc, _reason in rejected] == [("/Volumes/colordata-1", "//NAS/ColorData")]
    assert "/Volumes/colordata" in rejected[0][2]


def test_has_additions_ignores_choices_that_cannot_be_merged():
    """합칠 수 없는 짝 때문에 시작할 때마다 창이 뜨지 않도록: 합칠 수 있는 짝으로 달라지는 것이 있을 때만 True."""
    proposal = two_prefixes_one_share()
    assert pms.has_additions(None, proposal)  # 하나는 넣을 수 있음
    saved = pms.merge_path_map(None, [("/Volumes/colordata-1", NAS_C)])
    assert not pms.has_additions(saved, proposal)  # 넣을 수 있는 것은 이미 들어 있음, 나머지는 넣을 수 없음
    existing = {"version": 1, "shares": [{"mac": "/Volumes/colordata", "windows": [NAS_C]}]}
    assert not pms.has_additions(existing, Proposal(
        pairs=[PairChoice("/Volumes/colordata-1", [Candidate("/Volumes/colordata-1", NAS_C, ["Z:"], ["FL"])])],
        unmatched={}, shares=[S_NAS_C],
    ))


def test_read_existing_and_save_with_backup(tmp_path):
    assert pms.read_existing(str(tmp_path)) == (None, None)
    (tmp_path / "path_map.json").write_text(
        '{"version": 1, "shares": [{"mac": "/a", "windows": ["여기에_붙여넣기"]}]}', encoding="utf-8")
    data, error = pms.read_existing(str(tmp_path))
    assert data is None and "여기에_붙여넣기" in error
    backup = pms.save_path_map(
        str(tmp_path), {"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\s\\a"]}]}, backup_existing=True)
    assert os.path.basename(backup).startswith("path_map.json.bak-")
    assert "여기에_붙여넣기" in open(backup, encoding="utf-8").read()
    data, error = pms.read_existing(str(tmp_path))
    assert error is None and data["shares"][0]["windows"] == ["\\\\s\\a"]


def test_save_path_map_leaves_original_untouched_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "path_map.json"
    original = {"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\203.0.113.3\\usadata2"]}]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(original, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    with open(path, "rb") as fh:
        original_bytes = fh.read()

    def boom(src, dst):
        raise OSError("디스크가 가득 찼습니다")

    monkeypatch.setattr(pms.os, "replace", boom)

    with pytest.raises(OSError):
        pms.save_path_map(
            str(tmp_path),
            {"version": 1, "shares": [{"mac": "/usadata2", "windows": ["\\\\NAS3\\usadata2"]}]},
            backup_existing=False,
        )

    with open(path, "rb") as fh:
        assert fh.read() == original_bytes
    assert [name for name in os.listdir(tmp_path) if name.startswith("path_map.json.tmp")] == []


def test_read_existing_raises_when_nas_hiccups(tmp_path, monkeypatch):
    """NAS가 잠깐 끊겨 파일 정보를 못 읽으면(stat 실패) '파일 없음'으로 보고 덮어쓰지 않도록 오류를 그대로 올림."""
    path = str(tmp_path / "path_map.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(EXIST, fh)
    real_stat = os.stat

    def flaky_stat(target, *args, **kwargs):
        if os.fspath(target) == path:
            raise PermissionError(13, "네트워크 연결이 잠깐 끊김 (가짜 재현)", path)
        return real_stat(target, *args, **kwargs)

    def flaky_open(target, *args, **kwargs):
        raise PermissionError(13, "네트워크 연결이 잠깐 끊김 (가짜 재현)", os.fspath(target))

    monkeypatch.setattr(os, "stat", flaky_stat)
    monkeypatch.setattr(pms, "open", flaky_open, raising=False)
    with pytest.raises(PermissionError):
        pms.read_existing(str(tmp_path))


@pytest.mark.parametrize("encoding", ["cp949", "utf-16"])
def test_read_existing_non_utf8_is_backed_up_and_recreated(tmp_path, encoding):
    """메모장 ANSI(CP949)·UTF-16으로 저장된 파일: 읽을 수 없는 이유를 돌려주고, 저장할 때 원래 바이트 그대로 백업."""
    raw = json.dumps(
        {"version": 1, "shares": [{"mac": "/Volumes/작품", "windows": ["\\\\nas\\작품"]}]}, ensure_ascii=False,
    ).encode(encoding)
    (tmp_path / "path_map.json").write_bytes(raw)
    data, error = pms.read_existing(str(tmp_path))
    assert data is None and error
    backup = pms.save_path_map(
        str(tmp_path), {"version": 1, "shares": [{"mac": "/a", "windows": ["\\\\s\\a"]}]}, backup_existing=True)
    with open(backup, "rb") as fh:
        assert fh.read() == raw


# --- 시스템 드라이브의 Harmony용 링크 (C:\USA_DB → \\서버\USA_DB) ---

def fake_entry(name, link=None, root="C:\\", is_dir=True):
    """os.DirEntry 흉내: link='symlink'·'junction'·None(보통 폴더·파일). is_dir: 링크 자체의 디렉터리 속성
    (Windows에서 디렉터리 링크·정션은 FILE_ATTRIBUTE_DIRECTORY, 파일 링크는 없음)."""
    tag = {"junction": pms.IO_REPARSE_TAG_MOUNT_POINT, "symlink": pms.IO_REPARSE_TAG_SYMLINK}.get(link, 0)
    attributes = pms.FILE_ATTRIBUTE_DIRECTORY if is_dir else 0
    mode = stat.S_IFLNK if link == "symlink" else (stat.S_IFDIR if is_dir else stat.S_IFREG)
    return SimpleNamespace(
        name=name, path=root + name,
        is_symlink=lambda: link == "symlink",
        is_file=lambda follow_symlinks=True: link is None and not is_dir,
        stat=lambda follow_symlinks=True: SimpleNamespace(st_reparse_tag=tag, st_file_attributes=attributes, st_mode=mode),
    )


def test_local_link_shares_resolves_only_links_to_unc():
    entries = [
        fake_entry("USA_DB", "symlink"), fake_entry("Users"), fake_entry("usadata2", "symlink"),
        fake_entry("Documents and Settings", "junction"), fake_entry("dead", "symlink"),
        fake_entry("pagefile.sys", is_dir=False), fake_entry("notes.lnk", "symlink", is_dir=False),  # 파일 링크는 건너뜀
    ]
    targets = {
        "C:\\USA_DB": "\\\\Mainnas\\USA_DB",
        "C:\\usadata2": "\\\\?\\UNC\\Mainnas\\usadata2",  # 긴 경로 접두사가 남은 경우
        "C:\\Documents and Settings": "C:\\Users",  # 정션은 로컬 폴더만 가리킴 → 공유가 아님
    }
    resolved = []

    def realpath(path):
        resolved.append(path)
        if path == "C:\\dead":
            raise OSError(53, "네트워크 경로를 찾을 수 없습니다 (가짜 재현)")
        return targets[path]

    shares, problems = pms.local_link_shares(
        root="C:\\", scandir=lambda root: contextlib.nullcontext(entries), realpath=realpath,
    )
    assert [(s.unc, s.drives) for s in shares] == [
        ("\\\\Mainnas\\USA_DB", ["C:\\USA_DB"]),
        ("\\\\Mainnas\\usadata2", ["C:\\usadata2"]),
    ]
    assert sorted(resolved) == sorted(["C:\\USA_DB", "C:\\usadata2", "C:\\Documents and Settings", "C:\\dead"])
    assert len(problems) == 1 and problems[0].startswith("C:\\dead — ") and "가짜 재현" in problems[0]


def test_local_link_shares_reports_unreadable_root():
    def scandir(root):
        raise PermissionError(13, "접근 거부 (가짜 재현)")

    shares, problems = pms.local_link_shares(root="C:\\", scandir=scandir, realpath=lambda p: pytest.fail(p))
    assert shares == [] and len(problems) == 1 and "가짜 재현" in problems[0]


def test_merge_shares_keeps_letters_and_link_labels_together():
    connected = [Share("\\\\mainnas\\usa_db", ["U:"]), Share("\\\\nas\\x", ["X:"])]
    links = [Share("\\\\Mainnas\\USA_DB", ["C:\\USA_DB"]), Share("\\\\Mainnas\\usadata3", ["C:\\usadata3"])]
    merged = pms.merge_shares(connected, links)
    assert [(s.unc, s.drives) for s in merged] == [
        ("\\\\mainnas\\usa_db", ["U:", "C:\\USA_DB"]),
        ("\\\\nas\\x", ["X:"]),
        ("\\\\Mainnas\\usadata3", ["C:\\usadata3"]),
    ]
    assert connected[0].drives == ["U:"]  # 원본은 그대로


def test_find_local_config_dir_uses_harmony_link_to_nas(capsys):
    """C:\\USA_DB\\test_jn\\.yesoncheck → (폴더, 문제). 실제 위치가 UNC(NAS 링크)일 때만 씀."""
    checked = []
    files = {"c:\\usa_db\\test_jn\\.yesoncheck\\work_paths.json"}
    mirror = "C:\\USA_DB\\test_jn\\.yesoncheck"

    def is_file(path):
        checked.append(path)
        return path.casefold() in files

    real = {mirror: "\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck"}
    assert pms.find_local_config_dir("C:", is_file=is_file, realpath=real.__getitem__) == \
        ("\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck", None)
    assert checked == [mirror + "\\work_paths.json"]
    # 링크가 아니라 진짜 로컬 폴더 → 쓰지 않음 (로그에 보임)
    capsys.readouterr()
    assert pms.find_local_config_dir("C:", is_file=is_file, realpath=lambda p: p) == (None, None)
    assert f"{mirror} 는 링크가 아니라 로컬 폴더 — 쓰지 않음" in capsys.readouterr().out
    # 없으면 실제 위치는 묻지 않음
    assert pms.find_local_config_dir("D:", is_file=is_file, realpath=lambda p: pytest.fail(p)) == (None, None)


def test_find_local_config_dir_reports_realpath_error(capsys):
    def broken(path):
        raise OSError(53, "네트워크 경로를 찾을 수 없습니다 (가짜 재현)")

    folder, problem = pms.find_local_config_dir("C:", is_file=lambda p: True, realpath=broken)
    assert folder is None
    assert problem.startswith("C:\\USA_DB\\test_jn\\.yesoncheck — ") and "가짜 재현" in problem
    assert "가짜 재현" in capsys.readouterr().out


# --- 응답하지 않는 공유: 정해진 시간까지만 기다림 (S1–S3) ---

def hanging(answer=False, raises=None):
    """release될 때까지 막히는 가짜 확인 → (함수, entered, release, finished). 시험은 반드시 release.set()."""
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def func(path):
        try:
            entered.set()
            release.wait(30)
            if raises is not None:
                raise raises
            return answer
        finally:
            finished.set()

    return func, entered, release, finished


def test_probe_answers_true_false_and_raises():
    assert pms.probe(lambda p: True, "\\\\s\\x", timeout=5) is True
    assert pms.probe(lambda p: False, "\\\\s\\x", timeout=5) is False

    def broken(path):
        raise OSError("확인 실패 (가짜 재현)")

    with pytest.raises(OSError, match="가짜 재현"):
        pms.probe(broken, "\\\\s\\x", timeout=5)


def test_probe_times_out_and_abandoned_thread_is_harmless(monkeypatch, capsys):
    late_errors = []
    monkeypatch.setattr(threading, "excepthook", lambda args: late_errors.append(args))
    func, entered, release, finished = hanging(raises=OSError("늦은 오류 (가짜 재현)"))
    try:
        started = time.monotonic()
        assert pms.probe(func, "\\\\dead\\x", timeout=0.2) is None
        assert time.monotonic() - started < 2
        assert entered.is_set() and not finished.is_set()
    finally:
        release.set()
    assert finished.wait(5)
    deadline = time.monotonic() + 5
    log = ""
    while "늦은 오류 (가짜 재현)" not in log and time.monotonic() < deadline:
        time.sleep(0.01)
        log += capsys.readouterr().out
    # 버려진 확인이 나중에 실패하면 로그에만 남김 (호출한 쪽은 이미 '응답 없음' — 예외로 올리지 않음)
    assert "\\\\dead\\x" in log and "늦은 오류 (가짜 재현)" in log
    assert late_errors == []


def test_probe_on_wait_is_called_and_can_cancel():
    func, entered, release, finished = hanging()
    calls = []
    try:
        assert pms.probe(func, "\\\\dead\\x", timeout=0.45, on_wait=lambda: calls.append(1)) is None
        assert len(calls) >= 3  # 약 0.1초마다
        started = time.monotonic()
        with pytest.raises(pms.SetupCancelled):
            pms.probe(func, "\\\\dead\\x", timeout=30, on_wait=lambda: False)
        assert time.monotonic() - started < 2
    finally:
        release.set()


def test_find_config_dirs_bounded_when_a_share_never_answers(capsys):
    a, dead, c = Share("\\\\srv\\a", ["A:"]), Share("\\\\srv\\dead", ["W:"]), Share("\\\\srv\\c", ["C:"])
    found_file = "\\\\srv\\a\\test_jn\\.yesoncheck\\work_paths.json"
    release = threading.Event()

    def is_file(path):
        if path.startswith(dead.unc):
            release.wait(30)
        return path.casefold() == found_file.casefold()

    problems = []
    try:
        started = time.monotonic()
        found = pms.find_config_dirs([a, dead, c], is_file=is_file, problems=problems, timeout=0.3)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert found == ["\\\\srv\\a\\test_jn\\.yesoncheck"]
    assert elapsed < 2
    assert problems == ["W: (\\\\srv\\dead) — 0.3초 안에 응답 없음 (서버가 꺼졌거나 느림)"]
    assert "\\\\srv\\dead 응답 없음 (0.3초) — 건너뜀" in capsys.readouterr().out


def test_propose_mapping_skips_root_that_never_answers():
    dead = Share("\\\\localhost\\yc_dead", ["W:"])
    alive = dirs("\\\\203.0.113.3\\usadata2\\KOTH")
    release = threading.Event()

    def is_dir(path):
        if path.casefold().startswith(dead.unc.casefold()):
            release.wait(30)
            return False
        return alive(path)

    try:
        started = time.monotonic()
        proposal = pms.propose_mapping({"KOTH": "/usadata2/KOTH"}, [dead, S_USA2], is_dir, timeout=0.3)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 2
    assert [(p.mac_prefix, [c.unc for c in p.candidates]) for p in proposal.pairs] == [("/usadata2", [S_USA2.unc])]
    assert proposal.share_problems == [
        "W: (\\\\localhost\\yc_dead) — 공유 폴더가 0.3초 안에 응답 없음 (서버가 꺼졌거나 느림)"
    ]


def test_propose_mapping_wait_can_be_cancelled():
    func, entered, release, finished = hanging()
    try:
        with pytest.raises(pms.SetupCancelled):
            pms.propose_mapping({"A": "/usadata2/A"}, [S_USA2], func, timeout=30, on_wait=lambda: False)
    finally:
        release.set()


# --- Harmony 바로 가기 (C:\USA_DB.lnk → \\Mainnas\USA_DB; 탐색기에는 확장자 없이 'USA_DB'로 보임) (S7) ---

def shortcut_resolver(targets, calls=None):
    """가짜 resolve_shortcuts: {lnk: 대상 또는 예외}. calls에 호출마다 받은 목록을 남김."""
    def resolve(lnk_paths):
        if calls is not None:
            calls.append(list(lnk_paths))
        result = {}
        for path in lnk_paths:
            target = targets[path]
            if isinstance(target, BaseException) and not isinstance(target, pms.ShortcutError):
                raise target
            result[path] = target
        return result

    return resolve


def test_find_local_config_dir_follows_harmony_shortcut(capsys):
    lnk = "C:\\USA_DB.lnk"
    files = {lnk.casefold(), "\\\\mainnas\\usa_db\\test_jn\\.yesoncheck\\work_paths.json"}
    is_file = lambda p: p.casefold() in files  # noqa: E731 (C:\USA_DB는 폴더가 아님 — 바로 가기만 있음)
    found = pms.find_local_config_dir(
        "C:", is_file=is_file, is_dir=lambda p: False,
        resolve_shortcuts=shortcut_resolver({lnk: "\\\\Mainnas\\USA_DB"}), timeout=5,
    )
    assert found == ("\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck", None)
    assert f"{lnk} → \\\\Mainnas\\USA_DB" in capsys.readouterr().out


def test_find_local_config_dir_shortcut_to_mapped_drive_and_local(monkeypatch, capsys):
    lnk = "C:\\USA_DB.lnk"
    files = {lnk.casefold(), "\\\\mainnas\\usa_db\\test_jn\\.yesoncheck\\work_paths.json"}
    is_file = lambda p: p.casefold() in files  # noqa: E731
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: {"U:": "\\\\Mainnas\\USA_DB"}.get(drive))
    # 연결된 네트워크 드라이브 위의 대상 → UNC로 바꿔서 확인
    assert pms.find_local_config_dir("C:", is_file=is_file, is_dir=lambda p: False,
                                     resolve_shortcuts=shortcut_resolver({lnk: "U:\\"}), timeout=5) == \
        ("\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck", None)
    # 로컬 디스크의 대상 → 쓰지 않음 (로그)
    capsys.readouterr()
    assert pms.find_local_config_dir("C:", is_file=is_file, is_dir=lambda p: False,
                                     resolve_shortcuts=shortcut_resolver({lnk: "D:\\USA_DB"}), timeout=5) == (None, None)
    log = capsys.readouterr().out
    assert f"{lnk} → D:\\USA_DB" in log and "쓰지 않음" in log


def test_find_local_config_dir_shortcut_problems():
    lnk = "C:\\USA_DB.lnk"
    is_file = lambda p: p.casefold() == lnk.casefold()  # noqa: E731
    # 바로 가기 대상을 알 수 없음 (PowerShell 없음·시간 초과 등) → 문제 줄
    folder, problem = pms.find_local_config_dir(
        "C:", is_file=is_file, is_dir=lambda p: False,
        resolve_shortcuts=shortcut_resolver({lnk: pms.ShortcutError("PowerShell을 실행하지 못했습니다 (가짜 재현)")}),
        timeout=5,
    )
    assert folder is None and problem.startswith(lnk + " — ") and "가짜 재현" in problem
    # 대상 공유가 응답하지 않음 → 문제 줄
    release = threading.Event()

    def slow_is_file(path):
        if path.startswith("\\\\"):
            release.wait(30)
            return False
        return is_file(path)

    try:
        folder, problem = pms.find_local_config_dir(
            "C:", is_file=slow_is_file, is_dir=lambda p: False,
            resolve_shortcuts=shortcut_resolver({lnk: "\\\\Mainnas\\USA_DB"}), timeout=0.3,
        )
    finally:
        release.set()
    assert folder is None and "\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck" in problem and "응답 없음" in problem
    # C:\USA_DB가 폴더면(링크 포함) 바로 가기는 보지 않음
    assert pms.find_local_config_dir("C:", is_file=lambda p: False, is_dir=lambda p: True,
                                     resolve_shortcuts=lambda paths_: pytest.fail("바로 가기를 봤습니다"),
                                     timeout=5) == (None, None)


def test_local_link_shares_accepts_shortcuts_to_unc(monkeypatch):
    def shortcut_entry(name):
        return fake_entry(name, is_dir=False)  # .lnk는 보통 파일 (링크 아님)

    entries = [
        fake_entry("USA_DB_link", "symlink"),
        shortcut_entry("USA_DB.lnk"), shortcut_entry("usadata2.lnk"), shortcut_entry("usadata3.lnk"),
        shortcut_entry("Local.lnk"), shortcut_entry("Broken.lnk"), shortcut_entry("readme.txt"),
        fake_entry("Folder.lnk"),  # 이름만 .lnk인 폴더 → 바로 가기 아님
    ]
    calls = []
    resolver = shortcut_resolver({
        "C:\\USA_DB.lnk": "\\\\Mainnas\\USA_DB", "C:\\usadata2.lnk": "\\\\Mainnas\\usadata2",
        "C:\\usadata3.lnk": "\\\\mainnas\\usadata3", "C:\\Local.lnk": "C:\\Users\\Public",
        "C:\\Broken.lnk": pms.ShortcutError("바로 가기를 읽지 못함 (가짜 재현)"),
    }, calls)
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)
    shares, problems = pms.local_link_shares(
        root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
        realpath=lambda p: {"C:\\USA_DB_link": "\\\\Mainnas\\USA_DB"}[p], resolve_shortcuts=resolver,
    )
    assert calls == [["C:\\USA_DB.lnk", "C:\\usadata2.lnk", "C:\\usadata3.lnk", "C:\\Local.lnk", "C:\\Broken.lnk"]]
    assert [(s.unc, s.drives) for s in shares] == [
        ("\\\\Mainnas\\USA_DB", ["C:\\USA_DB_link", "C:\\USA_DB.lnk"]),
        ("\\\\Mainnas\\usadata2", ["C:\\usadata2.lnk"]),
        ("\\\\mainnas\\usadata3", ["C:\\usadata3.lnk"]),
    ]
    assert len(problems) == 1 and problems[0].startswith("C:\\Broken.lnk — ") and "가짜 재현" in problems[0]


def test_local_link_shares_reports_resolver_failure_and_keeps_links():
    entries = [fake_entry("USA_DB_link", "symlink"), fake_entry("USA_DB.lnk", is_dir=False)]

    def failing(lnk_paths):
        raise pms.ShortcutError("바로 가기 대상 확인이 10초 안에 끝나지 않았습니다 (가짜 재현)")

    shares, problems = pms.local_link_shares(
        root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
        realpath=lambda p: "\\\\Mainnas\\USA_DB", resolve_shortcuts=failing,
    )
    assert [(s.unc, s.drives) for s in shares] == [("\\\\Mainnas\\USA_DB", ["C:\\USA_DB_link"])]
    assert len(problems) == 1 and "C:\\USA_DB.lnk" in problems[0] and "가짜 재현" in problems[0]


def test_local_link_shares_bounds_link_realpath():
    entries = [fake_entry("dead_link", "symlink"), fake_entry("USA_DB", "symlink")]
    release = threading.Event()

    def realpath(path):
        if path.endswith("dead_link"):
            release.wait(30)
            return "\\\\dead\\x"
        return "\\\\Mainnas\\USA_DB"

    try:
        started = time.monotonic()
        shares, problems = pms.local_link_shares(root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
                                                 realpath=realpath, resolve_shortcuts=lambda p: {}, timeout=0.3)
        elapsed = time.monotonic() - started
    finally:
        release.set()
    assert elapsed < 2
    assert [(s.unc, s.drives) for s in shares] == [("\\\\Mainnas\\USA_DB", ["C:\\USA_DB"])]
    assert len(problems) == 1 and "C:\\dead_link" in problems[0] and "응답 없음" in problems[0]


def completed(stdout=b"", stderr=b"", returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_resolve_shortcuts_runs_one_hidden_powershell(monkeypatch):
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append((cmd, kwargs))
        # 오류 문구 안의 줄 구분 문자(U+2028·\x0b)로는 나누지 않음 — "\n"으로만
        out = "\ufeffOK\t\\\\Mainnas\\USA_DB\r\nERR\t손상된\u2028바로 가기\x0b(가짜 재현)\r\nOK\t\r\n"
        return completed(stdout=out.encode("utf-8"))

    monkeypatch.setattr(pms.subprocess, "run", fake_run)
    tricky = "C:\\it\u2019s 작품.lnk"  # 타이포그래피 작은따옴표 (PowerShell에서는 따옴표로 취급됨)
    result = pms.resolve_shortcuts(["C:\\USA_DB.lnk", tricky, "C:\\empty.lnk"])
    assert len(runs) == 1
    cmd, kwargs = runs[0]
    assert cmd[1:4] == ["-NoProfile", "-NonInteractive", "-Command"]
    script = cmd[4]
    assert "[Console]::OutputEncoding=[Text.Encoding]::UTF8" in script and "WScript.Shell" in script
    assert "$env:YC_LNKS" in script and "USA_DB" not in script and "작품" not in script  # 경로는 명령에 넣지 않음
    assert kwargs["env"]["YC_LNKS"] == "\n".join(["C:\\USA_DB.lnk", tricky, "C:\\empty.lnk"])
    assert "-replace" in script  # 오류 문구의 CR/LF는 공백으로
    assert kwargs["stdin"] is pms.subprocess.DEVNULL
    assert kwargs["timeout"] == pms.SHORTCUT_TIMEOUT_S and kwargs["capture_output"] is True
    assert result["C:\\USA_DB.lnk"] == "\\\\Mainnas\\USA_DB"
    assert isinstance(result[tricky], pms.ShortcutError) and "가짜 재현" in str(result[tricky])
    assert result["C:\\empty.lnk"] == ""


def test_blocked_powershell_is_a_problem_line_not_a_crash(monkeypatch):
    """AppLocker·SRP·WDAC 등으로 PowerShell 실행이 막힘(PermissionError/WinError 5, 1260 …) → ShortcutError → 문제 줄."""
    for error in (PermissionError(13, "액세스가 거부되었습니다 (가짜 재현)"),
                  OSError(1260, "그룹 정책에 의해 차단되었습니다 (가짜 재현)")):
        def blocked(cmd, error=error, **kwargs):
            raise error

        monkeypatch.setattr(pms.subprocess, "run", blocked)
        with pytest.raises(pms.ShortcutError, match="PowerShell을 실행하지 못했습니다.*가짜 재현"):
            pms.resolve_shortcuts(["C:\\USA_DB.lnk"])
        shares, problems = pms.local_link_shares(  # 기본 resolver로 — 불러오기는 계속됨
            root="C:\\", scandir=lambda root: contextlib.nullcontext([fake_entry("USA_DB.lnk", is_dir=False)]),
            realpath=lambda p: pytest.fail(p),
        )
        assert shares == [] and len(problems) == 1 and "가짜 재현" in problems[0]


def test_shortcut_unc_rejects_device_and_long_path_prefixes():
    for target in ("\\\\?\\C:\\USA_DB", "\\\\?\\UNC\\Mainnas\\USA_DB", "\\\\.\\pipe\\x"):
        assert pms._shortcut_unc(target) is None, target
    assert pms._shortcut_unc("\\\\Mainnas\\USA_DB") == "\\\\Mainnas\\USA_DB"


def test_resolve_shortcuts_errors(monkeypatch):
    def missing(cmd, **kwargs):
        raise FileNotFoundError(2, "지정된 파일을 찾을 수 없습니다 (가짜 재현)")

    monkeypatch.setattr(pms.subprocess, "run", missing)
    with pytest.raises(pms.ShortcutError, match="PowerShell을 실행하지 못했습니다"):
        pms.resolve_shortcuts(["C:\\USA_DB.lnk"])

    def slow(cmd, **kwargs):
        raise pms.subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(pms.subprocess, "run", slow)
    with pytest.raises(pms.ShortcutError, match="초 안에 끝나지 않았습니다"):
        pms.resolve_shortcuts(["C:\\USA_DB.lnk"])

    monkeypatch.setattr(pms.subprocess, "run", lambda cmd, **kw: completed(stderr="오류 (가짜 재현)".encode(), returncode=1))
    with pytest.raises(pms.ShortcutError, match="가짜 재현"):
        pms.resolve_shortcuts(["C:\\USA_DB.lnk"])

    monkeypatch.setattr(pms.subprocess, "run", lambda cmd, **kw: completed(stdout=b"OK\t\\\\a\\b\r\n"))
    with pytest.raises(pms.ShortcutError, match="줄"):
        pms.resolve_shortcuts(["C:\\a.lnk", "C:\\b.lnk"])  # 출력 줄 수가 맞지 않음

    assert pms.resolve_shortcuts([]) == {}


# --- 바로 가기 대상 캐시 (lnk 경로, 수정 시각) — 백그라운드 불러오기와 GUI 스레드가 같은 결과를 씀 ---

def test_shortcut_targets_are_cached_per_path_and_mtime(monkeypatch):
    lnk = "C:\\USA_DB.lnk"
    mtimes = {lnk: 1000}
    monkeypatch.setattr(pms, "_default_mtime", lambda path: mtimes[path])
    calls = []
    resolver = shortcut_resolver({lnk: "\\\\Mainnas\\USA_DB"}, calls)
    entries = [fake_entry("USA_DB.lnk", is_dir=False)]
    files = {lnk.casefold(), "\\\\mainnas\\usa_db\\test_jn\\.yesoncheck\\work_paths.json"}

    def scan():
        return pms.local_link_shares(root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
                                     realpath=lambda p: pytest.fail(p), resolve_shortcuts=resolver)

    def mirror():
        return pms.find_local_config_dir("C:", is_file=lambda p: p.casefold() in files, is_dir=lambda p: False,
                                         resolve_shortcuts=resolver, timeout=5)

    assert [s.unc for s in scan()[0]] == ["\\\\Mainnas\\USA_DB"]
    assert [s.unc for s in scan()[0]] == ["\\\\Mainnas\\USA_DB"]  # 두 번째 호출 (GUI 스레드의 자동 설정 등)
    assert mirror() == ("\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck", None)  # Harmony 경로도 같은 캐시
    assert calls == [[lnk]]
    mtimes[lnk] = 2000  # 바로 가기를 바꿈 → 다시 읽음
    assert mirror()[0] == "\\\\Mainnas\\USA_DB\\test_jn\\.yesoncheck"
    assert calls == [[lnk], [lnk]]


def test_shortcut_errors_are_not_cached(monkeypatch):
    lnk = "C:\\USA_DB.lnk"
    monkeypatch.setattr(pms, "_default_mtime", lambda path: 1000)
    answers = [pms.ShortcutError("바로 가기를 읽지 못함 (가짜 재현)"), "\\\\Mainnas\\USA_DB"]
    calls = []

    def resolver(paths_):
        calls.append(list(paths_))
        return {lnk: answers.pop(0)}

    entries = [fake_entry("USA_DB.lnk", is_dir=False)]

    def scan():
        return pms.local_link_shares(root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
                                     realpath=lambda p: pytest.fail(p), resolve_shortcuts=resolver)

    shares, problems = scan()
    assert shares == [] and "가짜 재현" in problems[0]
    shares, problems = scan()  # 다음번에는 다시 읽어 봄
    assert [s.unc for s in shares] == ["\\\\Mainnas\\USA_DB"] and problems == []
    assert len(calls) == 2

    def failing(paths_):
        calls.append(list(paths_))
        raise pms.ShortcutError("PowerShell을 실행하지 못했습니다 (가짜 재현)")

    pms.clear_shortcut_cache()
    for _ in range(2):  # 호출 전체가 실패해도 캐시하지 않음
        assert pms.local_link_shares(root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
                                     realpath=lambda p: pytest.fail(p), resolve_shortcuts=failing)[0] == []
    assert len(calls) == 4


# --- 바로 가기 짐작이 틀렸을 때도 다음 로그로 알 수 있게 (항목 종류) ---

def lstat_of(kinds):
    """가짜 lstat: {경로: 'dir'·'file'·'dirlink'·'filelink'·'junction'} (없으면 FileNotFoundError)."""
    def fake(path):
        kind = kinds.get(path)
        if kind is None:
            raise FileNotFoundError(2, "없음", path)
        mode = {"dir": stat.S_IFDIR, "file": stat.S_IFREG, "junction": stat.S_IFDIR}.get(kind, stat.S_IFLNK)
        tag = {"dirlink": pms.IO_REPARSE_TAG_SYMLINK, "filelink": pms.IO_REPARSE_TAG_SYMLINK,
               "junction": pms.IO_REPARSE_TAG_MOUNT_POINT}.get(kind, 0)
        attributes = pms.FILE_ATTRIBUTE_DIRECTORY if kind in ("dir", "dirlink", "junction") else 0
        return SimpleNamespace(st_mode=mode, st_reparse_tag=tag, st_file_attributes=attributes)
    return fake


def test_find_local_config_dir_logs_what_c_usa_db_is(monkeypatch, capsys):
    resolver = lambda paths_: pytest.fail("바로 가기를 읽었습니다")  # noqa: E731
    # 진짜 폴더 (링크 아님) → 그 아래에 설정 폴더 없음
    monkeypatch.setattr(pms, "_default_lstat", lstat_of({"C:\\USA_DB": "dir"}))
    assert pms.find_local_config_dir("C:", is_file=lambda p: False, is_dir=lambda p: True,
                                     resolve_shortcuts=resolver, timeout=5) == (None, None)
    assert "C:\\USA_DB 는 폴더(링크 아님)" in capsys.readouterr().out
    # /D 없이 만든 심볼릭 링크(파일 링크) → 따라가지 않음, 바로 가기도 없음
    monkeypatch.setattr(pms, "_default_lstat", lstat_of({"C:\\USA_DB": "filelink"}))
    assert pms.find_local_config_dir("C:", is_file=lambda p: False, is_dir=lambda p: False,
                                     resolve_shortcuts=resolver, timeout=5) == (None, None)
    log = capsys.readouterr().out
    assert "C:\\USA_DB 는 파일 링크(/D 없는 심볼릭 링크) — 따라가지 않음" in log and "C:\\USA_DB.lnk 없음" in log
    # 아무것도 없음
    monkeypatch.setattr(pms, "_default_lstat", lstat_of({}))
    assert pms.find_local_config_dir("C:", is_file=lambda p: False, is_dir=lambda p: False,
                                     resolve_shortcuts=resolver, timeout=5) == (None, None)
    log = capsys.readouterr().out
    assert "C:\\USA_DB 없음" in log and "C:\\USA_DB.lnk 없음" in log


def test_link_scan_summary_names_harmony_entry_kinds(monkeypatch, capsys):
    monkeypatch.setattr(paths, "_remote_name_of_drive", lambda drive: None)  # D:는 로컬 디스크
    entries = [
        fake_entry("USA_DB.lnk", is_dir=False), fake_entry("usadata2"), fake_entry("usadata3", "symlink"),
        fake_entry("Users"), fake_entry("Windows"),
    ]
    pms.local_link_shares(root="C:\\", scandir=lambda root: contextlib.nullcontext(entries),
                          realpath=lambda p: "D:\\x", resolve_shortcuts=lambda paths_: {p: "D:\\y" for p in paths_})
    log = capsys.readouterr().out
    summary = [line for line in log.splitlines() if "Harmony 항목" in line]
    assert len(summary) == 1
    line = summary[0]
    assert "USA_DB.lnk=바로 가기(.lnk)" in line and "usadata2=폴더(링크 아님)" in line and "usadata3=디렉터리 링크" in line
    assert "Users" not in line


# --- 늦은 오류: 시간 안에 온 오류는 올리고, 호출한 쪽이 포기한 뒤의 오류는 로그에 (on_wait 예외 포함) ---

def test_probe_logs_late_error_after_on_wait_raises(capsys):
    func, entered, release, finished = hanging(raises=OSError("늦은 오류 (가짜 재현)"))

    def broken_on_wait():
        raise RuntimeError("on_wait 실패 (가짜 재현)")

    try:
        with pytest.raises(RuntimeError, match="on_wait 실패"):
            pms.probe(func, "\\\\dead\\y", timeout=30, on_wait=broken_on_wait)
    finally:
        release.set()
    assert finished.wait(5)
    deadline = time.monotonic() + 5
    log = ""
    while "늦은 오류 (가짜 재현)" not in log and time.monotonic() < deadline:
        time.sleep(0.01)
        log += capsys.readouterr().out
    assert "\\\\dead\\y" in log and "늦은 오류 (가짜 재현)" in log


def test_probe_error_in_time_is_raised_not_logged_as_late(capsys):
    def broken(path):
        raise OSError("바로 난 오류 (가짜 재현)")

    for _ in range(50):
        with pytest.raises(OSError, match="바로 난 오류"):
            pms.probe(broken, "\\\\s\\x", timeout=5)
    time.sleep(0.05)
    assert "늦게 난 오류" not in capsys.readouterr().out


def test_find_config_dirs_late_suffix_only_for_shares_that_missed_the_deadline(capsys):
    a, dead = Share("\\\\srv\\a", ["A:"]), Share("\\\\srv\\dead", ["W:"])
    release, late_done = threading.Event(), threading.Event()

    def is_file(path):
        if path.startswith(dead.unc):
            release.wait(30)
            late_done.set()
        return False

    problems = []
    try:
        assert pms.find_config_dirs([a, dead], is_file=is_file, problems=problems, timeout=0.3) == []
    finally:
        release.set()
    assert late_done.wait(5)
    deadline = time.monotonic() + 5
    log = capsys.readouterr().out
    while "\\\\srv\\dead 확인" not in log and time.monotonic() < deadline:
        time.sleep(0.01)
        log += capsys.readouterr().out
    lines = log.splitlines()
    assert any("\\\\srv\\a 확인" in line and "없음" in line and "늦게" not in line for line in lines)
    assert any("\\\\srv\\dead 확인" in line and "늦게 응답 — 이미 건너뜀" in line for line in lines)
    assert len(problems) == 1
