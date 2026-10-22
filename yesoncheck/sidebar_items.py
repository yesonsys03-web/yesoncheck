"""사이드바 항목이 쓰는 상수(창 제목·안내 문구·항목 데이터 역할·다시 읽기 간격)와 항목의 썸네일 자리(ThumbnailContext).

잎 모듈 — yesoncheck 안의 다른 모듈을 불러오지 않고 PyQt5의 Qt 이름 하나만 씀(위젯 없음). 사이드바 코드를 여러 파일로 나눠도
서로 이 모듈에서 가져오면 되므로 순환 import가 생기지 않음. 기존 경로 `yesoncheck.player_sidebar`에서도 같은 객체로 불러올 수
있음(player_sidebar가 다시 내보냄 — `ThumbnailContext`는 `==`로 같은 자리를 찾으므로 클래스 객체가 하나여야 함).
"""

from dataclasses import dataclass

from PyQt5.QtCore import Qt

LOADING_TITLE_SUFFIX = " — 공유 설정 불러오는 중…"  # 불러오는 동안 창 제목: build_info.title_base() 뒤에 붙임
LOADING_NOTICE = "공유 설정을 불러오는 중입니다. 잠시 뒤 다시 시도하세요."
LOADING_WORK_ITEM = "공유 설정 불러오는 중…"  # 불러오는 동안 작품 목록의 첫 항목 ("작품선택" 대신)
WORK_PLACEHOLDER = "작품선택"
NO_SEASON_WORKS = ("The_Johnsons", "TJS_Animatic")  # 시즌이 없는 작품: 작품 폴더 바로 아래가 job (작품 → job)
THUMBNAIL_SAVE_FAILED = "썸네일 저장 실패"  # 썸네일 파일을 쓰지 못함 (창 제목)
THUMBNAIL_FOLDER_PROBLEM = "썸네일 폴더 문제"  # 썸네일 폴더를 만들지 못함 등 (창 제목)
THUMBNAIL_VIDEO_PROBLEM = "영상 확인 실패"  # 썸네일을 만들 영상을 확인하지 못함 (창 제목)
THUMBNAIL_MAKE_FAILED = "썸네일 만들기 실패"  # 영상은 있지만 썸네일을 만들지 못함 — OpenCV가 열지 못함 등 (창 제목)
THUMBNAIL_CONTEXT_ROLE = Qt.UserRole + 1  # 사이드바 항목 데이터: 그 영상의 썸네일 자리 (ThumbnailContext)
SIDEBAR_SOURCE_ROLE = Qt.UserRole + 2  # 사이드바 항목 데이터: 그 영상이 들어온 곳 (video_list.ListSource, 따로 넣은 파일은 None)
LIST_READ_FAILED = "목록 폴더를 읽지 못함"  # 영상 목록을 만들거나 다시 읽을 폴더를 읽지 못함 (창 제목)
LIST_FOLDER_GONE = "목록 폴더 없음"  # 목록에 영상을 넣은 폴더가 지워짐 (창 제목)
ACTIVATION_REFRESH_GAP_S = 2.0  # 앱이 다시 활성될 때 이 시간 안에 이미 목록을 읽었으면 또 읽지 않음
ACTIVATION_REFRESH_GAP_FACTOR = 10  # … 마지막 읽기가 오래 걸렸으면(Windows SMB의 큰 job) 그 시간의 이만큼 배 동안


@dataclass(frozen=True)
class ThumbnailContext:
    """사이드바 영상의 썸네일을 어디에 둘지. 항목을 넣을 때의 상태로 정하고, 나중에 다른 폴더를 끌어다 놓아 덧붙이거나
    job·북마크를 바꿔도 그 항목은 바뀌지 않음 (재검토 L1).
    """

    folder: str = None  # 썸네일 폴더: 여기서 읽고 여기에 저장
    problem: tuple = None  # (폴더, 창 제목, 내용): 썸네일 폴더를 만들지 못함 → 화면에만, 창은 썸네일을 쓸 때
    pending_base: str = None  # 아직 정하지 않음: 처음 쓸 때 이 폴더 아래에 썸네일 폴더를 만듦 (예: 처음 끌어다 놓은 파일)
