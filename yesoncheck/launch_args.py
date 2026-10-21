"""앱을 켤 때 받은 인자 읽기 (Qt 없음).

- `--update-result TOKEN`: 업데이트 도우미가 다시 켠 앱 — 업데이트 기록(update_install.Pending)의 토큰과 같을 때만 지난
  업데이트의 결과를 판정하고(update_install.startup_result), 업데이트 중이어도 켜진다(app.launch).
- `--smoke-test DIR`: 실행 시험 (smoke_test.run).
- 나머지는 열 파일 — 경로 하나가 인자 하나 그대로 (공백·한글·작은따옴표·`#`도 나누거나 벗기지 않음).

값이 없거나 두 번 온 옵션은 ValueError (도우미·빌드 도구만 넘기는 인자 — 틀리면 그대로 드러나게).
"""

from dataclasses import dataclass

UPDATE_RESULT_OPTION = "--update-result"
SMOKE_TEST_OPTION = "--smoke-test"
_OPTIONS = (UPDATE_RESULT_OPTION, SMOKE_TEST_OPTION)


@dataclass(frozen=True)
class LaunchArgs:
    files: list[str]
    update_token: str | None  # --update-result의 값 (도우미가 켠 앱만)
    smoke_test: str | None  # --smoke-test의 작업 폴더


def parse(argv: list[str]) -> LaunchArgs:
    """argv: sys.argv 그대로 (0번 — 실행 파일·스크립트 — 은 건너뜀)."""
    files = []
    values = {}
    rest = list(argv[1:])
    i = 0
    while i < len(rest):
        arg = rest[i]
        if arg not in _OPTIONS:
            files.append(arg)
            i += 1
            continue
        if i + 1 >= len(rest) or not rest[i + 1]:
            raise ValueError(f"{arg} 뒤에 값이 없습니다: {argv!r}")
        if arg in values:
            raise ValueError(f"{arg}가 두 번 왔습니다: {argv!r}")
        values[arg] = rest[i + 1]
        i += 2
    return LaunchArgs(files=files, update_token=values.get(UPDATE_RESULT_OPTION),
                      smoke_test=values.get(SMOKE_TEST_OPTION))
