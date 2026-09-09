#!/usr/bin/env bash

# stage 50/60/90 共用的 kubectl 门禁与 admin.conf 生命周期。
# 取 stage 90 的形态：kubectl 一律读**已捕获内容**而非磁盘文件，且在每次调用前后
# 各做一次 admin_conf_is_safe（含 cmp 比对磁盘与捕获内容）。这比"直接把磁盘路径交给
# kubectl"严格得多——后者在读取期间文件被替换不会被发现。
# 依赖：safe_file（lib/exec-safety.sh）、admin_conf_json_is_exact（lib/admin-conf.sh）、
# 以及各 stage 声明的 $kubectl_binary、$admin_conf 与 $PYTHON_BINARY。它们由 stage
# 提供而非本库兜底，与 exec-safety.sh 的契约一致：缺失时 set -u 直接报未绑定变量。
# SC2154 对小写变量才告警（全大写被当成环境变量豁免），故此处显式关闭。
# shellcheck disable=SC2154
kubectl_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
# shellcheck disable=SC1091
source "${kubectl_lib_dir}/exec-safety.sh"
# shellcheck disable=SC1091
source "${kubectl_lib_dir}/admin-conf.sh"

admin_conf_metadata_is_safe() {
  safe_file "$admin_conf" 600
}

ADMIN_CONF_CAPTURED=0
ADMIN_CONF_CONTENT=
KUBE_RUNNER_PID=
KUBE_RUNNER_GROUP=
KUBE_RUNNER_CONTROL_READ_FD=
KUBE_RUNNER_CONTROL_WRITE_FD=
KUBE_RUNNER_CONTROL_BUFFER=
KUBE_RUNNER_CONTROL_MESSAGE=
KUBE_RUNNER_ACTIVE=0

capture_admin_conf() {
  local captured output with_sentinel
  admin_conf_metadata_is_safe || return 1
  with_sentinel=$(/bin/cat -- "$admin_conf"; printf x) || return 1
  [[ "${with_sentinel: -1}" == x ]] || return 1
  captured=${with_sentinel%?}
  cmp -s "$admin_conf" <(printf '%s' "$captured") || return 1
  output=$(
    PYTHONDONTWRITEBYTECODE=1 KUBECTL_KUBERC=false "$kubectl_binary" \
      --kubeconfig <(printf '%s' "$captured") --cache-dir=/dev/null \
      config view --raw --merge=false --output=json 2>/dev/null
  ) || return 1
  printf '%s' "$output" | admin_conf_json_is_exact || return 1
  admin_conf_metadata_is_safe || return 1
  cmp -s "$admin_conf" <(printf '%s' "$captured") || return 1
  ADMIN_CONF_CONTENT=$captured
  ADMIN_CONF_CAPTURED=1
}

admin_conf_is_safe() {
  [[ "$ADMIN_CONF_CAPTURED" == 1 ]] || return 1
  admin_conf_metadata_is_safe || return 1
  cmp -s "$admin_conf" <(printf '%s' "$ADMIN_CONF_CONTENT")
}

kubectl_run() {
  local exit_code=0
  admin_conf_is_safe || return 1
  PYTHONDONTWRITEBYTECODE=1 KUBECTL_KUBERC=false "$kubectl_binary" \
    --kubeconfig <(printf '%s' "$ADMIN_CONF_CONTENT") \
    --cache-dir=/dev/null "$@" || exit_code=$?
  admin_conf_is_safe || return 1
  return "$exit_code"
}

kubectl_process_identity() {
  local process_id=$1 stat_line stat_tail
  local -a stat_fields=()
  [[ "$process_id" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ -r "/proc/${process_id}/stat" ]] || return 1
  stat_line=$(<"/proc/${process_id}/stat") || return 1
  [[ "$stat_line" == *') '* ]] || return 1
  stat_tail=${stat_line##*) }
  read -r -a stat_fields <<<"$stat_tail" || return 1
  ((${#stat_fields[@]} >= 20)) || return 1
  [[ "${stat_fields[2]}" =~ ^[1-9][0-9]*$ &&
     "${stat_fields[3]}" =~ ^[1-9][0-9]*$ &&
     "${stat_fields[19]}" =~ ^[1-9][0-9]*$ ]] || return 1
  printf '%s|%s|%s|%s\n' \
    "${stat_fields[0]}" "${stat_fields[2]}" \
    "${stat_fields[3]}" "${stat_fields[19]}"
}

kubectl_isolated_state_clear() {
  KUBE_RUNNER_PID=
  KUBE_RUNNER_GROUP=
  KUBE_RUNNER_CONTROL_READ_FD=
  KUBE_RUNNER_CONTROL_WRITE_FD=
  KUBE_RUNNER_CONTROL_BUFFER=
  KUBE_RUNNER_CONTROL_MESSAGE=
  KUBE_RUNNER_ACTIVE=0
}

kubectl_isolated_read_control() {
  local timeout=$1 fragment='' read_status=0
  [[ "$timeout" =~ ^[0-9]+([.][0-9]+)?$ ]] || return 1
  [[ "$KUBE_RUNNER_CONTROL_READ_FD" =~ ^[0-9]+$ ]] || return 1
  KUBE_RUNNER_CONTROL_MESSAGE=
  # A timed line read can consume its newline yet report a timeout. Keep
  # delimiters in the payload so completion never depends on that exit race.
  if [[ "$KUBE_RUNNER_CONTROL_BUFFER" != *$'\n'* ]]; then
    IFS= read -r -N 4096 -t "$timeout" \
      -u "$KUBE_RUNNER_CONTROL_READ_FD" fragment || read_status=$?
    KUBE_RUNNER_CONTROL_BUFFER+=${fragment}
  fi
  if [[ "$KUBE_RUNNER_CONTROL_BUFFER" == *$'\n'* ]]; then
    KUBE_RUNNER_CONTROL_MESSAGE=${KUBE_RUNNER_CONTROL_BUFFER%%$'\n'*}
    KUBE_RUNNER_CONTROL_BUFFER=${KUBE_RUNNER_CONTROL_BUFFER#*$'\n'}
    return 0
  fi
  if [[ "$read_status" == 1 ]]; then
    KUBE_RUNNER_CONTROL_BUFFER=
    return 1
  fi
  return 2
}

kubectl_isolated_start() {
  local identity state process_group session_id child_id
  local supervisor_pid stdin_fd stdout_fd stderr_fd kubeconfig_fd
  local control_read_fd control_write_fd ready_line='' ready=false read_status
  [[ "$KUBE_RUNNER_ACTIVE" == 0 &&
     -z "$KUBE_RUNNER_PID" &&
     -z "$KUBE_RUNNER_GROUP" ]] || return 1
  admin_conf_is_safe || return 1
  exec {stdin_fd}<&0 || return 1
  exec {stdout_fd}>&1 || {
    exec {stdin_fd}<&-
    return 1
  }
  exec {stderr_fd}>&2 || {
    exec {stdin_fd}<&-
    exec {stdout_fd}>&-
    return 1
  }
  exec {kubeconfig_fd}< <(printf '%s' "$ADMIN_CONF_CONTENT") || {
    exec {stdin_fd}<&-
    exec {stdout_fd}>&-
    exec {stderr_fd}>&-
    return 1
  }
  coproc KUBE_RUNNER_CONTROL {
    PYTHONDONTWRITEBYTECODE=1 KUBECTL_KUBERC=false \
      exec "$PYTHON_BINARY" -I -B -c '
import ctypes
import os
import select
import signal
import sys
import time

CONTROL_OUTPUT = 3
CONTROL_INPUT = 4
control_buffer = b""
main_status = None
kubeconfig_fd = int(sys.argv[1])
if kubeconfig_fd < 5:
    raise SystemExit(125)


def write_control(message):
    payload = message.encode("ascii") + b"\n"
    while payload:
        written = os.write(CONTROL_OUTPUT, payload)
        payload = payload[written:]


def read_control(timeout):
    global control_buffer
    deadline = None if timeout is None else time.monotonic() + timeout
    while b"\n" not in control_buffer:
        remaining = None
        if deadline is not None:
            remaining = max(0.0, deadline - time.monotonic())
        readable, _, _ = select.select([CONTROL_INPUT], [], [], remaining)
        if not readable:
            return None
        chunk = os.read(CONTROL_INPUT, 4096)
        if not chunk:
            raise EOFError
        control_buffer += chunk
    line, control_buffer = control_buffer.split(b"\n", 1)
    return line.decode("ascii")


def status_code(status):
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 125


def reap_children():
    global main_status
    while True:
        try:
            waited, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return False
        if waited == 0:
            return True
        if waited == child:
            main_status = status


def direct_children():
    path = "/proc/%d/task/%d/children" % (os.getpid(), os.getpid())
    with open(path, "r", encoding="ascii") as stream:
        fields = stream.read().split()
    if any(not field.isdigit() or int(field) <= 0 for field in fields):
        raise RuntimeError("invalid child inventory")
    return [int(field) for field in fields]


def signal_original_group(signal_number):
    if main_status is not None:
        return
    try:
        os.killpg(child, signal_number)
    except ProcessLookupError:
        pass


def terminate_all(initial_signal):
    signal_original_group(initial_signal)
    phases = (
        (None, 0.5),
        (signal.SIGTERM, 0.5),
        (signal.SIGKILL, 2.0),
    )
    for signal_number, duration in phases:
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            if not reap_children():
                return True
            if signal_number is not None:
                signal_original_group(signal_number)
                try:
                    process_ids = direct_children()
                except OSError:
                    process_ids = []
                for process_id in process_ids:
                    try:
                        os.kill(process_id, signal_number)
                    except ProcessLookupError:
                        pass
            time.sleep(0.02)
    return not reap_children()

os.setsid()
if os.getsid(0) != os.getpid():
    raise SystemExit(125)
if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
    raise SystemExit(125)
for signal_number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
    signal.signal(signal_number, signal.SIG_DFL)
child_ready_read, child_ready_write = os.pipe()
release_read, release_write = os.pipe()
child = os.fork()
if child == 0:
    os.close(child_ready_read)
    os.close(release_write)
    os.setpgid(0, 0)
    for signal_number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_number, signal.SIG_DFL)
    os.close(CONTROL_OUTPUT)
    os.close(CONTROL_INPUT)
    os.write(child_ready_write, b"x")
    os.close(child_ready_write)
    if os.read(release_read, 1) != b"x":
        raise SystemExit(125)
    os.close(release_read)
    try:
        os.execv(sys.argv[2], sys.argv[2:])
    except FileNotFoundError:
        os._exit(127)
    except OSError:
        os._exit(126)
os.close(child_ready_write)
os.close(release_read)
os.close(kubeconfig_fd)
if os.read(child_ready_read, 1) != b"x":
    raise SystemExit(125)
os.close(child_ready_read)
write_control("READY|%d" % child)
try:
    start_command = read_control(None)
except EOFError:
    start_command = None
if start_command != "START":
    os.close(release_write)
    while reap_children():
        time.sleep(0.01)
    raise SystemExit(125)
os.write(release_write, b"x")
os.close(release_write)
while True:
    try:
        command = read_control(0.05)
    except EOFError:
        terminate_all(signal.SIGTERM)
        raise SystemExit(125)
    if command is not None:
        parts = command.split("|", 1)
        if len(parts) != 2 or parts[0] != "STOP" or parts[1] not in {
            "HUP", "INT", "TERM"
        }:
            terminate_all(signal.SIGTERM)
            raise SystemExit(125)
        requested_signal = {
            "HUP": signal.SIGHUP,
            "INT": signal.SIGINT,
            "TERM": signal.SIGTERM,
        }[parts[1]]
        while not terminate_all(requested_signal):
            requested_signal = signal.SIGKILL
        write_control("STOPPED|OK")
        try:
            close_command = read_control(None)
        except EOFError:
            close_command = None
        if close_command != "CLOSE":
            raise SystemExit(125)
        raise SystemExit(0)
    if not reap_children():
        write_control(
            "DONE|%d" % (125 if main_status is None else status_code(main_status))
        )
        try:
            close_command = read_control(None)
        except EOFError:
            close_command = None
        if close_command is not None and close_command.startswith("STOP|"):
            parts = close_command.split("|", 1)
            if len(parts) != 2 or parts[1] not in {"HUP", "INT", "TERM"}:
                raise SystemExit(125)
            write_control("STOPPED|OK")
            try:
                close_command = read_control(None)
            except EOFError:
                close_command = None
        if close_command != "CLOSE":
            raise SystemExit(125)
        raise SystemExit(0)
' "$kubeconfig_fd" "$kubectl_binary" \
      --kubeconfig "/dev/fd/${kubeconfig_fd}" \
      --cache-dir=/dev/null "$@" \
      3>&1 4<&0 <&"$stdin_fd" >&"$stdout_fd" 2>&"$stderr_fd"
  }
  supervisor_pid=$KUBE_RUNNER_CONTROL_PID
  control_read_fd=${KUBE_RUNNER_CONTROL[0]}
  control_write_fd=${KUBE_RUNNER_CONTROL[1]}
  exec {kubeconfig_fd}<&-
  exec {stdin_fd}<&-
  exec {stdout_fd}>&-
  exec {stderr_fd}>&-
  KUBE_RUNNER_PID=$supervisor_pid
  KUBE_RUNNER_CONTROL_READ_FD=$control_read_fd
  KUBE_RUNNER_CONTROL_WRITE_FD=$control_write_fd
  KUBE_RUNNER_CONTROL_BUFFER=
  KUBE_RUNNER_CONTROL_MESSAGE=
  for _ in {1..100}; do
    if kubectl_isolated_read_control 0.01; then
      ready_line=$KUBE_RUNNER_CONTROL_MESSAGE
      ready=true
      break
    else
      read_status=$?
    fi
    [[ "$read_status" != 1 ]] || break
    kill -0 -- "$supervisor_pid" 2>/dev/null || break
  done
  if [[ "$ready" != true || "$ready_line" != READY\|* ]]; then
    printf 'ABORT\n' 1>&"$KUBE_RUNNER_CONTROL_WRITE_FD" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
    kubectl_isolated_state_clear
    admin_conf_is_safe || return 1
    return 1
  fi
  child_id=${ready_line#READY|}
  identity=$(kubectl_process_identity "$supervisor_pid") || identity=
  if [[ -n "$identity" ]]; then
    IFS='|' read -r state process_group session_id _ <<<"$identity"
  fi
  if [[ -z "$identity" || "$state" == Z ||
        "$process_group" != "$supervisor_pid" ||
        "$session_id" != "$supervisor_pid" ]]; then
    printf 'ABORT\n' 1>&"$KUBE_RUNNER_CONTROL_WRITE_FD" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
    kubectl_isolated_state_clear
    admin_conf_is_safe || return 1
    return 1
  fi
  identity=$(kubectl_process_identity "$child_id") || identity=
  if [[ -n "$identity" ]]; then
    IFS='|' read -r state process_group session_id _ <<<"$identity"
  fi
  if [[ -z "$identity" || "$state" == Z ||
        "$process_group" != "$child_id" ||
        "$session_id" != "$supervisor_pid" ]]; then
    printf 'ABORT\n' 1>&"$KUBE_RUNNER_CONTROL_WRITE_FD" 2>/dev/null || true
    wait "$supervisor_pid" 2>/dev/null || true
    kubectl_isolated_state_clear
    admin_conf_is_safe || return 1
    return 1
  fi
  KUBE_RUNNER_GROUP=$child_id
  KUBE_RUNNER_ACTIVE=1
  if ! printf 'START\n' >&"$KUBE_RUNNER_CONTROL_WRITE_FD"; then
    wait "$supervisor_pid" 2>/dev/null || true
    kubectl_isolated_state_clear
    admin_conf_is_safe || return 1
    return 1
  fi
}

kubectl_isolated_wait() {
  local exit_code=$1 supervisor_status=0 close_ok=true
  [[ "$KUBE_RUNNER_ACTIVE" == 1 ]] || return 1
  [[ "$exit_code" =~ ^([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$ ]] ||
    return 1
  printf 'CLOSE\n' >&"$KUBE_RUNNER_CONTROL_WRITE_FD" || close_ok=false
  wait "$KUBE_RUNNER_PID" || supervisor_status=$?
  kubectl_isolated_state_clear
  admin_conf_is_safe || return 1
  [[ "$close_ok" == true && "$supervisor_status" == 0 ]] || return 1
  return "$exit_code"
}

kubectl_isolated_wait_interruptibly() {
  local message read_status
  [[ "$KUBE_RUNNER_ACTIVE" == 1 ]] || return 1
  while true; do
    if kubectl_isolated_read_control 0.05; then
      message=$KUBE_RUNNER_CONTROL_MESSAGE
      if [[ "$message" =~ ^DONE\|([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$ ]]; then
        kubectl_isolated_wait "${BASH_REMATCH[1]}"
        return
      fi
      kubectl_isolated_terminate TERM || true
      return 1
    else
      read_status=$?
    fi
    [[ "$read_status" != 1 ]] || {
      kubectl_isolated_terminate TERM || true
      return 1
    }
  done
}

kubectl_isolated_terminate() {
  local signal_name=$1 message read_status
  [[ "$KUBE_RUNNER_ACTIVE" == 1 ]] || return 1
  case "$signal_name" in
    HUP | INT | TERM) ;;
    *) return 1 ;;
  esac
  printf 'STOP|%s\n' "$signal_name" \
    >&"$KUBE_RUNNER_CONTROL_WRITE_FD" || return 1
  for _ in {1..300}; do
    if kubectl_isolated_read_control 0.02; then
      message=$KUBE_RUNNER_CONTROL_MESSAGE
      case "$message" in
        STOPPED\|OK)
          kubectl_isolated_wait 0
          return
          ;;
        DONE\|*)
          if [[ "$message" =~ ^DONE\|([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])$ ]]; then
            if kubectl_isolated_wait 0; then
              return 0
            fi
            return 1
          fi
          return 1
          ;;
        *) return 1 ;;
      esac
    else
      read_status=$?
      if [[ "$read_status" == 1 ]]; then
        return 1
      fi
    fi
  done
  return 1
}

kubectl_query_is_empty() {
  local captured
  captured=$(
    set +e
    kubectl_run "$@" 2>/dev/null
    printf '__EXIT_CODE__=%s\n' "$?"
  )
  [[ "$captured" == '__EXIT_CODE__=0' ]]
}
