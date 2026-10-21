#!/bin/bash
# YesonCheck Mac 업데이트 도우미 — 앱이 끝난 뒤 새 앱으로 바꾸고 다시 켜며, 잘 켜지지 않으면 되돌린다.
#
#   bash update_helper_mac.sh --pid PID --app APP --staged STAGED --target VER --ok OKFILE --log LOG [--timeout S]
#       [--token TOKEN]
#
# TOKEN: 앱의 업데이트 기록(pending_update.json)의 토큰. 도우미가 켜는 앱(새 앱, 되돌리거나 바꾸지 않고 다시 켜는 옛 앱)에
# 모두 `--update-result TOKEN`으로 넘김(open -n [-W] APP --args --update-result TOKEN, 직접 실행도 같은 인자) — 그 앱만
# 지난 업데이트의 결과를 판정하고, 업데이트 중에 사용자가 켠 앱은 "업데이트 중" 창만 보이고 끝남(launch_args,
# update_install.startup_result·update_in_progress). 없으면(토큰을 모르는 옛 앱이 띄움) 인자 없이 켬.
#
# 앱(update_install.launch_helper_mac)이 이 파일을 업데이트 상태 폴더로 복사해 새 세션으로 띄운 뒤 끝난다.
# 순서: PID가 끝나기를 기다림(300초 — 넘으면 아무것도 바꾸지 않음) → APP/Contents/MacOS/ 아래 실행 파일로 도는 다른
# 프로세스(다른 창 — 이 사용자·다른 사용자 모두)가 끝나기를 기다림(YC_OTHERS_TIMEOUT초 — 바꾸면 그 창들이 다음 지연
# import에서 죽음: PyInstaller가 import마다 PYZ를 경로로 다시 엶. 앱은 넘기기 전에 이 사용자의 다른 창을 닫고, 업데이트 중에
# 켜진 창은 몇 초 안에 스스로 끝남 — 이것은 그 뒤의 안전장치. 넘으면 바꾸지 않고 아래 되돌리기처럼 옛 앱을 켜고 끝냄)
# → APP을 <APP 이름>.update-backup.app으로,
# STAGED를 APP으로 옮김(앱 폴더에 쓸 수 없으면 두 mv를 관리자 암호 창으로 함께 — 그 뒤의 백업 지우기나 되돌리기도
# 앱 폴더를 건드리므로 암호 창을 한 번 더 띄움; 켜기는 늘 사용자로) → OKFILE을 지움 → 새 앱을 켬 →
# 새 앱이 창을 보인 뒤 쓰는 OKFILE({"version": "VER"})을 --timeout초까지 기다림 → 되면 백업과 OKFILE을 지움.
# 중간에 실패하거나, 새 앱이 표시 없이 끝나거나, 시간이 지나면 되돌림: 도우미가 켠 새 앱 프로세스만 끝내고(새 앱을 켜기
# 직전에 이미 돌던 같은 앱 프로세스 — 바꾸는 사이에 사용자가 켠 창 — 는 건드리지 않음) 새 앱을 치운 뒤
# 백업을 APP으로 되돌려 옛 앱을 켠다. APP 자리에 앱이 없는 채로 끝내지 않는다 — 되돌리기마저 실패하면 두 오류를
# 모두 기록하고, 알림 창(osascript display alert — 백업 앱의 자리)을 띄운 뒤(앱이 없으니 다음 실행에서 알릴 수 없음) 종료
# 코드 2. 시작할 때 앱 자리에 앱이 없을 때도 같음.
#
# 종료 코드: 0 업데이트 성공, 1 바꾸지 않았거나 되돌림(옛 앱을 켬), 2 되돌리기 실패 또는 잘못된 인자.
#
# 모든 단계와 실패를 LOG에 "YYYY-MM-DDTHH:MM:SS 도우미: 내용" 한 줄씩 덧붙인다 — update_install.log()와 같은 시각
# 형식이고(앱의 줄은 시각 뒤에 "[pid N]") 다시 켜진 앱이 log_tail_since로 업데이트를 건 창의 줄과 이 줄들을 "업데이트 실패"
# 창에 보여 준다(시각 없이 이어지는 줄은 앞줄을 따름).
# macOS 기본 /bin/bash(3.2)에서 돈다. set -e는 쓰지 않는다 — 실패마다 직접 처리해야 되돌리기가 반드시 돈다.
#
# 환경 변수 (주로 시험용):
#   YC_UPDATE_OK_TIMEOUT_S   --timeout의 기본값 (없으면 180초)
#   YC_UPDATE_PID_TIMEOUT_S  앱이 끝나기를 기다리는 시간 (없으면 300초)
#   YC_OTHERS_TIMEOUT        그 뒤 같은 앱의 다른 프로세스(다른 창)가 모두 끝나기를 기다리는 시간 (없으면 60초 — 업데이트 중에
#                            켜진 창이 "업데이트 중" 창을 보이고 스스로 끝나는 시간(app.UPDATE_IN_PROGRESS_CLOSE_MS)보다 넉넉히)
#   YC_UPDATE_DIRECT_LAUNCH  1이면 open 대신 APP/Contents/MacOS/YesonCheck_Autocut을 직접 백그라운드로 켬
#                            (환경 변수를 그대로 물려받고, 출력은 LOG에 덧붙임)
#   YC_UPDATE_OPEN           open 대신 부를 명령 (시험의 가짜 open)
#   YC_UPDATE_OSASCRIPT      관리자 암호 창·종료 코드 2의 알림 창에 쓸 osascript 대신 부를 명령
#   YC_UPDATE_NO_MESSAGEBOX  1이면 종료 코드 2의 알림 창을 띄우지 않음 (시험이 멈추지 않게)

set -u

EXE_NAME="YesonCheck_Autocut"
PID=""
APP=""
STAGED=""
TARGET=""
OKFILE=""
LOG=""
TOKEN=""
TIMEOUT="${YC_UPDATE_OK_TIMEOUT_S:-180}"
PID_TIMEOUT="${YC_UPDATE_PID_TIMEOUT_S:-300}"
OTHERS_TIMEOUT="${YC_OTHERS_TIMEOUT:-60}"

ADMIN=0          # 1: 앱 폴더에 쓸 수 없어 파일 작업을 관리자 암호 창(osascript)으로 함
SWAP_TRIED=0     # 1: APP을 백업 이름으로 옮기기 시작함 (그 뒤로는 백업이 있으면 우리가 옮긴 것)
NEW_LAUNCHED=0   # 1: 새 앱을 켰음 (되돌릴 때 그 프로세스를 끝내야 함)
LAUNCHED_PID=""  # 직접 실행(YC_UPDATE_DIRECT_LAUNCH=1)으로 켠 프로세스의 pid
OPEN_W_PID=""    # open 방식: 새 앱을 켜고 그 앱이 끝날 때까지 기다리는 백그라운드 `open -n -W`의 pid
PIDS_BEFORE=""   # 새 앱을 켜기 직전에 이미 돌던 이 사용자의 앱 프로세스 (공백으로 이음) — 새 앱으로 보지도 끝내지도 않음
OPEN_CMD="${YC_UPDATE_OPEN:-open}"
FS_OUT=""        # fs_run이 남긴 출력(오류)
FAIL_REASON=""
MY_UID=$(id -u)  # 새 앱 찾기(app_pids)는 이 사용자의 프로세스만 — 바꾸기 전 기다리기(all_app_pids)는 모든 사용자

log() {
    local line
    line="$(date '+%Y-%m-%dT%H:%M:%S') 도우미: $*"
    printf '%s\n' "$line"
    if [ -n "$LOG" ]; then
        printf '%s\n' "$line" >>"$LOG"
    fi
}

fatal_alert() {  # $1 = 알림 창의 글. 종료 코드 2 바로 전: 앱 자리에 앱이 없을 수 있어 다음 실행에서 알릴 수 없음 →
    # 마지막으로 알림 창을 띄우고 닫을 때까지 기다림 (Windows 도우미의 메시지 창과 같음). 글은 인자로 넘김 — AppleScript
    # 따옴표·줄바꿈 처리가 필요 없게. 띄우지 못하면 기록만
    local out
    if [ "${YC_UPDATE_NO_MESSAGEBOX:-}" = 1 ]; then
        log "알림 창은 띄우지 않음 (YC_UPDATE_NO_MESSAGEBOX=1)"
        return 0
    fi
    if ! out=$("${YC_UPDATE_OSASCRIPT:-osascript}" -e 'on run argv' \
            -e 'display alert "Yeson Checker 업데이트 실패" message (item 1 of argv) as critical' \
            -e 'end run' "$1" 2>&1); then
        log "알림 창을 띄우지 못함: $(first_lines "$out")"
    fi
}

usage_error() {
    log "잘못된 인자: $*"
    printf '%s\n' "사용법: bash update_helper_mac.sh --pid PID --app APP --staged STAGED --target VER --ok OKFILE --log LOG [--timeout S] [--token TOKEN]" >&2
    exit 2
}

# ---- 글자 다루기 ----

sh_quote() {  # 셸 작은따옴표로 감쌈 (안의 ' 는 '\'' 로)
    printf "'%s'" "$(printf '%s' "$1" | LC_ALL=C sed "s/'/'\\\\''/g")"
}

applescript_escape() {  # AppleScript 큰따옴표 글자 안에 넣을 수 있게 \ 와 " 앞에 \
    printf '%s' "$1" | LC_ALL=C sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

regex_escape() {  # pgrep -f(확장 정규식)가 경로를 글자 그대로 찾도록
    printf '%s' "$1" | LC_ALL=C sed 's/[][\.*^$+?(){}|]/\\&/g'
}

# ---- 프로세스 ----

pid_alive() {  # 좀비(끝났지만 아직 거둬들이지 않음)는 끝난 것으로 봄
    local state
    state=$(ps -o stat= -p "$1" 2>/dev/null) || return 1
    case "$state" in
        *Z* | "") return 1 ;;
    esac
    return 0
}

# app_pids·all_app_pids는 $(…) 안에서 부름 — 오류 기록은 stderr로 (stdout은 pid 목록; LOG에는 log가 따로 씀)
app_pids() {  # APP/Contents/MacOS/ 아래 실행 파일로 도는 이 사용자의 프로세스들의 pid (한 줄에 하나)
    local out rc
    out=$(pgrep -U "$MY_UID" -f "$PATTERN")
    rc=$?
    if [ "$rc" -gt 1 ]; then
        log "pgrep 오류 (종료 코드 $rc, 패턴 $PATTERN)" >&2
    fi
    printf '%s' "$out"
}

all_app_pids() {  # 같은 것을 모든 사용자의 프로세스에서 (macOS pgrep은 -U 없이 다른 사용자의 명령 줄도 봄). pgrep 오류면 1
    local out rc
    out=$(pgrep -f "$PATTERN")
    rc=$?
    if [ "$rc" -gt 1 ]; then
        log "pgrep 오류 (종료 코드 $rc, 패턴 $PATTERN)" >&2
        return 1
    fi
    printf '%s' "$out"
}

new_app_pids() {  # 새 앱을 켠 뒤에 생긴 이 사용자의 앱 프로세스 (PIDS_BEFORE에 없던 것, 한 줄에 하나)
    local pid
    for pid in $(app_pids); do
        case " $PIDS_BEFORE " in
            *" $pid "*) ;;
            *) printf '%s\n' "$pid" ;;
        esac
    done
}

describe_pids() {  # $1 = pid들(공백·줄바꿈으로 나눔) → "123(사용자) 456(사용자)" — 그 사이에 끝났으면 "(끝남)"
    local pid user out=""
    for pid in $1; do
        user=$(ps -o user= -p "$pid" 2>/dev/null | tr -d ' ')
        out="$out $pid(${user:-끝남})"
    done
    printf '%s' "${out# }"
}

# 기다리는 시간은 모두 bash SECONDS로 잼 — 초 단위로만 늘어 -ge로 비교하면 최대 1초 일찍 끝나므로 -gt(적어도 정한 시간)
wait_for_pid() {
    local deadline=$((SECONDS + PID_TIMEOUT))
    log "앱이 끝나기를 기다림 (pid $PID, 최대 ${PID_TIMEOUT}초)"
    while pid_alive "$PID"; do
        if [ "$SECONDS" -gt "$deadline" ]; then
            return 1
        fi
        sleep 0.5
    done
    return 0
}

signal_pids() {  # $1 = TERM·KILL, $2 = pid들. 그 사이에 끝난 pid의 "No such process"도 기록 (삼키지 않음)
    local out
    if ! out=$(kill -"$1" $2 2>&1); then  # $2는 따옴표 없이 — pid들을 낱낱의 인자로
        log "kill -$1 일부 실패 (그 사이에 끝났을 수 있음): $out"
    fi
}

kill_new_app() {  # 새 앱을 켠 뒤에 생긴 프로세스(new_app_pids)만 끝냄 — 앱 경로로 모두 끝내지 않음
    local pids deadline
    pids=$(new_app_pids)
    if [ -z "$pids" ]; then
        log "새 앱 프로세스는 이미 끝나 있음"
        return 0
    fi
    log "새 앱 프로세스를 끝냄 (TERM): $(printf '%s' "$pids" | tr '\n' ' ')"
    signal_pids TERM "$pids"
    deadline=$((SECONDS + 10))
    while pids=$(new_app_pids) && [ -n "$pids" ]; do
        if [ "$SECONDS" -gt "$deadline" ]; then
            log "10초 안에 끝나지 않아 강제로 끝냄 (KILL): $(printf '%s' "$pids" | tr '\n' ' ')"
            signal_pids KILL "$pids"
            sleep 1
            break
        fi
        sleep 0.5
    done
    pids=$(new_app_pids)
    if [ -n "$pids" ]; then
        log "새 앱 프로세스가 아직 남아 있음: $(printf '%s' "$pids" | tr '\n' ' ')"
    fi
}

wait_all_app_processes() {  # 앱(PID)이 끝난 뒤: 같은 앱의 다른 프로세스(다른 창 — 모든 사용자)가 모두 끝나기를 기다림.
    # 바꾸기 전에 — 켜진 채 바꾸면 그 창이 다음 지연 import에서 죽음. 시간이 지나거나 찾지 못하면 FAIL_REASON을 두고 1
    local deadline pids
    deadline=$((SECONDS + OTHERS_TIMEOUT))
    if ! pids=$(all_app_pids); then
        FAIL_REASON="다른 YesonCheck 창이 있는지 확인하지 못해 바꾸지 않음 (pgrep 오류 — 위 기록)"
        return 1
    fi
    if [ -z "$pids" ]; then
        return 0
    fi
    log "다른 YesonCheck 창이 끝나기를 기다림 (pid $(describe_pids "$pids"), 최대 ${OTHERS_TIMEOUT}초)"
    while [ -n "$pids" ]; do
        if [ "$SECONDS" -gt "$deadline" ]; then
            FAIL_REASON="다른 YesonCheck 창이 끝나지 않아 바꾸지 않음: pid $(describe_pids "$pids") (${OTHERS_TIMEOUT}초 기다림)"
            return 1
        fi
        sleep 0.5
        if ! pids=$(all_app_pids); then
            FAIL_REASON="다른 YesonCheck 창이 있는지 확인하지 못해 바꾸지 않음 (pgrep 오류 — 위 기록)"
            return 1
        fi
    done
    log "다른 YesonCheck 창이 모두 끝남"
    return 0
}

stop_open_w() {  # 되돌릴 때: 새 앱을 기다리던 open -n -W도 끝냄 (새 앱을 끝냈으면 보통 스스로 끝나 있음)
    if open_w_running; then
        log "새 앱을 기다리던 open -n -W를 끝냄 (pid $OPEN_W_PID)"
        kill "$OPEN_W_PID"
    fi
}

open_w_running() {  # 백그라운드 open -n -W가 아직 도는지 (이 셸의 작업 목록으로 봄 — 끝난 pid를 다른 프로세스로 착각하지 않게)
    [ -n "$OPEN_W_PID" ] || return 1
    case " $(jobs -rp | tr '\n' ' ') " in
        *" $OPEN_W_PID "*) return 0 ;;
    esac
    return 1
}

# 켜는 앱의 인자는 APP_ARGS(직접 실행)·OPEN_ARGS(open의 --args …) — 비었을 수 있어 ${X[@]+"${X[@]}"}로 씀
# (bash 3.2는 set -u에서 빈 배열의 "${X[@]}"를 오류로 봄)
launch_app() {  # $1 = 무엇을 켜는지 (로그용: "새 앱"·"옛 앱")
    local out
    if [ "${YC_UPDATE_DIRECT_LAUNCH:-}" = 1 ]; then
        nohup "$APP/Contents/MacOS/$EXE_NAME" ${APP_ARGS[@]+"${APP_ARGS[@]}"} >>"$LOG" 2>&1 </dev/null &
        LAUNCHED_PID=$!
        log "$1을 켬 (직접 실행, pid $LAUNCHED_PID): $APP"
        return 0
    fi
    if out=$("$OPEN_CMD" -n "$APP" ${OPEN_ARGS[@]+"${OPEN_ARGS[@]}"} 2>&1); then
        log "$1을 켬 (open -n): $APP"
        return 0
    fi
    log "$1을 켜지 못함 (open -n): $out"
    return 1
}

launch_new_app() {
    # open 방식은 `open -n -W`를 백그라운드로: 켠 새 앱이 끝나면 이것도 끝남 → 표시 없이 끝난 새 앱을 바로 알아챔.
    # (그냥 open -n은 곧바로 끝나고, 몇 ms 만에 죽는 새 앱은 pgrep으로도 못 봐 '잘 켜짐' 제한 시간을 다 기다렸음 — 실제
    # /Applications 시험.) 진짜 open -W는 앱이 끝나면 앱의 종료 코드와 상관없이 0, 켜지 못하면 곧바로 0이 아닌 값.
    # nohup·</dev/null: 성공 뒤 새 앱이 도는 동안 이것도 살아 있어야 하고, 도우미가 끝날 때 같이 끝나거나 도우미를
    # 붙잡지 않게 (출력은 LOG에 — "Unable to block on application …" 같은 open의 글도 기록에 남음)
    if [ "${YC_UPDATE_DIRECT_LAUNCH:-}" = 1 ]; then
        launch_app "새 앱"
        return
    fi
    nohup "$OPEN_CMD" -n -W "$APP" ${OPEN_ARGS[@]+"${OPEN_ARGS[@]}"} >>"$LOG" 2>&1 </dev/null &
    OPEN_W_PID=$!
    log "새 앱을 켬 (open -n -W, pid $OPEN_W_PID — 새 앱이 끝나면 끝남): $APP"
    return 0
}

# ---- 파일 작업 (보통은 사용자로, 앱 폴더에 쓸 수 없으면 관리자 암호 창으로) ----

run_admin() {  # $1 = 셸 명령. 관리자 권한으로 한 번에 실행 (암호 창 한 번)
    local script
    script="do shell script \"$(applescript_escape "$1")\" with prompt \"Yeson Checker 업데이트: 앱 폴더에 쓰려면 관리자 암호가 필요합니다.\" with administrator privileges"
    "${YC_UPDATE_OSASCRIPT:-osascript}" -e "$script"
}

fs_run() {  # $1 = 셸 명령. 출력(오류)은 FS_OUT에
    if [ "$ADMIN" = 1 ]; then
        FS_OUT=$(run_admin "$1" 2>&1)
    else
        FS_OUT=$(/bin/sh -c "$1" 2>&1)
    fi
}

is_permission_error() {  # $1 = 명령 출력
    case "$1" in
        *"Permission denied"* | *"Operation not permitted"*) return 0 ;;
    esac
    return 1
}

exists() {
    [ -e "$1" ] || [ -L "$1" ]
}

paths_overlap() {  # $1·$2가 같은 곳(별칭·심볼릭 링크 포함)이거나 한쪽이 다른 쪽 안에 있음
    if [ "$1" -ef "$2" ]; then
        return 0
    fi
    case "$1/" in "$2"/*) return 0 ;; esac
    case "$2/" in "$1"/*) return 0 ;; esac
    return 1
}

first_lines() {  # $1 = 명령 출력 → 앞 5줄만 (rm -rf는 못 지운 파일마다 한 줄 — 앱 번들이면 수천 줄이 로그에 쌓임)
    # osascript(do shell script)는 오류의 여러 줄을 \r로 이어 한 줄로 내므로 먼저 줄바꿈으로 바꿈
    local text total
    text=$(printf '%s' "$1" | LC_ALL=C tr '\r' '\n')
    total=$(printf '%s\n' "$text" | wc -l | tr -d ' ')
    if [ "$total" -le 5 ]; then
        printf '%s' "$text"
        return
    fi
    printf '%s\n… (%s줄 더)' "$(printf '%s\n' "$text" | head -n 5)" "$((total - 5))"
}

delete_path() {  # $1 = 지울 경로. 끝난 뒤 남아 있으면 실패 (출력은 FS_OUT에)
    # 다른 계정·root 것(관리자 계정이 둘이거나 sudo로 설치한 앱)이라 사용자로 못 지우면 관리자 암호 창으로 지운다
    # — 그대로 두면 남은 백업이 다음 업데이트를 모두 막음. 관리자 방식(ADMIN=1)이어도 늘 사용자로 먼저 해 본다:
    # 바꾸기 암호 창을 취소한 사용자에게, 사용자로 지울 수 있는 것 때문에 암호 창을 또 띄우지 않게
    local q rc
    q=$(sh_quote "$1")
    FS_OUT=$(/bin/sh -c "rm -rf $q" 2>&1)
    rc=$?
    if exists "$1" && is_permission_error "$FS_OUT"; then
        log "권한이 없어 지우지 못함 — 관리자 암호 창으로 지움: $1 ($(first_lines "$FS_OUT"))"
        FS_OUT=$(run_admin "rm -rf $q" 2>&1)
        rc=$?
    fi
    if [ -n "$FS_OUT" ]; then
        FS_OUT=$(first_lines "$FS_OUT")
    else
        FS_OUT="종료 코드 $rc"  # 출력 없이 실패한 경우에도 무엇이 있었는지 남김
    fi
    ! exists "$1"
}

remove_staged() {
    if ! exists "$STAGED"; then
        return 0
    fi
    if delete_path "$STAGED"; then
        log "준비했던 새 앱을 지움: $STAGED"
    else
        log "준비했던 새 앱을 지우지 못함: $STAGED ($FS_OUT)"
    fi
}

remove_stale_backup() {  # 지난 업데이트의 백업이 남아 있으면 지움 (그대로 두면 mv가 그 안으로 옮김)
    if ! exists "$BACKUP"; then
        return 0
    fi
    log "지난 업데이트의 백업이 남아 있어 먼저 지움: $BACKUP"
    if ! delete_path "$BACKUP"; then
        FAIL_REASON="지난 업데이트의 백업을 지우지 못함: $BACKUP ($FS_OUT)"
        return 1
    fi
    return 0
}

swap() {
    local q_app q_backup q_staged
    q_app=$(sh_quote "$APP")
    q_backup=$(sh_quote "$BACKUP")
    q_staged=$(sh_quote "$STAGED")
    SWAP_TRIED=1
    if fs_run "mv $q_app $q_backup"; then
        log "옛 앱을 백업 이름으로 옮김: $APP → $BACKUP"
        if fs_run "mv $q_staged $q_app"; then
            log "새 앱을 앱 자리로 옮김: $STAGED → $APP"
            return 0
        fi
        FAIL_REASON="새 앱을 앱 자리로 옮기지 못함: $FS_OUT"
        return 1
    fi
    if ! is_permission_error "$FS_OUT"; then
        FAIL_REASON="옛 앱을 백업 이름으로 옮기지 못함: $FS_OUT"
        return 1
    fi
    log "앱 폴더에 쓸 수 없어 관리자 암호 창으로 바꿈 ($FS_OUT)"
    ADMIN=1
    # 두 번째 mv가 실패하면 같은 명령 안에서 옛 앱을 되돌려 놓음 — 되돌리려고 암호 창을 또 띄우지 않음
    # (그 창에서 취소하면 앱 자리가 빈 채로 남음). 단, 앱 자리에 무엇이 남아 있으면(다른 볼륨에서 복사하다 멈춘
    # 반쪽 앱) 손대지 않음 — 그대로 mv하면 백업이 그 *안으로* 들어감; 그때는 restore_backup이 먼저 치우고 되돌림
    if ! fs_run "mv $q_app $q_backup && { mv $q_staged $q_app || { [ -e $q_app ] || [ -L $q_app ] || mv $q_backup $q_app; exit 1; }; }"; then
        FAIL_REASON="관리자 권한으로 바꾸지 못함: $FS_OUT"
        return 1
    fi
    if [ -e "$BACKUP" ] && [ -x "$APP/Contents/MacOS/$EXE_NAME" ] && [ ! -e "$STAGED" ]; then
        log "관리자 권한으로 바꿈: $APP → $BACKUP, $STAGED → $APP"
        return 0
    fi
    FAIL_REASON="관리자 권한 명령은 끝났지만 앱이 바뀌지 않음 (백업 있음: $([ -e "$BACKUP" ] && echo 예 || echo 아니오), 준비한 새 앱 남음: $([ -e "$STAGED" ] && echo 예 || echo 아니오))${FS_OUT:+ $FS_OUT}"
    return 1
}

ok_version() {  # OKFILE의 version 값 (없거나 아직 못 읽으면 빈 글자)
    if [ -f "$OKFILE" ]; then
        LC_ALL=C sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$OKFILE" | head -n 1
    fi
}

new_app_running() {  # 직접 실행이면 켠 pid, open 방식이면 새 앱을 켠 뒤에 생긴 프로세스 (켜기 전부터 돌던 창은 아님)
    if [ -n "$LAUNCHED_PID" ]; then
        pid_alive "$LAUNCHED_PID"
        return
    fi
    [ -n "$(new_app_pids)" ]
}

wait_ok() {
    local deadline seen version open_status
    deadline=$((SECONDS + TIMEOUT))
    seen=0
    log "새 앱의 '잘 켜짐' 표시를 기다림 (최대 ${TIMEOUT}초): $OKFILE"
    while :; do
        version=$(ok_version)
        if [ "$version" = "$TARGET" ]; then
            return 0
        fi
        if [ -n "$OPEN_W_PID" ] && ! open_w_running; then
            wait "$OPEN_W_PID"
            open_status=$?
            OPEN_W_PID=""
            if [ "$open_status" != 0 ]; then
                FAIL_REASON="새 앱을 켜지 못함 (open -n -W 종료 코드 $open_status — open의 글은 위 기록에)"
                return 1
            fi
            if [ -z "$(new_app_pids)" ]; then
                version=$(ok_version)  # 표시를 쓰고 바로 끝났을 수 있음
                if [ "$version" = "$TARGET" ]; then
                    return 0
                fi
                FAIL_REASON="새 앱이 '잘 켜짐' 표시 없이 끝남 (open -n -W가 끝남, 종료 코드 0; 표시 버전: ${version:-없음})"
                return 1
            fi
            log "open -n -W는 끝났지만 새 앱 프로세스가 보임 — 계속 기다림"
            seen=1
        fi
        if new_app_running; then
            seen=1
        elif [ "$seen" = 1 ] || [ -n "$LAUNCHED_PID" ]; then
            version=$(ok_version)  # 표시를 쓰고 바로 끝났을 수 있음
            if [ "$version" = "$TARGET" ]; then
                return 0
            fi
            FAIL_REASON="새 앱이 '잘 켜짐' 표시 없이 끝남 (표시 버전: ${version:-없음})"
            return 1
        fi
        if [ "$SECONDS" -gt "$deadline" ]; then
            FAIL_REASON="${TIMEOUT}초 안에 '잘 켜짐' 표시가 없음 (표시 버전: ${version:-없음})"
            return 1
        fi
        sleep 0.5
    done
}

restore_backup() {  # 새 앱을 숨김 이름으로 치우고 백업을 제자리로 (둘 다 이름 바꾸기) → 치운 것을 지움
    local q_app q_backup q_failed rc n
    # 치울 이름은 이번 실행만의 것(지난번에 못 지운 것이 남아 있어도 막히지 않음), 있는 이름은 피함
    FAILED="$APP_DIR/.$APP_BASE.update-failed-$$"
    n=0
    while exists "$FAILED"; do
        n=$((n + 1))
        FAILED="$APP_DIR/.$APP_BASE.update-failed-$$-$n"
    done
    q_app=$(sh_quote "$APP")
    q_backup=$(sh_quote "$BACKUP")
    q_failed=$(sh_quote "$FAILED")
    fs_run "if [ -e $q_app ] || [ -L $q_app ]; then mv $q_app $q_failed || exit 1; fi; mv $q_backup $q_app || exit 1; rm -rf $q_failed"
    rc=$?
    FS_OUT=$(first_lines "$FS_OUT")
    if [ -e "$BACKUP" ] || [ ! -x "$APP/Contents/MacOS/$EXE_NAME" ]; then
        log "되돌리기 실패 — 백업을 제자리로 옮기지 못함 (종료 코드 $rc): $FS_OUT"
        log "되돌리기 실패 — 처음 실패: $FAIL_REASON"
        log "되돌리기 실패 — 옛 앱 백업: $BACKUP, 앱 자리: $APP, 치운 새 앱: $FAILED (손으로 옮겨 주세요)"
        return 1
    fi
    log "백업을 제자리로 되돌림: $BACKUP → $APP"
    if [ "$rc" != 0 ] || exists "$FAILED"; then
        log "치운 새 앱을 지우지 못함: $FAILED (종료 코드 $rc)${FS_OUT:+ $FS_OUT}"
    fi
    return 0
}

rollback() {  # FAIL_REASON을 기록하고 옛 앱으로 되돌려 켠 뒤 끝냄
    log "업데이트 실패: $FAIL_REASON"
    log "되돌림 시작"
    if [ "$NEW_LAUNCHED" = 1 ]; then
        kill_new_app
        stop_open_w
    fi
    if [ "$SWAP_TRIED" = 1 ] && { [ -e "$BACKUP" ] || [ -L "$BACKUP" ]; }; then
        if ! restore_backup; then
            fatal_alert "업데이트에 실패했고, 이전 버전으로 되돌리지도 못했습니다.

이전 버전(백업): $BACKUP
앱 자리: $APP${FAILED:+
치운 새 앱: $FAILED}

앱 자리에 남은 것을 지우거나 다른 이름으로 바꾼 뒤, 백업 앱의 이름을 $APP_BASE(으)로 바꾸면 이전 버전을 다시 쓸 수 있습니다.

자세한 기록: $LOG"
            exit 2
        fi
    else
        log "앱은 바뀌지 않았음: $APP"
    fi
    remove_staged
    if [ ! -x "$APP/Contents/MacOS/$EXE_NAME" ]; then
        log "되돌리기 실패 — 앱 자리에 옛 앱이 없음: $APP (처음 실패: $FAIL_REASON)"
        fatal_alert "업데이트에 실패했고, 앱 자리에 이전 버전이 없습니다: $APP

이전 버전(백업)이 있다면: $BACKUP

자세한 기록: $LOG"
        exit 2
    fi
    log "되돌림: 옛 앱을 다시 켬"
    LAUNCHED_PID=""
    launch_app "옛 앱"
    exit 1
}

# ---- 시작 ----

while [ $# -gt 0 ]; do
    case "$1" in
        --pid | --app | --staged | --target | --ok | --log | --timeout | --token)
            if [ $# -lt 2 ]; then
                usage_error "$1 뒤에 값이 없음"
            fi
            case "$1" in
                --pid) PID=$2 ;;
                --app) APP=$2 ;;
                --staged) STAGED=$2 ;;
                --target) TARGET=$2 ;;
                --ok) OKFILE=$2 ;;
                --log) LOG=$2 ;;
                --timeout) TIMEOUT=$2 ;;
                --token) TOKEN=$2 ;;
            esac
            shift 2
            ;;
        *) usage_error "알 수 없는 인자: $1" ;;
    esac
done
for pair in "--pid:$PID" "--app:$APP" "--staged:$STAGED" "--target:$TARGET" "--ok:$OKFILE" "--log:$LOG"; do
    if [ -z "${pair#*:}" ]; then
        usage_error "${pair%%:*} 값이 없음"
    fi
done
for pair in "--pid:$PID" "--timeout(YC_UPDATE_OK_TIMEOUT_S):$TIMEOUT" "YC_UPDATE_PID_TIMEOUT_S:$PID_TIMEOUT" \
        "YC_OTHERS_TIMEOUT:$OTHERS_TIMEOUT"; do
    case "${pair#*:}" in
        "" | *[!0-9]*) usage_error "${pair%%:*} 값은 숫자여야 함: ${pair#*:}" ;;
    esac
done

APP="${APP%/}"
STAGED="${STAGED%/}"
APP_DIR=$(dirname "$APP")
APP_BASE=$(basename "$APP")
BACKUP="$APP_DIR/${APP_BASE%.app}.update-backup.app"
FAILED=""  # 되돌릴 때 restore_backup이 정함
PATTERN=$(regex_escape "$APP/Contents/MacOS/")
# 도우미가 켜는 앱의 인자 (launch_app·launch_new_app) — 맨 위 TOKEN 설명. 빈 --update-result는 앱이 거절하므로 토큰이
# 없으면 넘기지 않음
APP_ARGS=()
OPEN_ARGS=()
if [ -n "$TOKEN" ]; then
    APP_ARGS=(--update-result "$TOKEN")
    OPEN_ARGS=(--args --update-result "$TOKEN")
fi
# 준비한 새 앱이 앱(또는 백업) 자리와 겹치면 바꾸기가 실패한 뒤 '준비한 새 앱 지우기'가 되돌린 앱을 지움 — 손대기 전에 거절
if paths_overlap "$STAGED" "$APP" || paths_overlap "$STAGED" "$BACKUP"; then
    usage_error "--staged가 --app(또는 그 백업 자리)과 같거나 겹침: --staged $STAGED, --app $APP"
fi

log "시작: 대상 버전 $TARGET, 앱 $APP, 준비한 새 앱 $STAGED"
if [ -z "$TOKEN" ]; then
    log "--token이 없음 — 켜는 앱에 결과 판정 인자(--update-result)를 넘기지 않음"
fi

if ! wait_for_pid; then
    log "앱(pid $PID)이 ${PID_TIMEOUT}초가 지나도 끝나지 않아 아무것도 바꾸지 않음"
    exit 1
fi
log "앱이 끝남 (pid $PID)"

if [ ! -x "$APP/Contents/MacOS/$EXE_NAME" ]; then
    log "업데이트 실패 — 앱 자리에 지금 앱이 없음: $APP"
    fatal_alert "업데이트를 시작하지 못했습니다 — 앱 자리에 Yeson Checker가 없습니다:
$APP

자세한 기록: $LOG"
    exit 2
fi
if ! wait_all_app_processes; then
    rollback  # 바꾸지 않음: 옛 앱을 토큰과 함께 켜('업데이트 실패' 창에 이 기록) 준비한 새 앱을 지우고 끝냄
fi
if [ ! -x "$STAGED/Contents/MacOS/$EXE_NAME" ]; then
    FAIL_REASON="준비한 새 앱이 없음: $STAGED/Contents/MacOS/$EXE_NAME"
    rollback
fi
if ! remove_stale_backup; then
    rollback
fi
if ! swap; then
    rollback
fi
if ! out=$(rm -f "$OKFILE" 2>&1); then
    FAIL_REASON="지난 '잘 켜짐' 표시를 지우지 못함: $OKFILE ($out)"
    rollback
fi
PIDS_BEFORE=$(app_pids | tr '\n' ' ')
if [ -n "$PIDS_BEFORE" ]; then
    log "새 앱을 켜기 전부터 도는 YesonCheck 프로세스 (새 앱으로 보지 않고, 되돌릴 때 끝내지 않음): pid $PIDS_BEFORE"
fi
NEW_LAUNCHED=1
if ! launch_new_app; then
    FAIL_REASON="새 앱을 켜지 못함"
    rollback
fi
if ! wait_ok; then
    rollback
fi
log "새 앱이 잘 켜짐 (버전 $TARGET)"
if open_w_running; then
    disown "$OPEN_W_PID"  # 새 앱이 도는 동안 살아 있음 — 기다리지도 끝내지도 않음
fi
if delete_path "$BACKUP"; then
    log "백업을 지움: $BACKUP"
else
    log "백업을 지우지 못함: $BACKUP ($FS_OUT)"
fi
if ! out=$(rm -f "$OKFILE" 2>&1); then
    log "'잘 켜짐' 표시를 지우지 못함: $OKFILE ($out)"
fi
log "업데이트 끝: $TARGET"
exit 0
