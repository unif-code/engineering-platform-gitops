# Bootstrap 主机参数化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让"新增一台机器"变成纯数据变更：只在 `bootstrap/hosts/<hostname>/` 填写主机身份，脚本按 `hostname` 自动选取，零脚本改动、零测试改动。

**Architecture:** 新增 `lib/host-config.sh` 严格解析 `host.env`（不 `source`）；两份主机相关 yaml 与其 digest pin 迁入按主机目录；Stage 00/50/60/90 用 `HOST_*` 变量替换全部字面量，Stage 10–40 不动。`validate.py` 静态校验每个 host 目录的一致性，使填错在本地即红。

**Tech Stack:** Bash 3.2 兼容 shell、Python `unittest`、`scripts/test_bootstrap.py` 的假主机 fixture、`scripts/validate.py` + `test_validate.py`、ShellCheck。

**Spec:** `docs/superpowers/specs/2026-08-18-bootstrap-host-parametrization-design.md`

## Global Constraints

- `host.env` 恰好 8 个键：`HOST_NAME HOST_NODE_IP HOST_CLUSTER_NAME HOST_POD_CIDR HOST_SERVICE_CIDR HOST_SWAP_FILE HOST_SWAP_MIN_BYTES HOST_SWAP_MAX_BYTES`；多一个少一个都拒绝。
- `host.env` 只允许 `KEY=VALUE` 行、`#` 注释行、空行；不 `source`；值字符集 `[A-Za-z0-9./_-]`。
- host 目录文件集精确为 `host.env kubeadm-init.yaml cilium-values.yaml pins.sha256`；目录 `0755`、文件 `0644`、root 拥有（测试模式下为测试用户）。
- 加载失败一律 `STOP_PRECONDITION`（退出码 `10`），reason 取 `host-not-registered` / `host-config-unsafe` / `host-config-invalid` / `host-config-name-mismatch` / `hostname-unreadable`；pins 格式错为 `STOP_SUPPLY_CHAIN_MISMATCH host-pins-invalid`（`20`）。
- 两份 yaml 仍被 digest pin 且仍做形状校验；Stage 60 `values_semantics_are_exact` 只把 `k8sServiceHost` 一行改为取 `HOST_NODE_IP`。
- Stage 10/20/30/40 不含主机参数，不加载 host config。
- 端口 `6443`、evidence 目录、PCS staging 路径、`kubernetes-admin` 用户名不参数化。
- 每个 Task 一个 commit、每个 commit 全绿；`retail-test-workflow` 的服务器行为在整个迁移中不变。
- 直接在 `main` 上工作，普通 push，禁止改写历史；每次 push 后等 GitHub `validation-gate` 全绿才允许服务器操作。

## 文件结构

| 文件 | 职责 |
| --- | --- |
| `scripts/bootstrap/lib/host-config.sh`（新建） | 解析 `host.env`、校验 host 目录合同、读取 pins；只判定不 `complete` |
| `bootstrap/hosts/retail-test-workflow/host.env`（新建） | 该机 8 个身份参数 |
| `bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml`（迁自 `bootstrap/kubeadm/init.yaml`） | 该机完整 kubeadm 配置 |
| `bootstrap/hosts/retail-test-workflow/cilium-values.yaml`（迁自 `bootstrap/cilium/values.yaml`） | 该机完整 Cilium values |
| `bootstrap/hosts/retail-test-workflow/pins.sha256`（新建） | 上两个文件的 digest |
| `scripts/bootstrap/pin-host.sh`（新建） | 重算并原子写入 `pins.sha256` |
| `scripts/validate.py` | `validate_bootstrap_contracts` 改为遍历 host 目录做静态校验 |
| `scripts/validation_catalog.py` | 登记新测试类 `HostConfigTest` |
| `scripts/bootstrap/00-preflight.sh` / `50-kubeadm-init.sh` / `60-install-cilium.sh` / `90-verify.sh` | 加载 host config，字面量换 `HOST_*` |
| `scripts/bootstrap/lib/admin-conf.sh` | 去掉常量，谓词直接读 `HOST_CLUSTER_NAME` / `HOST_NODE_IP` |
| `scripts/test_bootstrap.py` | 新 `HostConfigTest`；各 fixture 增加 hosts seam 与 `hostname` fake；结构约束与 `fixture-host-b` 流通测试 |
| `scripts/test_validate.py` | host 目录静态校验的正负用例、`pin-host.sh` 用例 |

---

### Task 1: `lib/host-config.sh` 与 `host.env`（尚无消费者）

**Files:**
- Create: `scripts/bootstrap/lib/host-config.sh`
- Create: `bootstrap/hosts/retail-test-workflow/host.env`
- Modify: `scripts/test_bootstrap.py`（新增 `HOST_CONFIG` 常量与 `HostConfigTest`）
- Modify: `scripts/validation_catalog.py:14-26,39-45`

**Interfaces:**
- Produces: `host_env_parse <file>`：纯解析，成功后设置 8 个 `HOST_*` 变量（未 readonly）并返回 0；失败设 `HOST_CONFIG_ERROR=host-config-invalid` 返回 1。
- Produces: `load_host_config`：`hostname` → 选目录 → 目录/文件合同 → `host_env_parse` → 名称双向绑定 → `readonly HOST_CONFIG_DIR HOST_*`；失败设 `HOST_CONFIG_ERROR` 为 `hostname-unreadable|host-not-registered|host-config-unsafe|host-config-invalid|host-config-name-mismatch` 返回 1。
- Produces: `host_pin <kubeadm-init.yaml|cilium-values.yaml>`：打印 pins 中对应 digest；失败返回 1（调用方固定用 reason `host-pins-invalid`）。
- Produces: 测试 seam `BOOTSTRAP_TEST_HOSTS_DIR`（仅 `BOOTSTRAP_TEST_MODE=1` 时生效）。

- [ ] **Step 1: 写 `host.env`**

```bash
mkdir -p bootstrap/hosts/retail-test-workflow
cat > bootstrap/hosts/retail-test-workflow/host.env <<'EOF'
# 主机身份参数。改动后运行 ./scripts/validate-fast.sh；改 yaml 后运行
# scripts/bootstrap/pin-host.sh bootstrap/hosts/retail-test-workflow
HOST_NAME=retail-test-workflow
HOST_NODE_IP=10.93.1.27
HOST_CLUSTER_NAME=engineering-platform-dev
HOST_POD_CIDR=172.21.0.0/16
HOST_SERVICE_CIDR=172.20.0.0/16
HOST_SWAP_FILE=/swap.img
HOST_SWAP_MIN_BYTES=4000000000
HOST_SWAP_MAX_BYTES=4400000000
EOF
chmod 0644 bootstrap/hosts/retail-test-workflow/host.env
chmod 0755 bootstrap/hosts bootstrap/hosts/retail-test-workflow
```

- [ ] **Step 2: 写 `HostConfigTest` 的解析器 RED**

在 `scripts/test_bootstrap.py` 顶部常量区（`COMMON = ...` 之后）加：

```python
HOST_CONFIG = ROOT / 'scripts/bootstrap/lib/host-config.sh'
```

在 `class CommonLibraryTest` 之前加新类：

```python
class HostConfigTest(BootstrapTestCase):
    """lib/host-config.sh 的纯解析与目录合同边界。"""

    VALID_HOST_ENV = (
        '# fixture\n'
        'HOST_NAME=retail-test-workflow\n'
        'HOST_NODE_IP=10.93.1.27\n'
        '\n'
        'HOST_CLUSTER_NAME=engineering-platform-dev\n'
        'HOST_POD_CIDR=172.21.0.0/16\n'
        'HOST_SERVICE_CIDR=172.20.0.0/16\n'
        'HOST_SWAP_FILE=/swap.img\n'
        'HOST_SWAP_MIN_BYTES=4000000000\n'
        'HOST_SWAP_MAX_BYTES=4400000000\n'
    )

    def run_parse(self, content: str) -> subprocess.CompletedProcess[str]:
        directory = self.temporary_directory()
        target = directory / 'host.env'
        target.write_bytes(content.encode('utf-8'))
        body = (
            'set -u\n'
            'if host_env_parse "$2"; then\n'
            '  printf "%s|%s|%s|%s|%s|%s|%s|%s\\n" '
            '"$HOST_NAME" "$HOST_NODE_IP" "$HOST_CLUSTER_NAME" '
            '"$HOST_POD_CIDR" "$HOST_SERVICE_CIDR" "$HOST_SWAP_FILE" '
            '"$HOST_SWAP_MIN_BYTES" "$HOST_SWAP_MAX_BYTES"\n'
            'else\n'
            '  printf "ERROR=%s\\n" "$HOST_CONFIG_ERROR"\n'
            '  exit 1\n'
            'fi\n'
        )
        return self.run_command(
            ['/bin/bash', '-c', f'source "$1"\n{body}', 'test-host-config',
             str(HOST_CONFIG), str(target)],
            env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'},
        )

    def test_parse_accepts_comments_blank_lines_and_exact_key_set(self) -> None:
        result = self.run_parse(self.VALID_HOST_ENV)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            'retail-test-workflow|10.93.1.27|engineering-platform-dev|'
            '172.21.0.0/16|172.20.0.0/16|/swap.img|4000000000|4400000000\n',
        )

    def test_parse_rejects_every_invalid_shape(self) -> None:
        valid = self.VALID_HOST_ENV
        cases = {
            'missing-key': valid.replace('HOST_SWAP_FILE=/swap.img\n', ''),
            'extra-key': valid + 'HOST_EXTRA=1\n',
            'unknown-key': valid.replace('HOST_NAME=', 'HOSTNAME='),
            'duplicate-key': valid + 'HOST_NODE_IP=10.93.1.27\n',
            'quoted-value': valid.replace(
                'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE="/swap.img"'
            ),
            'space-in-value': valid.replace(
                'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE=/swap img'
            ),
            'dollar-in-value': valid.replace(
                'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE=/$HOME/swap.img'
            ),
            'backtick-in-value': valid.replace(
                'HOST_CLUSTER_NAME=engineering-platform-dev',
                'HOST_CLUSTER_NAME=`id`',
            ),
            'crlf': valid.replace('\n', '\r\n'),
            'no-trailing-newline': valid.rstrip('\n'),
            'empty-file': '',
            'bad-ip-octet': valid.replace('10.93.1.27', '10.93.1.256'),
            'bad-ip-leading-zero': valid.replace('10.93.1.27', '010.93.1.27'),
            'bad-ip-shape': valid.replace('10.93.1.27', '10.93.1'),
            'bad-cidr-prefix': valid.replace('172.21.0.0/16', '172.21.0.0/33'),
            'bad-cidr-no-prefix': valid.replace('172.21.0.0/16', '172.21.0.0'),
            'uppercase-hostname': valid.replace(
                'HOST_NAME=retail-test-workflow', 'HOST_NAME=Retail'
            ),
            'hostname-trailing-dash': valid.replace(
                'HOST_NAME=retail-test-workflow', 'HOST_NAME=retail-'
            ),
            'relative-swap-path': valid.replace(
                'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE=swap.img'
            ),
            'dotdot-swap-path': valid.replace(
                'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE=/../swap.img'
            ),
            'swap-min-not-numeric': valid.replace(
                'HOST_SWAP_MIN_BYTES=4000000000', 'HOST_SWAP_MIN_BYTES=4G'
            ),
            'swap-min-zero': valid.replace(
                'HOST_SWAP_MIN_BYTES=4000000000', 'HOST_SWAP_MIN_BYTES=0'
            ),
            'swap-min-not-below-max': valid.replace(
                'HOST_SWAP_MAX_BYTES=4400000000', 'HOST_SWAP_MAX_BYTES=4000000000'
            ),
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                result = self.run_parse(content)

                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertEqual(result.stdout, 'ERROR=host-config-invalid\n')
```

- [ ] **Step 3: 登记测试类**

`scripts/validation_catalog.py` 的 `SHARDS['contracts']` 在 `'test_bootstrap.CommonLibraryTest',` 之前插入 `'test_bootstrap.HostConfigTest',`；`FAST_SELECTORS` 在 `'test_bootstrap.CommonLibraryTest',` 之前插入 `'test_bootstrap.HostConfigTest',`。

- [ ] **Step 4: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.HostConfigTest -v 2>&1 | tail -20`
Expected: 两个测试 FAIL（`host_env_parse: command not found`，退出码 127 ≠ 0/1）。

- [ ] **Step 5: 写 `lib/host-config.sh`**

```bash
cat > scripts/bootstrap/lib/host-config.sh <<'EOF'
#!/usr/bin/env bash

# 主机身份唯一来源：bootstrap/hosts/<hostname>/host.env。
# 本库只判定：失败时把 reason 写入 HOST_CONFIG_ERROR 并返回 1，
# 由调用 stage 决定 RESULT。不 source host.env——逐行按白名单语法解析。

readonly -a HOST_CONFIG_KEYS=(
  HOST_NAME HOST_NODE_IP HOST_CLUSTER_NAME HOST_POD_CIDR HOST_SERVICE_CIDR
  HOST_SWAP_FILE HOST_SWAP_MIN_BYTES HOST_SWAP_MAX_BYTES
)
readonly -a HOST_CONFIG_FILES=(host.env kubeadm-init.yaml cilium-values.yaml pins.sha256)
HOST_CONFIG_ERROR=
HOST_CONFIG_DIR=

host_config_path_mode() {
  stat -c '%a' "$1" 2>/dev/null || stat -f '%Lp' "$1" 2>/dev/null
}

host_config_path_owner() {
  stat -c '%u:%g' "$1" 2>/dev/null || stat -f '%u:%g' "$1" 2>/dev/null
}

host_config_owned_by_expected() {
  local expected_uid=0 expected_gid=0
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 && "$EUID" -ne 0 ]]; then
    expected_uid=$EUID
    expected_gid=${GROUPS[0]}
  fi
  [[ "$(host_config_path_owner "$1")" == "${expected_uid}:${expected_gid}" ]]
}

host_config_root() {
  local lib_dir root
  if [[ "${BOOTSTRAP_TEST_MODE:-0}" == 1 && -n "${BOOTSTRAP_TEST_HOSTS_DIR:-}" ]]; then
    root=$BOOTSTRAP_TEST_HOSTS_DIR
    [[ "$root" == /* && -d "$root" && ! -L "$root" && -O "$root" ]] || return 1
    printf '%s\n' "$root"
    return 0
  fi
  lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P) || return 1
  root=$(cd "${lib_dir}/../../../bootstrap/hosts" 2>/dev/null && pwd -P) || return 1
  printf '%s\n' "$root"
}

host_config_key_is_known() {
  local known
  for known in "${HOST_CONFIG_KEYS[@]}"; do
    [[ "$1" != "$known" ]] || return 0
  done
  return 1
}

host_config_file_is_known() {
  local known
  for known in "${HOST_CONFIG_FILES[@]}"; do
    [[ "$1" != "$known" ]] || return 0
  done
  return 1
}

host_config_ipv4_is_valid() {
  local octet
  [[ "$1" =~ ^([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  for octet in "${BASH_REMATCH[@]:1:4}"; do
    [[ "$octet" == 0 || "$octet" =~ ^[1-9][0-9]{0,2}$ ]] || return 1
    (( 10#$octet <= 255 )) || return 1
  done
}

host_config_value_is_valid() {
  local key=$1 value=$2
  case "$key" in
    HOST_NAME|HOST_CLUSTER_NAME)
      [[ "$value" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]] ;;
    HOST_NODE_IP)
      host_config_ipv4_is_valid "$value" ;;
    HOST_POD_CIDR|HOST_SERVICE_CIDR)
      [[ "$value" =~ ^[0-9.]+/([0-9]|[12][0-9]|3[0-2])$ ]] &&
        host_config_ipv4_is_valid "${value%/*}" ;;
    HOST_SWAP_FILE)
      [[ "$value" =~ ^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$ && "$value" != *..* ]] ;;
    HOST_SWAP_MIN_BYTES|HOST_SWAP_MAX_BYTES)
      [[ "$value" =~ ^[1-9][0-9]{0,17}$ ]] ;;
    *) return 1 ;;
  esac
}

host_env_parse() {
  local file=$1 line key value seen=' '
  HOST_CONFIG_ERROR=
  while IFS= read -r line; do
    [[ -z "$line" || "$line" == '#'* ]] && continue
    if [[ ! "$line" =~ ^(HOST_[A-Z_]+)=([A-Za-z0-9./_-]+)$ ]]; then
      HOST_CONFIG_ERROR=host-config-invalid
      return 1
    fi
    key=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    if ! host_config_key_is_known "$key" || [[ "$seen" == *" $key "* ]] ||
       ! host_config_value_is_valid "$key" "$value"; then
      HOST_CONFIG_ERROR=host-config-invalid
      return 1
    fi
    printf -v "$key" '%s' "$value"
    seen+="$key "
  done <"$file"
  # 末行必须以换行结束：无终止换行时 read 返回非零并把残余留在 line 中。
  if [[ -n "$line" ]]; then
    HOST_CONFIG_ERROR=host-config-invalid
    return 1
  fi
  for key in "${HOST_CONFIG_KEYS[@]}"; do
    if [[ "$seen" != *" $key "* ]]; then
      HOST_CONFIG_ERROR=host-config-invalid
      return 1
    fi
  done
  if (( HOST_SWAP_MIN_BYTES >= HOST_SWAP_MAX_BYTES )); then
    HOST_CONFIG_ERROR=host-config-invalid
    return 1
  fi
}

# 子 shell 隔离 shopt；只允许精确 4 个已知文件名。
host_config_entries_are_exact() (
  local dir=$1 entry count=0
  shopt -s nullglob dotglob
  for entry in "$dir"/*; do
    host_config_file_is_known "${entry##*/}" || exit 1
    count=$((count + 1))
  done
  (( count == ${#HOST_CONFIG_FILES[@]} ))
)

load_host_config() {
  local actual root dir file
  HOST_CONFIG_ERROR=
  actual=$(hostname 2>/dev/null) || {
    HOST_CONFIG_ERROR=hostname-unreadable
    return 1
  }
  if [[ ! "$actual" =~ ^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$ ]]; then
    HOST_CONFIG_ERROR=host-not-registered
    return 1
  fi
  root=$(host_config_root) || {
    HOST_CONFIG_ERROR=host-config-unsafe
    return 1
  }
  dir="${root}/${actual}"
  if [[ ! -e "$dir" && ! -L "$dir" ]]; then
    HOST_CONFIG_ERROR=host-not-registered
    return 1
  fi
  if [[ -L "$dir" || ! -d "$dir" || "$(host_config_path_mode "$dir")" != 755 ]] ||
     ! host_config_owned_by_expected "$dir" ||
     ! host_config_entries_are_exact "$dir"; then
    HOST_CONFIG_ERROR=host-config-unsafe
    return 1
  fi
  for file in "${HOST_CONFIG_FILES[@]}"; do
    if [[ -L "${dir}/${file}" || ! -f "${dir}/${file}" ||
          "$(host_config_path_mode "${dir}/${file}")" != 644 ]] ||
       ! host_config_owned_by_expected "${dir}/${file}"; then
      HOST_CONFIG_ERROR=host-config-unsafe
      return 1
    fi
  done
  host_env_parse "${dir}/host.env" || return 1
  if [[ "$HOST_NAME" != "$actual" ]]; then
    HOST_CONFIG_ERROR=host-config-name-mismatch
    return 1
  fi
  HOST_CONFIG_DIR=$dir
  readonly HOST_CONFIG_DIR "${HOST_CONFIG_KEYS[@]}"
}

# 打印 pins.sha256 中指定文件的 digest；两行、固定顺序、sha256sum -c 兼容。
host_pin() {
  local wanted=$1 line count=0 pin_init= pin_values=
  [[ -n "$HOST_CONFIG_DIR" ]] || return 1
  while IFS= read -r line; do
    count=$((count + 1))
    case "$count" in
      1)
        [[ "$line" =~ ^([0-9a-f]{64})\ \ kubeadm-init\.yaml$ ]] || return 1
        pin_init=${BASH_REMATCH[1]}
        ;;
      2)
        [[ "$line" =~ ^([0-9a-f]{64})\ \ cilium-values\.yaml$ ]] || return 1
        pin_values=${BASH_REMATCH[1]}
        ;;
      *) return 1 ;;
    esac
  done <"${HOST_CONFIG_DIR}/pins.sha256"
  [[ -z "$line" && "$count" == 2 ]] || return 1
  case "$wanted" in
    kubeadm-init.yaml) printf '%s\n' "$pin_init" ;;
    cilium-values.yaml) printf '%s\n' "$pin_values" ;;
    *) return 1 ;;
  esac
}
EOF
chmod 0644 scripts/bootstrap/lib/host-config.sh
```

- [ ] **Step 6: 运行 GREEN 与 ShellCheck**

Run: `python3 -m unittest scripts.test_bootstrap.HostConfigTest -v 2>&1 | tail -6 && shellcheck scripts/bootstrap/lib/host-config.sh && echo shellcheck-ok`
Expected: `OK`（2 tests）；`shellcheck-ok`。

- [ ] **Step 7: 运行 catalog 与 fast 校验**

Run: `python3 -m unittest scripts.test_validate.ValidationCatalogTest 2>&1 | tail -3 && ./scripts/validate-fast.sh 2>&1 | tail -3`
Expected: 两处 `OK`。

- [ ] **Step 8: Commit**

```bash
git add scripts/bootstrap/lib/host-config.sh bootstrap/hosts scripts/test_bootstrap.py scripts/validation_catalog.py
git commit -m "feat(bootstrap): add strict host config loader"
```

---

### Task 2: 迁 yaml 入 host 目录、pins、`pin-host.sh`、`validate.py` 静态合同

**Files:**
- Move: `bootstrap/kubeadm/init.yaml` → `bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml`
- Move: `bootstrap/cilium/values.yaml` → `bootstrap/hosts/retail-test-workflow/cilium-values.yaml`
- Create: `bootstrap/hosts/retail-test-workflow/pins.sha256`
- Create: `scripts/bootstrap/pin-host.sh`
- Modify: `scripts/validate.py:283-402`
- Modify: `scripts/test_validate.py:368-514`
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:51`、`scripts/bootstrap/60-install-cilium.sh:79`（仅路径常量）
- Modify: `scripts/test_bootstrap.py`（fixture 读取路径 3 处）
- Modify: `docs/superpowers/specs/2026-08-18-bootstrap-host-parametrization-design.md`（`pin-host.sh` 参数改为 host 目录路径）

**Interfaces:**
- Consumes: 无（Task 1 的 lib 本任务尚不接入 stage）。
- Produces: `validate.py` 中 `parse_host_env(path) -> dict[str, str]`、`validate_host_directory(root, host_dir)`、`HOST_ENV_KEYS`、`HOST_FILES`；`bootstrap/hosts/<name>/pins.sha256` 两行格式；`scripts/bootstrap/pin-host.sh <host-dir>`。

- [ ] **Step 1: 移动文件并生成 pins（digest 值必须与现有常量一致）**

```bash
git mv bootstrap/kubeadm/init.yaml bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml
git mv bootstrap/cilium/values.yaml bootstrap/hosts/retail-test-workflow/cilium-values.yaml
rmdir bootstrap/kubeadm bootstrap/cilium
cat > bootstrap/hosts/retail-test-workflow/pins.sha256 <<'EOF'
e37b38f198bd7279ae3d203a990a4c2d40e1b2a8b59796475b814f09445103c6  kubeadm-init.yaml
105ca75fdefc07a32a1b944ad749baf0e66b2b2437dbe0ab995c323f71cdd887  cilium-values.yaml
EOF
chmod 0644 bootstrap/hosts/retail-test-workflow/*
( cd bootstrap/hosts/retail-test-workflow && shasum -a 256 -c pins.sha256 )
```
Expected: 两行 `OK`。这两个 digest 分别等于 `50-kubeadm-init.sh:49` 的 `CONFIG_SHA256` 与 `60-install-cilium.sh:78` 的 `VALUES_SHA256`。

- [ ] **Step 2: 更新 stage 路径常量与 fixture 读取路径**

`scripts/bootstrap/50-kubeadm-init.sh:51`：
```bash
readonly CONFIG_FILE="${repo_root}/bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml"
```
`scripts/bootstrap/60-install-cilium.sh:79`：
```bash
readonly VALUES_FILE="${repo_root}/bootstrap/hosts/retail-test-workflow/cilium-values.yaml"
```
`scripts/test_bootstrap.py`：
- 第 6375 行附近 `config_source.write_bytes((ROOT / 'bootstrap/kubeadm/init.yaml').read_bytes())` → `ROOT / 'bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml'`
- 第 8871 行附近 `values.write_bytes((ROOT / 'bootstrap/cilium/values.yaml').read_bytes())` → `ROOT / 'bootstrap/hosts/retail-test-workflow/cilium-values.yaml'`
- `test_admin_conf_contract_tracks_pinned_cluster_name` 中 `(ROOT / 'bootstrap/kubeadm/init.yaml')` → `(ROOT / 'bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml')`

- [ ] **Step 3: 写 `test_validate.py` RED**

确认 `scripts/test_validate.py` 顶部已 `import subprocess`（缺则补）。把 `BootstrapContractTest.test_kubeadm_contract_rejects_pod_cidr_drift` 与 `test_cilium_contract_rejects_disabled_kube_proxy_replacement` 里的路径改为 `root / 'bootstrap/hosts/retail-test-workflow/kubeadm-init.yaml'` 与 `.../cilium-values.yaml`，并在类末尾追加：

```python
    HOST_DIR = Path('bootstrap/hosts/retail-test-workflow')

    def rewrite_host_env(self, root: Path, old: str, new: str) -> None:
        path = root / self.HOST_DIR / 'host.env'
        text = path.read_text(encoding='utf-8')
        self.assertIn(old, text)
        path.write_text(text.replace(old, new, 1), encoding='utf-8')

    def test_host_env_is_parsed_strictly(self) -> None:
        root = self.copy_bootstrap_root()
        parsed = validator.parse_host_env(root / self.HOST_DIR / 'host.env')

        self.assertEqual(parsed['HOST_NAME'], 'retail-test-workflow')
        self.assertEqual(parsed['HOST_NODE_IP'], '10.93.1.27')
        self.assertEqual(sorted(parsed), sorted(validator.HOST_ENV_KEYS))

    def test_host_env_drift_is_rejected(self) -> None:
        cases = (
            ('missing-key', 'HOST_SWAP_FILE=/swap.img\n', ''),
            ('extra-key', 'HOST_SWAP_MAX_BYTES=4400000000\n',
             'HOST_SWAP_MAX_BYTES=4400000000\nHOST_EXTRA=1\n'),
            ('duplicate-key', 'HOST_NODE_IP=10.93.1.27\n',
             'HOST_NODE_IP=10.93.1.27\nHOST_NODE_IP=10.93.1.27\n'),
            ('bad-ip', 'HOST_NODE_IP=10.93.1.27', 'HOST_NODE_IP=10.93.1.256'),
            ('bad-cidr', 'HOST_POD_CIDR=172.21.0.0/16', 'HOST_POD_CIDR=172.21.0.1/16'),
            ('quoted', 'HOST_SWAP_FILE=/swap.img', 'HOST_SWAP_FILE="/swap.img"'),
            ('swap-range', 'HOST_SWAP_MAX_BYTES=4400000000', 'HOST_SWAP_MAX_BYTES=1'),
            ('name-mismatch', 'HOST_NAME=retail-test-workflow', 'HOST_NAME=other-host'),
        )
        for name, old, new in cases:
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                self.rewrite_host_env(root, old, new)
                self.assert_contract_fails(root)

    def test_host_env_without_trailing_newline_is_rejected(self) -> None:
        root = self.copy_bootstrap_root()
        path = root / self.HOST_DIR / 'host.env'
        path.write_text(path.read_text(encoding='utf-8').rstrip('\n'), encoding='utf-8')

        self.assert_contract_fails(root)

    def test_host_yaml_must_match_host_env(self) -> None:
        cases = (
            ('kubeadm-init.yaml', '10.93.1.27', '10.93.1.28'),
            ('kubeadm-init.yaml', 'clusterName: engineering-platform-dev', 'clusterName: other'),
            ('kubeadm-init.yaml', 'name: retail-test-workflow', 'name: other-host'),
            ('cilium-values.yaml', 'k8sServiceHost: 10.93.1.27', 'k8sServiceHost: 10.93.1.28'),
        )
        for filename, old, new in cases:
            with self.subTest(file=filename, old=old):
                root = self.copy_bootstrap_root()
                path = root / self.HOST_DIR / filename
                text = path.read_text(encoding='utf-8')
                self.assertIn(old, text)
                path.write_text(text.replace(old, new), encoding='utf-8')
                # 同步 pins，确保失败来自一致性校验而非 digest 校验。
                subprocess.run(
                    ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'),
                     str(root / self.HOST_DIR)],
                    check=True, capture_output=True,
                )

                self.assert_contract_fails(root)

    def test_pins_must_match_files(self) -> None:
        root = self.copy_bootstrap_root()
        pins = root / self.HOST_DIR / 'pins.sha256'
        pins.write_text(
            pins.read_text(encoding='utf-8').replace('e37b38f1', '00000000', 1),
            encoding='utf-8',
        )

        self.assert_contract_fails(root)

    def test_pins_shape_is_exact(self) -> None:
        good = (validator.ROOT / self.HOST_DIR / 'pins.sha256').read_text(encoding='utf-8')
        for name, content in (
            ('reversed', ''.join(reversed(good.splitlines(keepends=True)))),
            ('third-line', good + 'x\n'),
            ('single-space', good.replace('  kubeadm', ' kubeadm', 1)),
            ('no-newline', good.rstrip('\n')),
        ):
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                (root / self.HOST_DIR / 'pins.sha256').write_text(content, encoding='utf-8')
                self.assert_contract_fails(root)

    def test_host_directory_file_set_is_exact(self) -> None:
        for name in ('extra-file', 'missing-file', 'symlinked-file', 'legacy-directory'):
            with self.subTest(case=name):
                root = self.copy_bootstrap_root()
                host_dir = root / self.HOST_DIR
                if name == 'extra-file':
                    (host_dir / 'notes.txt').write_text('x\n', encoding='utf-8')
                elif name == 'missing-file':
                    (host_dir / 'pins.sha256').unlink()
                elif name == 'symlinked-file':
                    (host_dir / 'host.env').unlink()
                    (host_dir / 'host.env').symlink_to(root / 'outside.env')
                    (root / 'outside.env').write_text('HOST_NAME=x\n', encoding='utf-8')
                else:
                    (root / 'bootstrap/kubeadm').mkdir()
                    (root / 'bootstrap/kubeadm/init.yaml').write_text('x\n', encoding='utf-8')
                self.assert_contract_fails(root)

    def test_pin_host_tool_rewrites_only_pins(self) -> None:
        root = self.copy_bootstrap_root()
        host_dir = root / self.HOST_DIR
        (host_dir / 'pins.sha256').write_text('broken\n', encoding='utf-8')
        before = {p.name: p.read_bytes() for p in host_dir.iterdir() if p.name != 'pins.sha256'}

        result = subprocess.run(
            ['/bin/bash', str(validator.ROOT / 'scripts/bootstrap/pin-host.sh'), str(host_dir)],
            capture_output=True, text=True, check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            (host_dir / 'pins.sha256').read_text(encoding='utf-8'),
            (validator.ROOT / self.HOST_DIR / 'pins.sha256').read_text(encoding='utf-8'),
        )
        self.assertEqual({p.name: p.read_bytes() for p in host_dir.iterdir() if p.name != 'pins.sha256'}, before)
        self.assertEqual(oct((host_dir / 'pins.sha256').stat().st_mode & 0o777), '0o644')
        validator.validate_bootstrap_contracts(root)
```

- [ ] **Step 4: 运行 RED**

Run: `python3 -m unittest scripts.test_validate.BootstrapContractTest 2>&1 | tail -15`
Expected: `test_repository_bootstrap_contracts` 因 `bootstrap/kubeadm/init.yaml 不存在` 而 FAIL；新用例因 `parse_host_env`/`HOST_ENV_KEYS` 不存在而 ERROR。

- [ ] **Step 5: 写 `pin-host.sh`**

```bash
cat > scripts/bootstrap/pin-host.sh <<'EOF'
#!/bin/bash
# 重算并原子写入 bootstrap/hosts/<hostname>/pins.sha256；只写这一个文件。
set -Eeuo pipefail
export LC_ALL=C
umask 022

if [[ $# -ne 1 ]]; then
  printf 'usage: %s bootstrap/hosts/<hostname>\n' "${0##*/}" >&2
  exit 2
fi
host_dir=$1
if [[ ! -d "$host_dir" || -L "$host_dir" ]]; then
  printf 'not a host directory: %s\n' "$host_dir" >&2
  exit 2
fi
for name in kubeadm-init.yaml cilium-values.yaml; do
  if [[ ! -f "${host_dir}/${name}" || -L "${host_dir}/${name}" ]]; then
    printf 'missing regular file: %s\n' "${host_dir}/${name}" >&2
    exit 2
  fi
done

digest_of() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1"
  else
    shasum -a 256 "$1"
  fi | awk '{print $1}'
}

temporary=$(mktemp "${host_dir}/.pins.XXXXXX")
trap 'rm -f -- "$temporary"' EXIT
{
  printf '%s  kubeadm-init.yaml\n' "$(digest_of "${host_dir}/kubeadm-init.yaml")"
  printf '%s  cilium-values.yaml\n' "$(digest_of "${host_dir}/cilium-values.yaml")"
} >"$temporary"
chmod 0644 "$temporary"
mv -f -- "$temporary" "${host_dir}/pins.sha256"
trap - EXIT
cat "${host_dir}/pins.sha256"
EOF
chmod 0755 scripts/bootstrap/pin-host.sh
```

- [ ] **Step 6: 改写 `validate.py` 的 bootstrap 合同**

在 `validate.py` 顶部 import 区确认有 `import hashlib`、`import ipaddress`、`import re`（缺则补）。把 `validate_bootstrap_contracts` 中从 `kubeadm_config = bootstrap / 'kubeadm/init.yaml'` 起、到函数末尾的 kubeadm/cilium 段整体替换为下面的实现（containerd 段保留原样）：

```python
HOST_ENV_KEYS = (
    'HOST_NAME', 'HOST_NODE_IP', 'HOST_CLUSTER_NAME', 'HOST_POD_CIDR',
    'HOST_SERVICE_CIDR', 'HOST_SWAP_FILE', 'HOST_SWAP_MIN_BYTES',
    'HOST_SWAP_MAX_BYTES',
)
HOST_FILES = ('host.env', 'kubeadm-init.yaml', 'cilium-values.yaml', 'pins.sha256')
PIN_FILES = ('kubeadm-init.yaml', 'cilium-values.yaml')
LABEL_RE = re.compile(r'^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$')
HOST_ENV_LINE_RE = re.compile(r'^(HOST_[A-Z_]+)=([A-Za-z0-9./_-]+)$')
SWAP_FILE_RE = re.compile(r'^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$')
PIN_LINE_RE = re.compile(r'^([0-9a-f]{64})  (kubeadm-init\.yaml|cilium-values\.yaml)$')


def parse_host_env(path: Path) -> dict[str, str]:
    label = path.as_posix()
    try:
        text = path.read_bytes().decode('ascii')
    except (OSError, UnicodeDecodeError) as error:
        fail(f'{label} 必须是可读的 ASCII 文件：{error}')
    if not text.endswith('\n'):
        fail(f'{label} 末行必须以换行结束')
    values: dict[str, str] = {}
    for number, line in enumerate(text.split('\n')[:-1], 1):
        if not line or line.startswith('#'):
            continue
        match = HOST_ENV_LINE_RE.match(line)
        if match is None:
            fail(f'{label}:{number} 不符合 KEY=VALUE 语法（无引号、无空格、值仅含 [A-Za-z0-9./_-]）')
        key, value = match.groups()
        if key not in HOST_ENV_KEYS:
            fail(f'{label}:{number} 未知键 {key}')
        if key in values:
            fail(f'{label}:{number} 重复键 {key}')
        values[key] = value
    missing = [key for key in HOST_ENV_KEYS if key not in values]
    if missing:
        fail(f'{label} 缺少键：{", ".join(missing)}')
    for key in ('HOST_NAME', 'HOST_CLUSTER_NAME'):
        if LABEL_RE.match(values[key]) is None:
            fail(f'{label} {key} 必须是 RFC 1123 label：{values[key]}')
    octet = r'(0|[1-9][0-9]{0,2})'
    if re.fullmatch(rf'{octet}(\.{octet}){{3}}', values['HOST_NODE_IP']) is None:
        fail(f'{label} HOST_NODE_IP 不是点分四段且无前导零：{values["HOST_NODE_IP"]}')
    try:
        ipaddress.IPv4Address(values['HOST_NODE_IP'])
    except ValueError:
        fail(f'{label} HOST_NODE_IP 不是合法 IPv4：{values["HOST_NODE_IP"]}')
    for key in ('HOST_POD_CIDR', 'HOST_SERVICE_CIDR'):
        try:
            ipaddress.IPv4Network(values[key], strict=True)
        except ValueError:
            fail(f'{label} {key} 不是合法 IPv4 网络：{values[key]}')
        if '/' not in values[key]:
            fail(f'{label} {key} 必须带前缀长度：{values[key]}')
    if SWAP_FILE_RE.match(values['HOST_SWAP_FILE']) is None or '..' in values['HOST_SWAP_FILE']:
        fail(f'{label} HOST_SWAP_FILE 必须是绝对路径：{values["HOST_SWAP_FILE"]}')
    for key in ('HOST_SWAP_MIN_BYTES', 'HOST_SWAP_MAX_BYTES'):
        if not re.fullmatch(r'[1-9][0-9]{0,17}', values[key]):
            fail(f'{label} {key} 必须是正整数：{values[key]}')
    if int(values['HOST_SWAP_MIN_BYTES']) >= int(values['HOST_SWAP_MAX_BYTES']):
        fail(f'{label} HOST_SWAP_MIN_BYTES 必须小于 HOST_SWAP_MAX_BYTES')
    return values


def validate_host_kubeadm(path: Path, host: dict[str, str]) -> None:
    label = path.as_posix()
    try:
        documents = {
            document.get('kind'): document
            for document in yaml.safe_load_all(path.read_text(encoding='utf-8'))
            if isinstance(document, dict)
        }
    except yaml.YAMLError as error:
        fail(f'{label} YAML 解析失败：{error}')
    expect_contract(
        f'{label} kinds', set(documents),
        {'InitConfiguration', 'ClusterConfiguration', 'KubeletConfiguration'},
    )
    node_ip = host['HOST_NODE_IP']
    init = documents['InitConfiguration']
    expect_contract('InitConfiguration apiVersion', init.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('API advertiseAddress', value_at(init, ('localAPIEndpoint', 'advertiseAddress')), node_ip)
    expect_contract('API bindPort', value_at(init, ('localAPIEndpoint', 'bindPort')), 6443)
    expect_contract('Node name', value_at(init, ('nodeRegistration', 'name')), host['HOST_NAME'])
    expect_contract('CRI socket', value_at(init, ('nodeRegistration', 'criSocket')), 'unix:///run/containerd/containerd.sock')
    expect_contract('single-node taints', value_at(init, ('nodeRegistration', 'taints')), [])
    expect_contract(
        'kubelet node-ip',
        value_at(init, ('nodeRegistration', 'kubeletExtraArgs')),
        [{'name': 'node-ip', 'value': node_ip}],
    )
    expect_contract('kube-proxy skip phase', init.get('skipPhases'), ['addon/kube-proxy'])

    cluster = documents['ClusterConfiguration']
    expect_contract('ClusterConfiguration apiVersion', cluster.get('apiVersion'), 'kubeadm.k8s.io/v1beta4')
    expect_contract('Kubernetes version', cluster.get('kubernetesVersion'), 'v1.36.3')
    expect_contract('clusterName', cluster.get('clusterName'), host['HOST_CLUSTER_NAME'])
    expect_contract('controlPlaneEndpoint', cluster.get('controlPlaneEndpoint'), f'{node_ip}:6443')
    expect_contract('API certificate SANs', value_at(cluster, ('apiServer', 'certSANs')), [node_ip])
    expect_contract('Service CIDR', value_at(cluster, ('networking', 'serviceSubnet')), host['HOST_SERVICE_CIDR'])
    expect_contract('Pod CIDR', value_at(cluster, ('networking', 'podSubnet')), host['HOST_POD_CIDR'])
    expect_contract('DNS domain', value_at(cluster, ('networking', 'dnsDomain')), 'cluster.local')
    expect_contract('kube-proxy disabled', value_at(cluster, ('proxy', 'disabled')), True)

    kubelet = documents['KubeletConfiguration']
    expect_contract('KubeletConfiguration apiVersion', kubelet.get('apiVersion'), 'kubelet.config.k8s.io/v1beta1')
    expect_contract('kubelet cgroup driver', kubelet.get('cgroupDriver'), 'systemd')
    expect_contract('kubelet failSwapOn', kubelet.get('failSwapOn'), False)
    expect_contract('kubelet swap behavior', value_at(kubelet, ('memorySwap', 'swapBehavior')), 'NoSwap')
    expect_contract('kubelet serverTLSBootstrap', kubelet.get('serverTLSBootstrap'), True)


def validate_host_cilium(path: Path, host: dict[str, str]) -> None:
    label = path.as_posix()
    try:
        cilium = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as error:
        fail(f'{label} YAML 解析失败：{error}')
    if not isinstance(cilium, dict):
        fail(f'{label} 顶层必须是 YAML mapping')
    expect_contract(
        f'{label} 顶层键集', set(cilium),
        {'kubeProxyReplacement', 'k8sServiceHost', 'k8sServicePort', 'cgroup',
         'gatewayAPI', 'hubble', 'image', 'ipam', 'operator'},
    )
    contracts = (
        (('kubeProxyReplacement',), True, 'kube-proxy replacement'),
        (('k8sServiceHost',), host['HOST_NODE_IP'], 'Cilium API host'),
        (('k8sServicePort',), 6443, 'Cilium API port'),
        (('ipam', 'mode'), 'kubernetes', 'Cilium IPAM'),
        (('gatewayAPI', 'enabled'), True, 'Cilium Gateway API'),
        (('cgroup', 'autoMount', 'enabled'), False, 'Cilium cgroup automount'),
        (('cgroup', 'hostRoot'), '/sys/fs/cgroup', 'Cilium cgroup root'),
        (('operator', 'replicas'), 1, 'Cilium operator replicas'),
        (('hubble', 'enabled'), False, 'Hubble staged state'),
        (('image', 'useDigest'), True, 'Cilium image useDigest'),
        (('image', 'digest'), 'sha256:383968cd5e8873f7976fa76aa6196045643558f4cc9518a207b9335cb24a0e93', 'Cilium image digest'),
        (('operator', 'image', 'useDigest'), True, 'Cilium operator useDigest'),
        (('operator', 'image', 'genericDigest'), 'sha256:80744a8cc7c91c2f9e6347629406844eb35d79b30a732c6d41c15b17232a74f3', 'Cilium operator digest'),
    )
    for path_tokens, expected, name in contracts:
        expect_contract(name, value_at(cilium, path_tokens), expected)


def validate_host_pins(host_dir: Path) -> None:
    pins = host_dir / 'pins.sha256'
    label = pins.as_posix()
    text = pins.read_text(encoding='utf-8')
    if not text.endswith('\n'):
        fail(f'{label} 末行必须以换行结束')
    lines = text.split('\n')[:-1]
    if len(lines) != len(PIN_FILES):
        fail(f'{label} 必须恰好 {len(PIN_FILES)} 行')
    hint = f'运行 scripts/bootstrap/pin-host.sh {host_dir.as_posix()}'
    for line, expected_name in zip(lines, PIN_FILES):
        match = PIN_LINE_RE.match(line)
        if match is None or match.group(2) != expected_name:
            fail(f'{label} 第 {PIN_FILES.index(expected_name) + 1} 行必须是 "<sha256>  {expected_name}"；{hint}')
        actual = hashlib.sha256((host_dir / expected_name).read_bytes()).hexdigest()
        if match.group(1) != actual:
            fail(f'{label} 中 {expected_name} 的 digest 与文件不一致；{hint}')


def validate_host_directory(host_dir: Path) -> None:
    label = host_dir.as_posix()
    if host_dir.is_symlink() or not host_dir.is_dir():
        fail(f'{label} 必须是真实目录')
    if LABEL_RE.match(host_dir.name) is None:
        fail(f'{label} 目录名必须是 RFC 1123 label')
    entries = sorted(entry.name for entry in host_dir.iterdir())
    if entries != sorted(HOST_FILES):
        fail(f'{label} 文件集必须精确为 {", ".join(HOST_FILES)}，实际：{", ".join(entries)}')
    for name in HOST_FILES:
        entry = host_dir / name
        if entry.is_symlink() or not entry.is_file():
            fail(f'{entry.as_posix()} 必须是常规文件（非软链）')
    host = parse_host_env(host_dir / 'host.env')
    if host['HOST_NAME'] != host_dir.name:
        fail(f'{label} 目录名必须等于 HOST_NAME={host["HOST_NAME"]}')
    validate_host_kubeadm(host_dir / 'kubeadm-init.yaml', host)
    validate_host_cilium(host_dir / 'cilium-values.yaml', host)
    validate_host_pins(host_dir)
```

`validate_bootstrap_contracts` 的尾部（containerd 段之后）改为：

```python
    for legacy in ('kubeadm', 'cilium'):
        if (bootstrap / legacy).exists():
            fail(f'bootstrap/{legacy}/ 已迁入 bootstrap/hosts/<hostname>/，禁止保留旧目录')
    hosts_root = bootstrap / 'hosts'
    if hosts_root.is_symlink() or not hosts_root.is_dir():
        fail('bootstrap/hosts/ 必须是真实目录')
    host_dirs = sorted(entry for entry in hosts_root.iterdir())
    if not host_dirs:
        fail('bootstrap/hosts/ 至少需要一个主机目录')
    for host_dir in host_dirs:
        validate_host_directory(host_dir)
```

并把函数开头 `for path in (containerd_config, containerd_unit, kubeadm_config, cilium_values):` 的存在性循环缩减为只检查 `containerd_config`、`containerd_unit`。

- [ ] **Step 7: 更新 spec 中工具用法**

`docs/superpowers/specs/2026-08-18-bootstrap-host-parametrization-design.md` 的"工具"一节改为：`scripts/bootstrap/pin-host.sh <host-dir>`（例：`scripts/bootstrap/pin-host.sh bootstrap/hosts/retail-test-workflow`）；`validate.py` 提示语同步。

- [ ] **Step 8: 运行 GREEN**

Run: `python3 -m unittest scripts.test_validate.BootstrapContractTest -v 2>&1 | tail -20 && shellcheck scripts/bootstrap/pin-host.sh && ./scripts/validate-fast.sh 2>&1 | tail -3`
Expected: 全部 `ok`；shellcheck 无输出；`validate-fast` `OK`。

- [ ] **Step 9: 运行受影响 fixture（路径改动）**

Run: `python3 -m unittest scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_declared_client_doc_exclusions scripts.test_bootstrap.CiliumInstallTest.test_check_is_zero_write_for_clean_apply_required_state scripts.test_bootstrap.CiliumInstallTest.test_admin_conf_contract_tracks_pinned_cluster_name 2>&1 | tail -4`
Expected: `OK`（3 tests）。

- [ ] **Step 10: Commit**

```bash
git add -A bootstrap scripts docs/superpowers/specs/2026-08-18-bootstrap-host-parametrization-design.md
git commit -m "feat(bootstrap): move host inputs into per-host directory with pins"
```

---

### Task 3: Stage 00 参数化

**Files:**
- Modify: `scripts/bootstrap/00-preflight.sh:9-17,54,65-67,94-113,166-167,186-187`
- Modify: `scripts/test_bootstrap.py`（`BootstrapTestCase.write_fixture_host`、`PreflightTest.make_environment`、`test_stops_on_wrong_hostname`、新增 host 目录合同矩阵）

**Interfaces:**
- Consumes: Task 1 的 `load_host_config`、`HOST_CONFIG_ERROR`、`HOST_*`。
- Produces: `BootstrapTestCase.write_fixture_host(hosts_root, *, name=..., node_ip=..., cluster_name=..., pod_cidr=..., service_cidr=..., swap_file=..., swap_min=..., swap_max=...) -> Path`，后续 Task 4–7 的 fixture 都用它。

- [ ] **Step 1: 加 fixture helper**

在 `BootstrapTestCase` 中 `tree_snapshot` 之前加：

```python
    HOST_TEMPLATE_DIR = ROOT / 'bootstrap/hosts/retail-test-workflow'

    def write_fixture_host(
        self,
        hosts_root: Path,
        *,
        name: str = 'retail-test-workflow',
        node_ip: str = '10.93.1.27',
        cluster_name: str = 'engineering-platform-dev',
        pod_cidr: str = '172.21.0.0/16',
        service_cidr: str = '172.20.0.0/16',
        swap_file: str = '/swap.img',
        swap_min: int = 4000000000,
        swap_max: int = 4400000000,
    ) -> Path:
        """按 retail-test-workflow 的真实文件生成一台 fixture 主机目录。

        默认参数生成的文件与仓库文件逐字节相同，pins 因而也相同。"""
        host_dir = hosts_root / name
        host_dir.mkdir(parents=True)
        substitutions = (
            ('10.93.1.27', node_ip),
            ('retail-test-workflow', name),
            ('engineering-platform-dev', cluster_name),
            ('172.21.0.0/16', pod_cidr),
            ('172.20.0.0/16', service_cidr),
        )
        for filename in ('kubeadm-init.yaml', 'cilium-values.yaml'):
            text = (self.HOST_TEMPLATE_DIR / filename).read_text(encoding='utf-8')
            for old, new in substitutions:
                text = text.replace(old, new)
            (host_dir / filename).write_text(text, encoding='utf-8')
        (host_dir / 'host.env').write_text(
            f'HOST_NAME={name}\n'
            f'HOST_NODE_IP={node_ip}\n'
            f'HOST_CLUSTER_NAME={cluster_name}\n'
            f'HOST_POD_CIDR={pod_cidr}\n'
            f'HOST_SERVICE_CIDR={service_cidr}\n'
            f'HOST_SWAP_FILE={swap_file}\n'
            f'HOST_SWAP_MIN_BYTES={swap_min}\n'
            f'HOST_SWAP_MAX_BYTES={swap_max}\n',
            encoding='utf-8',
        )
        (host_dir / 'pins.sha256').write_text(
            ''.join(
                hashlib.sha256((host_dir / filename).read_bytes()).hexdigest()
                + f'  {filename}\n'
                for filename in ('kubeadm-init.yaml', 'cilium-values.yaml')
            ),
            encoding='utf-8',
        )
        for entry in host_dir.iterdir():
            entry.chmod(0o644)
        host_dir.chmod(0o755)
        hosts_root.chmod(0o755)
        return host_dir
```

- [ ] **Step 2: PreflightTest fixture 接入 seam**

`PreflightTest.make_environment` 中在 `fake_bin.mkdir()` 之后加：

```python
        hosts_root = directory / 'hosts'
        hosts_root.mkdir()
        self.write_fixture_host(hosts_root)
```

环境字典加 `'BOOTSTRAP_TEST_HOSTS_DIR': str(hosts_root),`。fake `stat` 改为支持属主漂移：

```python
        self.write_executable(
            fake_bin / 'stat',
            '''
            #!/bin/sh
            if [ "$1" = "-fc" ]; then
              printf '%s\n' "${FAKE_CGROUP_FS:-cgroup2fs}"
              exit 0
            fi
            last=
            for last do :; done
            if [ -n "${FAKE_STAT_OWNER_DRIFT:-}" ] && [ "$last" = "$FAKE_STAT_OWNER_DRIFT" ] &&
               { [ "$2" = '%u:%g' ] || [ "$2" = '%u' ]; }; then
              printf '65534:65534\n'
              exit 0
            fi
            exec /usr/bin/stat "$@"
            ''',
        )
```

- [ ] **Step 3: 写 RED**

改写 `test_stops_on_wrong_hostname`：

```python
    def test_stops_on_wrong_hostname(self) -> None:
        result, _ = self.run_preflight(FAKE_HOSTNAME='wrong-host')

        self.assertEqual(result.returncode, 10)
        self.assertIn('RESULT=STOP_PRECONDITION', result.stdout)
        self.assertIn('REASON=host-not-registered', result.stdout)
```

在其后新增：

```python
    def test_host_directory_contract_is_fail_closed(self) -> None:
        cases = (
            'directory-symlink', 'directory-mode', 'directory-owner',
            'env-symlink', 'env-mode', 'env-owner', 'extra-file',
            'missing-file', 'pins-mode', 'name-mismatch', 'invalid-env',
        )
        for case in cases:
            with self.subTest(case=case):
                environment, host = self.make_environment()
                hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
                host_dir = hosts_root / 'retail-test-workflow'
                expected = 'host-config-unsafe'
                if case == 'directory-symlink':
                    real = hosts_root / 'real'
                    host_dir.rename(real)
                    host_dir.symlink_to(real)
                elif case == 'directory-mode':
                    host_dir.chmod(0o777)
                elif case == 'directory-owner':
                    environment['FAKE_STAT_OWNER_DRIFT'] = str(host_dir)
                elif case == 'env-symlink':
                    (host_dir / 'host.env').rename(hosts_root / 'outside.env')
                    (host_dir / 'host.env').symlink_to(hosts_root / 'outside.env')
                elif case == 'env-mode':
                    (host_dir / 'host.env').chmod(0o666)
                elif case == 'env-owner':
                    environment['FAKE_STAT_OWNER_DRIFT'] = str(host_dir / 'host.env')
                elif case == 'extra-file':
                    (host_dir / 'README.md').write_text('x\n', encoding='utf-8')
                elif case == 'missing-file':
                    (host_dir / 'pins.sha256').unlink()
                elif case == 'pins-mode':
                    (host_dir / 'pins.sha256').chmod(0o600)
                elif case == 'name-mismatch':
                    expected = 'host-config-name-mismatch'
                    env = host_dir / 'host.env'
                    env.write_text(
                        env.read_text(encoding='utf-8').replace(
                            'HOST_NAME=retail-test-workflow', 'HOST_NAME=other-host'
                        ),
                        encoding='utf-8',
                    )
                else:
                    expected = 'host-config-invalid'
                    env = host_dir / 'host.env'
                    env.write_text(
                        env.read_text(encoding='utf-8').replace(
                            'HOST_NODE_IP=10.93.1.27', 'HOST_NODE_IP=10.93.1.256'
                        ),
                        encoding='utf-8',
                    )

                result = self.run_command(
                    ['/bin/bash', str(PREFLIGHT), '--check'], env=environment
                )

                self.assertEqual(result.returncode, 10, result.stdout + result.stderr)
                self.assertIn('RESULT=STOP_PRECONDITION', result.stdout)
                self.assertIn(f'REASON={expected}', result.stdout)

    def test_swap_contract_comes_from_host_env(self) -> None:
        """swap 文件名与区间必须来自 host.env，而不是脚本字面量。"""
        environment, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        shutil.rmtree(hosts_root / 'retail-test-workflow')
        self.write_fixture_host(hosts_root, swap_min=1000, swap_max=2000)

        result = self.run_command(['/bin/bash', str(PREFLIGHT), '--check'], env=environment)

        self.assertEqual(result.returncode, 10, result.stdout)
        self.assertIn('REASON=swap-size-mismatch', result.stdout)
```

- [ ] **Step 4: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.PreflightTest.test_stops_on_wrong_hostname scripts.test_bootstrap.PreflightTest.test_host_directory_contract_is_fail_closed scripts.test_bootstrap.PreflightTest.test_swap_contract_comes_from_host_env 2>&1 | tail -8`
Expected: 三个 FAIL（现在返回 `STOP_HOST_IDENTITY hostname-mismatch` 或直接通过）。

- [ ] **Step 5: 改 `00-preflight.sh`**

第 9–17 行：

```bash
source "${script_dir}/lib/common.sh"
# shellcheck disable=SC1091
source "${script_dir}/lib/host-config.sh"
# shellcheck disable=SC1091
source "${script_dir}/lib/os-release.sh"

# PHASE 由公共 evidence helper 间接读取。
# shellcheck disable=SC2034
readonly PHASE=preflight
readonly CLEANUP_EVIDENCE_SHA256=a68a3d2ff340bcdcb4265853107a3a2c22a9f7328728473d81d9be2d1486e635
```

（删除 `EXPECTED_HOSTNAME`、`EXPECTED_NODE_IP`、`SERVICE_CIDR`、`POD_CIDR` 四个 readonly。）

第 65–69 行的 hostname 段改为：

```bash
load_host_config || complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE
log_evidence "HOSTNAME=${HOST_NAME}"
```

第 94–97 行：`awk -v ip="$EXPECTED_NODE_IP"` → `awk -v ip="$HOST_NODE_IP"`；`log_evidence "NODE_IP=${EXPECTED_NODE_IP}"` → `log_evidence "NODE_IP=${HOST_NODE_IP}"`。

第 99–113 行 swap 段：

```bash
swap_file=$(host_path "$HOST_SWAP_FILE")
if [[ ! -f "$swap_file" || -L "$swap_file" ]]; then
  complete STOP_SWAP swap-file-missing "$EXIT_PRECONDITION" NONE
fi
swap_output=$(swapon --show=NAME,SIZE --noheadings --raw --bytes 2>/dev/null) || complete STOP_SWAP swapon-unreadable "$EXIT_PRECONDITION" NONE
swap_lines=$(printf '%s\n' "$swap_output" | awk 'NF {count++} END {print count+0}')
swap_name=$(printf '%s\n' "$swap_output" | awk 'NF {print $1}')
swap_bytes=$(printf '%s\n' "$swap_output" | awk 'NF {print $2}')
if [[ "$swap_lines" != 1 || "$swap_name" != "$HOST_SWAP_FILE" || ! "$swap_bytes" =~ ^[0-9]+$ ]]; then
  complete STOP_SWAP swap-layout-mismatch "$EXIT_PRECONDITION" NONE
fi
if (( swap_bytes < HOST_SWAP_MIN_BYTES || swap_bytes > HOST_SWAP_MAX_BYTES )); then
  complete STOP_SWAP swap-size-mismatch "$EXIT_PRECONDITION" NONE
fi
log_evidence "SWAP=${HOST_SWAP_FILE}"
```

第 166–167 行：`--service-cidr "$HOST_SERVICE_CIDR"`、`--pod-cidr "$HOST_POD_CIDR"`。第 186–187 行：`log_evidence "SERVICE_CIDR=${HOST_SERVICE_CIDR}"`、`log_evidence "POD_CIDR=${HOST_POD_CIDR}"`。

- [ ] **Step 6: 运行 GREEN**

Run: `python3 -m unittest scripts.test_bootstrap.PreflightTest 2>&1 | tail -4 && shellcheck scripts/bootstrap/00-preflight.sh && ./scripts/validate-fast.sh 2>&1 | tail -3`
Expected: `PreflightTest` 全部 `OK`；shellcheck 无输出；`validate-fast` `OK`。

- [ ] **Step 7: Commit**

```bash
git add scripts/bootstrap/00-preflight.sh scripts/test_bootstrap.py
git commit -m "feat(bootstrap): read preflight host identity from host config"
```

---

### Task 4: Stage 50 参数化

**Files:**
- Modify: `scripts/bootstrap/50-kubeadm-init.sh:34-51,272-277,285-286,300,303-312,319,526,543,613-623`
- Modify: `scripts/test_bootstrap.py`（`KubeadmInitTest.make_environment` 接入 seam；hostname-mismatch 用例改 reason）

**Interfaces:**
- Consumes: Task 1 `load_host_config`、`host_pin`、`HOST_*`、`HOST_CONFIG_DIR`；Task 3 `write_fixture_host`。
- Produces: 无新接口。

- [ ] **Step 1: fixture 接入 seam**

`KubeadmInitTest.make_environment` 中，在 `config_source` 写入之后加：

```python
        hosts_root = directory / 'hosts'
        hosts_root.mkdir()
        self.write_fixture_host(hosts_root)
```

环境字典加 `'BOOTSTRAP_TEST_HOSTS_DIR': str(hosts_root),`。

- [ ] **Step 2: 写 RED**

找到断言 `hostname-mismatch` 的 KubeadmInitTest 用例（`grep -n "hostname-mismatch" scripts/test_bootstrap.py`），把期望改为 `REASON=host-not-registered`。新增：

```python
    def test_config_pin_and_host_values_come_from_host_directory(self) -> None:
        """CONFIG digest 与主机值必须来自 host 目录，而不是脚本字面量。"""
        environment, host, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        pins = hosts_root / 'retail-test-workflow' / 'pins.sha256'
        pins.write_text(
            pins.read_text(encoding='utf-8').replace('e37b38f1', '00000000', 1),
            encoding='utf-8',
        )

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 20, result.stdout)
        self.assertIn('RESULT=STOP_SUPPLY_CHAIN_MISMATCH', result.stdout)

    def test_pins_shape_drift_is_fail_closed(self) -> None:
        for name, mutate in (
            ('reversed', lambda t: ''.join(reversed(t.splitlines(keepends=True)))),
            ('third-line', lambda t: t + 'x\n'),
            ('no-newline', lambda t: t.rstrip('\n')),
        ):
            with self.subTest(case=name):
                environment, _, _ = self.make_environment()
                pins = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR']) / 'retail-test-workflow/pins.sha256'
                pins.write_text(mutate(pins.read_text(encoding='utf-8')), encoding='utf-8')

                result = self.run_stage(environment)

                self.assertEqual(result.returncode, 20, result.stdout)
                self.assertIn('REASON=host-pins-invalid', result.stdout)
```

- [ ] **Step 3: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.KubeadmInitTest.test_config_pin_and_host_values_come_from_host_directory scripts.test_bootstrap.KubeadmInitTest.test_pins_shape_drift_is_fail_closed 2>&1 | tail -6`
Expected: FAIL（现在忽略 pins，返回 `PASS_KUBEADM_CHECK`）。

- [ ] **Step 4: 改 `50-kubeadm-init.sh`**

source 区（第 34 行后）加：

```bash
# shellcheck disable=SC1091
source "${script_dir}/lib/host-config.sh"
```

删除第 45–49 行 `EXPECTED_HOSTNAME`、`EXPECTED_NODE_IP`、`SERVICE_CIDR`、`POD_CIDR`、`CONFIG_SHA256` 与第 51 行 `CONFIG_FILE` 五个 readonly。

在 `for required_command in ...; done` 循环（约第 532–534 行）之后加：

```bash
load_host_config || complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE
CONFIG_SHA256=$(host_pin kubeadm-init.yaml) ||
  complete STOP_SUPPLY_CHAIN_MISMATCH host-pins-invalid "$EXIT_SUPPLY_CHAIN" NONE
readonly CONFIG_SHA256
readonly CONFIG_FILE="${HOST_CONFIG_DIR}/kubeadm-init.yaml"
```

> 顺序固定为：`parse_mode` → `require_root` → `for required_command`（含 `hostname`）→ `load_host_config` → `host_pin`。放在 `required_command` 循环之后，是为了 `hostname` 缺失时仍得到明确的 `missing-command-hostname`。

`host_and_dependency_gates` 中：
- 删除第 285–286 行的 `actual_hostname=$(hostname ...)` 与 hostname-mismatch 两行（loader 已完成）。
- 第 300 行 `awk -v ip="$EXPECTED_NODE_IP"` → `awk -v ip="$HOST_NODE_IP"`。
- 第 303–312 行 swap：`host_path /swap.img` → `host_path "$HOST_SWAP_FILE"`；`"$swap_name" == /swap.img` → `"$swap_name" == "$HOST_SWAP_FILE"`；`swap_bytes >= 4000000000 && swap_bytes <= 4400000000` → `swap_bytes >= HOST_SWAP_MIN_BYTES && swap_bytes <= HOST_SWAP_MAX_BYTES`。
- 第 319 行 `cidr_arguments=(--service-cidr "$HOST_SERVICE_CIDR" --pod-cidr "$HOST_POD_CIDR")`。
- 第 526 行 `grep -Fq 'IP Address:10.93.1.27'` → `grep -Fq "IP Address:${HOST_NODE_IP}"`。
- 第 613–623 行 evidence：`log_evidence NODE="$HOST_NAME"`、`log_evidence CONTROL_PLANE_ENDPOINT="${HOST_NODE_IP}:6443"`、`log_evidence CERTIFICATE_SAN_IP="$HOST_NODE_IP"`，并在 `log_evidence CONFIG_SHA256=` 之前加 `log_evidence "HOST_NAME=${HOST_NAME}"` 与 `log_evidence "HOST_NODE_IP=${HOST_NODE_IP}"`。

- [ ] **Step 5: 运行 GREEN**

Run: `python3 -m unittest scripts.test_bootstrap.KubeadmInitTest.test_config_pin_and_host_values_come_from_host_directory scripts.test_bootstrap.KubeadmInitTest.test_pins_shape_drift_is_fail_closed scripts.test_bootstrap.KubeadmInitTest.test_check_accepts_declared_client_doc_exclusions 2>&1 | tail -4 && shellcheck scripts/bootstrap/50-kubeadm-init.sh`
Expected: `OK`；shellcheck 无输出。

- [ ] **Step 6: 跑 Stage 50 完整套件（后台，约 40 分钟）**

Run: `python3 -m unittest -v scripts.test_bootstrap.KubeadmInitTest 2>&1 | tail -5`
Expected: `OK`。

- [ ] **Step 7: Commit**

```bash
git add scripts/bootstrap/50-kubeadm-init.sh scripts/test_bootstrap.py
git commit -m "feat(bootstrap): read kubeadm host identity and config pin from host directory"
```

---

### Task 5: Stage 60 参数化（含 `lib/admin-conf.sh` 派生）

**Files:**
- Modify: `scripts/bootstrap/60-install-cilium.sh:60-79,153-192,276-281,935-946,1084-1101`
- Modify: `scripts/bootstrap/lib/admin-conf.sh:1-11,100-106`
- Modify: `scripts/test_bootstrap.py`（`CiliumInstallTest.make_environment` 加 `hostname` fake 与 seam；`test_admin_conf_contract_tracks_pinned_cluster_name` 改写）

**Interfaces:**
- Consumes: `load_host_config`、`host_pin cilium-values.yaml`、`HOST_NODE_IP`、`HOST_CLUSTER_NAME`、`HOST_CONFIG_DIR`、`write_fixture_host`。
- Produces: `admin_conf_json_is_exact` 改为读取 `HOST_CLUSTER_NAME` 与 `HOST_NODE_IP`（Stage 90 复用）。

- [ ] **Step 1: fixture 接入**

`CiliumInstallTest.make_environment` 中在 `self.write_executable(fake_bin / 'id', ...)` 之后加：

```python
        self.write_executable(
            fake_bin / 'hostname',
            '#!/bin/sh\nprintf "%s\\n" "${FAKE_HOSTNAME:-retail-test-workflow}"\n',
        )
        hosts_root = directory / 'hosts'
        hosts_root.mkdir()
        self.write_fixture_host(hosts_root)
```

环境字典加 `'BOOTSTRAP_TEST_HOSTS_DIR': str(hosts_root),`。

- [ ] **Step 2: 写 RED**

把 `test_admin_conf_contract_tracks_pinned_cluster_name` 整体替换为：

```python
    def test_admin_conf_contract_is_derived_from_host_config(self) -> None:
        """admin.conf 合同来自 host.env，lib 与 stage 内不得再写死名字。"""
        library = (ROOT / 'scripts/bootstrap/lib/admin-conf.sh').read_text(encoding='utf-8')
        for literal in ('engineering-platform-dev', '10.93.1.27', 'ADMIN_CONF_CLUSTER_NAME='):
            self.assertNotIn(literal, library)

        environment, _, _, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        shutil.rmtree(hosts_root / 'retail-test-workflow')
        self.write_fixture_host(hosts_root, cluster_name='fixture-cluster')

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 30, result.stdout)
        self.assertIn('REASON=admin-conf-content-or-structure-drift', result.stdout)

    def test_values_semantics_and_endpoint_come_from_host_env(self) -> None:
        cases = ('pin', 'semantics', 'endpoint')
        for case in cases:
            with self.subTest(case=case):
                environment, _, _, _ = self.make_environment()
                hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
                retail_pins = (hosts_root / 'retail-test-workflow/pins.sha256').read_text(encoding='utf-8')
                if case == 'pin':
                    pins = hosts_root / 'retail-test-workflow/pins.sha256'
                    pins.write_text(retail_pins.replace('105ca75f', '00000000', 1), encoding='utf-8')
                    expected_code, expected_reason = 20, 'staged-input-contract-drift'
                elif case == 'semantics':
                    # host.env 说 IP 是 .99，但 values 文件与 pins 仍是 retail 的：
                    # digest 通过，形状比对必须按 .99 拒绝。
                    shutil.rmtree(hosts_root / 'retail-test-workflow')
                    host_dir = self.write_fixture_host(hosts_root, node_ip='10.93.1.99')
                    (host_dir / 'pins.sha256').write_text(retail_pins, encoding='utf-8')
                    expected_code, expected_reason = 20, 'staged-input-contract-drift'
                else:
                    # values 与 pins 一致地换成 .99，staged inputs 通过；
                    # admin.conf fixture 仍是 .27 → 谓词按 .99 拒绝。
                    shutil.rmtree(hosts_root / 'retail-test-workflow')
                    host_dir = self.write_fixture_host(hosts_root, node_ip='10.93.1.99')
                    environment['BOOTSTRAP_TEST_VALUES_FILE'] = str(host_dir / 'cilium-values.yaml')
                    expected_code, expected_reason = 30, 'admin-conf-content-or-structure-drift'

                result = self.run_stage(environment)

                self.assertEqual(result.returncode, expected_code, result.stdout)
                self.assertIn(f'REASON={expected_reason}', result.stdout)
```

> `endpoint` 子用例把 `BOOTSTRAP_TEST_VALUES_FILE` 指向 fixture 主机目录里的 `cilium-values.yaml`——其 basename 不是 `values.yaml`，CiliumInstallTest 的 fake `sha256sum` 会退回真实 `shasum`，因此 digest 与 fixture pins 一致；到 `capture_admin_conf` 时 admin.conf fixture 的 server 仍是 `.27` 而谓词期望 `.99`，证明 endpoint 派生已生效。

- [ ] **Step 3: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.CiliumInstallTest.test_admin_conf_contract_is_derived_from_host_config scripts.test_bootstrap.CiliumInstallTest.test_values_semantics_and_endpoint_come_from_host_env 2>&1 | tail -8`
Expected: FAIL/ERROR（lib 仍含字面量；pins/endpoint 未接入）。

- [ ] **Step 4: 改 `lib/admin-conf.sh`**

删除第 3–10 行的四个常量与 readonly；把 python 段末尾的实参改为：

```bash
' "$HOST_CLUSTER_NAME" "kubernetes-admin@${HOST_CLUSTER_NAME}" \
    kubernetes-admin "https://${HOST_NODE_IP}:6443" >/dev/null 2>&1
```

文件头注释改为：

```bash
# admin.conf 的 cluster/context 名由 kubeadm 依据 host.env 的 HOST_CLUSTER_NAME 生成，
# server 由 HOST_NODE_IP 派生；调用方须先完成 load_host_config。
```

- [ ] **Step 5: 改 `60-install-cilium.sh`**

第 60–66 行 source 顺序改为 `common.sh` → `host-config.sh` → `admin-conf.sh` → `dpkg-package-verification.sh`（admin-conf 不再在 source 时依赖常量，顺序只为可读）。

删除第 78–79 行 `VALUES_SHA256`、`VALUES_FILE`。

`values_semantics_are_exact` 改为把 IP 作为实参传入：

```bash
values_semantics_are_exact() {
  python_isolated - "$1" "$HOST_NODE_IP" <<'PY' >/dev/null 2>&1
import pathlib
import sys

node_ip = sys.argv[2]
expected = f"""kubeProxyReplacement: true
k8sServiceHost: {node_ip}
k8sServicePort: 6443
```

（其余行原样保留，注意 f-string 内已有的 `{`/`}` 只出现在 `sha256:` digest 之外，无需转义；末尾 `"""` 后逻辑不变。）

`api_endpoint_is_exact`：`[[ "$output" == "https://${HOST_NODE_IP}:6443" ]]`。

`helm_values_json_is_exact`（第 935 行起）改为 `python_isolated -c '...' "$HOST_NODE_IP"` 并在脚本内 `expected["k8sServiceHost"] = sys.argv[1]`：把 `"k8sServiceHost": "10.93.1.27",` 改为 `"k8sServiceHost": sys.argv[1],`，调用处末尾追加实参 `"$HOST_NODE_IP"`。

主流程：`for required_command in ...` 列表加入 `hostname`；在该循环之后、`staged_root=` 之前加：

```bash
load_host_config || complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE
VALUES_SHA256=$(host_pin cilium-values.yaml) ||
  complete STOP_SUPPLY_CHAIN_MISMATCH host-pins-invalid "$EXIT_SUPPLY_CHAIN" NONE
readonly VALUES_SHA256
readonly VALUES_FILE="${HOST_CONFIG_DIR}/cilium-values.yaml"
```

evidence（`PASS_CILIUM_INSTALLED` 之前的 `log_evidence` 块）加 `log_evidence "HOST_NAME=${HOST_NAME}"`、`log_evidence "HOST_NODE_IP=${HOST_NODE_IP}"`。

- [ ] **Step 6: 运行 GREEN**

Run: `python3 -m unittest scripts.test_bootstrap.CiliumInstallTest.test_admin_conf_contract_is_derived_from_host_config scripts.test_bootstrap.CiliumInstallTest.test_values_semantics_and_endpoint_come_from_host_env scripts.test_bootstrap.CiliumInstallTest.test_check_is_zero_write_for_clean_apply_required_state scripts.test_bootstrap.CiliumInstallTest.test_rejects_unsafe_admin_config_or_source_race 2>&1 | tail -4 && shellcheck scripts/bootstrap/60-install-cilium.sh scripts/bootstrap/lib/admin-conf.sh`
Expected: `OK`；shellcheck 无输出。

- [ ] **Step 7: 跑 Stage 60 完整套件（后台）**

Run: `python3 -m unittest -v scripts.test_bootstrap.CiliumInstallTest 2>&1 | tail -5`
Expected: `OK`。

- [ ] **Step 8: Commit**

```bash
git add scripts/bootstrap/60-install-cilium.sh scripts/bootstrap/lib/admin-conf.sh scripts/test_bootstrap.py
git commit -m "feat(bootstrap): derive cilium stage host contracts from host config"
```

---

### Task 6: Stage 90 参数化

**Files:**
- Modify: `scripts/bootstrap/90-verify.sh:63-75,423-428,448-458,876-878,888-894,899,955,980-984,1003,1046-1063`
- Modify: `scripts/test_bootstrap.py`（`FinalVerifyTest.make_environment` 加 `hostname` fake 与 seam；新增两条流通用例）

**Interfaces:**
- Consumes: `load_host_config`、`HOST_*`、`admin_conf_json_is_exact`（Task 5 已派生）、`write_fixture_host`。

- [ ] **Step 1: fixture 接入**

`FinalVerifyTest.make_environment` 中在 `self.write_executable(fake_bin / 'id', ...)` 之后加：

```python
        self.write_executable(
            fake_bin / 'hostname',
            '#!/bin/sh\nprintf "%s\\n" "${FAKE_HOSTNAME:-retail-test-workflow}"\n',
        )
        hosts_root = directory / 'hosts'
        hosts_root.mkdir()
        self.write_fixture_host(hosts_root)
```

环境字典加 `'BOOTSTRAP_TEST_HOSTS_DIR': str(hosts_root),`。

- [ ] **Step 2: 写 RED**

在 `test_rejects_package_hold_binary_or_cni_drift` 之前加：

```python
    def test_verify_stops_on_unregistered_host(self) -> None:
        environment, host, _ = self.make_environment()
        environment['FAKE_HOSTNAME'] = 'wrong-host'

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 10, result.stdout)
        self.assertIn('RESULT=STOP_PRECONDITION', result.stdout)
        self.assertIn('REASON=host-not-registered', result.stdout)
        self.assertEqual(
            list((host / 'root/dev-infra-evidence').glob('14-verify-*.txt')), []
        )

    def test_node_csr_and_swap_contracts_come_from_host_env(self) -> None:
        """把 host.env 的值改掉后，对应 gate 必须按新值拒绝原 fixture。"""
        cases = (
            ('node-name', {'name': 'fixture-host-b'}, 'node-readiness-or-address-drift'),
            ('node-ip', {'node_ip': '10.93.1.99'}, 'admin-conf-content-or-structure-drift'),
            ('swap-range', {'swap_min': 1000, 'swap_max': 2000}, 'swap-contract-drift'),
        )
        for case, overrides, expected in cases:
            with self.subTest(case=case):
                environment, host, _ = self.make_environment()
                hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
                shutil.rmtree(hosts_root / 'retail-test-workflow')
                name = overrides.get('name', 'retail-test-workflow')
                self.write_fixture_host(hosts_root, **overrides)
                environment['FAKE_HOSTNAME'] = name

                result = self.run_stage(environment)

                self.assert_stops_without_evidence(result, host)
                self.assertIn(f'REASON={expected}', result.stdout)
```

> `node-name` 子用例把 host 改名为 `fixture-host-b`（hostname fake 同步），cluster 名与 IP 不变，admin.conf 谓词通过；90 期望 node 名为 `fixture-host-b`，而 fixture 的 node JSON 仍是 `retail-test-workflow` → 在 `node_is_ready` 停。`node-ip` 子用例只改 IP：90 的 gate 顺序里 `capture_admin_conf` 先于 `api_is_exact_and_ready`，admin.conf fixture 的 server 仍是 `.27` 而谓词期望 `.99` → 停在 `admin-conf-content-or-structure-drift`（`STOP_VERIFY_FAILED`，退出码 50），这正是 admin.conf 谓词已按 `HOST_NODE_IP` 派生的证据。`swap-range` 子用例：fake `swapon` 输出的字节数落在 1000–2000 之外 → `swap-contract-drift`。

- [ ] **Step 3: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.FinalVerifyTest.test_verify_stops_on_unregistered_host scripts.test_bootstrap.FinalVerifyTest.test_node_csr_and_swap_contracts_come_from_host_env 2>&1 | tail -8`
Expected: FAIL（90 尚未加载 host config，`wrong-host` 也能通过；改值后仍按字面量判定）。

- [ ] **Step 4: 改 `90-verify.sh`**

source 区加 `host-config.sh`（放在 `common.sh` 之后、`admin-conf.sh` 之前）；删除第 74–75 行 `EXPECTED_NODE`、`EXPECTED_NODE_IP`。

`api_is_exact_and_ready`：`[[ "$output" == "https://${HOST_NODE_IP}:6443" ]]`。

`helm_values_json_is_exact`（第 448 行起）：同 Task 5 —— `"k8sServiceHost": sys.argv[1],` 并追加实参 `"$HOST_NODE_IP"`。

`node_is_ready`（第 858 行起）：`python_isolated -c '...' "$HOST_NAME" "$HOST_NODE_IP"`，脚本内 `metadata.get("name") == sys.argv[1]`、`internal == [sys.argv[2]]`。

`swap_is_exact`：`safe_file "$(host_path "$HOST_SWAP_FILE")" 600`；`"$name" == "$HOST_SWAP_FILE"`；`(( bytes >= HOST_SWAP_MIN_BYTES && bytes <= HOST_SWAP_MAX_BYTES ))`。

`kubelet_swap_config_is_exact`：`--raw="/api/v1/nodes/${HOST_NAME}/proxy/configz"`。

`csr_summaries_are_safe`：
- 第一个 python 段改为 `python_isolated -c '...' "$HOST_NAME"`，`requester != "system:node:" + sys.argv[1]`。
- SAN 段改为 `python_isolated -c '...' "$HOST_NAME" "$HOST_NODE_IP"`，
  `if sorted(values) != ["DNS:" + sys.argv[1], "IP Address:" + sys.argv[2]]: raise SystemExit(1)`，
  `print("DNS:" + sys.argv[1] + ",IP:" + sys.argv[2])`；外层 `[[ "$san_marker" == "DNS:${HOST_NAME},IP:${HOST_NODE_IP}" ]]`。

主流程：`for required_command in awk cmp date dpkg dpkg-query find grep hostname id sed sort stat swapon`；循环后加 `load_host_config || complete STOP_PRECONDITION "$HOST_CONFIG_ERROR" "$EXIT_PRECONDITION" NONE`。

evidence：`API_ENDPOINT="${HOST_NODE_IP}:6443"`、`NODE_NAME="$HOST_NAME"`、`NODE_INTERNAL_IP="$HOST_NODE_IP"`、`SWAP_DEVICE="$HOST_SWAP_FILE"`、`SWAP_BYTES="${HOST_SWAP_MIN_BYTES}-${HOST_SWAP_MAX_BYTES}"`；`KUBERNETES_VERSION` 之前加 `HOST_NAME=`/`HOST_NODE_IP=` 两行。

- [ ] **Step 5: 运行 GREEN**

Run: `python3 -m unittest scripts.test_bootstrap.FinalVerifyTest.test_verify_stops_on_unregistered_host scripts.test_bootstrap.FinalVerifyTest.test_node_csr_and_swap_contracts_come_from_host_env scripts.test_bootstrap.FinalVerifyTest.test_check_succeeds_read_only_with_allowlisted_evidence scripts.test_bootstrap.FinalVerifyTest.test_csr_summary_is_strict_and_never_leaks_request_or_certificate 2>&1 | tail -4 && shellcheck scripts/bootstrap/90-verify.sh`
Expected: `OK`；shellcheck 无输出。

- [ ] **Step 6: 跑 Stage 90 完整套件（后台）**

Run: `python3 -m unittest -v scripts.test_bootstrap.FinalVerifyTest 2>&1 | tail -5`
Expected: `OK`。

- [ ] **Step 7: Commit**

```bash
git add scripts/bootstrap/90-verify.sh scripts/test_bootstrap.py
git commit -m "feat(bootstrap): derive final verify host contracts from host config"
```

---

### Task 7: 结构约束测试与 `fixture-host-b` 全链路流通

**Files:**
- Modify: `scripts/test_bootstrap.py`（`HostConfigTest` 增加结构约束用例；`PreflightTest`、`KubeadmInitTest`、`CiliumInstallTest`、`FinalVerifyTest` 各增加一条 host-b 流通用例）
- Modify: `scripts/bootstrap/*.sh`（若结构约束测试发现残留字面量，在本任务内清理）

**Interfaces:**
- Consumes: Task 1–6 全部。
- Produces: 无。

- [ ] **Step 1: 写结构约束 RED**

在 `HostConfigTest` 末尾加：

```python
    def test_stage_scripts_contain_no_host_literals(self) -> None:
        """主机身份只能出现在 bootstrap/hosts/ 与测试文件里。"""
        forbidden = (
            '10.93.1.27', 'retail-test-workflow', 'engineering-platform-dev',
            'CONFIG_SHA256=e', 'VALUES_SHA256=1', 'EXPECTED_HOSTNAME=',
            'EXPECTED_NODE_IP=', 'EXPECTED_NODE=', '/swap.img',
            '4000000000', '4400000000', '172.20.0.0/16', '172.21.0.0/16',
        )
        scripts = sorted(
            list((ROOT / 'scripts/bootstrap').glob('*.sh'))
            + list((ROOT / 'scripts/bootstrap/lib').glob('*.sh'))
            + [ROOT / 'scripts/bootstrap/check_cidrs.py']
        )
        for script in scripts:
            text = script.read_text(encoding='utf-8')
            for literal in forbidden:
                with self.subTest(script=script.name, literal=literal):
                    self.assertNotIn(literal, text)

    def test_only_host_directories_carry_host_identity(self) -> None:
        for path in sorted((ROOT / 'bootstrap').rglob('*')):
            relative = path.relative_to(ROOT / 'bootstrap')
            if not path.is_file() or relative.parts[0] == 'hosts':
                continue
            with self.subTest(path=str(relative)):
                self.assertNotIn('10.93.1.27', path.read_text(encoding='utf-8', errors='ignore'))
```

- [ ] **Step 2: 运行 RED，清理残留**

Run: `python3 -m unittest scripts.test_bootstrap.HostConfigTest.test_stage_scripts_contain_no_host_literals 2>&1 | grep -E "FAIL|OK|literal="`
Expected: 若 Task 3–6 有遗漏，会逐条列出 `script=... literal=...`；按列表清理（每处都改为对应 `HOST_*` 派生值），直至通过。若一次通过，说明前面任务已清理干净。

- [ ] **Step 3: 写 host-b 流通 RED**

`PreflightTest`：

```python
    def test_registered_second_host_flows_through_preflight(self) -> None:
        environment, host = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        self.write_fixture_host(
            hosts_root, name='fixture-host-b', node_ip='10.200.0.2',
            cluster_name='fixture-b', pod_cidr='10.244.0.0/16',
            service_cidr='10.96.0.0/12', swap_file='/swap.img',
            swap_min=4000000000, swap_max=4400000000,
        )
        environment['FAKE_HOSTNAME'] = 'fixture-host-b'
        environment['FAKE_NODE_IP'] = '10.200.0.2'

        result = self.run_command(['/bin/bash', str(PREFLIGHT), '--check'], env=environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT=PASS_PREFLIGHT', result.stdout)
        evidence = self.evidence_text(host)
        self.assertIn('HOSTNAME=fixture-host-b', evidence)
        self.assertIn('NODE_IP=10.200.0.2', evidence)
        self.assertIn('POD_CIDR=10.244.0.0/16', evidence)
```

> 若 PreflightTest 的 fake `ip` 尚不读 `FAKE_NODE_IP`（检查 `make_environment` 中 `fake_bin / 'ip'`），把它输出的地址行改为 `printf '2: ens160    inet %s/24 ...' "${FAKE_NODE_IP:-10.93.1.27}"`，路由行同理；只改默认值来源，不改行格式。

`KubeadmInitTest`：

```python
    def test_registered_second_host_flows_through_kubeadm_check(self) -> None:
        environment, _, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        host_dir = self.write_fixture_host(
            hosts_root, name='fixture-host-b', node_ip='10.200.0.2',
            cluster_name='fixture-b', pod_cidr='10.244.0.0/16',
            service_cidr='10.96.0.0/12',
        )
        environment['FAKE_HOSTNAME'] = 'fixture-host-b'
        environment['FAKE_NODE_IP'] = '10.200.0.2'
        environment['BOOTSTRAP_TEST_CONFIG_FILE'] = str(host_dir / 'kubeadm-init.yaml')

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT=PASS_KUBEADM_CHECK', result.stdout)
```

> KubeadmInitTest 的 fake `ip`/`swapon`/CIDR gate 若写死了 `10.93.1.27`，同样改为读 `FAKE_NODE_IP` 默认 `10.93.1.27`；`FAKE_CONFIG_SOURCE` 若被 fake `kubeadm` 用来比对文件内容，也指向 `host_dir / 'kubeadm-init.yaml'`。

`CiliumInstallTest`：

```python
    def test_registered_second_host_flows_through_cilium_check(self) -> None:
        environment, _, _, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        host_dir = self.write_fixture_host(
            hosts_root, name='fixture-host-b', node_ip='10.200.0.2',
            cluster_name='fixture-b',
        )
        environment['FAKE_HOSTNAME'] = 'fixture-host-b'
        environment['BOOTSTRAP_TEST_VALUES_FILE'] = str(host_dir / 'cilium-values.yaml')
        environment['FAKE_API_ENDPOINT'] = 'https://10.200.0.2:6443'
        payload = self.admin_config_object()
        payload['clusters'][0]['name'] = 'fixture-b'
        payload['clusters'][0]['cluster']['server'] = 'https://10.200.0.2:6443'
        payload['contexts'][0]['name'] = 'kubernetes-admin@fixture-b'
        payload['contexts'][0]['context']['cluster'] = 'fixture-b'
        payload['current-context'] = 'kubernetes-admin@fixture-b'
        environment['FAKE_ADMIN_VIEW_JSON'] = json.dumps(payload)

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT=PASS_CILIUM_CHECK', result.stdout)
```

`FinalVerifyTest`：

```python
    def test_registered_second_host_flows_through_verify(self) -> None:
        environment, _, _ = self.make_environment()
        hosts_root = Path(environment['BOOTSTRAP_TEST_HOSTS_DIR'])
        self.write_fixture_host(
            hosts_root, name='fixture-host-b', node_ip='10.200.0.2',
            cluster_name='fixture-b',
        )
        environment['FAKE_HOSTNAME'] = 'fixture-host-b'
        environment['FAKE_API_ENDPOINT'] = 'https://10.200.0.2:6443'
        environment['FAKE_NODE_NAME'] = 'fixture-host-b'
        environment['FAKE_NODE_IP'] = '10.200.0.2'
        environment['FAKE_CSR_SAN'] = 'DNS:fixture-host-b, IP Address:10.200.0.2'
        environment['FAKE_CSR_JSON'] = self.csr_json(username='system:node:fixture-host-b')
        payload = self.admin_config_object()
        payload['clusters'][0]['name'] = 'fixture-b'
        payload['clusters'][0]['cluster']['server'] = 'https://10.200.0.2:6443'
        payload['contexts'][0]['name'] = 'kubernetes-admin@fixture-b'
        payload['contexts'][0]['context']['cluster'] = 'fixture-b'
        payload['current-context'] = 'kubernetes-admin@fixture-b'
        environment['FAKE_ADMIN_VIEW_JSON'] = json.dumps(payload)

        result = self.run_stage(environment)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RESULT=PASS_BOOTSTRAP_VERIFIED', result.stdout)
        self.assertIn('NODE_NAME=fixture-host-b', result.stdout)
        self.assertIn('CSR_SAN=DNS:fixture-host-b,IP:10.200.0.2', result.stdout)
```

> FinalVerifyTest 的 fake `kubectl get nodes` 与 `helm ... get values` 若写死了 node 名/IP/`k8sServiceHost`，改为读 `FAKE_NODE_NAME`（默认 `retail-test-workflow`）、`FAKE_NODE_IP`（默认 `10.93.1.27`）；`configz` 路径匹配同理。只加默认值来源，不改输出形状。

- [ ] **Step 4: 运行 RED**

Run: `python3 -m unittest scripts.test_bootstrap.PreflightTest.test_registered_second_host_flows_through_preflight scripts.test_bootstrap.KubeadmInitTest.test_registered_second_host_flows_through_kubeadm_check scripts.test_bootstrap.CiliumInstallTest.test_registered_second_host_flows_through_cilium_check scripts.test_bootstrap.FinalVerifyTest.test_registered_second_host_flows_through_verify 2>&1 | tail -30`
Expected: 各用例在第一处仍写死 retail 值的 fake 或脚本上失败；按失败输出补 fake 的 `FAKE_*` 默认值来源（脚本侧不应再有失败——若有，说明 Task 3–6 有漏，回到对应脚本修）。

- [ ] **Step 5: 运行 GREEN 与全部相关套件**

Run: `python3 -m unittest scripts.test_bootstrap.HostConfigTest scripts.test_bootstrap.PreflightTest 2>&1 | tail -4 && ./scripts/validate-fast.sh 2>&1 | tail -3`
Expected: `OK`。

Run（后台，分开跑）：
```bash
python3 -m unittest -v scripts.test_bootstrap.KubeadmInitTest 2>&1 | tail -5
python3 -m unittest -v scripts.test_bootstrap.CiliumInstallTest scripts.test_bootstrap.FinalVerifyTest 2>&1 | tail -5
python3 -m unittest -v scripts.test_bootstrap.KubernetesInstallTest 2>&1 | tail -5
```
Expected: 三个 `OK`。

- [ ] **Step 6: Commit**

```bash
git add scripts/test_bootstrap.py scripts/bootstrap
git commit -m "test(bootstrap): prove host identity flows from host directory end to end"
```

---

### Task 8: 服务器基线对比（只读，人工）

**Files:** 无代码改动。

- [ ] **Step 1: push 并等 CI**

```bash
git push origin main
gh run list --commit "$(git rev-parse HEAD)" --limit 3
gh run watch <run-id> --exit-status
```
Expected: `validate` 全部 job `success`，含 `validation-gate`。

- [ ] **Step 2: 服务器 fast-forward 后核对新增文件权限**

服务器上 `git merge --ff-only` 由登录 shell 的 umask 决定新文件权限，`load_host_config` 要求目录 `0755`、文件 `0644`：

```bash
APPROVED_SHA=<CI 全绿的 SHA> bash <<'EOF'
set -Eeuo pipefail
repo=/opt/uni-code/engineering-platform-gitops
/usr/bin/git -C "$repo" fetch --prune origin main
[[ "$(/usr/bin/git -C "$repo" rev-parse origin/main)" == "$APPROVED_SHA" ]] || { echo STOP-sha; exit 96; }
umask 022
/usr/bin/git -C "$repo" merge --ff-only "$APPROVED_SHA"
stat -c '%a %U:%G %n' "$repo/bootstrap/hosts" "$repo/bootstrap/hosts/retail-test-workflow" "$repo"/bootstrap/hosts/retail-test-workflow/*
EOF
```
Expected: 目录 `755 root:root`，四个文件 `644 root:root`。若不符，说明 merge 时 umask 不是 022——不要手工 `chmod`（会让工作树与 git 一致性问题被掩盖），而是重跑上面带 `umask 022` 的 merge（先 `git reset --hard <上一 SHA>` 回退再 merge）。

- [ ] **Step 3: 只读 `--check` 与基线逐字对比**

```bash
/opt/uni-code/engineering-platform-gitops/scripts/bootstrap/bootstrap-all.sh --check
```
Expected: 与迁移前最后一次 `--check` 的 `STAGE_xx_RESULT=` 行逐字一致（迁移前基线在第 0 步拿到；期望 `00 PASS_PREFLIGHT`、`10–50 ALREADY_COMPLIANT`，`60` 与 `90` 的结果取决于第 0 步是否已把 cilium 装完——两次运行必须给出**相同**结果）。任何差异都是回归，停下来查，不要继续 `--apply`。

- [ ] **Step 4: 记录**

把 `--check` 回执贴回对话；不修改 runbook（子项目 3 处理文档）。

---

## Self-Review 记录

- Spec 覆盖：目录合同（T1/T2）、host.env 语法（T1）、主机选择门（T1/T3）、各 stage 合同（T3–T6）、供应链锁保留（T2/T4/T5）、validate.py 静态合同（T2）、工具（T2）、错误行为（T1/T3/T4）、测试策略 1–6（T1、T7、T7、T2、全程、T8）、迁移 8 步（T1–T8 对应）。
- 与 spec 的两处小偏差已在文中说明：`pin-host.sh` 参数为 host 目录路径而非 hostname（T2 Step 7 同步改 spec）；Stage 50/60 改读 host 目录在 T4/T5 完成而非 spec 迁移步骤 2（T2 只改路径常量，保证每步绿）。
- 类型/名称一致性：`load_host_config` / `host_env_parse` / `host_pin` / `HOST_CONFIG_ERROR` / `HOST_CONFIG_DIR` / `write_fixture_host` / `BOOTSTRAP_TEST_HOSTS_DIR` 在各任务中拼写一致。
