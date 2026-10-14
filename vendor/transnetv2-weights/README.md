# TransNetV2 가중치 (애니매틱2 씬 감지)

애니매틱2(TransNetV2) 모드가 쓰는 학습된 모델(TensorFlow SavedModel)입니다.
YesonCheck_Autocut.spec이 각 파일의 sha256을 확인한 뒤 앱의 `transnetv2-weights/`에 넣고,
`yesoncheck/transnetv2_detector.py`가 이 폴더(빌드된 앱에서는 `sys._MEIPASS/transnetv2-weights`)를 엽니다.

- 출처: https://github.com/soCzech/TransNetV2 (`inference/transnetv2-weights/`)
- 커밋: `85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed`
- 받은 주소: `https://media.githubusercontent.com/media/soCzech/TransNetV2/85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed/inference/transnetv2-weights/<파일>`
  (upstream 저장소에서는 Git LFS 파일이라 `pip install git+…`로 받으면 132바이트짜리 포인터 파일만 들어옴 → 직접 받아 여기에 넣음)
- 받은 날: 2026-10-14, 아래 sha256 대조함
- 라이선스: MIT, Copyright (c) 2020 Tomáš Souček — 전문은 같은 폴더의 `LICENSE`
- 함께 쓰는 로더 코드: `yesoncheck/transnetv2_model.py` (같은 커밋의 `inference/transnetv2.py`를 그대로 복사)

| 파일 | 크기 (바이트) | sha256 |
|---|---:|---|
| `saved_model.pb` | 5,933,260 | 8ac2a52c5719690d512805b6eaf5ce12097c1d8860b3d9de245dcbbc3100f554 |
| `variables/variables.data-00000-of-00001` | 30,516,656 | b8c9dc3eb807583e6215cabee9ca61737b3eb1bceff68418b43bf71459669367 |
| `variables/variables.index` | 5,526 | 8b99e28b4ad11372d9a1ad9703298c2e370df14859da4245fdbe818e92dd403f |

파일을 바꾸면 YesonCheck_Autocut.spec의 sha256 표와 위 표를 같이 고치세요.
