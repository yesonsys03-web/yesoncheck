import os
import unicodedata

import pytest

from yesoncheck import path_map_setup as pms
from yesoncheck import paths
from yesoncheck.path_map_setup import Candidate, PairChoice, Proposal, Share


def dirs(*items):
    """주어진 폴더만 열리는 가짜 is_dir (대소문자 무시)."""
    keys = {item.casefold() for item in items}
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
        return False

    pms.propose_mapping({"A": "/usadata2/X/A", "B": "/usadata2/X/A"}, [S_USA2], is_dir)
    assert len(calls) == len(set(calls))


def test_progress_cancel():
    with pytest.raises(pms.SetupCancelled):
        pms.propose_mapping({"A": "/usadata2/A"}, [S_USA2], dirs(), progress=lambda done, total: False)


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
