# Helm 判定作用域收窄设计

## Context

2026-08-21 服务器 `--check` 在 stage 60 停止：

```
RESULT=STOP_UNKNOWN_STATE
REASON=gateway-cilium-cluster-state-unknown
EXIT_CODE=30
```

只读普查（`kubectl get`，无 apply/delete）显示集群里 Cilium **已经装好**：
`daemonset.apps/cilium`、`deployment.apps/cilium-operator`、
`daemonset.apps/cilium-envoy`、`pod/cilium-envoy-*`、`configmap/cilium-config`
全部存在，10 个 gateway CRD 齐备，kube-proxy 三件套干净，helm 为 `v3.21.0+ge0878d4`。

停止的唯一原因是第 3 项：

```
secret/sh.helm.release.v1.retail-test-workflow-gitlab-runner.v1
secret/sh.helm.release.v1.cilium.v1
```

集群里有**两个** Helm release，而判定要求全集群**有且仅有一个**：

| 位置 | 判定 | 结果 |
| --- | --- | --- |
| `60-install-cilium/gates.sh:409` | `elif len(items) == 1:` … `else: UNKNOWN` | `HELM_SECRET_STATE=UNKNOWN` |
| `60-install-cilium/gates.sh:712` | `helm list --all-namespaces --all`，同样 `len(items) == 1` | `HELM_RELEASE_STATE=UNKNOWN` |

两个 UNKNOWN 使 `load_cluster_state` 既进不了「全 COMPLIANT」也进不了
「全 MISSING」，落进 `else` 分支 → `CLUSTER_STATE=UNKNOWN` → 停止。

`90-verify/gates.sh:171` 与 `:206` 是字节等价的两处 `len(items) != 1`，
因此即使绕过 60，90 也会以同样理由停止。

全仓搜不到任何 `gitlab` 字样：该 release 由本 bootstrap 之外的运维动作装入。
这不是迁移回归——`a3eb3945..a341272` 之间这段逻辑只有注释变化。

### 为什么这是缺陷而不是「按设计工作」

判定的本意是检测漂移。但「全集群恰好一个 release」把两件性质完全不同的事
判成同一件：

- 别的运维同事装了个 gitlab-runner —— 正常运维，与我们无关
- 有人动了 cilium —— 真实威胁

后果是：**只要集群里存在任何其他 Helm release，stage 60/90 就永远红**。
这台机器是要长期跑活的 DEV 主机，还会陆续装东西；把 stage 60 写成
「一次性全新安装」的一次性门禁，与 `run-approved.sh --check` 的可重入承诺冲突。

## Decision

判定作用域从「这个集群里有没有别人」收窄为「**我们的 cilium 对不对**」。

关键约束：收窄**不得**削弱检测能力。天真的「按对象名精确过滤
`sh.helm.release.v1.cilium.v1`」会引入新盲区——若有人 `helm upgrade` 过 cilium，
集群里会多出 `…cilium.v2`，按名字过滤时它**完全不可见**，判定会错误放行一个
实际已是 revision 2 的 cilium。

因此过滤依据是 Helm 自己的 `name` label，而非对象名：

```
--selector owner=helm,name=cilium
```

`v1` 与 `v2` 都带 `name=cilium`，故两者都会被选中；随后仍然要求
**恰好一条**、且 `namespace=kube-system`、且 `version=1`。
`retail-test-workflow-gitlab-runner` 的 label 是
`name=retail-test-workflow-gitlab-runner`，天然被排除。

收窄前后的检测能力对照：

| 情形 | 收窄前 | 收窄后 |
| --- | --- | --- |
| 外来 release（gitlab-runner） | UNKNOWN（误报） | 忽略 ✅ |
| cilium 被 upgrade（多出 v2） | UNKNOWN | UNKNOWN ✅ |
| cilium 装在错误 namespace | UNKNOWN | UNKNOWN ✅ |
| cilium release 缺失 | MISSING | MISSING ✅ |
| cilium 字段被篡改 | UNKNOWN | UNKNOWN ✅ |

唯一真实损失：无法再发现「集群里存在我们不认识的 Helm release」。这正是本次
要放弃的判定——它属于集群治理，不属于 bootstrap 的可重入性判定。

`helm list` 侧同理：`--all-namespaces --all` 后在 Python 里先过滤
`name == "cilium"` 再要求恰好一条。`helm list --all` 每个 release 只列最新
revision，故升级过的会以 `revision: "2"` 出现，被既有的 `revision == "1"`
断言接住——两层独立堵上同一个盲区。

## 改动面

生产代码 4 处，两个 stage 对称：

| 文件 | 函数 | 改动 |
| --- | --- | --- |
| `60-install-cilium/gates.sh` | `helm_secret_state` | selector 加 `,name=cilium` |
| `60-install-cilium/gates.sh` | `helm_list_json_state` | 计数前先按 `name == "cilium"` 过滤 |
| `90-verify/gates.sh` | `helm_release_is_exact`（secret 段） | selector 加 `,name=cilium` |
| `90-verify/gates.sh` | `helm_release_is_exact`（list 段） | 计数前先按 `name == "cilium"` 过滤 |

`helm_secret_json_state` 里既有的 `required = {"name": "cilium", …}` label 断言
保留不动：selector 已在服务端筛过一遍，这里是第二道，防止 selector 被误改后
判定静默放宽。

测试侧 fake kubectl 路由表按 argv 精确匹配，两处 key 需同步：
`test_bootstrap.py:11913` 与 `:14181`。
`:11912` / `:14180` 的 `('get', 'secrets', …)` 是无生产调用方的死路由
（生产只发 `secrets,configmaps`），本次一并删除。

## 验证

除既有用例外，新增三条针对**收窄边界**的用例（攻击判定的位置与区分力，
而非只测谓词体）：

1. 存在一个外来 helm release 时，`HELM_SECRET_STATE` / `HELM_RELEASE_STATE`
   仍为 COMPLIANT——证明收窄生效。
2. 存在第二个 cilium revision（`…cilium.v2`，label `name=cilium version=2`）时
   仍为 UNKNOWN——证明收窄**没有**打开升级盲区。这条是本设计的核心风险，
   必须有独立用例。
3. cilium release 出现在非 `kube-system` namespace 时仍为 UNKNOWN。

用例 2 若在「按对象名过滤」的实现下会通过，则说明该实现有盲区——本用例的
区分力正建立在此。

## Scope

只覆盖 stage 60 与 90 的 helm release 判定作用域。不在范围内：

- 其他判定的作用域（gateway CRD、cilium workload 等本就是按名字精确 get，
  不存在「全集群唯一」问题）
- 集群治理层面的「未知 Helm release 巡检」——若需要，属独立子项目
- 每 gate 一行进度与终端 UX（子项目 A）
- 新手册与 runbook 梳理（子项目 B/C）
