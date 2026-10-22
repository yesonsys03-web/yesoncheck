"""선택 재생 믹스인 (SidebarPlaylistMixin): 사이드바에서 고른 영상들을 차례로 열어 재생하는 'Selected Play' —
재생목록 만들기·시작, 차례마다 열기(디스크에 없는 영상 건너뛰기), 현재 항목 강조 색 되돌리기, 영상이 끝나면 다음, 끝 처리.

PlayerSidebarMixin의 부모 클래스로 붙음 — `class PlayerSidebarMixin(SidebarBookmarksMixin, SidebarPlaylistMixin)`. 그래서
VideoPlayer의 MRO에서 PlayerSidebarMixin 뒤(PlayerPlaybackMixin 앞)에 오고, 이 메서드들의 이름은 다른 믹스인·
VideoPlayerBase와 겹치지 않으므로 어느 것이 불리는지는 예전과 같음. 상태(`self.playlist`·`self.current_playlist_index`·
`self.is_playlist_playing` 등)는 예전처럼 VideoPlayerBase.__init__이 만들고, 이 메서드들을 부르는 VideoPlayerBase의 버튼 연결과
재생 믹스인(`play_selected_files`·`play_next_in_playlist`·`reset_sidebar_colors`)도 `self.`로 부르므로 그대로 닿음.

player_sidebar를 모듈 수준에서 import하지 말 것 — player_sidebar가 상속하려고 이 모듈을 불러오므로 순환이 됨.
"""

import os
import traceback

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QMessageBox

from yesoncheck import paths, video_list


class SidebarPlaylistMixin:
    """VideoPlayer의 선택 재생(Play Selected) — 재생목록 시작·차례대로 열기·없는 영상 건너뛰기·강조 색·끝 처리."""

    def play_selected_files(self):
        selected_items = self.sidebar.selectedItems()
        if selected_items:
            selected_items.sort(key=lambda x: self.sidebar.row(x))
            self.playlist = [item.toolTip() for item in selected_items]
            self.current_playlist_index = 0
            self.is_playlist_playing = True
            self._playlist_played_any = False
            print(f"Play Selected: {len(selected_items)} files selected, starting playback")
            self.play_current_playlist_item()
        else:
            print("No files selected")
            # 사용자에게 선택된 파일이 없다는 것을 알림
            QMessageBox.information(self, "Play Selected", "Please select one or more files from the sidebar first.")

    def play_current_playlist_item(self):
        """선택 재생: 지금 차례의 영상을 열어 재생. 열 수 없는 영상은 건너뛰고 다음 영상으로 (되부르지 않고 반복).

        디스크에 없는 영상을 처음 만나면 남은 차례의 영상을 한 번에 확인해 없는 것을 모두 빼고 창 한 번·목록 다시 읽기 한 번
        (예전에는 없는 영상마다 창과 NAS 다시 읽기). 영상을 확인하지 못하면(NAS 연결 끊김·권한) 창으로 알리고 선택 재생을
        멈춤 (다음 영상도 그럴 것이므로 영상마다 창이 뜨지 않게). OpenCV가 열지 못한 영상은 open_file이 알리고 다음 영상으로.
        다음 영상을 정하는 동안(창이 떠 이벤트를 처리함) 보던 영상이 끝나도 선택 재생을 거기서 또 진행하지 않음
        (_playlist_resolving — 예전에는 같은 영상을 두 번 열고 하나를 건너뜀).
        """
        self._playlist_resolving = True
        try:
            self._play_playlist_from_current()
        finally:
            self._playlist_resolving = False

    def _play_playlist_from_current(self):
        while 0 <= self.current_playlist_index < len(self.playlist):
            current_file = self.playlist[self.current_playlist_index]
            try:
                os.stat(current_file)
            except OSError as e:
                gone, note = video_list.check_gone(current_file, e)
                if gone:
                    self._skip_missing_playlist_videos()
                    continue
                reason = f"{type(e).__name__}: {e}" + (f"\n{note}" if note else "")
                print(f"선택 재생할 영상을 확인하지 못함: {current_file} ({reason})")
                QMessageBox.critical(self, "영상을 열 수 없음",
                                     "선택 재생할 영상을 확인하지 못해 선택 재생을 멈춥니다 (NAS 연결 끊김·권한 등).\n"
                                     f"영상: {current_file}\n이유: {reason}")
                self._end_playlist_mode()
                return
            print(f"Playing playlist item {self.current_playlist_index + 1}/{len(self.playlist)}: {os.path.basename(current_file)}")
            print(f"is_playlist_playing before: {self.is_playlist_playing}")
            
            # 플레이리스트 재생 상태 확실히 설정
            self.is_playlist_playing = True
            
            # 사이드바에서 현재 파일 강조
            for i in range(self.sidebar.count()):
                item = self.sidebar.item(i)
                is_current = paths.same_path(item.toolTip(), current_file)
                font = item.font()
                font.setBold(is_current)
                item.setFont(font)
                if is_current:
                    item.setForeground(QColor("red"))  # 현재 재생 중인 항목은 빨간색
                else:
                    # 현재 테마에 맞는 색상으로 설정
                    if self.current_theme == 'dark':
                        item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
                    else:
                        item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상
            
            # 파일 열기 및 재생
            try:
                if self.open_file('A', current_file):
                    self._playlist_played_any = True
                    # 첫 번째 프레임으로 이동
                    self.seek_to_frame(1)
                    self.play_video()
                    self.playSelectedPauseButton.setText('Selected Pause')
                    self.playSelectedPauseButton.setStyleSheet("background-color: yellow;")
                    print(f"Successfully started playing: {os.path.basename(current_file)}")
                    print(f"is_playlist_playing after: {self.is_playlist_playing}")
                    return
                # 열지 못함 (open_file이 창으로 알림) — 예전에는 보던 영상을 처음부터 다시 재생했음
            except Exception as e:
                print(f"Error playing file {current_file}: {e}")
                traceback.print_exc()
                QMessageBox.warning(self, "Play Error", f"Failed to play file: {os.path.basename(current_file)}\nError: {str(e)}")
            # 오류 발생 시 다음 파일로 이동
            self.current_playlist_index += 1
        print(f"Playlist index {self.current_playlist_index} is past the end ({len(self.playlist)} items)")
        self._finish_playlist()

    def _skip_missing_playlist_videos(self):
        """선택 재생 중 디스크에 없는 영상을 만남 (지금 차례): 남은 차례의 영상도 한 번에 확인해 없어진 것을 모두 선택 재생에서
        빼고 창 한 번, 목록 다시 읽기 한 번. 확인하지 못한 영상(공유가 끊김 등)은 남겨 그 차례에 알림."""
        current = self.playlist[self.current_playlist_index]
        gone = [current]
        kept = []
        for path in self.playlist[self.current_playlist_index + 1:]:
            try:
                os.stat(path)
            except OSError as e:
                if video_list.is_gone(path, e):
                    gone.append(path)
                    continue
            kept.append(path)
        self.playlist = self.playlist[:self.current_playlist_index] + kept
        print(f"선택 재생: 디스크에 없는 영상 {len(gone)}개를 건너뜀:\n" + "\n".join(gone))
        lines = gone[:10] + ([f"… 외 {len(gone) - 10}개"] if len(gone) > 10 else [])
        QMessageBox.warning(self, "영상 없음",
                            f"디스크에 없는 영상 {len(gone)}개를 건너뜁니다:\n" + "\n".join(lines) + "\n목록을 다시 읽습니다.")
        self.refresh_sidebar()

    def _end_playlist_mode(self):
        """선택 재생 상태만 끝냄 (보던 영상은 그대로)."""
        self.is_playlist_playing = False
        self.reset_sidebar_colors()
        self.playSelectedPauseButton.setText('Selected Play'); self.playSelectedPauseButton.setStyleSheet("")
        if not self.timer.isActive():
            # 창이 떠 있는 동안 보던 영상이 끝나 재생이 이미 멈춤 → 재생 버튼이 'Pause'로 남지 않게
            self.playPauseButton.setText('Play'); self.playPauseButton.setStyleSheet("")
            if hasattr(self, 'overlayPlayPause'):
                self.overlayPlayPause.setText('▶')

    def _finish_playlist(self):
        """선택 재생 끝. 재생한 영상이 있으면 예전처럼 멈추고 알림. 하나도 재생하지 못했으면(모두 없거나 열 수 없음 — 그때마다
        창으로 알림) 보던 영상은 멈추지 않고 선택 재생만 끝냄."""
        if not self._playlist_played_any:
            print("선택 재생: 재생할 수 있는 영상이 없어 선택 재생을 끝냄 (보던 영상은 그대로)")
            self._end_playlist_mode()
            return
        print("Reached end of playlist, stopping playback")
        self.is_playlist_playing = False
        self.stop_video()
        self.reset_sidebar_colors()
        QMessageBox.information(self, "Playlist Complete", "All selected files have been played.")

    def reset_sidebar_colors(self):
        for i in range(self.sidebar.count()):
            item = self.sidebar.item(i)
            font = item.font(); font.setBold(False)
            item.setFont(font)
            # 현재 테마에 맞는 색상으로 설정
            if self.current_theme == 'dark':
                item.setForeground(QColor("#fafafa"))  # 블랙 테마에서는 밝은 색상
            else:
                item.setForeground(QColor("#2c3e50"))  # 라이트 테마에서는 어두운 색상

    def play_next_in_playlist(self):
        if self._playlist_resolving:
            # 선택 재생이 다음 영상을 정하는 중(창이 떠 있음)에 영상이 끝남: 그 반복이 이어서 엶 — 여기서 또 진행하면 두 번 엶
            print("선택 재생: 다음 영상을 정하는 중에 영상이 끝남 — 진행은 그 반복이 함")
            return
        if self.current_playlist_index < len(self.playlist) - 1:
            self.current_playlist_index += 1
            print(f"Moving to next item in playlist: {self.current_playlist_index + 1}/{len(self.playlist)}")
            self.play_current_playlist_item()
        else:
            self._finish_playlist()
