"""재생 줄을 플레이어에 잇는 얇은 층 — `PlayerTransportMixin` (`VideoPlayerBase`의 부모, 2026-11-16 UI 개편).

재생 줄(`transport_bar.TransportBar`)은 플레이어를 모르고, 재생·탐색 코드(`player_playback`)는 재생 줄을 모른다.
여기서 둘을 잇는다:

- **옛 이름 잇기**(`_init_transport_bar`): 재생 코드가 표시를 고칠 때 쓰는 이름 — `filenameLabel`·`timeLabel`·
  `volumeSlider`·`loopCheckBox`·`wipeCheckBox`·`wipeXButton`·`wipeYButton`은 재생 줄의 위젯 그 자체, `labelFrameCount`·`labelTotalFrames`·`labelPlaybackFPS`·
  `playPauseButton`은 받은 글자를 재생 줄에 넘기는 어댑터(`TextSlot`·`PlayStateSlot` — `text()`는 받은 글 그대로라
  그 글자를 보는 코드·시험이 그대로 돈다).
- **단추 = 지금의 처리기**: 재생/일시정지 `toggle_play_pause`, 한 장 앞뒤 `next_frame`·`prev_frame`(← → 키와 같음),
  반복 `toggle_loop_play`, 볼륨 `setVolume`. 새로 생긴 조작 셋만 여기 있다 — 처음·끝·프레임 번호로 가기.
- **선택 재생 끝내기**: 예전 Stop 단추는 '멈추고 처음으로'이면서 선택 재생(고른 영상 이어 재생)을 끝내는 유일한 길이었다.
  Stop 단추가 없어져 그 일은 사이드바 맨 아래의 `endPlaylistButton`이 맡는다(선택 재생 중에만 보임 — `stop_video` 그대로).
  '처음' 단추는 선택 재생 중이면 지금 영상의 처음으로만 가고 선택 재생을 유지한다(사용자 결정 2026-11-16).
  단추의 보임은 `is_playlist_playing`을 property로 두어 맞춘다 — 그 값을 고치는 곳이 세 모듈에 열 곳 남짓이라
  곳마다 부르지 않고 값이 바뀌는 그 자리에서.
"""

from PyQt5 import sip
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QPushButton

from yesoncheck import ui_text
from yesoncheck.transport_bar import PlayStateSlot, TextSlot, TransportBar


class PlayerTransportMixin:
    def _init_transport_bar(self):
        """재생 줄과 '끝내기' 단추를 만들고 옛 이름·처리기에 잇는다 (initUI — 그 이름을 쓰는 코드보다 먼저)."""
        bar = TransportBar()
        self.transportBar = bar
        self.filenameLabel = bar.filenameLabel
        self.timeLabel = bar.timeLabel
        self.volumeSlider = bar.volumeSlider
        self.loopCheckBox = bar.loopButton  # 옛 이름 (예전에는 체크 상자) — setChecked·isChecked는 같음
        self.labelFrameCount = TextSlot("", bar.show_current)
        self.labelTotalFrames = TextSlot("", bar.show_total)
        self.labelPlaybackFPS = TextSlot("", bar.show_fps)
        self.labelPlaybackFPS.setText("재생: 대기")
        self.playPauseButton = PlayStateSlot(bar.show_playing)

        bar.playButton.clicked.connect(self.toggle_play_pause)
        bar.prevButton.clicked.connect(self.prev_frame)
        bar.nextButton.clicked.connect(self.next_frame)
        bar.firstButton.clicked.connect(self.go_to_first)
        bar.lastButton.clicked.connect(self.go_to_last)
        bar.loopButton.toggled.connect(lambda on: self.toggle_loop_play(Qt.Checked if on else Qt.Unchecked))
        # 와이프: 예전 체크 상자(Enable Wipe Effect)와 X/Y-Axis Wipe 단추의 이름을 재생 줄의 토글에 이음 —
        # isChecked·setChecked·setEnabled는 같고 처리기도 그대로 (X·Y는 와이프를 켜야 켜짐: toggle_wipe_effect)
        self.wipeCheckBox = bar.wipeButton
        self.wipeXButton = bar.wipeXButton
        self.wipeYButton = bar.wipeYButton
        bar.wipeButton.toggled.connect(lambda on: self.toggle_wipe_effect(Qt.Checked if on else Qt.Unchecked))
        bar.wipeXButton.toggled.connect(self.toggle_wipe_x)
        bar.wipeYButton.toggled.connect(self.toggle_wipe_y)
        # 볼륨: 슬라이더를 실제 볼륨(재생기에 줄 값 — 처음 player_base.START_VOLUME 50)에서 시작. 예전에는 슬라이더만 50에서
        # 시작하고 재생기는 100이라 슬라이더를 건드릴 때까지 표시와 소리가 달랐음. 그 뒤로는 setVolume이 볼륨이 바뀔 때마다
        # 이 슬라이더를 맞춤(오버레이에서 바꿔도)
        bar.volumeSlider.setValue(self.media_volume())
        bar.volumeSlider.valueChanged.connect(self.setVolume)
        bar.frameField.frameEntered.connect(self.go_to_frame_number)
        bar.frameField.editingEnded.connect(self.setFocus)  # 창이 포커스를 되찾아 Space·← → 같은 단축키가 다시 먹게

        self.endPlaylistButton = QPushButton(ui_text.text("playlist.end"))
        self.endPlaylistButton.setObjectName("playlistEndButton")  # 색·모양은 두 테마 시트의 #playlistEndButton
        self.endPlaylistButton.setToolTip(ui_text.text("playlist.end.tip"))
        self.endPlaylistButton.setFocusPolicy(Qt.NoFocus)
        self.endPlaylistButton.clicked.connect(self.end_playlist)
        self.endPlaylistButton.hide()  # 선택 재생 중에만 보임 (is_playlist_playing의 setter)

    # --- 선택 재생 상태 ↔ '끝내기' 단추 ---
    @property
    def is_playlist_playing(self):
        return self._is_playlist_playing

    @is_playlist_playing.setter
    def is_playlist_playing(self, playing):
        self._is_playlist_playing = playing
        button = getattr(self, "endPlaylistButton", None)  # 창을 만드는 중(__init__)에는 아직 없음
        if button is not None and not sip.isdeleted(button):
            button.setVisible(bool(playing))

    def end_playlist(self):
        """선택 재생 끝내기 — 예전 Stop 단추가 하던 일 그대로(멈춤 + 1번 프레임 + 선택 재생 끝 + 목록 강조 되돌림)."""
        self._slider_to_frame(0)
        self.stop_video()

    # --- 처음 · 끝 · 프레임 번호 ---
    def _slider_to_frame(self, index):
        """이동 직전에 슬라이더를 신호 없이 그 프레임(0부터)의 자리로 — 마지막 프레임이면 오른쪽 끝, 아니면 끝이 아닌 자리.
        `update_position_info`는 그 순간의 슬라이더가 오른쪽 끝이면 Current를 전체 장수로(시간도 끝으로) 적으므로, 슬라이더가
        끝에 남은 채 다른 프레임으로 가면 영상은 그 프레임인데 번호는 마지막 장으로 보인다('끝' 다음 '처음'·'끝' 다음 번호 입력)
        — `open_file`이 슬라이더 범위를 정할 때 하는 것과 같은 조치. 영상이 없으면 아무것도 안 함."""
        total = self._transport_total_frames()
        if total < 1:
            return
        maximum = self.positionScroll.maximum()
        if index >= total - 1:
            value = maximum
        else:
            value = min(round(index / (total - 1) * maximum), max(0, maximum - 1))
        self.positionScroll.blockSignals(True)
        self.positionScroll.setValue(value)
        self.positionScroll.blockSignals(False)

    def go_to_first(self):
        """'처음' 단추·Home: 멈추고 1번 프레임으로(예전 Stop). 선택 재생 중에는 지금 영상의 처음으로만 — 선택 재생은 유지."""
        self._slider_to_frame(0)
        if self.is_playlist_playing and self.cap_a:
            self.pause_video()
            self.seek_to_frame(1)
            return
        self.stop_video()

    def go_to_last(self):
        """'끝' 단추·End: 재생 중이면 멈추고 마지막 프레임으로 — 슬라이더 오른쪽 끝을 누른 것과 같은 이동(`_precise_seek`)."""
        total = self._transport_total_frames()
        if total < 1:
            return
        if self.timer.isActive():
            self.pause_video()
        self._slider_to_frame(total - 1)
        self._precise_seek(total - 1, total)

    def go_to_frame_number(self, number):
        """프레임 칸에 친 번호(1부터)로: 범위 밖은 가장 가까운 끝으로. 슬라이더의 그 자리를 누른 것과 같은 이동
        (`_precise_seek` — 재생 중이면 재생은 이어짐)."""
        total = self._transport_total_frames()
        if total < 1:
            return
        import cv2  # 지연 import — _transport_total_frames와 같은 까닭

        target = max(1, min(int(number), total)) - 1
        self._slider_to_frame(target)
        self._precise_seek(target, total)
        if target < total - 1 and int(self.cap_a.get(cv2.CAP_PROP_POS_FRAMES)) - 1 != target:
            # _precise_seek가 아무것도 안 했음: 끝에서 셋째 장 안(목표 ≥ 전체 − 3)의 이동 _seek_conservative는 '목표 == 캡처가
            # 다음에 읽을 자리'(= 지금 프레임의 바로 다음 장)면 이미 거기 있다고 보고 돌아옴 — 직접 이동으로 맞춤
            # (슬라이더를 놓을 때 sync_audio_on_release가 같은 경우에 하는 보정; 마지막 프레임 길은 그대로 둠)
            self._seek_direct(target, total)

    def _transport_total_frames(self):
        """열린 영상 A의 전체 장수, 없으면 0."""
        if not self.cap_a:
            return 0
        import cv2  # 지연 import — player_base는 cv2를 모듈 수준에서 부르지 않음

        return int(self.cap_a.get(cv2.CAP_PROP_FRAME_COUNT))
