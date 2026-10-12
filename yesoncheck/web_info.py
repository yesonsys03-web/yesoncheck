"""Web export functionality for OCR analysis results."""

import base64
import os
import webbrowser
import sys
import subprocess
from datetime import datetime


def generate_web_report(segments, video_path, fps, total_frames, ocr_mode='titmouse'):
    """
    OCR 분석 결과를 웹 페이지로 생성합니다.

    Args:
        segments: OCR 세그먼트 리스트
        video_path: 비디오 파일 경로
        fps: 프레임률
        total_frames: 전체 프레임 수
        ocr_mode: OCR 모드 ('king', 'titmouse', 'bento', 'animatic', 'animatic2')

    Returns:
        str: 생성된 HTML 파일 경로
    """

    # 세그먼트가 없으면 종료
    if not segments:
        print("[웹 분석] 세그먼트가 없습니다.")
        return None

    # HTML 파일 경로 생성 (같은 파일이 있으면 오버라이트)
    video_name = os.path.splitext(os.path.basename(video_path))[0] if video_path else "unknown"
    html_filename = f"{video_name}_ocr_report.html"

    # 홈 폴더의 yesoncheck_html 디렉토리에 저장
    home_dir = os.path.expanduser("~")
    output_dir = os.path.join(home_dir, "yesoncheck_html")

    # 디렉토리가 없으면 생성
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"[웹 분석] 디렉토리 생성: {output_dir}")

    html_path = os.path.join(output_dir, html_filename)
    
    # 같은 파일이 있으면 오버라이트 (기존 파일 삭제)
    if os.path.exists(html_path):
        try:
            os.remove(html_path)
            print(f"[웹 분석] 기존 파일 삭제: {html_path}")
        except Exception as e:
            print(f"[웹 분석] 기존 파일 삭제 실패: {e}")

    # 비디오 파일 절대 경로 사용 (HTML이 다른 위치에 저장되므로)
    video_absolute_path = os.path.abspath(video_path) if video_path else None

    # HTML 생성
    html_content = _generate_html(segments, video_name, fps, total_frames, ocr_mode, video_absolute_path)

    # 파일 저장
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"[웹 분석] HTML 생성 완료: {html_path}")
        return html_path
    except Exception as e:
        print(f"[웹 분석] HTML 저장 실패: {e}")
        return None


def _generate_html(segments, video_name, fps, total_frames, ocr_mode, video_path=None):
    """HTML 콘텐츠를 생성합니다."""

    # 세그먼트를 프레임 순서대로 정렬
    segments = sorted(segments, key=lambda s: s.get('start_frame', 0))

    # 통계 계산
    total_segments = len(segments)
    total_duration = sum(s.get('duration', 0) for s in segments)

    # 세그먼트 데이터를 JSON으로 변환 (JavaScript에서 사용)
    import json
    segments_json = json.dumps([{
        'start_frame': seg.get('start_frame', 0),
        'end_frame': seg.get('end_frame', 0),
        'start_time': seg.get('start_time', 0.0),
        'end_time': seg.get('end_time', 0.0),
        'duration': seg.get('duration', 0.0),
        'text': seg.get('text', ''),
        'edited_text': seg.get('edited_text', seg.get('text', ''))
    } for seg in segments])

    # 세그먼트 행 생성
    segment_rows = []
    for idx, seg in enumerate(segments, 1):
        start_frame = seg.get('start_frame', 0)
        end_frame = seg.get('end_frame', 0)
        start_time = seg.get('start_time', 0.0)
        end_time = seg.get('end_time', 0.0)
        duration = seg.get('duration', 0.0)
        text = seg.get('text', '')
        edited_text = seg.get('edited_text', text)
        roi_image = seg.get('roi_image', None)

        # 썸네일 이미지를 base64로 인코딩
        thumbnail_data = ""
        if roi_image:
            thumbnail_data = base64.b64encode(roi_image).decode('utf-8')

        # 시간 포맷팅
        start_time_str = _format_time(start_time)
        end_time_str = _format_time(end_time)
        duration_str = _format_time(duration)

        # 썸네일에 클릭 이벤트 추가 (data 속성으로 세그먼트 정보 저장)
        thumbnail_html = f'<img src="data:image/png;base64,{thumbnail_data}" alt="Frame {start_frame}" class="clickable-thumb" data-start="{start_time}" data-end="{end_time}" data-start-frame="{start_frame}" data-end-frame="{end_frame}">' if thumbnail_data else '<div class="no-image">No Image</div>'

        row_html = f"""
        <tr data-index="{idx - 1}" data-start-time="{start_time}" data-end-time="{end_time}" data-start-frame="{start_frame}" data-end-frame="{end_frame}">
            <td class="index">{idx}</td>
            <td class="thumbnail">
                {thumbnail_html}
            </td>
            <td class="text-original">{_escape_html(text)}</td>
            <td class="text-edited editable" data-original-text="{_escape_html(edited_text)}">{_escape_html(edited_text)}</td>
            <td class="frame">{start_frame}</td>
            <td class="frame">{end_frame}</td>
            <td class="time">{start_time_str}</td>
            <td class="time">{end_time_str}</td>
            <td class="duration">{duration_str}</td>
        </tr>
        """
        segment_rows.append(row_html)

    segments_html = "\n".join(segment_rows)

    # 타임라인 썸네일 생성
    timeline_items = []
    for idx, seg in enumerate(segments, 1):
        start_frame = seg.get('start_frame', 0)
        end_frame = seg.get('end_frame', start_frame)
        frame_count = end_frame - start_frame + 1
        edited_text = seg.get('edited_text', seg.get('text', f'Scene {idx:03d}'))
        roi_image = seg.get('roi_image', None)

        # 썸네일 이미지
        thumbnail_data = ""
        if roi_image:
            thumbnail_data = base64.b64encode(roi_image).decode('utf-8')

        timeline_item = f"""
        <div class="timeline-item" data-segment-index="{idx - 1}" title="{_escape_html(edited_text)}">
            <div class="timeline-frame-count-area">
                <div class="timeline-frame-count">{frame_count}</div>
            </div>
            <div class="timeline-thumb-container">
                {f'<img src="data:image/png;base64,{thumbnail_data}" class="timeline-thumb" alt="{edited_text}">' if thumbnail_data else '<div class="timeline-no-thumb">No Image</div>'}
            </div>
            <div class="timeline-label">{_escape_html(edited_text)}</div>
        </div>
        """
        timeline_items.append(timeline_item)

    timeline_html = "\n".join(timeline_items)

    # 전체 HTML 구조
    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OCR 분석 결과 - {video_name}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #0a0a0a;
            color: #f0f0f0;
            padding: 20px;
            line-height: 1.6;
        }}

        .container {{
            max-width: 1800px;
            margin: 0 auto;
        }}

        h1 {{
            color: #ffae00;
            margin-bottom: 10px;
            font-size: 28px;
            border-bottom: 2px solid #ffae00;
            padding-bottom: 10px;
        }}

        .info-section {{
            background: #111;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 20px;
        }}

        .info-row {{
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
            margin-bottom: 10px;
        }}

        .info-item {{
            display: flex;
            gap: 8px;
        }}

        .info-label {{
            color: #ffae00;
            font-weight: bold;
        }}

        .info-value {{
            color: #ffd27f;
        }}

        .summary-section {{
            background: #0d0d0d;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 20px;
        }}

        .summary-section h2 {{
            color: #ffae00;
            font-size: 18px;
            margin-bottom: 10px;
        }}

        .summary-stats {{
            display: flex;
            gap: 30px;
            flex-wrap: wrap;
        }}

        .stat-item {{
            background: #000;
            border: 1px solid #222;
            border-radius: 4px;
            padding: 10px 15px;
        }}

        .stat-label {{
            color: #888;
            font-size: 12px;
            margin-bottom: 5px;
        }}

        .stat-value {{
            color: #ffae00;
            font-size: 20px;
            font-weight: bold;
        }}

        .edit-controls {{
            margin-bottom: 15px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
            padding: 15px;
            background: #111;
            border: 1px solid #333;
            border-radius: 4px;
        }}

        .edit-btn {{
            background: #1a1a1a;
            color: #ffae00;
            border: 1px solid #555;
        }}

        .edit-btn:hover {{
            background: #2a2a2a;
            border-color: #ffae00;
        }}

        .undo-btn {{
            background: #1a1a3a;
            color: #88aaff;
            border: 1px solid #555;
        }}

        .undo-btn:hover:not(:disabled) {{
            background: #2a2a4a;
            border-color: #88aaff;
        }}

        .undo-btn:disabled {{
            opacity: 0.3;
            cursor: not-allowed;
        }}

        .controls {{
            margin-bottom: 20px;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }}

        .btn {{
            background: #333;
            color: #ffae00;
            border: 1px solid #ffae00;
            border-radius: 4px;
            padding: 8px 15px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}

        .btn:hover {{
            background: #ffae00;
            color: #000;
        }}

        .btn:active {{
            transform: scale(0.98);
        }}

        .search-box {{
            background: #111;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 8px 12px;
            color: #f0f0f0;
            font-size: 14px;
            width: 300px;
        }}

        .search-box:focus {{
            outline: none;
            border-color: #ffae00;
        }}

        /* 비디오 프리뷰 영역 */
        .preview-section {{
            background: #0d0d0d;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 15px;
            margin-bottom: 20px;
        }}

        .preview-section h2 {{
            color: #ffae00;
            font-size: 18px;
            margin-bottom: 10px;
        }}

        .video-container {{
            position: relative;
            background: #000;
            border: 2px solid #ff00ff;
            border-radius: 4px;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 400px;
        }}

        #previewVideo {{
            width: 100%;
            max-height: 600px;
            display: none;
        }}

        #previewVideo.active {{
            display: block;
        }}

        .video-placeholder {{
            color: #555;
            text-align: center;
            padding: 40px;
            font-size: 16px;
        }}

        .frame-overlay {{
            position: absolute;
            bottom: 10px;
            right: 10px;
            background: rgba(255, 174, 0, 0.9);
            color: #000;
            font-size: 18px;
            font-weight: bold;
            padding: 10px 15px;
            border: 2px solid #ffae00;
            border-radius: 4px;
            pointer-events: none;
        }}

        .video-controls {{
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            background: #111;
            padding: 10px;
            border-radius: 4px;
        }}

        .control-btn {{
            background: #333;
            color: #ffae00;
            border: 1px solid #ffae00;
            border-radius: 3px;
            padding: 6px 12px;
            cursor: pointer;
            font-size: 14px;
            min-width: 40px;
            transition: all 0.2s;
        }}

        .control-btn:hover {{
            background: #ffae00;
            color: #000;
        }}

        .control-btn:active {{
            transform: scale(0.95);
        }}

        .control-btn:disabled {{
            opacity: 0.3;
            cursor: not-allowed;
        }}

        .frame-slider {{
            flex: 1;
            min-width: 200px;
            height: 6px;
            background: #333;
            border-radius: 3px;
            outline: none;
            cursor: pointer;
        }}

        .frame-slider::-webkit-slider-thumb {{
            appearance: none;
            width: 16px;
            height: 16px;
            background: #ffae00;
            border-radius: 50%;
            cursor: pointer;
        }}

        .frame-slider::-moz-range-thumb {{
            width: 16px;
            height: 16px;
            background: #ffae00;
            border-radius: 50%;
            cursor: pointer;
        }}

        .frame-info {{
            color: #ffae00;
            font-weight: bold;
            font-family: 'Roboto Mono', 'Menlo', monospace;
            font-size: 14px;
            min-width: 150px;
            text-align: center;
        }}

        .volume-icon {{
            color: #ffae00;
            font-size: 18px;
            margin-left: 10px;
        }}

        .volume-slider {{
            width: 100px;
            height: 6px;
            background: #333;
            border-radius: 3px;
            outline: none;
            cursor: pointer;
        }}

        .volume-slider::-webkit-slider-thumb {{
            appearance: none;
            width: 14px;
            height: 14px;
            background: #ffae00;
            border-radius: 50%;
            cursor: pointer;
        }}

        .volume-slider::-moz-range-thumb {{
            width: 14px;
            height: 14px;
            background: #ffae00;
            border-radius: 50%;
            cursor: pointer;
        }}

        .volume-info {{
            color: #ffae00;
            font-weight: bold;
            font-family: 'Roboto Mono', 'Menlo', monospace;
            font-size: 14px;
            min-width: 40px;
            text-align: center;
        }}

        .clickable-thumb {{
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .clickable-thumb:hover {{
            transform: scale(1.05);
            box-shadow: 0 0 10px #ffae00;
        }}

        /* 타임라인 */
        .timeline-container {{
            background: #000;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 10px;
            margin-top: 15px;
            overflow-x: auto;
            overflow-y: hidden;
        }}

        .timeline-scroll {{
            display: flex;
            gap: 10px;
            min-height: 140px;
            padding: 5px 0;
        }}

        .timeline-item {{
            flex-shrink: 0;
            width: 160px;
            cursor: pointer;
            transition: transform 0.2s;
        }}

        .timeline-item:hover {{
            transform: translateY(-3px);
        }}

        .timeline-item.active {{
            outline: 3px solid #ffae00;
            outline-offset: 2px;
            border-radius: 4px;
        }}

        .timeline-item.selected {{
            background: rgba(255, 174, 0, 0.2) !important;
            border-radius: 4px;
        }}

        .timeline-item.selected .timeline-thumb-container {{
            border-color: #ffae00 !important;
        }}

        /* 우클릭 메뉴 스타일 */
        .context-menu {{
            position: fixed;
            background: #1a1a1a;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 4px 0;
            min-width: 200px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
            z-index: 10000;
            display: none;
        }}

        .context-menu-item {{
            padding: 8px 16px;
            color: #f0f0f0;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.2s;
        }}

        .context-menu-item:hover {{
            background: #333;
        }}

        .context-menu-item:disabled {{
            color: #666;
            cursor: not-allowed;
        }}

        .context-menu-item:disabled:hover {{
            background: transparent;
        }}

        .context-menu-separator {{
            height: 1px;
            background: #444;
            margin: 4px 0;
        }}

        .timeline-frame-count-area {{
            width: 160px;
            height: 25px;
            background: #000000;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .timeline-frame-count {{
            background: rgba(255, 20, 147, 255);
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 11px;
            font-weight: bold;
            padding: 2px 6px;
            min-width: 35px;
            text-align: center;
        }}

        .timeline-thumb-container {{
            position: relative;
            width: 160px;
            height: 90px;
            background: #050505;
            border: 1px solid #222;
            border-radius: 3px;
            overflow: hidden;
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .timeline-thumb {{
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
        }}

        .timeline-no-thumb {{
            color: #555;
            font-size: 11px;
            text-align: center;
            padding: 10px;
        }}

        .timeline-play-overlay {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(255, 174, 0, 0.4);
            color: #000;
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            opacity: 0;
            transition: opacity 0.2s;
            pointer-events: none;
        }}

        .timeline-item:hover .timeline-play-overlay {{
            opacity: 1;
        }}

        .timeline-label {{
            margin-top: 5px;
            font-size: 11px;
            color: #ffea9f;
            text-align: center;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            padding: 0 2px;
        }}

        .table-container {{
            background: #000;
            border: 1px solid #222;
            border-radius: 4px;
            overflow: auto;
            max-height: calc(100vh - 400px);
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}

        thead {{
            position: sticky;
            top: 0;
            background: #1a1a1a;
            z-index: 10;
        }}

        th {{
            color: #ffae00;
            font-weight: bold;
            padding: 12px 8px;
            text-align: left;
            border-bottom: 2px solid #ffae00;
            white-space: nowrap;
        }}

        td {{
            padding: 8px;
            border-bottom: 1px solid #111;
        }}

        tr:hover {{
            background: #0d0d0d;
        }}

        tr.selected {{
            background: #1a1a0a !important;
            border-left: 3px solid #ffae00 !important;
        }}

        tr.selected td {{
            background: #1a1a0a !important;
        }}

        .index {{
            color: #888;
            text-align: center;
            width: 50px;
        }}

        .thumbnail {{
            width: 200px;
            text-align: center;
        }}

        .thumbnail img {{
            max-width: 192px;
            max-height: 108px;
            border: 1px solid #222;
            border-radius: 2px;
            display: block;
            margin: 0 auto;
        }}

        .no-image {{
            color: #555;
            font-size: 11px;
            padding: 20px;
            background: #050505;
            border: 1px solid #111;
            border-radius: 2px;
        }}

        .text-original {{
            color: #aaa;
            max-width: 250px;
            word-wrap: break-word;
        }}

        .text-edited {{
            color: #ffea9f;
            max-width: 250px;
            word-wrap: break-word;
            font-weight: 500;
        }}

        .text-edited.editable {{
            cursor: text;
            padding: 4px 6px;
            border-radius: 2px;
            transition: background 0.2s;
        }}

        .text-edited.editable:hover {{
            background: #1a1a0a;
            outline: 1px solid #ffae00;
        }}

        .text-edited input {{
            width: 100%;
            background: #000;
            color: #ffea9f;
            border: 2px solid #ffae00;
            border-radius: 2px;
            padding: 4px 6px;
            font-size: 13px;
            font-weight: 500;
        }}

        .text-edited input:focus {{
            outline: none;
            border-color: #ffc850;
        }}

        .frame {{
            color: #66ccff;
            text-align: right;
            font-family: 'Roboto Mono', 'Menlo', monospace;
            font-size: 12px;
            width: 80px;
        }}

        .time {{
            color: #88ee88;
            text-align: right;
            font-family: 'Roboto Mono', 'Menlo', monospace;
            font-size: 12px;
            width: 90px;
        }}

        .duration {{
            color: #ff88ff;
            text-align: right;
            font-family: 'Roboto Mono', 'Menlo', monospace;
            font-size: 12px;
            width: 80px;
        }}

        .highlight {{
            background: #ffae0030 !important;
        }}

        .footer {{
            margin-top: 20px;
            padding: 15px;
            text-align: center;
            color: #666;
            font-size: 12px;
            border-top: 1px solid #222;
        }}

        @media print {{
            body {{
                background: white;
                color: black;
            }}
            .controls {{
                display: none;
            }}
            .table-container {{
                max-height: none;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>OCR 분석 결과 - {video_name}</h1>

        <!-- 비디오 프리뷰 영역 -->
        <div class="preview-section">
            <h2>프리뷰 영상</h2>
            <div class="video-container" id="videoContainer">
                {'<video id="previewVideo" preload="metadata"><source src="' + video_path + '" type="video/mp4"></video>' if video_path else ''}
                <div class="video-placeholder" id="videoPlaceholder">썸네일을 클릭하여 세그먼트를 재생하세요</div>
                <div class="frame-overlay" id="frameOverlay" style="display: none;">Frame: 1</div>
            </div>
            <div class="video-controls">
                <button class="control-btn" id="prevFrameBtn" title="이전 프레임" disabled>◀◀</button>
                <button class="control-btn" id="playBtn" title="재생/일시정지" disabled>▶</button>
                <button class="control-btn" id="nextFrameBtn" title="다음 프레임" disabled>▶▶</button>
                <input type="range" class="frame-slider" id="frameSlider" min="0" max="100" value="0" disabled>
                <div class="frame-info" id="frameInfo">Frame: 1 / 0</div>
                <span class="volume-icon" title="볼륨">🔊</span>
                <input type="range" class="volume-slider" id="volumeSlider" min="0" max="100" value="50">
                <div class="volume-info" id="volumeInfo">50%</div>
            </div>

            <!-- 타임라인 -->
            <div class="timeline-container">
                <div class="timeline-scroll" id="timelineScroll">
                    {timeline_html}
                </div>
            </div>
        </div>

        <!-- 편집 컨트롤 -->
        <div class="edit-controls">
            <button class="btn edit-btn" id="mergeBtn" title="선택한 구간을 하나로 병합합니다 (Shift 클릭으로 다중 선택)">선택한 구간 병합</button>
            <button class="btn edit-btn" id="smartMergeBtn" title="인접한 유사 씬을 자동으로 병합합니다">스마트 병합</button>
            <button class="btn edit-btn" id="splitBtn" title="선택한 씬을 지정한 프레임 위치에서 두 개의 씬으로 분할합니다">씬 분할</button>
            <button class="btn edit-btn" id="deleteBtn" title="선택한 구간을 삭제합니다">선택 구간 삭제</button>
            <button class="btn edit-btn" id="sceneNumberBtn" title="자동으로 씬 번호를 부여합니다">씬 번호</button>
            <button class="btn edit-btn" id="renameBtn" title="선택한 항목들의 이름을 일괄 변경합니다">항목 리네임</button>

            <div style="flex: 1;"></div>

            <button class="btn undo-btn" id="undoBtn" title="실행 취소 (Ctrl/Cmd+Z)" disabled>↶ 실행 취소</button>
            <button class="btn undo-btn" id="redoBtn" title="다시 실행 (Ctrl/Cmd+Shift+Z)" disabled>↷ 다시 실행</button>
        </div>

        <div class="controls">
            <input type="text" class="search-box" id="searchBox" placeholder="텍스트 검색...">
            <button class="btn" onclick="clearSearch()">검색 초기화</button>
        </div>

        <!-- 내보내기 컨트롤 -->
        <div class="export-controls" style="padding: 10px; border-top: 1px solid #333; background: #1a1a1a;">
            <div style="display: flex; align-items: center; gap: 15px;">
                <label style="display: flex; align-items: center; gap: 5px; color: #ccc;">
                    <input type="checkbox" id="includeAudioCheckBox" checked style="cursor: pointer;">
                    <span>사운드 포함</span>
                </label>
                <button class="btn" id="exportSelectedBtn" title="선택된 구간만 내보냅니다">선택한 항목만 내보내기</button>
                <button class="btn" id="exportAllBtn" title="전체 내보내기">전체 내보내기</button>
            </div>
        </div>

        <div class="table-container">
            <table id="segmentTable">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>썸네일</th>
                        <th>원본 텍스트</th>
                        <th>편집된 텍스트</th>
                        <th>시작 프레임</th>
                        <th>종료 프레임</th>
                        <th>시작 시간</th>
                        <th>종료 시간</th>
                        <th>재생 시간</th>
                    </tr>
                </thead>
                <tbody>
                    {segments_html}
                </tbody>
            </table>
        </div>

        <div class="footer">
            <p>YesonCheck OCR 분석 결과 | 생성 일시: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        </div>
    </div>

    <script>
        // 전역 변수
        const FPS = {fps};
        let segments = {segments_json};

        // WebSocket 실시간 동기화
        let ws = null;
        let wsConnected = false;

        function connectWebSocket() {{
            try {{
                ws = new WebSocket('ws://localhost:8765');

                ws.onopen = function() {{
                    console.log('[WebSocket] 연결 성공');
                    wsConnected = true;
                    // 초기 동기화 요청
                    ws.send(JSON.stringify({{ type: 'request_sync' }}));
                }};

                ws.onclose = function() {{
                    console.log('[WebSocket] 연결 종료');
                    wsConnected = false;
                    // 5초 후 재연결 시도
                    setTimeout(connectWebSocket, 5000);
                }};

                ws.onerror = function(error) {{
                    console.error('[WebSocket] 오류:', error);
                    wsConnected = false;
                }};

                ws.onmessage = function(event) {{
                    try {{
                        const data = JSON.parse(event.data);
                        handleServerMessage(data);
                    }} catch (e) {{
                        console.error('[WebSocket] 메시지 파싱 오류:', e);
                    }}
                }};
            }} catch (e) {{
                console.error('[WebSocket] 연결 실패:', e);
                wsConnected = false;
                // 5초 후 재연결 시도
                setTimeout(connectWebSocket, 5000);
            }}
        }}

        function handleServerMessage(data) {{
            if (data.type === 'full_sync') {{
                // 서버로부터 전체 동기화 수신
                console.log('[WebSocket] 서버로부터', data.segments.length, '개 세그먼트 수신 (selected_index=' + data.selected_index + ')');
                applySyncFromServer(data.segments, data.selected_index);
            }}
        }}

        function applySyncFromServer(serverSegments, selectedIndex) {{
            // 서버에서 내려온 최신 데이터를 전역 segments에 반영하여 프리뷰/타임라인이 데스크탑과 일치하도록 유지
            segments = serverSegments.slice();

            // 현재 재생 중인 세그먼트 인덱스 저장 (프리뷰 영상 상태 복원용)
            let currentPlayingIndex = null;
            if (currentSegment) {{
                // 현재 재생 중인 세그먼트의 start_frame로 인덱스 찾기
                for (let i = 0; i < segments.length; i++) {{
                    if (segments[i].start_frame === currentSegment.start_frame && 
                        segments[i].end_frame === currentSegment.end_frame) {{
                        currentPlayingIndex = i;
                        break;
                    }}
                }}
            }}

            // 서버로부터 받은 세그먼트로 테이블 업데이트
            const tbody = document.querySelector('#segmentTable tbody');
            tbody.innerHTML = '';

            serverSegments.forEach((seg, idx) => {{
                const row = document.createElement('tr');
                row.dataset.index = idx;
                row.dataset.startFrame = seg.start_frame;
                row.dataset.endFrame = seg.end_frame;
                row.dataset.startTime = seg.start_time;
                row.dataset.endTime = seg.end_time;

                // 썸네일 이미지 처리
                let thumbnailHtml = '<div class="no-image">No Image</div>';
                if (seg.roi_image) {{
                    thumbnailHtml = '<img src="data:image/png;base64,' + seg.roi_image + '" alt="Frame ' + seg.start_frame + '" class="clickable-thumb" data-start="' + seg.start_time + '" data-end="' + seg.end_time + '" data-start-frame="' + seg.start_frame + '" data-end-frame="' + seg.end_frame + '">';
                }}

                row.innerHTML = '<td class="index">' + (idx + 1) + '</td>' +
                    '<td class="thumbnail">' + thumbnailHtml + '</td>' +
                    '<td class="text-original">' + (seg.text || '') + '</td>' +
                    '<td class="text-edited editable" data-original-text="' + (seg.edited_text || seg.text || '') + '">' + (seg.edited_text || seg.text || '') + '</td>' +
                    '<td class="frame">' + (seg.start_frame + 1) + '</td>' +
                    '<td class="frame">' + (seg.end_frame + 1) + '</td>' +
                    '<td class="time">' + formatTime(seg.start_time) + '</td>' +
                    '<td class="time">' + formatTime(seg.end_time) + '</td>' +
                    '<td class="duration">' + formatTime(seg.duration) + '</td>';

                tbody.appendChild(row);
            }});

            rebuildTimeline();
            selectedRows.clear();

            // 서버에서 선택한 인덱스가 있으면 해당 행 선택
            let targetIndex = selectedIndex;
            if (targetIndex === null || targetIndex === undefined) {{
                // 서버에서 선택 인덱스가 없으면 현재 재생 중인 세그먼트 인덱스 사용
                targetIndex = currentPlayingIndex;
            }}

            if (targetIndex !== null && targetIndex !== undefined) {{
                const rows = Array.from(tbody.querySelectorAll('tr'));
                if (targetIndex >= 0 && targetIndex < rows.length) {{
                    rows[targetIndex].classList.add('selected');
                    selectedRows.add(targetIndex);
                    // 해당 행으로 스크롤
                    rows[targetIndex].scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                    // 프리뷰 업데이트 (loadSegment 사용)
                    loadSegment(targetIndex);
                    console.log('[WebSocket] 서버 선택 인덱스 적용:', targetIndex);
                }}
            }}

            updateSelection();

            console.log('[WebSocket] 서버 데이터 적용 완료');
        }}

        function sendSegmentsToServer() {{
            if (!wsConnected || !ws) {{
                console.log('[WebSocket] 서버 미연결 - 전송 건너뜀');
                return;
            }}

            const tbody = document.querySelector('#segmentTable tbody');
            const currentSegments = Array.from(tbody.querySelectorAll('tr')).map((row, idx) => {{
                // 썸네일 이미지 추출 (base64 데이터)
                let roi_image = '';
                const thumbImg = row.querySelector('.thumbnail img');
                if (thumbImg && thumbImg.src) {{
                    // data:image/png;base64, 형태에서 base64 부분만 추출
                    if (thumbImg.src.startsWith('data:image')) {{
                        const base64Index = thumbImg.src.indexOf('base64,');
                        if (base64Index !== -1) {{
                            roi_image = thumbImg.src.substring(base64Index + 7);
                        }}
                    }}
                }}
                
                return {{
                    start_frame: parseInt(row.dataset.startFrame),
                    end_frame: parseInt(row.dataset.endFrame),
                    start_time: parseFloat(row.dataset.startTime),
                    end_time: parseFloat(row.dataset.endTime),
                    duration: (parseInt(row.dataset.endFrame) - parseInt(row.dataset.startFrame) + 1) / FPS,
                    text: row.querySelector('.text-original').textContent || '',
                    edited_text: row.querySelector('.text-edited').textContent,
                    roi_image: roi_image  // 썸네일 이미지 base64 데이터 포함
                }};
            }});

            // 로컬 segments 배열도 최신 상태로 유지 (프리뷰/타임라인 동기화)
            segments = currentSegments.slice();

            // 현재 선택된 행의 인덱스 가져오기
            let selectedIndex = null;
            const rows = Array.from(tbody.querySelectorAll('tr'));
            for (let i = 0; i < rows.length; i++) {{
                if (rows[i].classList.contains('selected')) {{
                    selectedIndex = i;
                    break;
                }}
            }}

            const message = {{
                type: 'segments_update',
                segments: currentSegments,
                selected_index: selectedIndex
            }};

            ws.send(JSON.stringify(message));
            console.log('[WebSocket] 서버로', currentSegments.length, '개 세그먼트 전송 (selected_index=' + selectedIndex + ')');
        }}

        // WebSocket 연결 시작
        connectWebSocket();

        // DOM 요소
        const searchBox = document.getElementById('searchBox');
        const table = document.getElementById('segmentTable');
        const tbody = table.querySelector('tbody');
        const previewVideo = document.getElementById('previewVideo');
        const videoPlaceholder = document.getElementById('videoPlaceholder');
        const frameOverlay = document.getElementById('frameOverlay');
        const playBtn = document.getElementById('playBtn');
        const prevFrameBtn = document.getElementById('prevFrameBtn');
        const nextFrameBtn = document.getElementById('nextFrameBtn');
        const frameSlider = document.getElementById('frameSlider');
        const frameInfo = document.getElementById('frameInfo');

        // 비디오 재생 상태
        let currentSegment = null;
        let isPlaying = false;
        let currentFrame = 0;
        let startFrame = 0;
        let endFrame = 0;
        let segmentStartTime = 0;
        let segmentEndTime = 0;

        // 편집 상태
        let undoStack = [];
        let redoStack = [];
        const MAX_HISTORY = 50;
        let selectedRows = new Set();

        // Undo/Redo 버튼 참조
        const undoBtn = document.getElementById('undoBtn');
        const redoBtn = document.getElementById('redoBtn');

        searchBox.addEventListener('input', function() {{
            const searchTerm = this.value.toLowerCase();
            const rows = tbody.querySelectorAll('tr');

            rows.forEach(row => {{
                const textOriginal = row.querySelector('.text-original').textContent.toLowerCase();
                const textEdited = row.querySelector('.text-edited').textContent.toLowerCase();

                if (textOriginal.includes(searchTerm) || textEdited.includes(searchTerm)) {{
                    row.style.display = '';
                    if (searchTerm) {{
                        row.classList.add('highlight');
                    }} else {{
                        row.classList.remove('highlight');
                    }}
                }} else {{
                    row.style.display = 'none';
                    row.classList.remove('highlight');
                }}
            }});
        }});

        function clearSearch() {{
            searchBox.value = '';
            const rows = tbody.querySelectorAll('tr');
            rows.forEach(row => {{
                row.style.display = '';
                row.classList.remove('highlight');
            }});
        }}

        // 비디오 재생 기능
        function loadSegment(segIndex) {{
            if (!previewVideo || segIndex < 0 || segIndex >= segments.length) return;

            currentSegment = segments[segIndex];
            startFrame = currentSegment.start_frame;
            endFrame = currentSegment.end_frame;
            segmentStartTime = currentSegment.start_time;
            segmentEndTime = currentSegment.end_time;
            // currentFrame을 startFrame으로 초기화 (0-based)
            currentFrame = startFrame;
            
            // 디버깅: 프레임 정보 확인
            console.log('[loadSegment] segIndex=' + segIndex + ', startFrame=' + startFrame + ', endFrame=' + endFrame + ', currentFrame=' + currentFrame);

            // 비디오 표시
            videoPlaceholder.style.display = 'none';
            previewVideo.classList.add('active');
            frameOverlay.style.display = 'block';

            // 데스크탑에서 전달받은 start_time과 end_time을 그대로 사용
            // 데스크탑에서는 start_time = start_frame / FPS, end_time = (end_frame + 1) / FPS로 계산됨
            // 하지만 HTML5 비디오는 키프레임으로 seek하므로, start_time이 정확히 start_frame에 해당하지 않을 수 있음
            // 따라서 프레임의 중간 지점(+0.5)으로 이동하여 확실히 start_frame이 표시되도록 함
            const exactStartTime = (startFrame + 0.5) / FPS;
            
            // 디버깅: 전달받은 값 확인
            console.log('[loadSegment] segmentStartTime=' + segmentStartTime + ', startFrame=' + startFrame + ', expected time=' + (startFrame / FPS).toFixed(6));
            
            // seeked 이벤트를 기다려서 정확한 프레임이 로드되도록 함
            let seekAttempts = 0;
            const maxSeekAttempts = 10;
            
            const onSeeked = function() {{
                seekAttempts++;
                
                // 실제 currentTime 확인
                const actualTime = previewVideo.currentTime;
                // 실제 프레임 계산 (0-based)
                const actualFrame = Math.floor(actualTime * FPS);
                
                // 디버깅: 실제 프레임 확인
                console.log('[loadSegment] seeked attempt ' + seekAttempts + ': actualTime=' + actualTime.toFixed(6) + ', actualFrame=' + actualFrame + ', startFrame=' + startFrame);
                
                // 이전 프레임이면 보정 (HTML5 비디오의 키프레임 문제)
                if (actualFrame < startFrame && seekAttempts < maxSeekAttempts) {{
                    // 이전 프레임이면 startFrame에 해당하는 시간으로 다시 seek
                    // startFrame의 중간 지점으로 이동하여 확실히 startFrame이 표시되도록 함
                    const correctedTime = (startFrame + 0.5) / FPS;
                    console.log('[loadSegment] 이전 프레임 감지! 보정: ' + actualFrame + ' -> ' + startFrame + ', time=' + correctedTime.toFixed(6));
                    previewVideo.currentTime = correctedTime;
                    previewVideo.addEventListener('seeked', onSeeked, {{ once: true }});
                    return;
                }}
                
                // 정확한 프레임 또는 최대 재시도 횟수 도달
                currentFrame = Math.max(startFrame, Math.min(endFrame, actualFrame));
                
                // 슬라이더 설정
                const totalFrames = endFrame - startFrame + 1;
                frameSlider.min = 0;
                frameSlider.max = totalFrames - 1;
                frameSlider.value = currentFrame - startFrame;
                frameSlider.disabled = false;

                // 버튼 활성화
                playBtn.disabled = false;
                prevFrameBtn.disabled = false;
                nextFrameBtn.disabled = false;

                // 프레임 정보 업데이트
                updateFrameInfo();

                // 타임라인 하이라이트 업데이트
                updateTimelineHighlight(segIndex);
            }};
            
            // 초기 시간 설정 (데스크탑의 start_time 그대로 사용)
            previewVideo.currentTime = exactStartTime;
            
            // seeked 이벤트 리스너 추가 (비동기로 정확한 프레임 로드 대기)
            previewVideo.addEventListener('seeked', onSeeked, {{ once: true }});
            
            // 이미 seeked 상태일 수 있으므로 즉시 확인
            if (previewVideo.readyState >= 2) {{
                // 이미 로드된 경우 약간의 지연 후 확인 (비디오가 seek을 완료할 시간 제공)
                setTimeout(() => {{
                    if (previewVideo.readyState >= 2) {{
                        onSeeked();
                    }}
                }}, 50);
            }}
        }}

        function updateFrameInfo() {{
            if (startFrame === undefined || endFrame === undefined || currentFrame === undefined) {{
                frameInfo.textContent = 'Frame: 1 / 0';
                frameOverlay.textContent = 'Frame: 1';
                return;
            }}
            const relativeFrame = currentFrame - startFrame;
            const totalFrames = endFrame - startFrame + 1;
            // 1-based로 표시 (relativeFrame은 0부터 시작하므로 +1)
            const displayFrame = Math.max(1, relativeFrame + 1);
            frameInfo.textContent = 'Frame: ' + displayFrame + ' / ' + totalFrames;
            // 오버레이도 씬 내 상대 프레임 번호로 표시 (데스크톱과 동일하게)
            // relativeFrame은 0부터 시작하므로 +1하여 1-based로 표시
            const overlayFrame = Math.max(1, relativeFrame + 1);
            frameOverlay.textContent = 'Frame: ' + overlayFrame;
        }}

        // 재생 중 endFrame 체크를 위한 animation frame ID
        let checkEndFrameAnimationId = null;
        
        function checkEndFrame() {{
            if (!isPlaying || !currentSegment) {{
                if (checkEndFrameAnimationId) {{
                    cancelAnimationFrame(checkEndFrameAnimationId);
                    checkEndFrameAnimationId = null;
                }}
                return;
            }}
            
            // 현재 프레임 계산 (0-based)
            const calculatedFrame = Math.floor(previewVideo.currentTime * FPS);
            
            // endFrame에 도달하거나 넘어서면 정지
            if (calculatedFrame >= endFrame) {{
                previewVideo.pause();
                // 시작 프레임으로 이동 (다음 씬의 첫 프레임이 보이지 않도록)
                const startTime = (startFrame + 0.5) / FPS;
                previewVideo.currentTime = startTime;
                currentFrame = startFrame;
                playBtn.textContent = '▶';
                isPlaying = false;
                updateFrameInfo();
                // 슬라이더를 0 (시작 프레임)으로 이동
                frameSlider.value = 0;
                
                if (checkEndFrameAnimationId) {{
                    cancelAnimationFrame(checkEndFrameAnimationId);
                    checkEndFrameAnimationId = null;
                }}
                return;
            }}
            
            // 다음 프레임에서 다시 체크
            checkEndFrameAnimationId = requestAnimationFrame(checkEndFrame);
        }}
        
        function togglePlay() {{
            if (!previewVideo || !currentSegment) return;

            if (isPlaying) {{
                previewVideo.pause();
                playBtn.textContent = '▶';
                isPlaying = false;
                
                // animation frame 체크 중지
                if (checkEndFrameAnimationId) {{
                    cancelAnimationFrame(checkEndFrameAnimationId);
                    checkEndFrameAnimationId = null;
                }}
            }} else {{
                // 슬라이더 위치에 따라 현재 프레임 결정
                const relativeFrame = parseInt(frameSlider.value) || 0;
                const targetFrame = startFrame + relativeFrame;
                const targetTime = (targetFrame + 0.5) / FPS;
                
                // 현재 시간이 세그먼트 범위를 벗어났으면 슬라이더 위치로 이동
                const currentTime = previewVideo.currentTime;
                const startTime = (startFrame + 0.5) / FPS;
                const endFrameTime = (endFrame + 0.5) / FPS;
                
                if (currentTime < startTime || currentTime >= endFrameTime) {{
                    // seek를 먼저 수행하고, seeked 이벤트를 기다린 후 재생
                    previewVideo.currentTime = targetTime;
                    currentFrame = targetFrame;
                    updateFrameInfo();
                    
                    // seeked 이벤트를 기다린 후 재생
                    const onSeekedForPlay = function() {{
                        previewVideo.removeEventListener('seeked', onSeekedForPlay);
                        previewVideo.play();
                        playBtn.textContent = '⏸';
                        isPlaying = true;
                        // 재생 시작 후 endFrame 체크 시작
                        checkEndFrameAnimationId = requestAnimationFrame(checkEndFrame);
                    }};
                    previewVideo.addEventListener('seeked', onSeekedForPlay, {{ once: true }});
                }} else {{
                    // 범위 내에 있으면 바로 재생
                    previewVideo.play();
                    playBtn.textContent = '⏸';
                    isPlaying = true;
                    // 재생 시작 후 endFrame 체크 시작
                    checkEndFrameAnimationId = requestAnimationFrame(checkEndFrame);
                }}
            }}
        }}

        function seekToFrame(frame) {{
            if (!previewVideo || !currentSegment) return;

            // 프레임 번호를 정확하게 설정 (0-based)
            currentFrame = Math.max(startFrame, Math.min(endFrame, frame));
            // 프레임의 중간 지점으로 이동하여 정확한 프레임 표시 (HTML5 비디오의 키프레임 문제 회피)
            const time = (currentFrame + 0.5) / FPS;
            previewVideo.currentTime = time;
            
            // 프레임 정보 업데이트 (데스크톱과 동일하게 1-based로 표시)
            updateFrameInfo();

            // 슬라이더 업데이트 (0-based relative frame)
            const relativeFrame = currentFrame - startFrame;
            frameSlider.value = relativeFrame;
        }}

        function prevFrame() {{
            if (currentFrame > startFrame) {{
                seekToFrame(currentFrame - 1);
            }}
        }}

        function nextFrame() {{
            if (currentFrame < endFrame) {{
                seekToFrame(currentFrame + 1);
            }}
        }}

        // 비디오 이벤트 리스너
        if (previewVideo) {{
            previewVideo.addEventListener('timeupdate', function() {{
                if (!currentSegment) return;

                // 현재 프레임 계산 (0-based)
                // Math.floor를 사용하여 정확한 프레임 번호 계산
                // seekToFrame에서 (frame + 0.5) / FPS로 설정했으므로, floor를 사용해야 원래 프레임 번호가 나옴
                // 예: time = (100 + 0.5) / 24 = 4.1875 → Math.floor(4.1875 * 24) = Math.floor(100.5) = 100
                const calculatedFrame = Math.floor(previewVideo.currentTime * FPS);
                
                // 테이블의 시작/종료 프레임을 직접 참고하여 체크
                // timeupdate 이벤트는 빈도가 낮을 수 있으므로, 시간 기반으로도 체크
                // endFrame에 해당하는 시간: (endFrame + 0.5) / FPS
                // endFrame 직전 시간: (endFrame - 0.5) / FPS
                const endFrameTime = (endFrame + 0.5) / FPS;
                const endFrameCheckTime = (endFrame - 0.3) / FPS;  // endFrame 직전에서 미리 체크
                
                // 프레임 번호나 시간 기반으로 endFrame에 도달했는지 체크
                // calculatedFrame이 endFrame에 도달하거나, 시간이 endFrameCheckTime을 넘어서면 정지
                if ((calculatedFrame >= endFrame || previewVideo.currentTime >= endFrameCheckTime) && isPlaying) {{
                    previewVideo.pause();
                    // 시작 프레임으로 이동 (다음 씬의 첫 프레임이 보이지 않도록)
                    const startTime = (startFrame + 0.5) / FPS;
                    previewVideo.currentTime = startTime;
                    currentFrame = startFrame;
                    playBtn.textContent = '▶';
                    isPlaying = false;
                    updateFrameInfo();
                    // 슬라이더를 0 (시작 프레임)으로 이동
                    frameSlider.value = 0;
                    return;  // 더 이상 업데이트하지 않음
                }}
                
                // 프레임 번호가 범위를 벗어나지 않도록 제한
                currentFrame = Math.max(startFrame, Math.min(endFrame, calculatedFrame));

                // 프레임 정보 업데이트
                updateFrameInfo();

                // 슬라이더 업데이트
                const relativeFrame = currentFrame - startFrame;
                frameSlider.value = relativeFrame;
            }});

            previewVideo.addEventListener('loadedmetadata', function() {{
                console.log('Video loaded, duration:', previewVideo.duration);
            }});

            // 비디오 재생 종료 이벤트 처리
            previewVideo.addEventListener('ended', function() {{
                if (!currentSegment) return;
                
                // 재생이 끝났을 때 startFrame으로 이동 (다음 씬의 첫 프레임이 보이지 않도록)
                const startTime = (startFrame + 0.5) / FPS;
                previewVideo.currentTime = startTime;
                currentFrame = startFrame;
                isPlaying = false;
                playBtn.textContent = '▶';
                updateFrameInfo();
                // 슬라이더를 0 (시작 프레임)으로 이동
                frameSlider.value = 0;
            }});

            previewVideo.addEventListener('error', function(e) {{
                console.error('Video error:', e);
                videoPlaceholder.textContent = '비디오를 로드할 수 없습니다. 비디오 파일이 HTML 파일과 같은 디렉토리에 있는지 확인하세요.';
                videoPlaceholder.style.display = 'block';
                previewVideo.classList.remove('active');
            }});
        }}

        // 컨트롤 버튼 이벤트
        if (playBtn) playBtn.addEventListener('click', togglePlay);
        if (prevFrameBtn) prevFrameBtn.addEventListener('click', prevFrame);
        if (nextFrameBtn) nextFrameBtn.addEventListener('click', nextFrame);

        if (frameSlider) {{
            frameSlider.addEventListener('input', function() {{
                const relativeFrame = parseInt(this.value);
                seekToFrame(startFrame + relativeFrame);
            }});
        }}

        // 볼륨 슬라이더 이벤트 핸들러
        const volumeSlider = document.getElementById('volumeSlider');
        const volumeInfo = document.getElementById('volumeInfo');
        if (volumeSlider && previewVideo) {{
            volumeSlider.addEventListener('input', function() {{
                const volume = parseInt(this.value) / 100;
                previewVideo.volume = volume;
                if (volumeInfo) {{
                    volumeInfo.textContent = this.value + '%';
                }}
            }});
            // 초기 볼륨 설정
            previewVideo.volume = 0.5;
        }}

        // 타임라인 하이라이트 업데이트
        function updateTimelineHighlight(segIndex) {{
            const timelineItems = document.querySelectorAll('.timeline-item');
            timelineItems.forEach((item, idx) => {{
                if (idx === segIndex) {{
                    item.classList.add('active');
                    // 타임라인 스크롤하여 선택된 아이템이 보이도록
                    item.scrollIntoView({{ behavior: 'smooth', block: 'nearest', inline: 'center' }});
                }} else {{
                    item.classList.remove('active');
                }}
            }});
        }}

        // 테이블과 타임라인의 선택 상태 동기화
        function updateSelection() {{
            const allRows = tbody.querySelectorAll('tr');
            const allTimelineItems = document.querySelectorAll('.timeline-item');

            allRows.forEach((row, idx) => {{
                if (selectedRows.has(idx)) {{
                    row.classList.add('selected');
                }} else {{
                    row.classList.remove('selected');
                }}
            }});

            allTimelineItems.forEach((item, idx) => {{
                if (selectedRows.has(idx)) {{
                    item.classList.add('selected');
                }} else {{
                    item.classList.remove('selected');
                }}
            }});
        }}

        // 타임라인 클릭 이벤트
        const timelineScroll = document.getElementById('timelineScroll');
        if (timelineScroll) {{
            timelineScroll.addEventListener('click', function(e) {{
                const timelineItem = e.target.closest('.timeline-item');
                if (timelineItem) {{
                    const segIndex = parseInt(timelineItem.dataset.segmentIndex);

                    // 다중 선택 처리
                    if (e.shiftKey && selectedRows.size > 0) {{
                        // Shift 클릭: 범위 선택
                        const indices = Array.from(selectedRows);
                        const lastIndex = Math.max(...indices);
                        const start = Math.min(lastIndex, segIndex);
                        const end = Math.max(lastIndex, segIndex);

                        for (let i = start; i <= end; i++) {{
                            selectedRows.add(i);
                        }}
                        updateSelection();
                    }} else if (e.ctrlKey || e.metaKey) {{
                        // Ctrl/Cmd 클릭: 토글
                        if (selectedRows.has(segIndex)) {{
                            selectedRows.delete(segIndex);
                        }} else {{
                            selectedRows.add(segIndex);
                        }}
                        updateSelection();
                    }} else {{
                        // 일반 클릭: 비디오 로드 + 단일 선택
                        loadSegment(segIndex);

                        selectedRows.clear();
                        selectedRows.add(segIndex);
                        updateSelection();
                    }}
                }}
            }});
        }}

        // 타임라인 휠 이벤트 (좌우 스크롤)
        const timelineContainer = document.querySelector('.timeline-container');
        if (timelineContainer) {{
            timelineContainer.addEventListener('wheel', function(e) {{
                // 타임라인 컨테이너 위에 마우스가 있을 때만 좌우 스크롤
                e.preventDefault();
                // 휠 델타를 스크롤 값으로 변환
                timelineContainer.scrollLeft += e.deltaY;
            }}, {{ passive: false }});
        }}

        // ============================================
        // 편집 기능
        // ============================================

        // 히스토리 저장
        function saveState() {{
            const state = {{
                rows: Array.from(tbody.querySelectorAll('tr')).map(row => {{
                    const thumbImg = row.querySelector('.thumbnail img');
                    const thumbnailSrc = thumbImg ? thumbImg.src : null;
                    return {{
                        index: row.dataset.index,
                        editedText: row.querySelector('.text-edited').textContent,
                        startFrame: row.dataset.startFrame,
                        endFrame: row.dataset.endFrame,
                        startTime: row.dataset.startTime,
                        endTime: row.dataset.endTime,
                        thumbnailSrc: thumbnailSrc
                    }};
                }})
            }};

            undoStack.push(JSON.parse(JSON.stringify(state)));
            if (undoStack.length > MAX_HISTORY) {{
                undoStack.shift();
            }}
            redoStack = [];
            updateUndoRedoButtons();
        }}

        function updateUndoRedoButtons() {{
            if (undoBtn) undoBtn.disabled = undoStack.length === 0;
            if (redoBtn) redoBtn.disabled = redoStack.length === 0;
        }}

        function undo() {{
            if (undoStack.length === 0) return;

            // 현재 상태를 redo 스택에 저장
            const currentState = {{
                rows: Array.from(tbody.querySelectorAll('tr')).map(row => {{
                    const thumbImg = row.querySelector('.thumbnail img');
                    const thumbnailSrc = thumbImg ? thumbImg.src : null;
                    return {{
                        index: row.dataset.index,
                        editedText: row.querySelector('.text-edited').textContent,
                        startFrame: row.dataset.startFrame,
                        endFrame: row.dataset.endFrame,
                        startTime: row.dataset.startTime,
                        endTime: row.dataset.endTime,
                        thumbnailSrc: thumbnailSrc
                    }};
                }})
            }};
            redoStack.push(currentState);

            // 이전 상태 복원
            const prevState = undoStack.pop();
            restoreState(prevState);
            updateUndoRedoButtons();
            
            // 데스크탑에 변경사항 전송 (양방향 동기화)
            sendSegmentsToServer();
        }}

        function redo() {{
            if (redoStack.length === 0) return;

            // 현재 상태를 undo 스택에 저장
            const currentState = {{
                rows: Array.from(tbody.querySelectorAll('tr')).map(row => {{
                    const thumbImg = row.querySelector('.thumbnail img');
                    const thumbnailSrc = thumbImg ? thumbImg.src : null;
                    return {{
                        index: row.dataset.index,
                        editedText: row.querySelector('.text-edited').textContent,
                        startFrame: row.dataset.startFrame,
                        endFrame: row.dataset.endFrame,
                        startTime: row.dataset.startTime,
                        endTime: row.dataset.endTime,
                        thumbnailSrc: thumbnailSrc
                    }};
                }})
            }};
            undoStack.push(currentState);

            // 다음 상태 복원
            const nextState = redoStack.pop();
            restoreState(nextState);
            updateUndoRedoButtons();
            
            // 데스크탑에 변경사항 전송 (양방향 동기화)
            sendSegmentsToServer();
        }}

        function restoreState(state) {{
            // 현재 재생 중인 세그먼트 인덱스 저장 (프리뷰 영상 상태 복원용)
            let currentPlayingIndex = null;
            if (currentSegment) {{
                // 현재 재생 중인 세그먼트의 start_frame로 인덱스 찾기
                for (let i = 0; i < state.rows.length; i++) {{
                    if (parseInt(state.rows[i].startFrame) === currentSegment.start_frame && 
                        parseInt(state.rows[i].endFrame) === currentSegment.end_frame) {{
                        currentPlayingIndex = i;
                        break;
                    }}
                }}
            }}

            tbody.innerHTML = '';
            state.rows.forEach((rowData, idx) => {{
                const newRow = document.createElement('tr');
                newRow.dataset.index = idx;
                newRow.dataset.startFrame = rowData.startFrame;
                newRow.dataset.endFrame = rowData.endFrame;
                newRow.dataset.startTime = rowData.startTime;
                newRow.dataset.endTime = rowData.endTime;

                // 썸네일 이미지 처리
                let thumbnailHtml = '<div class="no-image">No Image</div>';
                if (rowData.thumbnailSrc) {{
                    const startFrame = parseInt(rowData.startFrame);
                    const startTime = parseFloat(rowData.startTime);
                    const endTime = parseFloat(rowData.endTime);
                    const endFrame = parseInt(rowData.endFrame);
                    thumbnailHtml = '<img src="' + rowData.thumbnailSrc + '" alt="Frame ' + startFrame + '" class="clickable-thumb" data-start="' + startTime + '" data-end="' + endTime + '" data-start-frame="' + startFrame + '" data-end-frame="' + endFrame + '">';
                }}

                // rowData.startFrame과 rowData.endFrame은 0-based이므로 1-based로 표시
                const startFrame1Based = parseInt(rowData.startFrame) + 1;
                const endFrame1Based = parseInt(rowData.endFrame) + 1;
                
                newRow.innerHTML = '<td class="index">' + (idx + 1) + '</td>' +
                    '<td class="thumbnail">' + thumbnailHtml + '</td>' +
                    '<td class="text-original"></td>' +
                    '<td class="text-edited editable" data-original-text="' + rowData.editedText + '">' + rowData.editedText + '</td>' +
                    '<td class="frame">' + startFrame1Based + '</td>' +
                    '<td class="frame">' + endFrame1Based + '</td>' +
                    '<td class="time">' + formatTime(parseFloat(rowData.startTime)) + '</td>' +
                    '<td class="time">' + formatTime(parseFloat(rowData.endTime)) + '</td>' +
                    '<td class="duration">' + formatTime((parseInt(rowData.endFrame) - parseInt(rowData.startFrame) + 1) / FPS) + '</td>';
                tbody.appendChild(newRow);
            }});

            // segments 배열도 업데이트 (프리뷰 영상 동기화용)
            segments = state.rows.map((rowData, idx) => {{
                const thumbImg = tbody.querySelectorAll('tr')[idx].querySelector('.thumbnail img');
                let roi_image = '';
                if (thumbImg && thumbImg.src) {{
                    if (thumbImg.src.startsWith('data:image')) {{
                        const base64Index = thumbImg.src.indexOf('base64,');
                        if (base64Index !== -1) {{
                            roi_image = thumbImg.src.substring(base64Index + 7);
                        }}
                    }}
                }}
                return {{
                    start_frame: parseInt(rowData.startFrame),
                    end_frame: parseInt(rowData.endFrame),
                    start_time: parseFloat(rowData.startTime),
                    end_time: parseFloat(rowData.endTime),
                    duration: (parseInt(rowData.endFrame) - parseInt(rowData.startFrame) + 1) / FPS,
                    text: '',
                    edited_text: rowData.editedText,
                    roi_image: roi_image
                }};
            }});

            rebuildTimeline();
            selectedRows.clear();
            updateSelection();

            // 프리뷰 영상 상태 복원
            if (currentPlayingIndex !== null && currentPlayingIndex >= 0 && currentPlayingIndex < segments.length) {{
                loadSegment(currentPlayingIndex);
                const rows = Array.from(tbody.querySelectorAll('tr'));
                if (currentPlayingIndex < rows.length) {{
                    rows[currentPlayingIndex].classList.add('selected');
                    selectedRows.add(currentPlayingIndex);
                    updateSelection();
                }}
            }}
        }}

        function formatTime(seconds) {{
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            if (hours > 0) {{
                return hours.toString().padStart(2, '0') + ':' + minutes.toString().padStart(2, '0') + ':' + secs.toFixed(3).padStart(6, '0');
            }}
            return minutes.toString().padStart(2, '0') + ':' + secs.toFixed(3).padStart(6, '0');
        }}

        // 텍스트 인라인 편집
        tbody.addEventListener('dblclick', function(e) {{
            const cell = e.target.closest('.text-edited.editable');
            if (!cell || cell.querySelector('input')) return;

            const originalText = cell.textContent;
            const input = document.createElement('input');
            input.type = 'text';
            input.value = originalText;

            cell.textContent = '';
            cell.appendChild(input);
            input.focus();
            input.select();

            function finishEdit() {{
                const newText = input.value.trim();
                if (newText !== originalText) {{
                    saveState();
                    cell.textContent = newText;
                    cell.dataset.originalText = newText;
                }} else {{
                    cell.textContent = originalText;
                }}
            }}

            input.addEventListener('blur', finishEdit);
            input.addEventListener('keydown', function(e) {{
                if (e.key === 'Enter') {{
                    finishEdit();
                }} else if (e.key === 'Escape') {{
                    cell.textContent = originalText;
                }}
            }});
        }});

        // 테이블 클릭 처리 (썸네일 클릭 + 다중 선택)
        tbody.addEventListener('click', function(e) {{
            const row = e.target.closest('tr');
            if (!row) return;

            const rowIndex = Array.from(tbody.querySelectorAll('tr')).indexOf(row);
            const thumb = e.target.closest('.clickable-thumb');

            // 썸네일 클릭: 비디오 로드 (다중 선택 무시)
            if (thumb && !e.shiftKey && !e.ctrlKey && !e.metaKey) {{
                const segIndex = parseInt(row.dataset.index);
                loadSegment(segIndex);

                // 단일 선택으로 변경
                selectedRows.clear();
                selectedRows.add(rowIndex);
                updateSelection();
                return;
            }}

            // 다중 선택 처리
            if (e.shiftKey && selectedRows.size > 0) {{
                // Shift 클릭: 범위 선택
                const indices = Array.from(selectedRows);
                const lastIndex = Math.max(...indices);
                const start = Math.min(lastIndex, rowIndex);
                const end = Math.max(lastIndex, rowIndex);

                for (let i = start; i <= end; i++) {{
                    selectedRows.add(i);
                }}
                updateSelection();
            }} else if (e.ctrlKey || e.metaKey) {{
                // Ctrl/Cmd 클릭: 토글
                if (selectedRows.has(rowIndex)) {{
                    selectedRows.delete(rowIndex);
                }} else {{
                    selectedRows.add(rowIndex);
                }}
                updateSelection();
            }} else if (!thumb) {{
                // 일반 클릭 (썸네일이 아닌 경우): 단일 선택
                selectedRows.clear();
                selectedRows.add(rowIndex);
                updateSelection();
            }}
        }});

        // 선택한 구간 병합
        document.getElementById('mergeBtn').addEventListener('click', function() {{
            if (selectedRows.size < 2) {{
                alert('병합할 구간을 2개 이상 선택하세요 (Shift 또는 Ctrl/Cmd 클릭)');
                return;
            }}

            const indices = Array.from(selectedRows).sort((a, b) => a - b);
            const rows = indices.map(i => tbody.querySelectorAll('tr')[i]);

            // 연속된 구간인지 확인
            for (let i = 0; i < indices.length - 1; i++) {{
                if (indices[i + 1] !== indices[i] + 1) {{
                    if (!confirm('선택한 구간이 연속되지 않습니다. 계속하시겠습니까?')) {{
                        return;
                    }}
                    break;
                }}
            }}

            saveState();

            // 첫 번째 행에 병합
            const firstRow = rows[0];
            const lastRow = rows[rows.length - 1];

            const mergedText = rows.map(r => r.querySelector('.text-edited').textContent).join(' ');
            firstRow.querySelector('.text-edited').textContent = mergedText;
            firstRow.dataset.endFrame = lastRow.dataset.endFrame;
            firstRow.dataset.endTime = lastRow.dataset.endTime;
            firstRow.querySelector('.frame:nth-child(6)').textContent = lastRow.dataset.endFrame;
            firstRow.querySelector('.time:nth-child(8)').textContent = formatTime(parseFloat(lastRow.dataset.endTime));

            const duration = (parseInt(lastRow.dataset.endFrame) - parseInt(firstRow.dataset.startFrame) + 1) / FPS;
            firstRow.querySelector('.duration').textContent = formatTime(duration);

            // 나머지 행 삭제
            for (let i = 1; i < rows.length; i++) {{
                rows[i].remove();
            }}

            selectedRows.clear();
            renumberRows();

            // 자동 리네임 (Scene_001, Scene_002...)
            tbody.querySelectorAll('tr').forEach((row, idx) => {{
                const sceneNum = 'Scene_' + String(idx + 1).padStart(3, '0');
                row.querySelector('.text-edited').textContent = sceneNum;
            }});

            rebuildTimeline();

            // 실시간 동기화
            sendSegmentsToServer();
        }});

        // 선택 구간 삭제
        document.getElementById('deleteBtn').addEventListener('click', function() {{
            if (selectedRows.size === 0) {{
                alert('삭제할 구간을 선택하세요');
                return;
            }}

            if (!confirm('선택한 ' + selectedRows.size + '개 구간을 삭제하시겠습니까?')) {{
                return;
            }}

            saveState();

            const indices = Array.from(selectedRows).sort((a, b) => b - a);
            indices.forEach(i => {{
                tbody.querySelectorAll('tr')[i].remove();
            }});

            selectedRows.clear();
            renumberRows();

            // 자동 리네임 (Scene_001, Scene_002...)
            tbody.querySelectorAll('tr').forEach((row, idx) => {{
                const sceneNum = 'Scene_' + String(idx + 1).padStart(3, '0');
                row.querySelector('.text-edited').textContent = sceneNum;
            }});

            rebuildTimeline();

            // 실시간 동기화
            sendSegmentsToServer();
        }});

        // 씬 번호 자동 부여
        document.getElementById('sceneNumberBtn').addEventListener('click', function() {{
            if (!confirm('모든 씬에 자동으로 번호를 부여하시겠습니까?')) {{
                return;
            }}

            saveState();

            tbody.querySelectorAll('tr').forEach((row, idx) => {{
                const sceneNum = 'Scene_' + String(idx + 1).padStart(3, '0');
                row.querySelector('.text-edited').textContent = sceneNum;
            }});

            rebuildTimeline();

            // 실시간 동기화
            sendSegmentsToServer();
        }});

        // 항목 리네임
        document.getElementById('renameBtn').addEventListener('click', function() {{
            if (selectedRows.size === 0) {{
                alert('리네임할 항목을 선택하세요');
                return;
            }}

            const pattern = prompt('새 이름 패턴을 입력하세요\\n{{n}}은 번호로 대체됩니다\\n예: Scene_{{n}}', 'Scene_{{n}}');
            if (!pattern) return;

            saveState();

            const indices = Array.from(selectedRows).sort((a, b) => a - b);
            indices.forEach((idx, i) => {{
                const row = tbody.querySelectorAll('tr')[idx];
                const newName = pattern.replace(/{{n}}/g, String(i + 1).padStart(3, '0'));
                row.querySelector('.text-edited').textContent = newName;
            }});

            rebuildTimeline();

            // 실시간 동기화
            sendSegmentsToServer();
        }});

        // 스마트 병합 (데스크탑과 동일한 로직: Scene 번호 기반)
        document.getElementById('smartMergeBtn').addEventListener('click', function() {{
            if (!confirm('같은 Scene 번호를 가진 연속된 항목을 자동으로 병합하시겠습니까?')) {{
                return;
            }}

            saveState();

            const rows = Array.from(tbody.querySelectorAll('tr'));
            const groups = [];
            let currentGroup = null;

            // Scene 번호 추출 함수 (데스크탑과 동일)
            function extractSceneNumber(text) {{
                if (!text) return null;
                // "Scene XXX" 또는 "Scene XXX - Panel Y" 패턴에서 Scene 번호 추출
                const match = text.match(/scene\s+(\d+)/i);
                if (match) {{
                    return parseInt(match[1]);
                }}
                return null;
            }}

            // Scene 번호 기반으로 그룹화 (데스크탑과 동일한 로직)
            for (let i = 0; i < rows.length; i++) {{
                const row = rows[i];
                if (!row) continue;

                const text = row.querySelector('.text-edited').textContent.trim();
                const sceneNum = extractSceneNumber(text);

                if (sceneNum === null) {{
                    // Scene 번호가 없으면 현재 그룹 종료
                    if (currentGroup && currentGroup.rows.length >= 2) {{
                        groups.push(currentGroup);
                    }}
                    currentGroup = null;
                }} else {{
                    if (currentGroup === null) {{
                        // 새 그룹 시작
                        currentGroup = {{ sceneNum: sceneNum, rows: [i] }};
                    }} else if (currentGroup.sceneNum === sceneNum) {{
                        // 같은 Scene 번호면 현재 그룹에 추가
                        currentGroup.rows.push(i);
                    }} else {{
                        // Scene 번호가 바뀌면 현재 그룹 저장하고 새 그룹 시작
                        if (currentGroup.rows.length >= 2) {{
                            groups.push(currentGroup);
                        }}
                        currentGroup = {{ sceneNum: sceneNum, rows: [i] }};
                    }}
                }}
            }}

            // 마지막 그룹 처리
            if (currentGroup && currentGroup.rows.length >= 2) {{
                groups.push(currentGroup);
            }}

            if (groups.length === 0) {{
                alert('병합할 그룹이 없습니다.\\n\\n같은 Scene 번호를 가진 연속된 항목이 2개 이상 있어야 합니다.\\n예: "Scene 8 - Panel A", "Scene 8 - Panel B" → 자동 병합');
                return;
            }}

            // 역순으로 병합 (뒤에서부터 병합해야 인덱스가 꼬이지 않음)
            let totalMerged = 0;
            for (let g = groups.length - 1; g >= 0; g--) {{
                const group = groups[g];
                if (group.rows.length < 2) continue;

                const firstRowIdx = group.rows[0];
                const lastRowIdx = group.rows[group.rows.length - 1];
                const firstRow = rows[firstRowIdx];
                const lastRow = rows[lastRowIdx];

                if (!firstRow || !lastRow) continue;

                // 병합: 첫 번째 행의 endFrame을 마지막 행의 endFrame으로 변경
                firstRow.dataset.endFrame = lastRow.dataset.endFrame;
                firstRow.dataset.endTime = lastRow.dataset.endTime;
                firstRow.querySelector('.frame:nth-child(6)').textContent = lastRow.dataset.endFrame;
                firstRow.querySelector('.time:nth-child(8)').textContent = formatTime(parseFloat(lastRow.dataset.endTime));

                const duration = (parseInt(lastRow.dataset.endFrame) - parseInt(firstRow.dataset.startFrame) + 1) / FPS;
                firstRow.querySelector('.duration').textContent = formatTime(duration);

                // 편집 텍스트: Panel 부분 제거, Scene 번호만 유지 (데스크탑과 동일)
                firstRow.querySelector('.text-edited').textContent = 'Scene ' + group.sceneNum;

                // 나머지 행들 삭제 (역순으로)
                for (let r = group.rows.length - 1; r >= 1; r--) {{
                    const rowIdx = group.rows[r];
                    if (rows[rowIdx]) {{
                        rows[rowIdx].remove();
                        rows[rowIdx] = null;
                        totalMerged++;
                    }}
                }}
            }}

            renumberRows();
            rebuildTimeline();
            alert(totalMerged + '개 씬이 병합되었습니다');

            // 실시간 동기화
            if (totalMerged > 0) {{
                sendSegmentsToServer();
            }}
        }});

        // 씬 분할
        document.getElementById('splitBtn').addEventListener('click', function() {{
            if (selectedRows.size !== 1) {{
                alert('분할하려면 정확히 1개의 씬을 선택하세요.');
                return;
            }}

            const selectedIndex = Array.from(selectedRows)[0];
            const row = tbody.querySelectorAll('tr')[selectedIndex];
            if (!row) return;

            const startFrame = parseInt(row.dataset.startFrame);
            const endFrame = parseInt(row.dataset.endFrame);

            // 분할할 수 있는지 확인 (최소 2프레임 이상)
            if (endFrame - startFrame < 2) {{
                alert('씬이 너무 짧아서 분할할 수 없습니다. (최소 2프레임 필요)');
                return;
            }}

            // 분할할 프레임 위치 입력받기 (1-based로 표시)
            const minFrame = startFrame + 2; // 최소 시작 프레임 + 2 (최소 1프레임은 남겨야 함) - 1-based
            const maxFrame = endFrame + 1; // 최대 종료 프레임 (최소 1프레임은 남겨야 함) - 1-based
            const defaultFrame = Math.floor((startFrame + endFrame) / 2) + 1; // 중간 지점 (1-based)

            const splitFrameInput = prompt(
                '분할할 프레임 위치를 입력하세요:\\n(현재 씬: 프레임 ' + (startFrame + 1) + ' ~ ' + (endFrame + 1) + ')\\n최소: ' + minFrame + ', 최대: ' + maxFrame,
                String(defaultFrame)
            );

            if (!splitFrameInput) return; // 사용자가 취소

            const splitFrame1Based = parseInt(splitFrameInput);
            if (isNaN(splitFrame1Based) || splitFrame1Based < minFrame || splitFrame1Based > maxFrame) {{
                alert('분할 위치가 유효하지 않습니다.');
                return;
            }}

            // 0-based로 변환
            const splitFrame = splitFrame1Based - 1;

            // 분할 위치 유효성 검사
            if (splitFrame <= startFrame || splitFrame >= endFrame) {{
                alert('분할 위치가 유효하지 않습니다.');
                return;
            }}

            // 씬 분할 전 현재 상태를 undo 스택에 저장
            saveState();

            // WebSocket으로 데스크탑에 분할 명령 전송
            if (ws && ws.readyState === WebSocket.OPEN) {{
                const message = {{
                    type: 'split_segment',
                    row_index: selectedIndex,
                    split_frame: splitFrame
                }};
                ws.send(JSON.stringify(message));
                console.log('[WebSocket] 씬 분할 명령 전송:', message);
                // 분할 후 변경사항을 서버에 전송 (데스크탑이 분할을 완료한 후 동기화)
                // 데스크탑에서 분할이 완료되면 broadcast_segments_change()가 호출되어
                // 웹UI에 변경사항이 자동으로 반영됨
            }} else {{
                alert('데스크탑과 연결이 끊어졌습니다. 페이지를 새로고침하세요.');
            }}
        }});

        // 선택한 항목만 내보내기
        document.getElementById('exportSelectedBtn').addEventListener('click', function() {{
            if (selectedRows.size === 0) {{
                alert('내보낼 구간을 먼저 선택하세요.');
                return;
            }}

            if (!confirm('선택된 ' + selectedRows.size + '개 구간을 내보내시겠습니까?')) {{
                return;
            }}

            // WebSocket으로 데스크탑에 선택 항목만 내보내기 명령 전송
            if (ws && ws.readyState === WebSocket.OPEN) {{
                const includeAudio = document.getElementById('includeAudioCheckBox').checked;
                const selectedIndices = Array.from(selectedRows).sort((a, b) => a - b);
                const message = {{
                    type: 'export_selected',
                    selected_indices: selectedIndices,
                    include_audio: includeAudio
                }};
                ws.send(JSON.stringify(message));
                console.log('[WebSocket] 선택 항목만 내보내기 명령 전송:', message);
            }} else {{
                alert('데스크탑과 연결이 끊어졌습니다. 페이지를 새로고침하세요.');
            }}
        }});

        // 전체 내보내기
        document.getElementById('exportAllBtn').addEventListener('click', function() {{
            // WebSocket으로 데스크탑에 전체 내보내기 명령 전송
            if (ws && ws.readyState === WebSocket.OPEN) {{
                const includeAudio = document.getElementById('includeAudioCheckBox').checked;
                const message = {{
                    type: 'export_all',
                    include_audio: includeAudio
                }};
                ws.send(JSON.stringify(message));
                console.log('[WebSocket] 전체 내보내기 명령 전송:', message);
            }} else {{
                alert('데스크탑과 연결이 끊어졌습니다. 페이지를 새로고침하세요.');
            }}
        }});

        function calculateSimilarity(s1, s2) {{
            const longer = s1.length > s2.length ? s1 : s2;
            const shorter = s1.length > s2.length ? s2 : s1;
            if (longer.length === 0) return 1.0;
            return (longer.length - editDistance(longer, shorter)) / longer.length;
        }}

        function editDistance(s1, s2) {{
            s1 = s1.toLowerCase();
            s2 = s2.toLowerCase();
            const costs = [];
            for (let i = 0; i <= s1.length; i++) {{
                let lastValue = i;
                for (let j = 0; j <= s2.length; j++) {{
                    if (i === 0) costs[j] = j;
                    else if (j > 0) {{
                        let newValue = costs[j - 1];
                        if (s1.charAt(i - 1) !== s2.charAt(j - 1))
                            newValue = Math.min(Math.min(newValue, lastValue), costs[j]) + 1;
                        costs[j - 1] = lastValue;
                        lastValue = newValue;
                    }}
                }}
                if (i > 0) costs[s2.length] = lastValue;
            }}
            return costs[s2.length];
        }}

        function renumberRows() {{
            tbody.querySelectorAll('tr').forEach((row, idx) => {{
                row.dataset.index = idx;
                row.querySelector('.index').textContent = idx + 1;
            }});
        }}

        function rebuildTimeline() {{
            const timelineScroll = document.getElementById('timelineScroll');
            if (!timelineScroll) return;

            timelineScroll.innerHTML = '';
            const allRows = tbody.querySelectorAll('tr');

            allRows.forEach((row, idx) => {{
                const editedText = row.querySelector('.text-edited').textContent;
                const startFrame = parseInt(row.dataset.startFrame);
                const endFrame = parseInt(row.dataset.endFrame);
                const frameCount = endFrame - startFrame + 1;
                
                // 썸네일 이미지 가져오기 (테이블 행에서)
                const thumbImg = row.querySelector('.thumbnail img');
                let timelineThumbHtml = '<div class="timeline-no-thumb">No Image</div>';
                if (thumbImg && thumbImg.src) {{
                    timelineThumbHtml = '<img src="' + thumbImg.src + '" class="timeline-thumb" alt="' + editedText + '">';
                }}

                const timelineItem = document.createElement('div');
                timelineItem.className = 'timeline-item';
                timelineItem.dataset.segmentIndex = idx;

                timelineItem.innerHTML = '<div class="timeline-frame-count-area">' +
                    '<div class="timeline-frame-count">' + frameCount + '</div>' +
                    '</div>' +
                    '<div class="timeline-thumb-container">' +
                    timelineThumbHtml +
                    '</div>' +
                    '<div class="timeline-label">' + editedText + '</div>';

                timelineScroll.appendChild(timelineItem);
            }});

            // 선택 상태 복원
            updateSelection();
        }}

        // Undo/Redo 버튼 이벤트
        if (undoBtn) undoBtn.addEventListener('click', undo);
        if (redoBtn) redoBtn.addEventListener('click', redo);

        // 우클릭 메뉴 생성 및 관리
        let contextMenu = null;
        let contextMenuVisible = false;

        function createContextMenu() {{
            if (contextMenu) return contextMenu;
            
            contextMenu = document.createElement('div');
            contextMenu.className = 'context-menu';
            contextMenu.id = 'contextMenu';
            document.body.appendChild(contextMenu);
            return contextMenu;
        }}

        function showContextMenu(x, y, items) {{
            const menu = createContextMenu();
            menu.innerHTML = '';
            
            items.forEach(item => {{
                if (item === 'separator') {{
                    const separator = document.createElement('div');
                    separator.className = 'context-menu-separator';
                    menu.appendChild(separator);
                }} else {{
                    const menuItem = document.createElement('div');
                    menuItem.className = 'context-menu-item';
                    menuItem.textContent = item.label;
                    if (item.shortcut) {{
                        menuItem.textContent += ' (' + item.shortcut + ')';
                    }}
                    if (item.disabled) {{
                        menuItem.style.opacity = '0.5';
                        menuItem.style.cursor = 'not-allowed';
                    }} else {{
                        menuItem.addEventListener('click', function() {{
                            hideContextMenu();
                            if (item.action) item.action();
                        }});
                    }}
                    menu.appendChild(menuItem);
                }}
            }});
            
            menu.style.display = 'block';
            menu.style.left = x + 'px';
            menu.style.top = y + 'px';
            contextMenuVisible = true;
            
            // 메뉴가 화면 밖으로 나가지 않도록 조정
            const rect = menu.getBoundingClientRect();
            if (rect.right > window.innerWidth) {{
                menu.style.left = (x - rect.width) + 'px';
            }}
            if (rect.bottom > window.innerHeight) {{
                menu.style.top = (y - rect.height) + 'px';
            }}
        }}

        function hideContextMenu() {{
            if (contextMenu) {{
                contextMenu.style.display = 'none';
                contextMenuVisible = false;
            }}
        }}

        // 클릭 시 메뉴 숨기기 (타임라인과 테이블 클릭은 정상 처리되도록)
        document.addEventListener('click', function(e) {{
            if (contextMenuVisible && contextMenu && !contextMenu.contains(e.target)) {{
                hideContextMenu();
            }}
        }}, false);

        // ESC 키로 메뉴 숨기기
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape' && contextMenuVisible) {{
                hideContextMenu();
            }}
        }});

        // 테이블 우클릭 메뉴
        tbody.addEventListener('contextmenu', function(e) {{
            e.preventDefault();
            const row = e.target.closest('tr');
            if (!row) return;
            
            const rowIndex = Array.from(tbody.querySelectorAll('tr')).indexOf(row);
            const menuItems = [
                {{ label: '선택한 구간 병합', action: function() {{ document.getElementById('mergeBtn').click(); }}, shortcut: 'D' }},
                {{ label: '스마트 병합', action: function() {{ document.getElementById('smartMergeBtn').click(); }} }},
                {{ label: '선택 구간 삭제', action: function() {{ document.getElementById('deleteBtn').click(); }}, shortcut: 'X' }},
                'separator',
                {{ label: '씬 분할', action: function() {{ document.getElementById('splitBtn').click(); }} }},
                {{ label: '일괄 리네임', action: function() {{ document.getElementById('renameBtn').click(); }} }},
                'separator',
                {{ label: '↶ 실행 취소', action: function() {{ if (undoBtn) undoBtn.click(); }}, shortcut: 'Ctrl+Z', disabled: !undoBtn || undoBtn.disabled }},
                {{ label: '↷ 다시 실행', action: function() {{ if (redoBtn) redoBtn.click(); }}, shortcut: 'Ctrl+Shift+Z', disabled: !redoBtn || redoBtn.disabled }},
                'separator',
                {{ label: '선택한 항목만 내보내기', action: function() {{ document.getElementById('exportSelectedBtn').click(); }} }},
                {{ label: '전체 내보내기', action: function() {{ document.getElementById('exportAllBtn').click(); }}, shortcut: 'R' }},
                'separator',
                {{ label: '재분석', action: function() {{ /* 재분석 기능은 데스크탑에서만 가능 */ }} }}
            ];
            
            showContextMenu(e.pageX, e.pageY, menuItems);
        }});

        // 타임라인 우클릭 메뉴 (기존 클릭 이벤트와 충돌하지 않도록 별도로 처리)
        // timelineScroll은 이미 위에서 선언되었으므로 재선언하지 않음
        if (timelineScroll) {{
            timelineScroll.addEventListener('contextmenu', function(e) {{
                e.preventDefault();
                e.stopPropagation(); // 이벤트 전파 중지
                const menuItems = [
                    {{ label: '선택한 구간 병합', action: function() {{ document.getElementById('mergeBtn').click(); }}, shortcut: 'D' }},
                    {{ label: '스마트 병합', action: function() {{ document.getElementById('smartMergeBtn').click(); }} }},
                    {{ label: '선택 구간 삭제', action: function() {{ document.getElementById('deleteBtn').click(); }}, shortcut: 'X' }},
                    'separator',
                    {{ label: '씬 분할', action: function() {{ document.getElementById('splitBtn').click(); }} }},
                    {{ label: '일괄 리네임', action: function() {{ document.getElementById('renameBtn').click(); }} }},
                    'separator',
                    {{ label: '↶ 실행 취소', action: function() {{ if (undoBtn) undoBtn.click(); }}, shortcut: 'Ctrl+Z', disabled: !undoBtn || undoBtn.disabled }},
                    {{ label: '↷ 다시 실행', action: function() {{ if (redoBtn) redoBtn.click(); }}, shortcut: 'Ctrl+Shift+Z', disabled: !redoBtn || redoBtn.disabled }},
                    'separator',
                    {{ label: '선택한 항목만 내보내기', action: function() {{ document.getElementById('exportSelectedBtn').click(); }} }},
                    {{ label: '전체 내보내기', action: function() {{ document.getElementById('exportAllBtn').click(); }}, shortcut: 'R' }},
                    'separator',
                    {{ label: '재분석', action: function() {{ /* 재분석 기능은 데스크탑에서만 가능 */ }} }}
                ];
                
                showContextMenu(e.pageX, e.pageY, menuItems);
            }});
        }}

        // 키보드 단축키
        document.addEventListener('keydown', function(e) {{
            // 텍스트 입력 중에는 비디오 단축키 무시
            const isInputFocused = e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA';

            // Ctrl/Cmd+Z: Undo
            if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z') {{
                e.preventDefault();
                undo();
                return;
            }}

            // Ctrl/Cmd+Shift+Z 또는 Ctrl/Cmd+Y: Redo
            if ((e.ctrlKey || e.metaKey) && (e.shiftKey && e.key === 'z' || e.key === 'y')) {{
                e.preventDefault();
                redo();
                return;
            }}

            // Ctrl+F 또는 Cmd+F: 검색 박스에 포커스
            if ((e.ctrlKey || e.metaKey) && e.key === 'f') {{
                e.preventDefault();
                searchBox.focus();
                return;
            }}

            // Escape: 검색 초기화
            if (e.key === 'Escape') {{
                clearSearch();
                return;
            }}

            // 비디오 재생 단축키 (입력 중이 아닐 때만)
            if (!isInputFocused && currentSegment) {{
                // Space: 재생/일시정지
                if (e.key === ' ') {{
                    e.preventDefault();
                    togglePlay();
                }}
                // 왼쪽 화살표: 이전 프레임
                else if (e.key === 'ArrowLeft') {{
                    e.preventDefault();
                    prevFrame();
                }}
                // 오른쪽 화살표: 다음 프레임
                else if (e.key === 'ArrowRight') {{
                    e.preventDefault();
                    nextFrame();
                }}
            }}
        }});
    </script>
</body>
</html>"""

    return html


def _format_time(seconds):
    """시간을 HH:MM:SS.mmm 형식으로 포맷팅합니다."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    else:
        return f"{minutes:02d}:{secs:06.3f}"


def _escape_html(text):
    """HTML 특수 문자를 이스케이프합니다."""
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def _generate_sequence_text(segments):
    """시퀀스 텍스트를 생성합니다."""
    lines = []
    for seg in segments:
        text = seg.get('edited_text', seg.get('text', ''))
        if text:
            lines.append(text)
    return _escape_html("\n".join(lines))


def open_web_report(html_path):
    """생성된 웹 리포트를 브라우저로 엽니다."""
    if html_path and os.path.exists(html_path):
        try:
            abs_path = os.path.abspath(html_path)
            print(f"[웹 분석] 브라우저 열기 시도: {abs_path}")
            
            # 1. webbrowser 모듈 시도
            # file:// 프로토콜 명시
            url = f"file://{abs_path}"
            
            try:
                # new=2: 새 탭에서 열기 시도
                success = webbrowser.open(url, new=2)
                if success:
                    print(f"[웹 분석] webbrowser.open 성공")
                    return True
            except Exception as e:
                print(f"[웹 분석] webbrowser.open 예외 발생: {e}")
            
            print(f"[웹 분석] webbrowser.open 실패 (또는 False 반환), 시스템 명령 시도")
            
            # 2. 시스템 명령 시도 (OS별 분기)
            if sys.platform == 'darwin':  # macOS
                subprocess.run(['open', abs_path], check=True)
                print(f"[웹 분석] macOS open 명령 성공")
                return True
            elif sys.platform == 'win32':  # Windows
                os.startfile(abs_path)
                print(f"[웹 분석] Windows os.startfile 성공")
                return True
            else:  # Linux etc.
                subprocess.run(['xdg-open', abs_path], check=True)
                print(f"[웹 분석] Linux xdg-open 명령 성공")
                return True
                
        except Exception as e:
            print(f"[웹 분석] 브라우저 열기 실패: {e}")
            return False
            
    print(f"[웹 분석] 파일이 없거나 경로가 잘못됨: {html_path}")
    return False
