# Bootstrap Stage 目录拆分与判定去重设计（子项目 E）

## Context

`scripts/bootstrap/` 现有 7134 行，8 个 stage 平铺为 8 个单文件，其中 3 个超过 1100
行（`40-install-kubernetes.sh` 1199、`60-install-cilium.sh` 1315、`90-verify.sh` 1122）。

8 个 stage 内共定义 216 个函数，其中跨 stage 同名的有 23 个：

| 形态 | 数量 | 例子 |
| --- | --- | --- |
| 各副本字节一致 | 10 | `path_mode` `path_owner` `path_size` `tar_safe` `helm_run` |
| 同名不同体 | 13 | `helm_cluster_run` `validate_archive` `owned_by_expected` `kubectl_run` |

（普查须同时覆盖 `name() { }` 与 `name() ( )` 两种函数体；只匹配前者会漏掉
`helm_kubeconfig_residue_exists` 这类子 shell 体函数。）

同名不同体又分两类，处置方式不同：

- **写法差异**：`array_contains`（10 用 `local value`，30 用 `local item`）、
  `host_path`（00 写 `== "1"`，其余写 `== 1`）——语义相同。
- **语义差异**：`kubectl_run` 在 60 调 `admin_conf_gate`、在 90 调
  `admin_conf_is_safe`；`helm_cluster_run` 两份实现相差一行；`owned_by_expected`
  有三种实现（20 / 30 / 40+50+60+90）。

本会话服务器 10 次 STOP 中，`kubectl-provenance-drift`、
`admin-conf-content-or-structure-drift`、`kubelet-serving-csr-drift`、
`gateway-cilium-cluster-state-unknown`、`partial-kubernetes-contract` 共 5 次，
根因都是**同一判定在不同位置有不同实现或不同预期**。同名不同体是这一根因的静态形态。

## Decision

按 stage 建目录，并把判定按「共享 / 本 stage 专属」两级归位：

```
scripts/bootstrap/
├── bootstrap-all.sh          编排器（stage 映射、锁、快照、门禁）
├── run-approved.sh           运维一行入口
├── pin-host.sh
├── check_cidrs.py
├── lib/                      跨 stage 共享判定
├── hosts/<hostname>/         每主机参数（子项目 D 已交付）
└── stages/<NN-name>/
    ├── run.sh                流程编排 + complete 调用
    ├── gates.sh              本 stage 专属判定函数
    └── README.md             本 stage 做什么 / 会停在哪些 REASON / 证据在哪
```

`run.sh` 只保留可读的流程主线；`gates.sh` 承载判定，可被测试单独 `source`；
`README.md` 让运维不读 bash 也能知道这个 stage 的职责、停止原因与证据位置。

## 共享库划分

新增/扩充的 `lib/` 文件与其承载函数（依实测归属）：

| 文件 | 函数 | 来源 stage |
| --- | --- | --- |
| `lib/path-facts.sh` | `path_owner` `path_mode` `path_size` `owned_by_expected` | 20 30 40 50 60 90 |
| `lib/archive.sh` | `validate_archive` `safe_archive_member` `safe_symlink_target` `approved_record` `array_contains` | 10 30 |
| `lib/kubectl.sh` | `kubectl_run` `kubectl_query_is_empty` `capture_admin_conf` | 50 60 90 |
| `lib/helm.sh` | `helm_run` `helm_cluster_run` `cleanup_helm_kubeconfig` `helm_kubeconfig_residue_exists` `helm_values_json_is_exact` `helm_archive_is_safe` | 60 90 |
| `lib/exec-safety.sh` | `python_isolated` `tar_safe` `safe_directory` | 60 90 |
| `lib/common.sh`（扩充） | `host_path` `complete` | 全部 8 个 |

`complete` 有三种形态（00+20+30 / 10 / 40+50+60+90），差异在于附带的证据字段。
上提为 `lib/common.sh` 中的单一实现，stage 专属字段通过参数传入，不得以复制解决。

## 同名不同体的处置规则

13 个同名不同体函数，**逐个**按下列规则处置，禁止「挑一个看起来对的」：

1. 判定是写法差异还是语义差异，并在提交信息中写明依据。
2. 写法差异：直接统一，无需改变行为。
3. 语义差异：必须先确定哪一版对生产是正确的，依据只能是**服务器实测证据或
   真实工具输出**，不得依据现有测试 fixture——本会话已证明 fixture 会编码实现
   的假设而非现实（5 次服务器 STOP 全部由此产生）。
4. 统一后的实现必须同时满足所有调用方的既有测试；任一调用方测试需要放宽才能
   通过，即视为该处语义差异尚未查清，停止并记录。

## 供应链门禁（必须新增）

现状缺口：`bootstrap-all.sh` 校验了 `scripts/bootstrap/` 目录（`safe_owned_directory`
非递归）与 8 个 stage 脚本文件的属主与权限位，但 **`lib/` 目录及其 `*.sh` 从未校验**，
而每个 stage 都以 root `source` 它们。E 会把被 source 的文件从 7 个增加到 15 个以上。

因此本子项目必须补齐：任何被 `source` 的文件在 source 之前，都要通过与 stage 脚本
同级的门禁（绝对路径、非符号链接、规范路径自等、属主为期望 uid、非 group/world 可写），
覆盖：

- `lib/` 目录本身与 `lib/*.sh`
- `stages/` 目录、每个 `stages/<NN-name>/` 目录、其 `run.sh` 与 `gates.sh`

不通过即以既有 STOP 形态与固定退出码停止，不得降级为告警。

## bootstrap-all 的变化

`STAGES=(00 10 20 30 40 50 60 90)` 与 `MUTATING_STAGES` 不变。`stage_path` 的
硬编码映射改为指向 `stages/<NN-name>/run.sh`——**保持硬编码，不改为目录扫描**：
扫描会让新增目录被静默执行，与 fail-closed 相悖。

## Test strategy

- stage 路径引用集中到测试侧单一 helper，26 处硬编码路径不得散落。
- 每个上提到 `lib/` 的函数都要有 lib 级测试，并用变异证明非空转（改坏实现必须变红）。
- 每个 `gates.sh` 必须可被测试单独 `source` 且不产生副作用。
- 新增门禁（属主/权限/符号链接）每一条都要有对应的拒绝用例。
- 已有 383 个测试全部保持绿；迁移不得放宽任何既有断言。

## 迁移顺序

一次一个 stage，每步独立提交并全绿后再进行下一步；顺序按风险从低到高：

1. `lib/` 门禁补齐（先于任何搬迁，避免中途扩大未校验面）
2. 共享函数上提：`path-facts` → `archive` → `exec-safety` → `kubectl` → `helm` → `common`
3. 目录迁移：00 → 10 → 20 → 30 → 50 → 40 → 60 → 90（大文件放最后）
4. `bootstrap-all` 映射与测试 helper 切换
5. runbook 与 AGENTS.md 路径更新

## Scope

只覆盖目录拆分、判定去重与被 source 文件的门禁。不在范围内：

- 每 gate 一行进度与终端 UX（子项目 A，建立在 E 之上）
- 新手册与 runbook 梳理（子项目 B/C）
- 任何 stage 的判定标准本身的变更（除非属于上面第 3 条的语义差异裁决）
