# 저장소 가이드라인

## 프로젝트 구조 및 모듈 구성
- `yesoncheck/` 디렉토리에 런타임 코드가 있습니다. `app.py`는 Qt를 부트스트랩하고, `main_window.py`는 `player_base.py`, `player_playback.py`, `player_sidebar.py`로부터 `VideoPlayer`를 조립합니다. `player_review.py`와 `player_timeline.py`는 OCR 검토 UI를 담당하며, `player_review.py`는 WebSocket 서버를 포함합니다. `web_info.py`는 웹UI HTML 생성 및 WebSocket 통신을 담당합니다. `video_widget.py`는 커스텀 뷰포트를 렌더링하고, `workers.py`는 FFmpeg 및 썸네일 스레드를 포함합니다. 헬퍼 함수들은 `frame_utils.py`와 `styles.py`에 있습니다.
- `YesonCheck_Autocut.spec`이 PyInstaller를 제어합니다 (정적 ffmpeg는 `vendor/ffmpeg/`, TransNetV2 가중치는 `vendor/transnetv2-weights/`). 빌드 방법은 `BUILD.md`.
- 썸네일과 같은 레거시 자산은 프로젝트별 `.yesoncheck_thumb/` 폴더에 캐시됩니다. 표시 문제를 보고하기 전에 오래된 캐시를 정리하세요.
- 문서는 `README.md` (환경 설정), `BUILD.md` (빌드)와 이 가이드에 있습니다. 자동화된 시험은 `tests/` (pytest)에 있습니다.

## 빌드, 테스트 및 개발 명령어
- `./setup_build_env.sh`로 `~/coding/p310_tf`(Python 3.10, 아키텍처별 lock의 고정 버전, TensorFlow 2.15.1 포함)를 만듭니다. TransNetV2는 pip로 설치하지 않습니다 (코드·가중치가 저장소에 있음).
- `python -m yesoncheck.app`로 개발 빌드를 실행합니다. 새로운 미디어 타입을 추가할 때 코덱 경고를 확인하세요.
- `./build_app.sh`(기본 `~/coding/p310_tf`)로 `dist/YesonCheck_Autocut_<Intel|AppleSilicon>.app`과 `.dmg`를 만들고 번들 검사(`check_min_macos.py`, `check_frozen_imports.py`)를 합니다. 저장소 루트에서 실행하세요.
- `~/coding/p310_tf/bin/python -m pytest tests -q`로 시험합니다.
- `python -m compileall yesoncheck`는 패치를 제출하기 전에 실행할 빠른 구문 검사입니다.

## 코딩 스타일 및 명명 규칙
- PEP 8을 따르며 4칸 들여쓰기를 사용합니다. 함수/변수는 `snake_case`, Qt 서브클래스는 `CamelCase`, 모듈 상수는 대문자로 작성합니다.
- UI 시그널/슬롯 연결은 위젯 선언 근처에 중앙화하고, 스레딩이 관련된 경우 `pyqtSlot`을 사용합니다.
- 지속되는 사용자 설정에 매핑되지 않는 한 새로운 전역 상태를 피하고, 관련 믹스인 내의 범위가 지정된 헬퍼를 선호합니다.

## 테스트 가이드라인
- 자동화된 테스트는 없습니다. 동작이 변경될 때마다 비디오 로드, 썸네일 생성, 오버레이 컨트롤, FFmpeg 내보내기를 포함한 수동 회귀 테스트를 수행하세요.
- 테스트를 추가할 때는 테스트 대상 모듈 옆에 `*_test.py` 파일을 배치하고 `python -m pytest`로 실행하세요.
- 리뷰어를 돕기 위해 PR 설명에 수동 테스트 입력(미디어 경로, OS, GPU 모드)을 문서화하세요.

## 커밋 및 Pull Request 가이드라인
- 72자 이하의 명령형, 범위 접두사가 있는 커밋 제목을 사용합니다 (예: `playback: guard cuda upload`). 본문에 사용자에게 보이는 위험 또는 완화 조치를 기록하세요.
- PR에는 다음을 포함해야 합니다: 간단한 의도, 설정 명령어, 검증 단계, UI 작업의 경우 스크린샷. 가능한 경우 Jira/Trello 이슈에 링크하세요.
- 동작 변경의 경우 최소 한 명의 리뷰어를 요청하세요. 문서만 업데이트하는 경우 CI(추가되면)가 녹색을 유지하는 한 자체 검토 후 병합할 수 있습니다.

## 아키텍처 노트
- `VideoPlayer`는 프레젠테이션(`player_base`)과 기능 슬라이스(`player_playback`, `player_sidebar`)를 믹스합니다. 응집력을 위해 관련 믹스인을 대상으로 편집하세요.
- 장기 실행 작업은 `QThread` 서브클래스를 사용합니다. 종료 경쟁을 피하기 위해 시그널을 발생시키기 전에 항상 `_is_running`을 확인하세요.

## 최근 주요 변경 사항 (2025.11.25)
- **웹UI 실시간 동기화**: WebSocket을 통한 양방향 실시간 동기화 구현
  - 데스크탑 ↔ 웹UI 양방향 동기화
  - 텍스트 편집, 프레임 변경 시 자동 동기화 (50ms 디바운스)
  - 병합, 삭제, 씬 분할, undo/redo 시 전체 동기화
  - 썸네일 이미지 포함하여 전송
- **씬 분할 기능**: 선택한 씬을 지정한 프레임 위치에서 두 개의 씬으로 분할
- **내보내기 기능 개선**: 선택한 항목만 내보내기, 전체 내보내기, 사운드 포함 옵션
- **썸네일 최적화**: 씬 감지 완료 후 프리로드, 저장된 썸네일 재사용
- **프리뷰 영상 동기화**: 썸네일 이미지와 프리뷰 영상의 첫 프레임 일치 보장
- **UI 개선**: 버튼 위치 조정 및 정렬
- **우클릭 컨텍스트 메뉴**: 타임라인 및 테이블에서 우클릭으로 모든 편집 기능 접근 가능 (데스크탑 및 웹UI)
- **프리뷰 재생 개선**: 종료 프레임까지 정확히 재생되도록 수정 (슬라이더 드래그 후 재생 시에도 정상 작동)
- **로그 출력 통일**: 로그 출력을 1-based 프레임 번호로 통일하여 UI와 일치
- **익스포트 안정성 개선**: OCRExportWorker 스레드 종료 시 안전하게 대기하도록 수정하여 익스포트 중 크래시 문제 해결

## 최근 주요 변경 사항 (2025.11.21)
- **코드 리팩터링**: `player_base.py` 분리 (`player_timeline.py`, `player_review.py` 생성)
- **임포트 최적화**: 미사용 임포트 제거 및 의존성 정리

## 최근 주요 변경 사항 (2025.11.18)
- **Python 버전**: 3.12 → 3.10 (p310 가상환경 사용)
- **빌드 파일**: `YesonCheck_final_20251105_path.spec` → `YesonCheck_p310_apted.spec`
- **타임라인 썸네일**: PaddleOCR 모드에서 ROI 종횡비 유지, 60% 축소 크기
- **성능 개선**: 병합 속도 및 클릭 반응 최적화
- **apted 모듈**: PaddleOCR 분석에 필수인 apted 모듈 포함
