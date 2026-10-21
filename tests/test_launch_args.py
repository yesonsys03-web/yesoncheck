"""yesoncheck/launch_args.py 시험: 앱을 켤 때 받은 인자 (`--update-result TOKEN`, `--smoke-test DIR`, 나머지는 파일)."""

import pytest

from yesoncheck import launch_args

# 더블클릭·연결 프로그램으로 넘어오는 경로 — 공백·한글·작은따옴표·`#` (Review Focus 1)
ODD_PATHS = [
    "/Volumes/USA_DB/FL_901 컷/장면 #3 (최종)'s.mov",
    "C:\\Users\\studio01\\동영상\\A B #1 'x'.mp4",
]


def test_parse_files_token_smoke():
    assert launch_args.parse(["yesoncheck"]) == launch_args.LaunchArgs(files=[], update_token=None, smoke_test=None)
    # 0번(실행 파일)은 건너뛰고, 경로는 한 인자 그대로 (나누거나 따옴표를 벗기지 않음)
    args = launch_args.parse(["/A/YesonCheck_Autocut", *ODD_PATHS])
    assert args.files == ODD_PATHS and args.update_token is None and args.smoke_test is None
    # 도우미가 다시 켠 앱: 토큰은 파일이 아님 (앞·뒤 어디에 있어도)
    args = launch_args.parse(["yc", "--update-result", "0123abcd4567ef89", ODD_PATHS[0]])
    assert args.update_token == "0123abcd4567ef89" and args.files == [ODD_PATHS[0]]
    args = launch_args.parse(["yc", ODD_PATHS[1], "--update-result", "ff00"])
    assert args.update_token == "ff00" and args.files == [ODD_PATHS[1]]
    # 실행 시험
    args = launch_args.parse(["yc", "--smoke-test", "/tmp/작업 폴더 #1"])
    assert args.smoke_test == "/tmp/작업 폴더 #1" and args.files == [] and args.update_token is None


@pytest.mark.parametrize("argv, match", [
    (["yc", "--update-result"], "--update-result 뒤에 값이 없습니다"),
    (["yc", "--smoke-test"], "--smoke-test 뒤에 값이 없습니다"),
    (["yc", "--update-result", ""], "--update-result 뒤에 값이 없습니다"),
    (["yc", "--update-result", "a", "--update-result", "b"], "--update-result가 두 번"),
])
def test_parse_rejects_missing_or_repeated_values(argv, match):
    with pytest.raises(ValueError, match=match):
        launch_args.parse(argv)
