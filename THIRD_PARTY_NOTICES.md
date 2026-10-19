# 제3자 구성 요소 고지 (Third-Party Notices)

이 문서는 빌드된 YesonCheck — Mac 앱(`YesonCheck_Autocut_<Intel|AppleSilicon>.app`, `.dmg`)과 Windows 설치 파일
(`YesonCheck_Setup_<커밋>.exe`) — 에 함께 들어가는 제3자 구성 요소와 그 라이선스·소스 위치입니다.

- YesonCheck 자체 코드(이 저장소)의 라이선스는 [LICENSE](LICENSE)(GNU GPL 3.0)입니다.
- 아래 구성 요소는 각자 적힌 라이선스를 따릅니다. 이 저장소의 `apted/`는 PaddleOCR이 쓰는 `apted` API를 이 프로젝트가
  다시 구현한 것이라 YesonCheck 코드에 속합니다.
- 이 파일과 `LICENSE`는 앱에도 들어 있습니다: Mac은 `YesonCheck_Autocut_<…>.app/Contents/Resources/`,
  Windows는 설치 폴더(기본 `C:\YesonCheck\`)와 그 아래 `_internal\`.
- 의존성(lock 파일)·spec·번들 ffmpeg를 바꾸면 이 파일도 같이 고치세요 (만드는 방법은 6절).

## 1. 주요 구성 요소

| 구성 요소 | 버전 | 라이선스 | 소스·출처 |
|---|---|---|---|
| Python (CPython) | 3.10.19 (Mac 빌드 환경 `~/coding/p310_tf`, uv가 받은 python-build-standalone 빌드). Windows는 빌드 때 uv가 받는 3.10.x | PSF-2.0 (함께 든 Tcl/Tk·OpenSSL·libffi 등은 3절) | https://www.python.org/ftp/python/3.10.19/ , https://github.com/astral-sh/python-build-standalone |
| PyInstaller 부트로더·로더 (실행 파일 `YesonCheck_Autocut`) | 6.14.1 | GPL-2.0-or-later WITH Bootloader-exception (`PyInstaller/hooks/rthooks`는 Apache-2.0) | https://github.com/pyinstaller/pyinstaller/tree/v6.14.1 |
| PyQt5 | 5.15.11 | GPL-3.0 | https://pypi.org/project/PyQt5/5.15.11/ (소스 배포본), https://www.riverbankcomputing.com/software/pyqt/ |
| Qt (PyQt5-Qt5 휠의 Qt 라이브러리·플러그인) | Mac 5.15.19, Windows 5.15.2 | LGPL-3.0 (Qt 안의 제3자 코드: https://doc.qt.io/qt-5/licenses-used-in-qt.html ) | https://download.qt.io/archive/qt/5.15/5.15.19/ , https://download.qt.io/archive/qt/5.15/5.15.2/ |
| FFmpeg (`ffmpeg`·`ffprobe` 정적 실행 파일) | 9.0.2 | GPL-3.0-or-later (libx264 등 GPL 라이브러리 포함) | 2절 |
| OpenCV (opencv-python·opencv-contrib-python·opencv-python-headless 휠, contrib 포함) | 4.6.0.66 (OpenCV 4.6.0) | OpenCV: Apache-2.0, 휠 포장 스크립트: MIT (휠 안의 FFmpeg 4.4.2 등은 3절) | https://github.com/opencv/opencv/tree/4.6.0 , https://github.com/opencv/opencv_contrib/tree/4.6.0 , https://github.com/opencv/opencv-python/tree/66 |
| PaddlePaddle | Mac 3.0.0, Windows 2.6.2 | Apache-2.0 | https://github.com/PaddlePaddle/Paddle/tree/v3.0.0 , https://github.com/PaddlePaddle/Paddle/tree/v2.6.2 |
| PaddleOCR | 2.7.3 | Apache-2.0 | https://github.com/PaddlePaddle/PaddleOCR/tree/v2.7.3 |
| PaddleOCR 모델 (PP-OCR 검출·인식·방향 분류) | PaddleOCR 2.7.3 기본 모델 | Apache-2.0 | **앱에 넣지 않음** — 처음 OCR을 쓸 때 PaddleOCR이 내려받아 사용자 폴더(`~/.paddleocr` 등)에 둠. 목록: https://github.com/PaddlePaddle/PaddleOCR/blob/v2.7.3/doc/doc_en/models_list_en.md |
| TensorFlow | 2.15.1 (Windows: tensorflow-intel 2.15.1) | Apache-2.0 (TensorFlow 안의 제3자 코드: https://github.com/tensorflow/tensorflow/tree/v2.15.1/third_party ) | https://github.com/tensorflow/tensorflow/tree/v2.15.1 |
| TransNetV2 (로더 코드 `yesoncheck/transnetv2_model.py`, 가중치 `vendor/transnetv2-weights/`) | upstream 커밋 85cef72 | MIT — 고지: `vendor/transnetv2-weights/LICENSE` (앱의 `transnetv2-weights/LICENSE`) | https://github.com/soCzech/TransNetV2/tree/85cef72af9a916bdfd7cc94a670c9cdfbf12d1ed |
| NumPy | 1.26.4 | BSD-3-Clause (휠 안의 OpenBLAS·GCC 런타임은 3절) | https://github.com/numpy/numpy/tree/v1.26.4 |
| scikit-image | 0.24.0 | BSD-3-Clause | https://github.com/scikit-image/scikit-image/tree/v0.24.0 |
| PySceneDetect (scenedetect) | 0.6.7.1 | BSD-3-Clause | https://github.com/Breakthrough/PySceneDetect/tree/v0.6.7.1-release |
| cryptography | 48.0.1 | Apache-2.0 OR BSD-3-Clause (휠 안에 정적으로 든 OpenSSL: Apache-2.0) | https://github.com/pyca/cryptography/tree/48.0.1 |
| PyMuPDF | 1.28.2 | AGPL-3.0 (Artifex 이중 라이선스, MuPDF 포함) — PaddleOCR이 PDF를 읽으려고 불러와 함께 들어감 | https://github.com/pymupdf/PyMuPDF/tree/1.28.2 |
| Microsoft Visual C++ 런타임 (Windows만: `msvcp140.dll`·`msvcp140_1.dll`·`vcruntime140*.dll` 등) | Visual C++ 2015–2022 | Microsoft 재배포 조건 (Visual Studio 라이선스의 재배포 가능 파일) | https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files |
| Inno Setup (Windows 설치·제거 프로그램 `YesonCheck_Setup_*.exe`·`unins000.exe`) | 6 | Inno Setup License | https://jrsoftware.org/files/is/license.txt , https://github.com/jrsoftware/issrc |

## 2. FFmpeg (번들 정적 실행 파일)

앱은 FFmpeg를 고치지 않고 따로 실행하는 프로그램으로 씁니다 (Mac `Contents/Frameworks/ffmpeg`·`ffprobe`,
Windows `_internal\ffmpeg.exe`·`ffprobe.exe`). 출처·sha256은 `vendor/ffmpeg/README.md`, 받는 스크립트는
`fetch_ffmpeg.sh`(Mac)·`fetch_ffmpeg_windows.ps1`(Windows).

- **Mac (x86_64·arm64): Martin Riedl 빌드 FFmpeg 9.0.2** — 정적 빌드, 최소 macOS 12.0.
  - 빌드 설정(`ffmpeg -buildconf`): `--enable-gpl --enable-version3`, libx264·libx265·libvpx·libaom·libdav1d·libsvtav1·
    librav1e·libvvenc·libopenh264·libmp3lame·libopus·libvorbis·libtheora·libwebp·libopenjpeg·libass·libfreetype·fontconfig·
    libharfbuzz·libbluray·libsnappy·libsrt·libvmaf·libklvanc·libzimg·libzvbi·libxml2·openssl → 전체가 **GPL-3.0-or-later**.
  - 받은 곳: https://ffmpeg.martin-riedl.de/ (release 9.0.2 —
    x86_64 `https://ffmpeg.martin-riedl.de/download/macos/amd64/1789931006_9.0.2/{ffmpeg,ffprobe}.zip`,
    arm64 `https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/{ffmpeg,ffprobe}.zip`)
  - 빌드 스크립트: https://git.martin-riedl.de/ffmpeg/build-script
- **Windows: gyan.dev FFmpeg 9.0.2 essentials 빌드** — 64비트 정적 빌드, **GPL-3.0-or-later**("All builds are … licensed as GPLv3"),
  libx264 포함.
  - 받은 곳: https://github.com/GyanD/codexffmpeg/releases/tag/9.0.2 (`ffmpeg-9.0.2-essentials_build.zip`,
    sha256 `60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`)
  - 빌드 안내(포함 라이브러리 목록): https://www.gyan.dev/ffmpeg/builds/
- 대응 소스: FFmpeg 9.0.2 https://ffmpeg.org/releases/ffmpeg-9.0.2.tar.xz (https://ffmpeg.org/download.html),
  x264 https://code.videolan.org/videolan/x264 , x265 https://bitbucket.org/multicoreware/x265_git/src/master/ ,
  그 밖의 라이브러리는 위 빌드 스크립트·빌드 안내에 적힌 버전과 출처.

## 3. 휠 안에 함께 든 네이티브 라이브러리

Python 휠 가운데 아래 것들은 자기 안에 네이티브 라이브러리를 담고 있고, 앱에도 그대로 들어갑니다 (Mac 앱 기준 —
Windows 앱에는 같은 배포본의 Windows 휠이 들어가며 이름이 `.dll`, 예: OpenCV가 담은 FFmpeg는 `opencv_videoio_ffmpeg*.dll`).
라이선스 원문은 각 휠의 라이선스 파일(예: opencv-python의 `LICENSE-3RD-PARTY.txt`)과 각 라이브러리 프로젝트에 있습니다.

| 휠 | 든 라이브러리 | 주요 라이선스 |
|---|---|---|
| opencv-python 4.6.0.66 | FFmpeg 4.4.2(libavcodec·libavformat·libavutil·libswscale·libswresample·libavresample), GnuTLS·Nettle·GMP·libidn2·libunistring·libtasn1·p11-kit, OpenSSL 1.1(libssl·libcrypto), mbedTLS, libaom·dav1d·rav1e·libvpx·libwebp·libjxl·openjpeg·libpng, LAME·Opus·Vorbis·Theora·Speex·opencore-amr·soxr, libbluray·SRT·RIST·ZeroMQ·libsodium, freetype·fontconfig·libintl, snappy·brotli·lzma·libffi·cJSON·vmaf | FFmpeg는 `--enable-version3`로 GPL 부분 없이 빌드 → LGPL-3.0-or-later. GnuTLS·libtasn1·libbluray·soxr·libintl: LGPL-2.1-or-later, Nettle·GMP·libidn2·libunistring: LGPL-3.0-or-later 또는 GPL-2.0-or-later, LAME: LGPL-2.0-or-later, ZeroMQ·SRT: MPL-2.0, OpenSSL 1.1: OpenSSL/SSLeay, freetype: FTL, libpng: libpng, 나머지는 BSD·MIT·ISC·Apache 계열. 원문: https://github.com/opencv/opencv-python/blob/66/LICENSE-3RD-PARTY.txt |
| opencv-contrib-python 4.6.0.66 | Tesseract, Leptonica, libarchive, libtiff, libjpeg, giflib, lz4, zstd, libb2 | Apache-2.0(Tesseract), BSD 계열(Leptonica·libarchive·lz4·zstd), libtiff·IJG·MIT(giflib)·CC0(libb2) |
| numpy 1.26.4, scipy 1.15.3 | OpenBLAS, GCC 런타임(libgfortran·libgcc_s·libquadmath) | OpenBLAS: BSD-3-Clause, libgfortran·libgcc_s: GPL-3.0-or-later WITH GCC-exception-3.1, libquadmath: LGPL-2.1-or-later |
| paddlepaddle | libpaddle·libphi·libpir·libcommon, warpctc·warprnnt, BLAS·LAPACK·GCC 런타임(Apple Silicon 앱에는 없음) | Apache-2.0(Paddle과 그 안의 제3자 코드: https://github.com/PaddlePaddle/Paddle/tree/v3.0.0/third_party ), BSD-3-Clause 계열(BLAS·LAPACK), GCC 런타임은 위와 같음 |
| pillow 12.3.0 | libjpeg-turbo, libpng, libtiff, libwebp, libavif, openjpeg, freetype, harfbuzz, lcms2, xz(liblzma), zlib-ng, brotli, libxcb·libXau | 휠의 LICENSE에 각 원문 (IJG/BSD/Zlib, libpng, libtiff, BSD-3, BSD-2, FTL, MIT, 0BSD 등) |
| pymupdf 1.28.2 | MuPDF(libmupdf·libmupdfcpp) | AGPL-3.0 (Artifex 이중 라이선스) |
| shapely 2.1.2 | GEOS(libgeos·libgeos_c) | LGPL-2.1 (원문: 휠의 `LICENSE_GEOS`) |
| h5py 3.16.0 | HDF5(libhdf5·libhdf5_hl), zlib | HDF5 License (BSD-3-Clause 계열), Zlib |
| scikit-image 0.24.0 | LLVM OpenMP(libomp) | Apache-2.0 WITH LLVM-exception (또는 MIT) |
| tensorflow 2.15.1 | libtensorflow_framework·libtensorflow_cc | Apache-2.0 (안에 든 제3자 코드는 1절 링크) |
| PyQt5-Qt5 | Qt 프레임워크(QtCore·QtGui·QtWidgets·QtMultimedia·QtNetwork·QtWebSockets·QtSvg·QtQml·QtQuick 등)와 플러그인 | LGPL-3.0 (Qt는 앱 안에 따로 된 동적 라이브러리로 들어 있어 바꿔 끼울 수 있음) |
| cryptography 48.0.1 | OpenSSL 3(정적 링크) | Apache-2.0 |
| Python 3.10.19 (python-build-standalone) | libpython, Tcl/Tk 9(tkinter), OpenSSL 3, libffi, SQLite, XZ, bzip2, zlib, expat, mpdecimal | PSF-2.0, TCL, Apache-2.0, MIT, Public Domain, 0BSD, bzip2-1.0.6, Zlib, MIT, BSD-2-Clause |

## 4. 앱에 들어간 Python 배포본 전체 (101개, Mac Intel 빌드 기준)

버전은 Mac Intel(`requirements-build-x86_64.lock`) 기준이고, Apple Silicon(`requirements-build-arm64.lock`)·
Windows(`requirements-build-windows.lock`)에서 다른 것은 괄호에 적었습니다. 소스는 PyPI 배포본 페이지(소스 배포본·
프로젝트 저장소 링크)입니다.

| 배포본 | 버전 | 라이선스 | PyPI |
|---|---|---|---|
| absl-py | 2.5.1 | Apache-2.0 | https://pypi.org/project/absl-py/2.5.1/ |
| altgraph | 0.17.5 | MIT | https://pypi.org/project/altgraph/0.17.5/ |
| anyio | 4.15.1 | MIT | https://pypi.org/project/anyio/4.15.1/ |
| astor | 0.8.1 | BSD-3-Clause | https://pypi.org/project/astor/0.8.1/ |
| astunparse | 1.6.3 | BSD-3-Clause AND PSF-2.0 | https://pypi.org/project/astunparse/1.6.3/ |
| backports.tarfile | 1.2.0 | MIT | https://pypi.org/project/backports.tarfile/1.2.0/ |
| beautifulsoup4 | 4.15.0 | MIT | https://pypi.org/project/beautifulsoup4/4.15.0/ |
| cachetools | 7.2.1 | MIT | https://pypi.org/project/cachetools/7.2.1/ |
| certifi | 2026.7.22 | MPL-2.0 | https://pypi.org/project/certifi/2026.7.22/ |
| cffi | 2.1.1 | MIT-0 | https://pypi.org/project/cffi/2.1.1/ |
| chardet | 7.6.0 | 0BSD | https://pypi.org/project/chardet/7.6.0/ |
| charset-normalizer | 3.5.2 | MIT | https://pypi.org/project/charset-normalizer/3.5.2/ |
| click | 8.2.1 | BSD-3-Clause | https://pypi.org/project/click/8.2.1/ |
| cryptography | 48.0.1 | Apache-2.0 OR BSD-3-Clause | https://pypi.org/project/cryptography/48.0.1/ |
| cssselect | 1.5.0 | BSD-3-Clause | https://pypi.org/project/cssselect/1.5.0/ |
| cssutils | 2.15.0 | LGPL-3.0-or-later | https://pypi.org/project/cssutils/2.15.0/ |
| Cython | 3.3.0 | Apache-2.0 | https://pypi.org/project/Cython/3.3.0/ |
| decorator | 5.3.1 | BSD-2-Clause | https://pypi.org/project/decorator/5.3.1/ |
| encutils | 1.0.0 | LGPL-3.0-or-later | https://pypi.org/project/encutils/1.0.0/ |
| et_xmlfile | 2.0.0 | MIT | https://pypi.org/project/et_xmlfile/2.0.0/ |
| exceptiongroup | 1.3.1 | MIT | https://pypi.org/project/exceptiongroup/1.3.1/ |
| fire | 0.7.1 | Apache-2.0 | https://pypi.org/project/fire/0.7.1/ |
| flatbuffers | 25.12.19 | Apache-2.0 | https://pypi.org/project/flatbuffers/25.12.19/ |
| fonttools | 4.65.0 | MIT | https://pypi.org/project/fonttools/4.65.0/ |
| gast | 0.7.0 | BSD-3-Clause | https://pypi.org/project/gast/0.7.0/ |
| google-auth | 2.62.0 | Apache-2.0 | https://pypi.org/project/google-auth/2.62.0/ |
| google-pasta | 0.2.0 | Apache-2.0 | https://pypi.org/project/google-pasta/0.2.0/ |
| grpcio | 1.84.0 | Apache-2.0 | https://pypi.org/project/grpcio/1.84.0/ |
| h11 | 0.16.0 | MIT | https://pypi.org/project/h11/0.16.0/ |
| h5py | 3.16.0 | BSD-3-Clause | https://pypi.org/project/h5py/3.16.0/ |
| httpcore | 1.0.9 | BSD-3-Clause | https://pypi.org/project/httpcore/1.0.9/ |
| httpx | 0.28.1 | BSD-3-Clause | https://pypi.org/project/httpx/0.28.1/ |
| idna | 3.20 | BSD-3-Clause | https://pypi.org/project/idna/3.20/ |
| ImageIO | 2.38.0 | BSD-2-Clause | https://pypi.org/project/ImageIO/2.38.0/ |
| imgaug | 0.4.0 | MIT | https://pypi.org/project/imgaug/0.4.0/ |
| iniconfig | 2.3.1 (시험용 requirements-test.txt로 빌드 환경에 설치됨 — Mac·Windows 모두 빌드 전에 설치) | MIT | https://pypi.org/project/iniconfig/2.3.1/ |
| jaraco.collections | 5.1.0 | MIT | https://pypi.org/project/jaraco.collections/5.1.0/ |
| jaraco.context | 6.1.2 | MIT | https://pypi.org/project/jaraco.context/6.1.2/ |
| jaraco.functools | 4.6.0 | MIT | https://pypi.org/project/jaraco.functools/4.6.0/ |
| jaraco.text | 3.12.1 | MIT | https://pypi.org/project/jaraco.text/3.12.1/ |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://pypi.org/project/Jinja2/3.1.6/ |
| keras | 2.15.0 | Apache-2.0 | https://pypi.org/project/keras/2.15.0/ |
| lazy-loader | 0.6 | BSD-3-Clause | https://pypi.org/project/lazy-loader/0.6/ |
| lmdb | 3.0.0 | OLDAP-2.8 | https://pypi.org/project/lmdb/3.0.0/ |
| lxml | 6.1.3 | BSD-3-Clause | https://pypi.org/project/lxml/6.1.3/ |
| macholib | 1.16.4 (Windows 없음) | MIT | https://pypi.org/project/macholib/1.16.4/ |
| MarkupSafe | 3.0.4 | BSD-3-Clause | https://pypi.org/project/MarkupSafe/3.0.4/ |
| matplotlib | 3.10.9 | Matplotlib License (PSF 기반) | https://pypi.org/project/matplotlib/3.10.9/ |
| ml-dtypes | 0.3.2 | Apache-2.0 | https://pypi.org/project/ml-dtypes/0.3.2/ |
| more-itertools | 11.1.0 | MIT | https://pypi.org/project/more-itertools/11.1.0/ |
| networkx | 3.4.2 | BSD-3-Clause | https://pypi.org/project/networkx/3.4.2/ |
| numpy | 1.26.4 | BSD-3-Clause | https://pypi.org/project/numpy/1.26.4/ |
| opencv-contrib-python | 4.6.0.66 | MIT (휠 포장) / Apache-2.0 (OpenCV) | https://pypi.org/project/opencv-contrib-python/4.6.0.66/ |
| opencv-python | 4.6.0.66 | MIT (휠 포장) / Apache-2.0 (OpenCV) | https://pypi.org/project/opencv-python/4.6.0.66/ |
| opencv-python-headless | 4.6.0.66 | MIT (휠 포장) / Apache-2.0 (OpenCV) | https://pypi.org/project/opencv-python-headless/4.6.0.66/ |
| openpyxl | 3.1.5 | MIT | https://pypi.org/project/openpyxl/3.1.5/ |
| opt-einsum | 3.3.0 | MIT | https://pypi.org/project/opt-einsum/3.3.0/ |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | https://pypi.org/project/packaging/26.3/ |
| paddleocr | 2.7.3 | Apache-2.0 | https://pypi.org/project/paddleocr/2.7.3/ |
| paddlepaddle | 3.0.0 (Windows 2.6.2) | Apache-2.0 | https://pypi.org/project/paddlepaddle/3.0.0/ |
| pandas | 2.3.3 | BSD-3-Clause | https://pypi.org/project/pandas/2.3.3/ |
| pdf2docx | 0.5.13 | MIT | https://pypi.org/project/pdf2docx/0.5.13/ |
| pillow | 12.3.0 | MIT-CMU | https://pypi.org/project/pillow/12.3.0/ |
| platformdirs | 4.12.3 (Windows 4.12.4) | MIT | https://pypi.org/project/platformdirs/4.12.3/ |
| pluggy | 1.6.0 (시험용 requirements-test.txt로 빌드 환경에 설치됨 — Mac·Windows 모두 빌드 전에 설치) | MIT | https://pypi.org/project/pluggy/1.6.0/ |
| premailer | 3.10.0 | BSD-3-Clause | https://pypi.org/project/premailer/3.10.0/ |
| protobuf | 4.25.9 (Windows 3.20.3) | BSD-3-Clause | https://pypi.org/project/protobuf/4.25.9/ |
| psutil | 7.2.2 | BSD-3-Clause | https://pypi.org/project/psutil/7.2.2/ |
| pyasn1 | 0.6.4 | BSD-2-Clause | https://pypi.org/project/pyasn1/0.6.4/ |
| pyasn1_modules | 0.4.2 | BSD-2-Clause | https://pypi.org/project/pyasn1_modules/0.4.2/ |
| pyclipper | 1.4.0 | MIT | https://pypi.org/project/pyclipper/1.4.0/ |
| pycparser | 3.11 | BSD-3-Clause | https://pypi.org/project/pycparser/3.11/ |
| pyinstaller | 6.14.1 | GPL-2.0-or-later WITH Bootloader-exception (런타임 훅 Apache-2.0) | https://pypi.org/project/pyinstaller/6.14.1/ |
| pymupdf | 1.28.2 | AGPL-3.0 (Artifex 이중 라이선스) | https://pypi.org/project/pymupdf/1.28.2/ |
| PyQt5 | 5.15.11 | GPL-3.0 | https://pypi.org/project/PyQt5/5.15.11/ |
| PyQt5-Qt5 | 5.15.19 (Windows 5.15.2) | LGPL-3.0 (Qt) | https://pypi.org/project/PyQt5-Qt5/5.15.19/ |
| PyQt5_sip | 12.20.0 | BSD-2-Clause | https://pypi.org/project/PyQt5_sip/12.20.0/ |
| pytest | 8.3.5 (시험용 requirements-test.txt로 빌드 환경에 설치됨 — Mac·Windows 모두 빌드 전에 설치) | MIT | https://pypi.org/project/pytest/8.3.5/ |
| python-dateutil | 2.9.0.post0 | Apache-2.0 AND BSD-3-Clause | https://pypi.org/project/python-dateutil/2.9.0.post0/ |
| python-docx | 1.2.0 | MIT | https://pypi.org/project/python-docx/1.2.0/ |
| pytz | 2026.5 | MIT | https://pypi.org/project/pytz/2026.5/ |
| PyYAML | 6.0.3 | MIT | https://pypi.org/project/PyYAML/6.0.3/ |
| RapidFuzz | 3.14.5 | MIT | https://pypi.org/project/RapidFuzz/3.14.5/ |
| requests | 2.34.2 | Apache-2.0 | https://pypi.org/project/requests/2.34.2/ |
| scenedetect | 0.6.7.1 | BSD-3-Clause | https://pypi.org/project/scenedetect/0.6.7.1/ |
| scikit-image | 0.24.0 | BSD-3-Clause | https://pypi.org/project/scikit-image/0.24.0/ |
| scipy | 1.15.3 | BSD-3-Clause | https://pypi.org/project/scipy/1.15.3/ |
| setuptools | 75.8.0 | MIT | https://pypi.org/project/setuptools/75.8.0/ |
| shapely | 2.1.2 | BSD-3-Clause | https://pypi.org/project/shapely/2.1.2/ |
| six | 1.17.0 | MIT | https://pypi.org/project/six/1.17.0/ |
| soupsieve | 2.10 | MIT | https://pypi.org/project/soupsieve/2.10/ |
| tensorflow | 2.15.1 | Apache-2.0 | https://pypi.org/project/tensorflow/2.15.1/ |
| tensorflow-estimator | 2.15.0 | Apache-2.0 | https://pypi.org/project/tensorflow-estimator/2.15.0/ |
| termcolor | 3.3.0 | MIT | https://pypi.org/project/termcolor/3.3.0/ |
| tifffile | 2025.5.10 | BSD-3-Clause | https://pypi.org/project/tifffile/2025.5.10/ |
| tomli | 2.5.0 (시험용 requirements-test.txt로 빌드 환경에 설치됨 — Mac·Windows 모두 빌드 전에 설치) | MIT | https://pypi.org/project/tomli/2.5.0/ |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | https://pypi.org/project/tqdm/4.70.1/ |
| typing_extensions | 4.16.0 | PSF-2.0 | https://pypi.org/project/typing_extensions/4.16.0/ |
| urllib3 | 2.8.0 | MIT | https://pypi.org/project/urllib3/2.8.0/ |
| wheel | 0.48.0 | MIT | https://pypi.org/project/wheel/0.48.0/ |
| wrapt | 1.14.2 | BSD-2-Clause | https://pypi.org/project/wrapt/1.14.2/ |

Windows lock에만 있는 배포본 (Windows 앱에 들어감 또는 들어갈 수 있음):

| 배포본 | 버전 | 라이선스 | 이유 | PyPI |
|---|---|---|---|---|
| tensorflow-intel | 2.15.1 | Apache-2.0 | TensorFlow의 Windows 휠 (tensorflow 2.15.1이 끌어옴) | https://pypi.org/project/tensorflow-intel/2.15.1/ |
| colorama | 0.4.6 | BSD-3-Clause | tqdm·click이 Windows에서 불러옴 | https://pypi.org/project/colorama/0.4.6/ |
| pefile | 2023.2.7 | MIT | PyInstaller의 Windows 의존성 (PyInstaller 모듈과 함께 들어갈 수 있음) | https://pypi.org/project/pefile/2023.2.7/ |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause | PyInstaller의 Windows 의존성 (PyInstaller 모듈과 함께 들어갈 수 있음) | https://pypi.org/project/pywin32-ctypes/0.2.3/ |

## 5. GPL·LGPL 구성 요소의 소스

GPL·LGPL·AGPL 구성 요소(FFmpeg, x264 등, PyQt5, Qt, PyMuPDF/MuPDF, PyInstaller 부트로더, cssutils·encutils(LGPL-3.0),
GEOS, GnuTLS 등)는 바꾸지 않고 넣었으며, 대응 소스는 위 각 링크(같은 버전)에서 받을 수 있습니다. YesonCheck 자체 소스는
https://github.com/yesonsys03-web/yesoncheck 입니다 (GPL-3.0).

## 6. 이 목록을 만든 방법

1. Mac Intel 빌드 환경(`~/coding/p310_tf`, Python 3.10.19)에서 `importlib.metadata.distributions()`로 설치된 배포본
   131개의 이름·버전·`License-Expression`·`License`·분류자(`License ::`)와 RECORD(파일 목록)를 모음.
2. PyInstaller 빌드 기록 `build/YesonCheck_Autocut/PYZ-00.toc`·`COLLECT-00.toc`(2026-10-16 Mac Intel 빌드, 커밋 `1e1c851`
   — 그 뒤 lock·spec 바뀜 없음)에 적힌 원본 파일 경로를 1의 RECORD와 대조 → 파일이 하나라도 앱에 들어간 배포본만 4절 표에 넣음.
   앱에 들어가지 않은 설치 배포본 30개: Flask, Markdown, Werkzeug, attrdict, autocommand, babel, bce-python-sdk, blinker, contourpy, crc32c, cycler, flask-babel, future, google-auth-oauthlib, inflect, itsdangerous, kiwisolver, libclang, oauthlib, pycryptodome, pyinstaller-hooks-contrib, pyparsing, rarfile, requests-oauthlib, tensorboard, tensorboard-data-server, tensorflow-io-gcs-filesystem, typeguard, tzdata, visualdl.
3. 라이선스 칸: `License-Expression`이 있으면 그대로, 없으면 `License` 필드·분류자를 SPDX 이름으로 옮겨 적음
   (`License` 필드가 저작권 문구나 전문인 것은 그 배포본의 라이선스 파일로 확인함).
4. Windows: 같은 spec·같은 코드로 모으므로 같은 배포본이 들어감 — Mac lock과 Windows lock을 비교해 버전 차이와
   Windows에만 있는 배포본을 적음 (Windows 빌드 목록으로는 확인하지 않음).
5. 3절: `COLLECT-00.toc`의 BINARY 항목을 RECORD로 배포본별로 묶어 휠 안의 네이티브 라이브러리를 찾음.
6. 2절: 번들 ffmpeg의 `-version`·`-buildconf`(Mac), `vendor/ffmpeg/README.md`·`fetch_ffmpeg*.{sh,ps1}`과 배포처 안내(Windows).
