# -*- coding: utf-8 -*-
"""슬라이더 호버 썸네일을 플레이어에 잇는 얇은 믹스인 (PlayerHoverThumbsMixin) — 띠의 수명(열기·놓기·닫기)·쉬는 때 판정·호버 조회·실패 알림.

잇기만 한다: 띠 계획·저장소는 hover_strip, ffmpeg 워커는 hover_strip_builder, 커서 위 창·슬라이더 필터는 slider_preview의 몫이고, 이 모듈은
디코드도 위젯 그리기도 설정 파일 읽기·쓰기도 하지 않는다. 재생 캡처(cap_a)에서는 틱과 열 때의 값 읽기(get — 위치·장수·크기)만 하고 프레임을
꺼내지 않는다 (꺼내면 본화면이 튀고 파이프 스트림·링이 깨짐 — hover_strip 설명).

VideoPlayerBase의 부모 클래스로 붙음 — `class VideoPlayerBase(PlayerHoverThumbsMixin, PlayerOcrMixin, PlayerOverlayMixin, QMainWindow)`.
상태는 VideoPlayerBase.__init__이 부르는 _init_hover_thumbs가 만들고(두 슬라이더가 창 안에 들어간 뒤 — 필터가 slider.window()에도 걸림),
open_file(A 영상)·_release_side('A')·_load_job_list(job을 바꿔 A를 놓을 때)·_release_resources_on_close가 _hover_thumbs_open·
_hover_thumbs_close를 부른다. 이름은 모두 `_hover_`로 시작해 다른 믹스인과 겹치지 않는다. player_base를 모듈 수준에서 import하지 말 것 (순환).

왜 쉬는 때를 재생·멈춤 훅이 아니라 재생 캡처의 위치 변화로 보나 (스펙 §5.5): 이 앱의 핵심 작업인 ←/→ 연타·휠 탐색·슬라이더 클릭도 4K면
한 칸마다 디코드라 쉬는 때가 아닌데, 이것들은 재생·멈춤을 거치지 않는다. 길마다(play_video·stop·next_frame·seek_to_frame·휠·선택 재생…)
훅을 달면 글자 그대로 둬야 할 재생·탐색 코드를 고치게 되고 새 길이 생기면 빠진다. 그래서 GUI 타이머가 TICK_MS마다
cap_a.get(CAP_PROP_POS_FRAMES)를 읽어 앞 값과 다르면 '움직임'으로 적고, IDLE_S(0.3초 — 전체 프레임 캐시 채움기의 IDLE_FILL_DELAY_S와 같은
값) 안에 움직였으면 바쁨으로 본다 — cv2·파이프·네이티브 어느 캡처에서나 같은 신호이고 get은 디코드하지 않는다. 재생(timer.isActive)과
드래그(두 슬라이더의 isSliderDown — 마우스를 누른 동안 참)는 그대로 본다: busy = 재생 ∨ 메인 누름 ∨ 오버레이 누름 ∨ 위치가 IDLE_S 안에 바뀜.
재생 중의 틱은 가장 싼 길이다(재생 틱과 같은 GUI 스레드라): 맨 앞에서 timer.isActive()면 재생 캡처의 get·슬라이더를 보지 않고 워커가 있으면
worker.paused = True만 둔 채 끝 — 그때를 '움직임'으로 적어(_hover_moved_at) 재생이 멈춘 뒤 IDLE_S를 새로 세고, 재생은 아래 진단 기록의 '오래
바쁨'에 넣지 않는다(보이는 까닭이라 — 재생 전부터 세던 바쁨이 재생 시간까지 더해 적히지 않게).
기존 표지 is_dragging은 보지 않는다 — on_slider_moved가 True로 두고 valueChanged(on_slider_value_changed)만 되돌리는데, 드래그 미리보기가
슬라이더 값을 blockSignals로 써 두면 놓을 때 Qt가 valueChanged를 내지 않아 드래그 뒤에도 True로 남을 수 있고(실기 보고 — 그 뒤 연 모든
파일에서 띠를 띄우지 않았음), 드래그 중은 isSliderDown이, 캐시에 안 맞는 미리보기 디코드는 위치 변화가 이미 덮는다. 워커가 돌면 틱마다
worker.paused = busy만 넘긴다(워커는 값이 바뀔 때만 잠금을 잡고 ffmpeg를 정지·재개 — 같은 값이면 아무것도 안 함; Qt 객체를 다른 스레드에서
읽지 않으려고 GUI 타이머가 표지를 넘김). 워커 없이 BUSY_LOG_S(5초)보다 오래 바쁘면 무엇이 바쁜지 기록 한 줄(계획마다 한 번 — 띠가 왜 안
생기는지 기록으로 바로 알게; 재생 중에는 세지 않음).

왜 워커를 열 때 바로 띄우지 않고 START_DELAY_S(1.0초) 뒤 쉴 때 띄우나: 선택 재생·↑↓ 연타처럼 열자마자 다음 파일로 넘어가면 바로 띄운
ffmpeg는 파일 전체(NAS)를 읽기 시작하자마자 kill될 뿐이고, 그 사이 새 파일의 첫 화면(파이프 ffmpeg 시작·첫 디코드)과 다툰다. 쉬기 전에
넘어간 파일은 프로세스를 아예 띄우지 않아 비용이 0이다. 1.0초(처음 0.5초 — 3차 측정 전 Ruling 14로 늘림)는 열고 곧바로 Play하는 흐름과도
겹치지 않게: 그 안에 Play하면 워커를 띄우지 않은 채 재생이 시작된다(측정에서 끊김은 띄운 지 0.5초 안에 Play한 판에서 났음). 띠를 만들지 않는 파일(크기 상한 — hover_strip.skip_reason)은 계획만 두고 저장소·
타이머는 만들지 않는다 (호버는 번호 + 빈 상자).

끝 신호(done·failed)는 워커 스레드가 내 GUI 대기열로 온다. 그래서 stop()·release_worker 전에 대기열에 들어간 신호가 다음 파일을 연 뒤에
도착할 수 있다 — 슬롯은 보낸 쪽(sender)이 지금 워커일 때만 받는다 (옛 워커가 이미 지워졌으면 sender가 None이라 그것도 버림). 실패는
기록(stderr)에 매번, 오류 창은 파일마다 한 번(_hover_failed_for — 이 창이 떠 있는 동안 실패한 파일을 모두 기억하는 set이라 실패하는 두
파일을 오가도 창이 다시 뜨지 않음; 다시 시도하지 않음; 같은 파일을 다시 열어 또 실패해도 기록만).

Settings → 슬라이더 썸네일 (켜기/끄기): create_menu_bar가 _add_hover_thumbs_menu를 화면 그리기 메뉴 바로 뒤에서 부르고(Mac·Windows 모두), 고르면
set_slider_thumbnails가 hover_strip의 설정 파일(prefs.json)에 저장한 뒤 이 창에 바로 적용한다 (끔 → _hover_thumbs_close, 켬 → 지금 A 영상의 띠를
다시 엶). 읽기·쓰기 규칙은 hover_strip의 것이고 이 모듈은 부르기만 한다. 체크는 파일이 아니라 이 프로세스의 캐시(hover_strip.enabled — 이 창이 실제로
하는 일)를 따른다: 창마다 프로세스라 다른 창이 파일을 고쳤어도 이 창은 그 창이 다음에 켤 때부터 따른다. 저장 실패는 기록 + 창 한 번 + 체크 되돌림
(깨진 파일을 덮지 않음). 시작 때 설정을 읽는 쪽은 app.load_slider_thumbnails.
"""

import sys
import time
import traceback

import cv2
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

from yesoncheck import error_window, hover_strip, hover_strip_builder, user_files, worker_lifecycle
from yesoncheck.external_tools import ToolNotFoundError
from yesoncheck.hover_strip import LOG_PREFIX, MENU_TEXT, THUMB_WIDTH
from yesoncheck.sequence_scan import is_sequence_path
from yesoncheck.slider_preview import LookupResult, SliderHoverFilter, SliderPreviewPopup

START_DELAY_S = 1.0  # 열린 뒤 이만큼 지나야 워커를 띄움 (모듈 설명)
IDLE_S = 0.3  # 재생 캡처의 위치가 이 안에 바뀌었으면 쉬는 때가 아님
TICK_MS = 50  # 쉬는 때 판정 간격 — 띄울 워커가 있거나 돌고 있는 동안만 돎
BUSY_LOG_S = 5.0  # 워커 없이 이만큼 넘게 바쁘면 진단 기록 한 줄 (계획마다 한 번)
BUILDER_LABEL = "슬라이더 썸네일 띠"  # release_worker의 기록 이름
HOVER_TITLE = "슬라이더 썸네일 설정"  # Settings → 슬라이더 썸네일의 저장 실패 창 제목 (app.SLIDER_THUMBS_TITLE의 읽기 실패 창과 같은 제목)
HOVER_TIP = "슬라이더 위에 커서를 올리면 그 프레임의 작은 그림을 보여 줍니다 — 이 창은 바로, 이미 열린 다른 창은 다음에 켤 때부터"


class PlayerHoverThumbsMixin:
    """VideoPlayer의 슬라이더 호버 썸네일 — 띠의 수명·쉬는 때 판정·두 슬라이더의 값 → (번호, 그림) 조회·실패 알림 (모듈 설명)."""

    def _init_hover_thumbs(self) -> None:
        """상태·커서 위 창·두 슬라이더의 필터·쉬는 때 타이머를 만듦 (VideoPlayerBase.__init__ — create_overlay_controls 뒤에)."""
        self._hover_plan = None  # 지금 A 영상의 띠 계획 (없으면 호버에 창 없음)
        self._hover_strip = None  # 띠 저장소 (크기 상한으로 만들지 않는 파일은 계획만 있고 None — 번호 + 빈 상자)
        self._hover_builder = None  # 지금 워커 (띄우기 전·닫은 뒤 None — 끝난 워커는 닫을 때까지 둠)
        self._hover_path = ""
        self._hover_opened_at = 0.0  # time.monotonic()
        self._hover_last_pos = None  # 앞 틱에서 읽은 재생 캡처 위치
        self._hover_moved_at = 0.0
        self._hover_busy_since = None  # 워커 없이 바빠진 때 (쉬면 None)
        self._hover_busy_logged = False  # 이 계획에서 진단 기록을 남겼음
        self._hover_failed_for: set[str] = set()  # 오류 창을 이미 띄운 파일들 (이 창이 떠 있는 동안)
        self._hover_popup = SliderPreviewPopup(THUMB_WIDTH, 180)  # 계획마다 그 파일의 그림 크기로 맞춤
        # Qt는 설치된 이벤트 필터를 붙잡아 주지 않음 — parent와 이 목록이 쥠
        self._hover_filters = [
            SliderHoverFilter(self.positionScroll, self._hover_lookup_main, self._hover_popup, self),
            SliderHoverFilter(self.overlaySlider, self._hover_lookup_overlay, self._hover_popup, self),
        ]
        self._hover_timer = QTimer(self)
        self._hover_timer.setInterval(TICK_MS)
        self._hover_timer.timeout.connect(self._hover_thumbs_tick)

    def _hover_thumbs_open(self, file_path: str, total: int, width: int, height: int) -> None:
        """A에 영상을 연 뒤 (open_file — 슬라이더 범위를 정한 직후): 옛 띠를 버리고 새 계획을 둠. 워커는 아직 띄우지 않음 (쉬는 때 틱이 띄움).
        기능이 꺼졌거나 시퀀스면 아무것도 두지 않음. total·width·height는 재생 캡처의 get 값."""
        self._hover_thumbs_close()
        if not hover_strip.enabled() or is_sequence_path(file_path):
            return
        if total < 1 or width < 1 or height < 1:  # 장수·크기를 모르는 캡처 (cv2가 0을 돌려주는 스트림 등) — 열기는 그대로 이어 감
            print(f"{LOG_PREFIX} 띠를 만들지 않음: 장수·크기를 알 수 없음 (장수 {total}, {width}×{height}) — {file_path}", flush=True)
            return
        try:
            reason = hover_strip.skip_reason(file_path)
        except OSError:
            print(f"{LOG_PREFIX} 파일 크기를 읽지 못해 띠를 만들지 않음 — {file_path}", file=sys.stderr, flush=True)
            traceback.print_exc()
            return
        plan = hover_strip.plan_for(total, width, height)
        self._hover_plan = plan
        self._hover_path = file_path
        self._hover_popup.set_thumb_size(plan.width, plan.height)
        if reason is not None:
            print(f"{LOG_PREFIX} 띠를 만들지 않음: {reason} — {file_path}", flush=True)
            return
        self._hover_strip = hover_strip.HoverStrip(plan)
        self._hover_opened_at = self._hover_moved_at = time.monotonic()
        self._hover_last_pos = None
        self._hover_busy_since = None
        self._hover_busy_logged = False
        self._hover_timer.start()

    def _hover_thumbs_close(self) -> None:
        """띠를 버림: 틱 정지, 워커가 있으면 stop()(ffmpeg kill·거두기·스레드 끝 대기) 뒤 release_worker(끝나지 않았으면 끝날 때까지 붙잡아 둠),
        계획·저장소를 놓고 창을 숨김. 여러 번 불러도 됨 (새 A 열기·_release_side('A')·창 닫기·틱이 본 죽은 캡처)."""
        self._hover_timer.stop()
        worker, self._hover_builder = self._hover_builder, None
        if worker is not None:
            worker.stop()
            worker_lifecycle.release_worker(worker, BUILDER_LABEL)
        self._hover_plan = None
        self._hover_strip = None
        self._hover_path = ""
        self._hover_popup.hide()

    def _hover_thumbs_tick(self) -> None:
        """쉬는 때 판정 (TICK_MS마다 — 모듈 설명). 재생 중이면 워커에 멈춤 표지만 두고 끝(재생 캡처·슬라이더를 보지 않음). 재생 캡처가 없거나
        닫혔으면 띠를 버리고 끝. 워커가 없으면 쉴 때 띄우고, 있으면 paused만 넘김."""
        now = time.monotonic()
        if self.timer.isActive():  # 재생 중: get·슬라이더 조회 없이 (모듈 설명)
            worker = self._hover_builder
            if worker is not None:
                worker.paused = True  # 이미 참이면 워커가 아무것도 안 함
            self._hover_moved_at = now  # 재생이 멈춘 뒤 IDLE_S를 새로 셈
            self._hover_busy_since = None  # 재생은 진단 기록의 '오래 바쁨'에 넣지 않음
            return
        cap = self.cap_a
        if cap is None or not cap.isOpened():
            self._hover_thumbs_close()
            return
        position = cap.get(cv2.CAP_PROP_POS_FRAMES)
        if position != self._hover_last_pos:
            self._hover_last_pos = position
            self._hover_moved_at = now
        busy = (self.positionScroll.isSliderDown() or self.overlaySlider.isSliderDown()
                or now - self._hover_moved_at < IDLE_S)  # 재생은 위에서 끝남, is_dragging은 보지 않음 (모듈 설명)
        worker = self._hover_builder
        if worker is not None:
            worker.paused = busy
        elif not busy:
            self._hover_busy_since = None
            if now - self._hover_opened_at >= START_DELAY_S:
                self._hover_spawn()
        elif self._hover_busy_since is None:
            self._hover_busy_since = now
        elif not self._hover_busy_logged and now - self._hover_busy_since > BUSY_LOG_S:
            self._hover_busy_logged = True
            print(f"{LOG_PREFIX} 쉬는 때를 기다리는 중 {now - self._hover_busy_since:.0f}초 — 재생 {self.timer.isActive()}, "
                  f"슬라이더 누름 {self.positionScroll.isSliderDown()}/{self.overlaySlider.isSliderDown()}, "
                  f"위치 변화 {now - self._hover_moved_at:.1f}초 전 — {self._hover_path}", flush=True)

    def _hover_spawn(self) -> None:
        """워커를 만들어 띄움 (기록 한 줄). ffmpeg를 찾지 못해 만들지 못하면 실패와 같은 길 — 틱을 멈춰 50ms마다 다시 시도하지 않음."""
        plan = self._hover_plan
        print(f"{LOG_PREFIX} 띠 만들기 시작: {plan.count}장(간격 {plan.step}, 전체 {plan.total}장) {plan.width}×{plan.height} — "
              f"{self._hover_path}", flush=True)
        try:
            worker = hover_strip_builder.HoverStripBuilder(self._hover_path, self._hover_strip, parent=self)
        except ToolNotFoundError:
            self._hover_fail(f"띠 워커를 만들지 못했습니다.\n{traceback.format_exc().rstrip()}")
            return
        worker.done.connect(self._hover_on_done)
        worker.failed.connect(self._hover_on_failed)
        self._hover_builder = worker
        worker.start()

    def _hover_from_current_builder(self) -> bool:
        """(끝 신호 슬롯 안) 보낸 쪽이 지금 워커인지 — 옛 워커가 놓이기 전에 대기열에 넣은 신호는 버림 (모듈 설명)."""
        sender = self.sender()
        return sender is not None and sender is self._hover_builder

    def _hover_on_done(self, filled: int, seconds: float) -> None:
        """워커가 끝까지 읽음: 기록 한 줄, 틱 정지. 워커 객체는 두고 놓기(release_worker)는 닫을 때."""
        if not self._hover_from_current_builder():
            return
        print(f"{LOG_PREFIX} 띠 완성: {filled}/{self._hover_plan.count}장 {seconds:.1f}초 — {self._hover_path}", flush=True)
        self._hover_timer.stop()

    def _hover_on_failed(self, text: str) -> None:
        """워커 실패 (text: 파일·명령·종료 코드·stderr 전문·트레이스백)."""
        if not self._hover_from_current_builder():
            return
        self._hover_fail(text)

    def _hover_fail(self, text: str) -> None:
        """틱 정지 + 알림: 기록(stderr)은 매번, 오류 창은 파일마다 한 번 (이미 띄운 파일이면 기록만). 이미 채운 장은 그대로 보임."""
        self._hover_timer.stop()
        message = f"띠를 만들지 못했습니다 — {self._hover_path}\n{text}\n\nSettings → {MENU_TEXT}을 끄면 만들지 않습니다"
        if self._hover_path in self._hover_failed_for:
            print(f"{LOG_PREFIX} {message}", file=sys.stderr, flush=True)
            return
        self._hover_failed_for.add(self._hover_path)
        error_window.show_error(LOG_PREFIX, message)

    def _hover_live_plan(self):
        """호버가 쓸 계획 — 계획이 없거나, 재생 캡처가 없거나 닫혔거나, A가 계획의 파일이 아니면 None. A를 놓는 길이 모두 _release_side를
        거치지는 않고(job 불러오기는 cap_a를 직접 놓음) 띠가 끝나면 틱도 멈춰 있으므로 조회마다 다시 본다 — 어느 길로 놓든 옛 파일의
        번호·그림이 뜨지 않게."""
        cap = self.cap_a
        if self._hover_plan is None or cap is None or not cap.isOpened() or self.filename_a != self._hover_path:
            return None
        return self._hover_plan

    def _hover_main_frame(self, value: int, last: int) -> int:
        """메인 슬라이더 값 → 프레임(0-based, last = N − 1) — on_slider_moved·on_slider_value_changed·sync_audio_on_release와 같은 식:
        최대값 − 1 이상이면 마지막 장 (한 장짜리는 최대값 1이라 늘 이 갈래 → 0), 아니면 비례 반올림."""
        maximum = self.positionScroll.maximum()
        if value >= maximum - 1:
            return last
        return max(0, min(round(value / maximum * last), last))

    def _hover_lookup_main(self, value: int) -> LookupResult:
        """메인 슬라이더 값 → (번호 글, 그림|None), 쓸 계획이 없으면 None."""
        plan = self._hover_live_plan()
        if plan is None:
            return None
        return self._hover_entry(self._hover_main_frame(value, plan.total - 1))

    def _hover_lookup_overlay(self, value: int) -> LookupResult:
        """오버레이 슬라이더 값 → (번호 글, 그림|None), 쓸 계획이 없으면 None. 클릭이 실제로 착지하는 프레임: on_overlay_slider_released가 값
        그대로의 프레임(min(v, N − 1))으로 간 뒤 부르는 sync_audio_on_release가 메인 슬라이더 규칙을 한 번 더 건다 — 그 프레임 자리의 메인
        슬라이더 값(update_position_info의 식 round(프레임 / (N − 1) × 최대값))에 메인 식(_hover_main_frame)을 건 것이 착지. 최대값 = N − 1이라
        그 값이 '최대값 − 1' 밑이면 프레임 그대로이고, v = N − 2는 마지막 장이다 (실측·시험: 클릭 착지 대조 — 스펙 §5.4의 'v = N − 2에서 한 장
        다름'은 이 두 번째 탐색을 빠뜨린 것)."""
        plan = self._hover_live_plan()
        if plan is None:
            return None
        last = plan.total - 1
        frame = max(0, min(value, last))
        if last > 0:  # 한 장짜리는 on_overlay_slider_released가 탐색 없이 끝남 → 0
            frame = self._hover_main_frame(round(frame / last * self.positionScroll.maximum()), last)
        return self._hover_entry(frame)

    def _hover_entry(self, frame: int) -> LookupResult:
        """프레임(0-based) → (번호 글 = 프레임 + 1 — 'Current:' 라벨과 같음, 가장 가까운 샘플의 그림 — 아직 없거나 저장소가 없으면 None)."""
        strip = self._hover_strip
        if strip is None:
            return str(frame + 1), None
        sample = strip.plan.sample_for(frame)
        return str(frame + 1), strip.image(sample) if strip.has(sample) else None

    def _add_hover_thumbs_menu(self, settings_menu) -> None:
        """Settings → 슬라이더 썸네일 — 체크 가능한 항목 하나 (Mac·Windows 모두). 툴팁이 보이게 하고 체크는 지금 캐시에 맞춤.
        create_menu_bar가 화면 그리기 메뉴(_add_display_menu) 바로 뒤에서 부름 — 창을 만드는 중이라 아직 _init_hover_thumbs 전일 수 있어 여기서는 항목만 만듦."""
        settings_menu.setToolTipsVisible(True)
        self.hover_thumbs_action = settings_menu.addAction(MENU_TEXT)
        self.hover_thumbs_action.setCheckable(True)
        self.hover_thumbs_action.setToolTip(HOVER_TIP)
        self.hover_thumbs_action.triggered.connect(lambda checked: self.set_slider_thumbnails(checked))
        self._sync_hover_thumbs_menu()

    def _sync_hover_thumbs_menu(self) -> None:
        """체크를 이 프로세스의 캐시(hover_strip.enabled)에 맞춤 — 메뉴를 만들 때, 고른 뒤, 저장 실패로 되돌릴 때."""
        self.hover_thumbs_action.setChecked(hover_strip.enabled())

    def set_slider_thumbnails(self, enabled: bool) -> None:
        """메뉴에서 고른 켬/끔을 prefs.json에 저장하고 이 창에 바로 적용 (모듈 설명).
        - 저장: 파일이 이미 그 값이면 쓰지 않음(창마다 프로세스라 다른 창이 먼저 저장했을 수 있음 — 이 창은 아래에서 그래도 따름). 파일의 값이 나쁘면(불리언이
          아님) 트레이스백을 기록하고 사용자가 고른 값으로 고침 — 시작 알림이 약속한 '다시 켤 수 있음'이 성립하려면 필요(명시적 선택이라 지어낸 값이 아님).
          저장 실패(깨진 파일·쓰기 실패·잠금 시간 초과)는 기록 + 창 한 번 + 체크 되돌림, 캐시·띠는 그대로.
        - 적용: 이 창이 이미 그 상태면 체크만 맞춤. 아니면 캐시를 바꾸고 기록 한 줄 — 끔은 띠를 버리고(워커·ffmpeg 정지), 켬은 A에 열린 영상이 있으면 그 영상의
          계획을 다시 엶(워커는 쉬는 때 틱이 띄움 — 시퀀스·크기 상한은 _hover_thumbs_open이 가름)."""
        try:
            try:
                saved = hover_strip.read_enabled()
            except ValueError:
                traceback.print_exc()
                saved = None
            if saved != enabled:
                hover_strip.save_enabled(enabled)
        except (user_files.UserFileError, OSError, TimeoutError) as exc:
            traceback.print_exc()
            QMessageBox.critical(self, HOVER_TITLE, f"설정을 저장하지 못해 바꾸지 않았습니다.\n{exc}")
            self._sync_hover_thumbs_menu()
            return
        if hover_strip.enabled() == enabled:
            self._sync_hover_thumbs_menu()
            return
        hover_strip.set_enabled(enabled)
        print(f"{LOG_PREFIX} 설정: {'켬' if enabled else '끔'} (Settings 메뉴)", flush=True)
        if not enabled:
            self._hover_thumbs_close()
        else:
            cap = self.cap_a
            if cap is not None and cap.isOpened():
                self._hover_thumbs_open(self.filename_a, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
                                        int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self._sync_hover_thumbs_menu()
