import json
import os
import threading
import time
import unicodedata

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
    assert elapsed < 1.2, f"{elapsed:.2f}초 (차례로 하면 1.8초, 동시에 하면 약 0.6초)"


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
