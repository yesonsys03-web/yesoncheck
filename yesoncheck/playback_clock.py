# -*- coding: utf-8 -*-
"""재생 틱의 시각표 — 정수 ms 타이머로 소수 프레임 간격(24fps = 41.67ms)을 맞춤. Qt 없음, 시각은 부른 쪽이 넘김.

간격을 고정하면 소수가 쌓임: int(1000/fps) = 41ms를 Qt 기본 타이머가 40ms로 돌려 24fps가 실제 25.00fps(4% 빠름 — 이 Mac 실측, 사용자 보고 2026-11-05).
그래서 k번째 틱의 시각을 시작 + k/fps로 정해 두고 틱마다 다음 시각까지 남은 시간만 기다린다 (24fps면 42·41·42…ms, 프레임 처리 시간은 자동으로 빠짐).

시계는 틱 시각만 정하고 프레임을 건너뛰게 하지 않음 — 틱마다 다음 프레임을 한 장 읽는 재생 코드가 그대로이므로 프레임 번호·장 수와 상관없음.
늦으면 바로 다음 틱으로 따라잡되, 프레임 BEHIND_LIMIT_FRAMES장 넘게 밀리면(탐색·창 끌기·NAS 끊김) 시각표를 지금으로 옮김 — 고집하면 밀린 프레임을 1ms 간격으로
몰아 보여 화면이 순간 빨라짐(0.25초 한도에서 12ms 간격 5~7장 실측 — 검토에서 고침). 옮길 때도 쉬지 않음: 처리가 늘 늦는 기계가 더 느려지지 않게.
"""

BEHIND_LIMIT_FRAMES = 2
MIN_DELAY_MS = 1  # 0(zero timer)은 Windows에서 입력 이벤트와 어떻게 섞이는지 재 보지 않음 — 처리가 늘 늦을 때 1~2% 느려지는 값(이 Mac)을 감수


class PlaybackClock:
    def __init__(self, fps, now):
        if not fps > 0:  # NaN도 여기서 걸림
            raise ValueError(f"프레임 속도가 잘못됨: {fps}")
        self._fps = fps
        self._start = now
        self._ticks_done = 0

    def first_delay_ms(self):
        """재생을 누른 뒤 첫 틱까지."""
        return max(MIN_DELAY_MS, round(1000 / self._fps))

    def next_delay_ms(self, now):
        """틱 하나를 마친 뒤: 다음 틱까지 기다릴 ms."""
        self._ticks_done += 1
        due = self._start + (self._ticks_done + 1) / self._fps
        if now - due > BEHIND_LIMIT_FRAMES / self._fps:
            self._start = now - (self._ticks_done + 1) / self._fps
            return MIN_DELAY_MS
        return max(MIN_DELAY_MS, round((due - now) * 1000))
