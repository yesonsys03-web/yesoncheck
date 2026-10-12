"""Auto trim module using PySceneDetect for automatic scene cut detection."""

import cv2
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable

try:
    from scenedetect import VideoManager, SceneManager
    from scenedetect.detectors import ContentDetector, ThresholdDetector
    from scenedetect.frame_timecode import FrameTimecode
    SCENEDETECT_AVAILABLE = True
except ImportError:
    SCENEDETECT_AVAILABLE = False
    print("Warning: PySceneDetect not available. Install with: pip install scenedetect[opencv]")


def detect_scene_cuts(
    video_path: str,
    threshold: float = 30.0,
    min_scene_len: int = 15,
    fps: Optional[float] = None,
    detect_background_change: bool = True,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[Dict]:
    """
    Detect scene cuts in a video using PySceneDetect.
    
    Args:
        video_path: Path to the video file
        threshold: Sensitivity threshold for content detection (lower = more sensitive)
        min_scene_len: Minimum scene length in frames
        fps: Video FPS (if None, will be detected automatically)
        detect_background_change: If True, use background change detection (better for storyboard/animatic)
        start_frame: Optional frame index (0-based) to start analysis from.
        end_frame: Optional frame index (0-based, inclusive) to stop analysis at.
        log_callback: Optional callback function for logging (takes a string message)
    
    Returns:
        List of segment dictionaries with keys:
        - start_frame: int
        - end_frame: int
        - start_time: float (seconds)
        - end_time: float (seconds)
        - duration: float (seconds)
        - text: str (auto-generated segment name)
        - edited_text: str (same as text)
    """
    if not SCENEDETECT_AVAILABLE:
        raise ImportError(
            "PySceneDetect is not installed. "
            "Install with: pip install scenedetect[opencv]"
        )
    
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    # 선택 구간 설정
    has_range = start_frame is not None or end_frame is not None
    selection_start: Optional[int] = None
    selection_end: Optional[int] = None
    range_fps: Optional[float] = None

    if has_range:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        range_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
        cap.release()

        if total_frames <= 0:
            raise ValueError("유효하지 않은 비디오 파일입니다.")

        selection_start = max(0, start_frame if start_frame is not None else 0)
        selection_end = min(end_frame if end_frame is not None else total_frames - 1, total_frames - 1)

        if selection_start >= total_frames or selection_start > selection_end:
            # 선택 구간이 비어있으면 즉시 반환
            return []

        if range_fps <= 0:
            range_fps = 24.0

    # Create video manager and scene manager
    # VideoManager는 비디오 파일 경로만 받고, FPS는 자동으로 감지됨
    video_manager = VideoManager([video_path])
    scene_manager = SceneManager()
    
    # Add detector based on mode
    if detect_background_change:
        # 배경 변화 감지: 더 민감하게 설정 (화이트/블랙 스토리보드용)
        # 임계값을 더 낮춰서 작은 변화도 감지
        scene_manager.add_detector(ContentDetector(threshold=threshold * 0.2, min_scene_len=min_scene_len))  # 0.3에서 0.2로 더 낮춤
        # ThresholdDetector도 추가하여 전체 프레임 변화 감지 (min_percent 파라미터는 최신 버전에서 제거됨)
        scene_manager.add_detector(ThresholdDetector(threshold=6.0))  # 8.0에서 6.0으로 더 낮춤
    else:
        # 일반 컷 감지
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    
    # Start detection
    if has_range:
        fps_for_timecode = fps if fps and fps > 0 else range_fps or 24.0
        start_timecode = FrameTimecode(timecode=selection_start or 0, fps=fps_for_timecode)
        # PySceneDetect end_time은 다음 프레임을 가리키므로 +1
        end_timecode = None
        if selection_end is not None:
            end_timecode = FrameTimecode(timecode=selection_end + 1, fps=fps_for_timecode)
        video_manager.set_duration(start_time=start_timecode, end_time=end_timecode)
    else:
        video_manager.set_duration()
    video_manager.start()
    scene_manager.detect_scenes(frame_source=video_manager)
    
    # Get FPS from video manager for conversion
    if fps is None:
        # VideoManager에서 FPS 가져오기
        try:
            fps = video_manager.get_fps()
        except:
            if range_fps is not None:
                fps = range_fps
            else:
                # Fallback: OpenCV로 FPS 가져오기
                cap = cv2.VideoCapture(video_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
                    cap.release()
                else:
                    fps = 24.0

    if fps <= 0:
        fps = range_fps or 24.0  # Default FPS
    
    # Get scene list
    scene_list = scene_manager.get_scene_list()
    scene_count_msg = f"[PySceneDetect] {len(scene_list)}개 씬 감지됨"
    print(scene_count_msg)
    if log_callback:
        log_callback(scene_count_msg)
    
    # Convert to segment format
    segments = []
    for idx, (start_timecode, end_timecode) in enumerate(scene_list, start=1):
        # Convert timecode to frame numbers
        start_frame = int(start_timecode.get_frames())
        # PySceneDetect의 end_timecode는 다음 씬의 시작 프레임을 가리키므로, 현재 씬의 마지막 프레임은 end_frame - 1
        end_frame_raw = int(end_timecode.get_frames())
        end_frame = end_frame_raw - 1  # 다음 씬의 첫 프레임을 제외하기 위해 1을 뺌
        
        # 선택 구간이 지정된 경우, 씬을 선택 구간으로 제한
        if has_range and selection_start is not None and selection_end is not None:
            # 선택 구간을 완전히 벗어나는 씬은 제외
            if end_frame < selection_start or start_frame > selection_end:
                continue  # 이 씬은 선택 구간 밖이므로 건너뛰기
            
            # 씬의 시작과 끝을 선택 구간으로 제한
            start_frame = max(start_frame, selection_start)
            end_frame = min(end_frame, selection_end)
        
        # Convert timecode to seconds (end_frame에 맞춰 조정)
        start_time = start_frame / fps if fps > 0 else start_timecode.get_seconds()
        end_time = (end_frame + 1) / fps if fps > 0 else end_timecode.get_seconds()
        duration = end_time - start_time
        
        # Generate segment name
        segment_name = f"Scene_{idx:03d}"
        
        scene_msg = f"[PySceneDetect] Scene_{idx:03d}: 프레임 {start_frame} → {end_frame} ({start_time:.3f}s → {end_time:.3f}s, {duration:.3f}초)"
        print(scene_msg)
        if log_callback:
            log_callback(scene_msg)
        
        segment = {
            'start_frame': start_frame,
            'end_frame': end_frame,
            'start_time': start_time,
            'end_time': end_time,
            'duration': duration,
            'text': segment_name,
            'edited_text': segment_name,
            'roi_preview': None,  # No ROI preview for scene detection
            'detections': [],  # No OCR detections
        }
        segments.append(segment)
    
    video_manager.release()
    
    return segments


def detect_scene_cuts_with_opencv(
    video_path: str,
    threshold: float = 30.0,
    min_scene_len: int = 15,
    fps: Optional[float] = None,
    detect_background_change: bool = True,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[Dict]:
    """
    Fallback scene detection using OpenCV (if PySceneDetect is not available).
    Uses frame difference to detect scene cuts.
    
    Args:
        video_path: Path to the video file
        threshold: Sensitivity threshold for frame difference
        min_scene_len: Minimum scene length in frames
        fps: Video FPS (if None, will be detected automatically)
        detect_background_change: If True, focus on background changes (better for storyboard/animatic)
        start_frame: Optional frame index (0-based) to start analysis from.
        end_frame: Optional frame index (0-based, inclusive) to stop analysis at.
        log_callback: Optional callback function for logging (takes a string message)
    
    Returns:
        List of segment dictionaries (same format as detect_scene_cuts)
    """
    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")
    
    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    
    if fps <= 0:
        fps = 24.0
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    if total_frames <= 0:
        cap.release()
        raise ValueError(f"Could not determine frame count for video: {video_path}")

    # 선택 구간 설정 (함수 파라미터 저장)
    has_range = start_frame is not None or end_frame is not None
    selection_start = max(0, start_frame if start_frame is not None else 0)
    selection_end = min(end_frame if end_frame is not None else total_frames - 1, total_frames - 1)

    if selection_start >= total_frames or selection_start > selection_end:
        cap.release()
        return []

    if selection_start > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, selection_start)

    if has_range:
        range_msg = f"[OpenCV 컷 감지] 선택 구간: 프레임 {selection_start}~{selection_end}"
        print(range_msg)
        if log_callback:
            log_callback(range_msg)

    segments = []
    current_scene_start = selection_start
    prev_frame = None
    prev_background = None
    frame_count = selection_start
    
    # 배경 변화 감지를 위한 임계값 조정
    if detect_background_change:
        # 배경 변화 감지 시 더 민감하게 설정 (화이트/블랙 스토리보드용)
        # 임계값을 더 낮춰서 작은 배경 변화도 감지
        background_threshold = threshold * 0.15  # 0.25에서 0.15로 더 낮춤 (더 민감하게)
    else:
        background_threshold = threshold
    
    # 배경 변화 감지 시 이전 프레임들을 저장 (여러 프레임과 비교)
    frame_history = []  # 최근 N개 프레임 저장
    max_history = 5  # 최대 5개 프레임과 비교
    
    while True:
        if frame_count > selection_end:
            break
        ret, frame = cap.read()
        if not ret:
            break
        
        frame_count += 1
        
        # Convert to grayscale for comparison
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        if detect_background_change and prev_frame is not None:
            # 배경 변화 감지: 여러 방법을 조합하여 더 정확하게 감지
            height, width = gray.shape
            
            # 현재 프레임을 히스토리에 추가
            frame_history.append(gray.copy())
            if len(frame_history) > max_history:
                frame_history.pop(0)
            
            # 1. 전체 프레임 차이 (이전 프레임과)
            full_diff = cv2.absdiff(gray, prev_frame)
            full_diff_mean = full_diff.mean()
            full_diff_max = full_diff.max()
            
            # 2. 히스토그램 비교 (배경 변화를 더 잘 감지) - 가중치 증가
            hist_current = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist_prev = cv2.calcHist([prev_frame], [0], None, [256], [0, 256])
            
            # 히스토그램 상관관계 계산 (나중에 사용)
            hist_correlation = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_CORREL)
            
            # 여러 히스토그램 비교 방법 사용
            hist_correl = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_CORREL)
            hist_chi = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_CHISQR)
            hist_bhatt = cv2.compareHist(hist_current, hist_prev, cv2.HISTCMP_BHATTACHARYYA)
            
            # CORREL: 1에 가까울수록 유사, 0에 가까울수록 다름
            # CHISQR: 0에 가까울수록 유사, 클수록 다름
            # BHATTACHARYYA: 0에 가까울수록 유사, 1에 가까울수록 다름
            hist_similarity = (
                (1.0 - hist_correl) * 0.4 +      # CORREL 기반 차이
                min(hist_chi / 1000.0, 1.0) * 0.3 +  # CHISQR 기반 차이 (정규화)
                hist_bhatt * 0.3                 # BHATTACHARYYA 기반 차이
            )
            
            # 3. 여러 이전 프레임과 비교 (더 안정적인 감지)
            multi_frame_diff = []
            multi_hist_diff = []
            for hist_frame in frame_history[:-1]:  # 마지막 프레임(현재) 제외
                # 프레임 차이
                mfd = cv2.absdiff(gray, hist_frame).mean()
                multi_frame_diff.append(mfd)
                
                # 히스토그램 차이
                hist_hist = cv2.calcHist([hist_frame], [0], None, [256], [0, 256])
                mhd = cv2.compareHist(hist_current, hist_hist, cv2.HISTCMP_CORREL)
                multi_hist_diff.append(1.0 - mhd)
            
            # 여러 프레임과의 평균 차이
            avg_multi_frame_diff = sum(multi_frame_diff) / len(multi_frame_diff) if multi_frame_diff else 0
            avg_multi_hist_diff = sum(multi_hist_diff) / len(multi_hist_diff) if multi_hist_diff else 0
            
            # 4. 중앙 영역 유사도 계산 (팬/줌 감지용)
            center_margin = int(min(height, width) * 0.3)  # 중앙 30% 영역
            center_region = gray[center_margin:height-center_margin, center_margin:width-center_margin]
            prev_center = prev_frame[center_margin:height-center_margin, center_margin:width-center_margin]
            center_diff = cv2.absdiff(center_region, prev_center).mean()
            
            # 중앙 영역 히스토그램 비교
            center_hist_current = cv2.calcHist([center_region], [0], None, [256], [0, 256])
            center_hist_prev = cv2.calcHist([prev_center], [0], None, [256], [0, 256])
            center_hist_similarity = cv2.compareHist(center_hist_current, center_hist_prev, cv2.HISTCMP_CORREL)
            center_similarity = 1.0 - center_hist_similarity  # 0에 가까울수록 유사
            
            # 5. 가장자리 영역 차이 (배경 영역) - 팬/줌 시 크게 변함
            edge_margin = int(min(height, width) * 0.2)  # 20%
            top_edge = gray[0:edge_margin, :]
            bottom_edge = gray[height-edge_margin:height, :]
            left_edge = gray[:, 0:edge_margin]
            right_edge = gray[:, width-edge_margin:width]
            
            prev_top = prev_frame[0:edge_margin, :]
            prev_bottom = prev_frame[height-edge_margin:height, :]
            prev_left = prev_frame[:, 0:edge_margin]
            prev_right = prev_frame[:, width-edge_margin:width]
            
            edge_diff_top = cv2.absdiff(top_edge, prev_top).mean()
            edge_diff_bottom = cv2.absdiff(bottom_edge, prev_bottom).mean()
            edge_diff_left = cv2.absdiff(left_edge, prev_left).mean()
            edge_diff_right = cv2.absdiff(right_edge, prev_right).mean()
            
            # 가장자리 영역의 최대 차이
            edge_diff_max = max(edge_diff_top, edge_diff_bottom, edge_diff_left, edge_diff_right)
            
            # 팬/줌 감지: 가장자리는 크게 변하지만 중앙은 유사한 경우
            # 배경만 팬하는 경우도 감지: 전체 히스토그램은 유사하지만 프레임이 이동한 경우
            # 배경이 확연하게 바뀌는 경우를 잘못 팬/줌으로 판단하지 않도록 더 엄격한 조건 적용
            is_pan_or_zoom = False
            
            # 조건 1: 가장자리 변화가 크고 중앙은 유사한 경우 (일반 팬/줌)
            # 히스토그램이 매우 유사해야 함 (같은 배경이 이동한 경우)
            if edge_diff_max > full_diff_mean * 1.5 and center_similarity < 0.3 and hist_correlation > 0.85:
                is_pan_or_zoom = True
            
            # 조건 2: 배경만 팬하는 경우 감지
            # - 전체 히스토그램은 매우 유사해야 함 (같은 배경) - 0.7에서 0.85로 상향
            # - 전체 프레임 차이는 크지만 (위치 이동)
            # - 히스토그램 유사도는 높음 (같은 배경)
            # hist_correlation은 위에서 이미 계산됨
            if not is_pan_or_zoom and hist_correlation > 0.85 and full_diff_mean > 15.0:  # 0.7에서 0.85로 상향
                # 히스토그램이 0.7 이상 유사하고 (같은 배경), 전체 차이가 15 이상 (위치 이동)
                # 중앙 영역을 여러 위치에서 비교하여 이동 패턴 감지
                center_h, center_w = center_region.shape
                if center_h > 20 and center_w > 20:
                    # 중앙 영역을 작은 패치로 나누어 비교
                    patch_size = min(center_h // 3, center_w // 3, 30)
                    patch_h = center_h - patch_size
                    patch_w = center_w - patch_size
                    
                    if patch_h > 0 and patch_w > 0:
                        # 현재 프레임의 중앙 패치
                        current_patch = center_region[patch_h//2:patch_h//2+patch_size, patch_w//2:patch_w//2+patch_size]
                        
                        # 이전 프레임의 여러 위치에서 유사한 패치 찾기
                        best_match = float('inf')  # 최소값 찾기 위해 큰 값으로 초기화
                        search_range = min(20, patch_size)
                        for dy in range(-search_range, search_range, 5):
                            for dx in range(-search_range, search_range, 5):
                                y1 = max(0, patch_h//2 + dy)
                                y2 = min(center_h - patch_size, y1 + patch_size)
                                x1 = max(0, patch_w//2 + dx)
                                x2 = min(center_w - patch_size, x1 + patch_size)
                                
                                if y2 - y1 == patch_size and x2 - x1 == patch_size:
                                    prev_patch = prev_center[y1:y2, x1:x2]
                                    patch_diff = cv2.absdiff(current_patch, prev_patch).mean()
                                    if patch_diff < best_match:
                                        best_match = patch_diff
                        
                        # 유사한 패치를 찾았으면 팬으로 판단
                        if best_match < 15.0:  # 패치 차이가 작으면 같은 배경이 이동한 것
                            is_pan_or_zoom = True
            
            
            # 6. 중앙 영역 제외한 배경 영역 차이 (팬/줌이 아닐 때만 사용)
            bg_region = gray.copy()
            bg_region[center_margin:height-center_margin, center_margin:width-center_margin] = 0
            prev_bg_region = prev_frame.copy()
            prev_bg_region[center_margin:height-center_margin, center_margin:width-center_margin] = 0
            bg_diff = cv2.absdiff(bg_region, prev_bg_region).mean()
            
            # 7. 종합 점수 계산 (가중 평균) - 팬/줌 감지 시 가장자리 가중치 감소
            # 배경이 완전히 다를 때 히스토그램 차이가 가장 명확함
            if is_pan_or_zoom:
                # 팬/줌인 경우: 중앙 영역을 더 중요하게, 가장자리는 덜 중요하게
                diff_value = (
                    full_diff_mean * 0.2 +              # 전체 차이 20%
                    full_diff_max * 0.05 +               # 최대 차이 5%
                    hist_similarity * 60.0 * 0.35 +     # 히스토그램 차이 35%
                    center_diff * 0.15 +                # 중앙 영역 차이 15% (신규, 팬/줌 감지용)
                    center_similarity * 30.0 * 0.1 +    # 중앙 유사도 10% (신규)
                    avg_multi_frame_diff * 0.1 +         # 다중 프레임 차이 10%
                    avg_multi_hist_diff * 30.0 * 0.05 + # 다중 히스토그램 차이 5% (감소)
                    edge_diff_max * 0.0 +                # 가장자리 차이 0% (팬/줌 시 무시)
                    bg_diff * 0.0                        # 배경 영역 차이 0% (팬/줌 시 무시)
                )
            else:
                # 일반 씬 전환: 배경 변화 감지를 위해 히스토그램 차이 가중치 증가
                diff_value = (
                    full_diff_mean * 0.2 +               # 전체 차이 20% (25%에서 감소)
                    full_diff_max * 0.05 +               # 최대 차이 5%
                    hist_similarity * 60.0 * 0.5 +       # 히스토그램 차이 50% (40%에서 증가) - 배경 변화에 가장 중요
                    center_diff * 0.05 +                 # 중앙 영역 차이 5%
                    avg_multi_frame_diff * 0.1 +         # 다중 프레임 차이 10%
                    avg_multi_hist_diff * 30.0 * 0.05 +  # 다중 히스토그램 차이 5% (10%에서 감소)
                    edge_diff_max * 0.03 +               # 가장자리 차이 3% (5%에서 감소)
                    bg_diff * 0.02                       # 배경 영역 차이 2% (5%에서 감소)
                )
            
            # 디버깅 로그 (매 30프레임마다 또는 컷 감지 시)
            if frame_count % 30 == 0 or diff_value > background_threshold:
                pan_zoom_text = " [팬/줌]" if is_pan_or_zoom else ""
                log_msg = f"[Frame {frame_count}] diff={diff_value:.2f} (threshold={background_threshold:.2f}){pan_zoom_text}"
                print(log_msg)
                if log_callback:
                    log_callback(log_msg)
                
                detail_msg = (
                    f"  - 전체차이: {full_diff_mean:.2f}, 최대차이: {full_diff_max:.2f}\n"
                    f"  - 히스토그램차이: {hist_similarity:.3f}, 다중히스토그램: {avg_multi_hist_diff:.3f}\n"
                    f"  - 중앙차이: {center_diff:.2f}, 중앙유사도: {center_similarity:.3f}\n"
                    f"  - 가장자리차이: {edge_diff_max:.2f}, 배경차이: {bg_diff:.2f}"
                )
                print(detail_msg)
                if log_callback:
                    log_callback(detail_msg)
                
                if diff_value > background_threshold:
                    cut_msg = f"  >>> 컷 감지! (diff={diff_value:.2f} > threshold={background_threshold:.2f})"
                    print(cut_msg)
                    if log_callback:
                        log_callback(cut_msg)
        elif prev_frame is not None:
            # 일반 모드: 전체 프레임 차이 계산
            diff = cv2.absdiff(gray, prev_frame)
            diff_value = diff.mean()
        else:
            diff_value = 0
        
        if prev_frame is not None:
            # Check if this is a scene cut
            if diff_value > background_threshold and (frame_count - current_scene_start) >= min_scene_len:
                # End current scene and start new one
                if current_scene_start < frame_count - 1:
                    start_frame = current_scene_start
                    end_frame = frame_count - 1
                    
                    # 선택 구간이 지정된 경우, 씬을 선택 구간으로 제한
                    if has_range:
                        # 선택 구간을 완전히 벗어나는 씬은 제외
                        if end_frame < selection_start or start_frame > selection_end:
                            # 이 씬은 선택 구간 밖이므로 건너뛰기
                            pass
                        else:
                            # 씬의 시작과 끝을 선택 구간으로 제한
                            start_frame = max(start_frame, selection_start)
                            end_frame = min(end_frame, selection_end)
                            
                            start_time = start_frame / fps
                            end_time = (end_frame + 1) / fps
                            duration = end_time - start_time
                            
                            segment_idx = len(segments) + 1
                            segment_name = f"Scene_{segment_idx:03d}"
                            
                            cut_detect_msg = f"[컷 감지] Scene_{segment_idx:03d}: 프레임 {start_frame} → {end_frame} ({duration:.3f}초)"
                            print(cut_detect_msg)
                            if log_callback:
                                log_callback(cut_detect_msg)
                            
                            segment = {
                                'start_frame': start_frame,
                                'end_frame': end_frame,
                                'start_time': start_time,
                                'end_time': end_time,
                                'duration': duration,
                                'text': segment_name,
                                'edited_text': segment_name,
                                'roi_preview': None,
                                'detections': [],
                            }
                            segments.append(segment)
                    else:
                        # 선택 구간이 없는 경우 기존 로직 유지
                        start_time = start_frame / fps
                        end_time = end_frame / fps
                        duration = end_time - start_time
                        
                        segment_idx = len(segments) + 1
                        segment_name = f"Scene_{segment_idx:03d}"
                        
                        cut_detect_msg = f"[컷 감지] Scene_{segment_idx:03d}: 프레임 {start_frame} → {end_frame} ({duration:.3f}초)"
                        print(cut_detect_msg)
                        if log_callback:
                            log_callback(cut_detect_msg)
                        
                        segment = {
                            'start_frame': start_frame,
                            'end_frame': end_frame,
                            'start_time': start_time,
                            'end_time': end_time,
                            'duration': duration,
                            'text': segment_name,
                            'edited_text': segment_name,
                            'roi_preview': None,
                            'detections': [],
                        }
                        segments.append(segment)
                
                current_scene_start = frame_count
                new_scene_msg = f"[새 씬 시작] 프레임 {frame_count}부터"
                print(new_scene_msg)
                if log_callback:
                    log_callback(new_scene_msg)
        
        prev_frame = gray.copy()
    
    # Add final scene
    if current_scene_start < frame_count:
        start_frame = current_scene_start
        end_frame = frame_count - 1
        
        # 선택 구간이 지정된 경우, 마지막 씬을 선택 구간으로 제한
        if has_range:
            # 선택 구간을 완전히 벗어나는 씬은 제외
            if end_frame < selection_start or start_frame > selection_end:
                # 마지막 씬이 선택 구간 밖이면 건너뛰기
                pass
            else:
                # 씬의 시작과 끝을 선택 구간으로 제한
                start_frame = max(start_frame, selection_start)
                end_frame = min(end_frame, selection_end)
                
                start_time = start_frame / fps
                end_time = (end_frame + 1) / fps
                duration = end_time - start_time
                
                segment_idx = len(segments) + 1
                segment_name = f"Scene_{segment_idx:03d}"
                
                last_scene_msg = f"[마지막 씬] Scene_{segment_idx:03d}: 프레임 {start_frame} → {end_frame} ({duration:.3f}초)"
                print(last_scene_msg)
                if log_callback:
                    log_callback(last_scene_msg)
                
                segment = {
                    'start_frame': start_frame,
                    'end_frame': end_frame,
                    'start_time': start_time,
                    'end_time': end_time,
                    'duration': duration,
                    'text': segment_name,
                    'edited_text': segment_name,
                    'roi_preview': None,
                    'detections': [],
                }
                segments.append(segment)
        else:
            # 선택 구간이 없는 경우 기존 로직 유지
            start_time = start_frame / fps
            end_time = end_frame / fps
            duration = end_time - start_time
            
            segment_idx = len(segments) + 1
            segment_name = f"Scene_{segment_idx:03d}"
            
            last_scene_msg = f"[마지막 씬] Scene_{segment_idx:03d}: 프레임 {start_frame} → {end_frame} ({duration:.3f}초)"
            print(last_scene_msg)
            if log_callback:
                log_callback(last_scene_msg)
            
            segment = {
                'start_frame': start_frame,
                'end_frame': end_frame,
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'text': segment_name,
                'edited_text': segment_name,
                'roi_preview': None,
                'detections': [],
            }
            segments.append(segment)
    
    complete_msg = f"[컷 감지 완료] 총 {len(segments)}개 씬 감지됨"
    print(complete_msg)
    if log_callback:
        log_callback(complete_msg)
    
    cap.release()
    
    return segments
