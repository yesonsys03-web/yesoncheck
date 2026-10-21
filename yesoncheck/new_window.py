"""새 YesonCheck 창 띄우기 (Qt 없음) — 한 프로세스에 창 하나이므로 창을 더 열면 앱(프로세스)을 하나 더 띄운다.

`spawn(files)`: 파일마다 새 앱 하나, 목록이 비었으면 파일 없는 새 앱 하나. 파일은 새 앱의 명령 줄 인자(launch_args가
읽음)로 넘기며 셸을 쓰지 않으므로 경로 하나가 인자 하나 그대로 닿는다(공백·한글·작은따옴표·`#`도 나누거나 벗기지 않음).

- Mac 빌드 앱: `/usr/bin/open -n <자기 번들> [--args 파일]` — `-n`이 이미 떠 있는 같은 앱 대신 새 인스턴스를 띄운다.
  `open`은 LaunchServices가 앱을 띄운 뒤 돌아오므로 끝나기를 기다린다(OPEN_TIMEOUT_S). 0이 아니거나 시간이 지나면
  RuntimeError(명령과 `open`의 출력).
- 소스 실행(어느 플랫폼이든)·Windows 빌드 앱: 앱 프로세스를 바로 띄우고 기다리지 않는다 — 그 프로세스가 새 창이다.
  소스 실행은 번들 위치를 묻지 않는다(update_install.running_app_location은 소스 실행에서 UpdateError).

Popen 자체의 실패(OSError)와 위의 RuntimeError는 감싸거나 삼키지 않고 그대로 올린다. 파일이 여럿일 때 한 파일이 실패하면
거기서 멈춘다 — 앞 파일의 창은 이미 떴고 뒤 파일은 띄우지 않는다.
"""

import os
import subprocess
import sys

from yesoncheck import update_install

OPEN_TIMEOUT_S = 30  # Mac `open`이 돌아오기를 기다리는 한도 (LaunchServices가 앱을 띄운 뒤 곧 돌아옴)
MAC_OPEN = "/usr/bin/open"
APP_MODULE = "yesoncheck.app"  # 소스 실행의 진입점: python -m yesoncheck.app [파일]


def spawn(files: list[str], platform: str = sys.platform, popen=subprocess.Popen) -> None:
    """새 앱을 파일마다 하나(빈 목록이면 파일 없이 하나) 띄움. platform·popen은 시험에서 바꿔 넣음."""
    for file in files or [None]:
        _spawn_one(file, platform, popen)


def _spawn_one(file: str | None, platform: str, popen) -> None:
    file_args = [] if file is None else [file]
    if not getattr(sys, "frozen", False):
        popen([sys.executable, "-m", APP_MODULE, *file_args], stdin=subprocess.DEVNULL)
    elif platform == "darwin":
        _open_new_instance(update_install.running_app_location(), file, popen)
    elif platform == "win32":
        # 같은 실행 파일을 띄우므로 새 앱으로 켜지게 PyInstaller 환경을 지움 (update_install._helper_env와 같은 이유)
        env = {**os.environ, update_install.PYINSTALLER_RESET_ENV: "1"}
        popen([sys.executable, *file_args], env=env, stdin=subprocess.DEVNULL)
    else:
        raise RuntimeError(f"이 플랫폼({platform})의 빌드 앱에서는 새 창을 띄울 수 없습니다")


def _open_new_instance(bundle: str, file: str | None, popen) -> None:
    """Mac: `open -n <번들> [--args 파일]`을 띄워 끝나기를 기다림. 0이 아니거나 시간이 지나면 RuntimeError."""
    args = [MAC_OPEN, "-n", bundle]
    if file is not None:
        args += ["--args", file]
    proc = popen(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # stdout+stderr를 한 줄기로
        encoding="utf-8",
        errors="replace",
    )
    try:
        output, _ = proc.communicate(timeout=OPEN_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        output, _ = proc.communicate()
        raise RuntimeError(_open_error(f"open이 {OPEN_TIMEOUT_S}초 안에 끝나지 않아 끝냈습니다", args, output)) from exc
    if proc.returncode != 0:
        raise RuntimeError(_open_error(f"open이 종료 코드 {proc.returncode}로 끝났습니다", args, output))


def _open_error(reason: str, args: list[str], output: str | None) -> str:
    return f"새 YesonCheck 창을 띄우지 못했습니다 — {reason}.\n명령: {' '.join(args)}\n출력: {(output or '').strip() or '(없음)'}"
