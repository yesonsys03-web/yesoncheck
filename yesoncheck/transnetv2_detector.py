"""TransNetV2-based scene detection module for gradual transitions (dissolves, fades)."""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from transnetv2 import TransNetV2
    TRANSNETV2_AVAILABLE = True
except ImportError:
    TRANSNETV2_AVAILABLE = False
    print("Warning: TransNetV2 not available. Install with: pip install git+https://github.com/soCzech/TransNetV2.git")


def detect_scene_cuts_transnetv2(
    video_path: str,
    threshold: float = 0.5,
    min_scene_len: int = 15,
    fps: Optional[float] = None,
    detect_gradual_transitions: bool = True,
    post_process_histogram: bool = False,
    start_frame: Optional[int] = None,
    end_frame: Optional[int] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[Dict]:
    """
    Detect scene cuts in a video using TransNetV2 (deep learning-based).

    TransNetV2 is specifically designed to detect both:
    - Hard cuts (sudden scene changes)
    - Gradual transitions (dissolves, fades)

    Args:
        video_path: Path to the video file
        threshold: Sensitivity threshold for scene detection (0.0-1.0, lower = more sensitive)
        min_scene_len: Minimum scene length in frames
        fps: Video FPS (if None, will be detected automatically)
        detect_gradual_transitions: If True, also detect gradual transitions (dissolves, fades)
        post_process_histogram: If True, apply histogram-based post-processing to find additional cuts
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
    if not TRANSNETV2_AVAILABLE:
        raise ImportError(
            "TransNetV2 is not installed. "
            "Install with: pip install git+https://github.com/soCzech/TransNetV2.git"
        )

    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Load TransNetV2 model
    log_msg = "TransNetV2 모델 로드 중..."
    print(log_msg)
    if log_callback:
        log_callback(log_msg)

    try:
        model = TransNetV2()
    except Exception as e:
        raise RuntimeError(f"TransNetV2 모델 로드 실패: {e}")

    # Open video to get basic info
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {video_path}")

    if fps is None:
        fps = cap.get(cv2.CAP_PROP_FPS) or 24.0

    if fps <= 0:
        fps = 24.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    info_msg = f"[TransNetV2] 비디오 정보: {total_frames}프레임, {fps:.2f}fps, {width}x{height}"
    print(info_msg)
    if log_callback:
        log_callback(info_msg)

    has_range = start_frame is not None or end_frame is not None
    selection_start = max(0, start_frame if start_frame is not None else 0)
    selection_end = min(end_frame if end_frame is not None else total_frames - 1, total_frames - 1)
    if selection_start >= total_frames:
        selection_start = max(0, total_frames - 1)
    if selection_start > selection_end:
        selection_end = selection_start

    frames_to_read = (selection_end - selection_start + 1) if total_frames > 0 else 0
    if frames_to_read <= 0:
        cap.release()
        raise ValueError("분석할 수 있는 프레임이 없습니다.")

    if selection_start > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, selection_start)

    if has_range:
        range_msg = f"[TransNetV2] 선택 구간 분석: 프레임 {selection_start}~{selection_end}"
        print(range_msg)
        if log_callback:
            log_callback(range_msg)

    # Extract frames for TransNetV2
    # TransNetV2 expects RGB frames in shape (frames, 48, 27, 3)
    # Note: TransNetV2 requires specific input size (27x48 pixels)
    TRANSNETV2_HEIGHT = 27
    TRANSNETV2_WIDTH = 48

    log_msg = f"프레임 추출 중 ({TRANSNETV2_WIDTH}x{TRANSNETV2_HEIGHT}로 리사이즈)..."
    print(log_msg)
    if log_callback:
        log_callback(log_msg)

    frames = []
    frame_count = 0
    while frame_count < frames_to_read:
        ret, frame = cap.read()
        if not ret:
            break

        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Resize to TransNetV2 input size (48x27)
        frame_resized = cv2.resize(frame_rgb, (TRANSNETV2_WIDTH, TRANSNETV2_HEIGHT), interpolation=cv2.INTER_AREA)
        frames.append(frame_resized)
        frame_count += 1

        # Log progress every 100 frames
        if frame_count % 100 == 0:
            progress_msg = f"프레임 추출: {selection_start + frame_count}/{selection_start + frames_to_read}"
            print(progress_msg)
            if log_callback:
                log_callback(progress_msg)

    cap.release()

    if not frames:
        raise ValueError("비디오에서 프레임을 추출할 수 없습니다.")

    actual_range_end = selection_start + len(frames) - 1

    extract_msg = f"총 {len(frames)}개 프레임 추출 완료 (프레임 {selection_start}~{actual_range_end})"
    print(extract_msg)
    if log_callback:
        log_callback(extract_msg)

    # Convert to numpy array with shape (frames, 27, 48, 3)
    frames_array = np.array(frames, dtype=np.uint8)
    shape_msg = f"프레임 배열 형태: {frames_array.shape}"
    print(shape_msg)
    if log_callback:
        log_callback(shape_msg)

    # Run TransNetV2 prediction
    predict_msg = "TransNetV2로 씬 전환 감지 중..."
    print(predict_msg)
    if log_callback:
        log_callback(predict_msg)

    try:
        # predictions shape: (frames, 1) for single-frame predictions
        # gradual_predictions shape: (frames, 1) for gradual transition predictions
        predictions, gradual_predictions = model.predict_frames(frames_array)
    except Exception as e:
        raise RuntimeError(f"TransNetV2 예측 실패: {e}")

    predict_done_msg = "TransNetV2 예측 완료"
    print(predict_done_msg)
    if log_callback:
        log_callback(predict_done_msg)

    # Find scene boundaries
    # predictions is a numpy array with shape (frames,) or (frames, 1)
    # Flatten to 1D if necessary
    if len(predictions.shape) > 1:
        predictions = predictions.flatten()
    if len(gradual_predictions.shape) > 1:
        gradual_predictions = gradual_predictions.flatten()

    # Detect scene cuts based on threshold
    # Hard cuts: predictions > threshold
    # Gradual transitions: gradual_predictions > threshold (if enabled)
    scene_cuts = []

    for i in range(len(predictions)):
        is_hard_cut = predictions[i] > threshold
        is_gradual_cut = detect_gradual_transitions and gradual_predictions[i] > threshold

        if is_hard_cut or is_gradual_cut:
            cut_type = "하드 컷" if is_hard_cut else "점진적 전환 (디졸브/페이드)"
            scene_cuts.append({
                'frame': selection_start + i,
                'score': float(predictions[i]),
                'gradual_score': float(gradual_predictions[i]),
                'type': cut_type
            })

    detect_msg = f"[TransNetV2] {len(scene_cuts)}개 컷 후보 감지됨 (threshold={threshold})"
    print(detect_msg)
    if log_callback:
        log_callback(detect_msg)

    # Merge nearby cuts (within min_scene_len frames)
    merged_cuts = []
    if scene_cuts:
        current_cut = scene_cuts[0]
        for next_cut in scene_cuts[1:]:
            if next_cut['frame'] - current_cut['frame'] < min_scene_len:
                # Keep the cut with higher score
                if next_cut['score'] + next_cut['gradual_score'] > current_cut['score'] + current_cut['gradual_score']:
                    current_cut = next_cut
            else:
                merged_cuts.append(current_cut)
                current_cut = next_cut
        merged_cuts.append(current_cut)

    merge_msg = f"[TransNetV2] 최소 씬 길이({min_scene_len}프레임) 적용 후 {len(merged_cuts)}개 컷"
    print(merge_msg)
    if log_callback:
        log_callback(merge_msg)

    # Convert to segment format
    segments = []

    # Add first scene (from selection_start to first cut, including cut frame)
    if merged_cuts:
        first_cut_frame = merged_cuts[0]['frame']
        # 첫 번째 씬은 항상 selection_start부터 시작 (첫 번째 컷이 selection_start와 같아도 생성)
        if first_cut_frame >= selection_start:
            scene_end = min(first_cut_frame, actual_range_end)
            # 첫 번째 씬은 컷 프레임까지 포함
            segment = {
                'start_frame': selection_start,
                'end_frame': scene_end,
                'start_time': selection_start / fps,
                'end_time': scene_end / fps,
                'duration': max(0.0, (scene_end - selection_start) / fps),
                'text': 'Scene_001',
                'edited_text': 'Scene_001',
                'roi_preview': None,
                'detections': [],
            }
            segments.append(segment)

            first_msg = (
                f"[TransNetV2] Scene_001: 프레임 {selection_start + 1} → {segment['end_frame'] + 1} "
                f"({segment['start_time']:.3f}s → {segment['end_time']:.3f}s)"
            )
            print(first_msg)
            if log_callback:
                log_callback(first_msg)

    # Add scenes between cuts
    for idx, cut in enumerate(merged_cuts[:-1]):
        # 컷 프레임은 이전 씬에 포함되므로, 다음 씬은 cut+1부터 시작
        start_frame = max(cut['frame'] + 1, selection_start)
        end_frame = min(merged_cuts[idx + 1]['frame'], actual_range_end)  # 다음 컷 프레임도 포함

        if start_frame > actual_range_end:
            break
        if end_frame < start_frame:
            continue

        start_time = start_frame / fps
        end_time = end_frame / fps
        duration = max(0.0, end_time - start_time)

        segment_name = f"Scene_{len(segments) + 1:03d}"

        cut_info_msg = (
            f"[TransNetV2] {segment_name}: 프레임 {start_frame + 1} → {end_frame + 1} "
            f"({start_time:.3f}s → {end_time:.3f}s, {duration:.3f}초) [{cut['type']}]"
        )
        print(cut_info_msg)
        if log_callback:
            log_callback(cut_info_msg)

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

    # Add last scene (from last cut to end)
    if merged_cuts:
        last_cut_frame = merged_cuts[-1]['frame']
        # 마지막 컷 프레임은 이전 씬에 포함되므로, 마지막 씬은 cut+1부터 시작
        last_start_frame = max(last_cut_frame + 1, selection_start)
        if last_start_frame <= actual_range_end:
            segment_name = f"Scene_{len(segments) + 1:03d}"
            start_time = last_start_frame / fps
            end_time = actual_range_end / fps
            duration = max(0.0, end_time - start_time)

            last_msg = (
                f"[TransNetV2] {segment_name}: 프레임 {last_start_frame + 1} → {actual_range_end + 1} "
                f"({start_time:.3f}s → {end_time:.3f}s, {duration:.3f}초)"
            )
            print(last_msg)
            if log_callback:
                log_callback(last_msg)

            segment = {
                'start_frame': last_start_frame,
                'end_frame': actual_range_end,
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration,
                'text': segment_name,
                'edited_text': segment_name,
                'roi_preview': None,
                'detections': [],
            }
            segments.append(segment)

    # If no cuts detected, add entire selection as one scene
    if not segments:
        segment = {
            'start_frame': selection_start,
            'end_frame': actual_range_end,
            'start_time': selection_start / fps if fps else 0.0,
            'end_time': actual_range_end / fps if fps else 0.0,
            'duration': max(0.0, (actual_range_end - selection_start) / fps) if fps else 0.0,
            'text': 'Scene_001',
            'edited_text': 'Scene_001',
            'roi_preview': None,
            'detections': [],
        }
        segments.append(segment)

        no_cuts_msg = "[TransNetV2] 컷이 감지되지 않아 전체 비디오를 하나의 씬으로 처리"
        print(no_cuts_msg)
        if log_callback:
            log_callback(no_cuts_msg)

    # 히스토그램 기반 후처리 (추가 컷 감지)
    if post_process_histogram and segments:
        post_msg = "[TransNetV2] 히스토그램 기반 후처리 시작..."
        print(post_msg)
        if log_callback:
            log_callback(post_msg)

        additional_cuts = _find_additional_cuts_with_histogram(
            video_path, segments, fps, min_scene_len, log_callback
        )

        if additional_cuts:
            # 기존 컷과 새로운 컷 병합
            all_cut_frames = set()
            for seg in segments:
                end_frame = seg.get('end_frame')
                if end_frame is not None:
                    all_cut_frames.add(end_frame)

            all_cut_frames.update(additional_cuts)
            all_cut_frames = sorted(all_cut_frames)

            # segments 재생성
            segments = _rebuild_segments_from_cuts(
                all_cut_frames, len(frames), fps, frame_offset=selection_start
            )

            post_complete_msg = f"[TransNetV2] 히스토그램 후처리 완료: {len(additional_cuts)}개 추가 컷 감지"
            print(post_complete_msg)
            if log_callback:
                log_callback(post_complete_msg)

    complete_msg = f"[TransNetV2] 컷 감지 완료: 총 {len(segments)}개 씬 감지됨"
    print(complete_msg)
    if log_callback:
        log_callback(complete_msg)

    return segments


def _find_additional_cuts_with_histogram(
    video_path: str,
    segments: List[Dict],
    fps: float,
    min_scene_len: int,
    log_callback: Optional[Callable[[str], None]] = None
) -> List[int]:
    """
    히스토그램 기반으로 세그먼트 내 추가 컷을 찾습니다.

    Args:
        video_path: 비디오 파일 경로
        segments: TransNetV2로 감지된 세그먼트 리스트
        fps: 비디오 FPS
        min_scene_len: 최소 씬 길이 (프레임)
        log_callback: 로그 콜백 함수

    Returns:
        추가 컷 프레임 번호 리스트
    """
    additional_cuts = []
    histogram_threshold = 0.7  # 히스토그램 상관계수 임계값 (0.7 이하면 다른 장면으로 판단)

    # 병렬 처리를 위한 세그먼트 분석 함수
    def analyze_segment(seg_idx, segment):
        """단일 세그먼트 분석 (병렬 실행용)"""
        segment_cuts = []
        cap_local = cv2.VideoCapture(video_path)
        if not cap_local.isOpened():
            return segment_cuts

        try:
            start_frame = int(segment.get('start_frame', 0))
            end_frame = int(segment.get('end_frame', start_frame))
            segment_length = end_frame - start_frame + 1

            # 세그먼트가 충분히 길 경우에만 분석 (최소 길이의 3배 이상)
            if segment_length < min_scene_len * 3:
                return segment_cuts

            # 적응형 샘플링
            if segment_length < 100:
                sample_interval = max(1, segment_length // 10)
            elif segment_length < 300:
                sample_interval = max(1, segment_length // 15)
            else:
                sample_interval = max(1, segment_length // 20)

            prev_hist = None
            prev_frame_idx = None

            for frame_offset in range(0, segment_length, sample_interval):
                frame_idx = start_frame + frame_offset
                cap_local.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap_local.read()

                if not ret:
                    break

                # 히스토그램 계산 최적화
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
                current_hist = cv2.normalize(hist, hist).flatten()

                if prev_hist is not None:
                    correlation = np.corrcoef(prev_hist, current_hist)[0, 1]

                    if correlation < histogram_threshold:
                        precise_cut = _find_precise_cut_frame(
                            cap_local, prev_frame_idx, frame_idx, histogram_threshold
                        )

                        if precise_cut and precise_cut > start_frame + min_scene_len:
                            if not segment_cuts or precise_cut - segment_cuts[-1] >= min_scene_len:
                                segment_cuts.append(precise_cut)

                prev_hist = current_hist
                prev_frame_idx = frame_idx

        finally:
            cap_local.release()

        return segment_cuts

    # 병렬 처리로 세그먼트 분석 (최대 4개 스레드)
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(analyze_segment, idx, seg): idx
            for idx, seg in enumerate(segments)
        }

        for future in as_completed(futures):
            seg_idx = futures[future]
            try:
                cuts = future.result()
                if cuts:
                    additional_cuts.extend(cuts)
                    for cut in cuts:
                        cut_msg = f"[히스토그램 후처리] Segment {seg_idx+1}에서 추가 컷 감지: 프레임 {cut}"
                        print(cut_msg)
                        if log_callback:
                            log_callback(cut_msg)
            except Exception as e:
                error_msg = f"[히스토그램 후처리] Segment {seg_idx+1} 분석 중 오류: {e}"
                print(error_msg)
                if log_callback:
                    log_callback(error_msg)

    # 정렬 및 중복 제거
    additional_cuts = sorted(set(additional_cuts))

    return additional_cuts


def _find_precise_cut_frame(
    cap: cv2.VideoCapture,
    start_frame: int,
    end_frame: int,
    threshold: float
) -> Optional[int]:
    """
    두 프레임 사이에서 정확한 컷 프레임을 찾습니다.

    최적화:
    - 순차 읽기로 seek 오버헤드 제거
    - 이진 탐색 방식 적용 (더 빠른 컷 발견)

    Args:
        cap: OpenCV VideoCapture 객체
        start_frame: 시작 프레임
        end_frame: 끝 프레임
        threshold: 히스토그램 상관계수 임계값

    Returns:
        컷 프레임 번호 (없으면 None)
    """
    # 범위가 작으면 선형 탐색
    frame_range = end_frame - start_frame + 1
    if frame_range <= 5:
        return _linear_search_cut(cap, start_frame, end_frame, threshold)

    # 이진 탐색으로 컷 프레임 좁히기
    mid_frame = (start_frame + end_frame) // 2

    # 시작과 중간 프레임 비교
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    ret_start, frame_start = cap.read()
    if not ret_start:
        return None

    cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame)
    ret_mid, frame_mid = cap.read()
    if not ret_mid:
        return None

    # 히스토그램 비교
    gray_start = cv2.cvtColor(frame_start, cv2.COLOR_BGR2GRAY)
    hist_start = cv2.calcHist([gray_start], [0], None, [32], [0, 256])
    hist_start = cv2.normalize(hist_start, hist_start).flatten()

    gray_mid = cv2.cvtColor(frame_mid, cv2.COLOR_BGR2GRAY)
    hist_mid = cv2.calcHist([gray_mid], [0], None, [32], [0, 256])
    hist_mid = cv2.normalize(hist_mid, hist_mid).flatten()

    correlation = np.corrcoef(hist_start, hist_mid)[0, 1]

    # 컷이 전반부에 있으면 전반부 탐색
    if correlation < threshold:
        return _linear_search_cut(cap, start_frame, mid_frame, threshold)

    # 컷이 후반부에 있으면 후반부 탐색
    return _linear_search_cut(cap, mid_frame, end_frame, threshold)


def _linear_search_cut(
    cap: cv2.VideoCapture,
    start_frame: int,
    end_frame: int,
    threshold: float
) -> Optional[int]:
    """선형 탐색으로 정확한 컷 프레임 찾기 (순차 읽기 최적화)"""
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    prev_hist = None

    for offset in range(end_frame - start_frame + 1):
        ret, frame = cap.read()  # 순차 읽기 (seek 없음)
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
        current_hist = cv2.normalize(hist, hist).flatten()

        if prev_hist is not None:
            correlation = np.corrcoef(prev_hist, current_hist)[0, 1]
            if correlation < threshold:
                return start_frame + offset

        prev_hist = current_hist

    return None


def _rebuild_segments_from_cuts(
    cut_frames: List[int],
    total_frames: int,
    fps: float,
    frame_offset: int = 0
) -> List[Dict]:
    """
    컷 프레임 리스트로부터 세그먼트를 재생성합니다.

    Args:
        cut_frames: 정렬된 컷 프레임 리스트 (절대 프레임 번호)
        total_frames: 분석한 프레임 개수
        fps: 비디오 FPS
        frame_offset: 프레임 오프셋 (선택 구간 시작 프레임)

    Returns:
        세그먼트 리스트
    """
    segments = []
    relative_cuts = [max(0, cut - frame_offset) for cut in cut_frames]

    # 첫 번째 씬
    if relative_cuts:
        first_cut = relative_cuts[0]
        if first_cut > 0:
            segments.append({
                'start_frame': 0,
                'end_frame': first_cut,
                'start_time': 0.0,
                'end_time': first_cut / fps,
                'duration': first_cut / fps,
                'text': 'Scene_001',
                'edited_text': 'Scene_001',
                'roi_preview': None,
                'detections': [],
            })

    # 중간 씬들
    for idx in range(len(relative_cuts) - 1):
        start_frame = relative_cuts[idx] + 1
        end_frame = relative_cuts[idx + 1]
        start_time = start_frame / fps
        end_time = end_frame / fps

        segments.append({
            'start_frame': start_frame,
            'end_frame': end_frame,
            'start_time': start_time,
            'end_time': end_time,
            'duration': end_time - start_time,
            'text': f'Scene_{len(segments) + 1:03d}',
            'edited_text': f'Scene_{len(segments) + 1:03d}',
            'roi_preview': None,
            'detections': [],
        })

    # 마지막 씬
    if relative_cuts:
        last_cut = relative_cuts[-1]
        if last_cut + 1 < total_frames:
            start_frame = last_cut + 1
            start_time = start_frame / fps
            end_time = (total_frames - 1) / fps

            segments.append({
                'start_frame': start_frame,
                'end_frame': total_frames - 1,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time,
                'text': f'Scene_{len(segments) + 1:03d}',
                'edited_text': f'Scene_{len(segments) + 1:03d}',
                'roi_preview': None,
                'detections': [],
            })

    # 컷이 하나도 없으면 전체 비디오를 하나의 씬으로
    if not segments:
        segments.append({
            'start_frame': 0,
            'end_frame': total_frames - 1,
            'start_time': 0.0,
            'end_time': (total_frames - 1) / fps,
            'duration': (total_frames - 1) / fps,
            'text': 'Scene_001',
            'edited_text': 'Scene_001',
            'roi_preview': None,
            'detections': [],
        })

    if frame_offset != 0:
        for seg in segments:
            seg['start_frame'] += frame_offset
            seg['end_frame'] += frame_offset
            seg['start_time'] = seg['start_frame'] / fps
            seg['end_time'] = seg['end_frame'] / fps
            seg['duration'] = seg['end_time'] - seg['start_time']

    return segments
