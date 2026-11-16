"""사이드바의 작품 묶음(작품·시즌·job 콤보)을 보일지 — 이 PC에서 작품을 읽어 온 적이 있는지의 기억 (Qt 없음).

작품 고르기는 사내 전용 기능이라 밖에서 설치한 PC에는 보이지 않게 하되, 켤 때마다 목록이 밀리거나 콤보가 떴다
사라지지 않게: **작품을 한 번이라도 읽어 온 PC에서는 늘 보임**(불러오는 동안·NAS가 끊겨 읽지 못한 때에도).
그 '읽어 온 적이 있음'을 이 PC의 prefs.json에 값 하나로 적는다 — 공유 설정(NAS)에는 넣지 않음(PC마다 다른 사실).
"""

from yesoncheck import hover_strip, mac_prefs

PREF_KEY = "work_picker_seen"


def read_seen(path=None):
    """이 PC에서 작품을 읽어 온 적이 있는지 (키가 없으면 False).
    불리언이 아니면 ValueError, 깨진 파일은 UserFileError 그대로 — 값을 지어내지 않음(부른 쪽이 정함)."""
    value = mac_prefs.read_prefs(path or hover_strip.prefs_path()).get(PREF_KEY, False)
    if not isinstance(value, bool):
        raise ValueError(f"{PREF_KEY}는 true 또는 false여야 합니다: {value!r}")
    return value


def remember_seen(path=None):
    """작품을 읽어 왔음을 적음 (그 키만 — 잠금 안에서 다시 읽고, 다른 키는 그대로)."""
    mac_prefs.update_pref(PREF_KEY, True, path or hover_strip.prefs_path())
