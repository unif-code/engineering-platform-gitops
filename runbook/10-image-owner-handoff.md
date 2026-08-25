# 应用 Image Owner Handoff

检查时间：`2026-08-25 02:52Z`（backend 交付输入核验；Runtime 仍沿用历史采样）
状态：`BLOCKED`

只读检查确认：

- frontend 当前 Source Commit 为 `da72238abc87a19c07a5cac96e41d88d5f6bf2d3`，已有 Dockerfile、nginx 80 启动合同和 main image workflow；CI run `32683635240` 与 publish-image job `97305929974` 已 `success`。
- 当前 OCI index digest 已确认为 `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1`；workflow 的 `build --platform linux/amd64`、导出 manifest 日志与独立 attestation manifest 已确认 `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` 为可部署 linux/amd64 manifest，运行 Image ID 仍为 `NOT_VERIFIED`。
- backend `engineering-platform-backend` main 位于 `4aaf721fa91abd729b33765e4e329b02aa2ece02`；CI run `32802909349` 的 verify 与 publish-image 均成功，tag 为 `sha-4aaf721`，不可变 OCI index digest 为 `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857`。
- backend 历史 commit `1d627b9` 的 digest `sha256:c77fb2d88a61659fa8c2b5074a4ea3103002698085e578652d999d2e2b45e8d7` 只作历史记录，不进入当前 handoff。
- `2026-08-24 12:16:47Z` 的历史 DEV Runtime inventory 没有 platform Namespace、migration Job 或 frontend/backend 工作负载，所有应用 Smoke 均未执行；该记录不冒充 2026-08-25 实时 readback。
- GitOps business-ready 候选已经锁定上述两个 digest，并包含 migration、Deployment、Service、
  HTTPRoute 与 Stage 110–160；它尚未合并/部署，运行 Image ID 和 Smoke 仍为 `NOT_VERIFIED`/
  `NOT_EXECUTED`。

backend/frontend 交付已成为 business-ready 候选的锁定输入。只有候选合并 SHA 的
`validation-gate` 与 `validated` 一致，并通过独立服务器写入审批后，Stage 110–160 才可执行；
不得把仓库候选冒充 runtime。进入运行阶段前的回执为：

## 当前 DEV Runtime 观测

本节记录 `2026-08-24 12:16:47Z` 的 Flux Phase A 历史验收；它不代表 2026-08-25
实时状态。Controller 基础层完成不等于应用 Desired State 或 frontend Runtime Image ID
已验证。
上层 `run-approved.sh --check` 对集群和主机配置只读，但会 `fetch` 并以 `ff-only` 更新服务器 Git checkout。

| 字段 | 值 |
| --- | --- |
| 采样时间 | `2026-08-24 12:16:47Z` |
| GIT_COMMIT | `685198db15299fdb6b8cdffd72162a4864c8666b` |
| RESULT | `PASS_FLUX_PHASE_A` |
| REASON | `four-controller-runtime-accepted` |
| FLUX_CHECK | `all checks passed` |
| CONTROLLERS | `source v1.9.3/kustomize v1.9.4/helm v1.6.3/notification v1.9.2` |
| FLUX_CRD_COUNT | `11` |
| SECRET_COUNT | `0` |
| SYNC_INVENTORY | `empty` |
| DOWNSTREAM_NAMESPACE_INVENTORY | `empty` |
| NETWORK_PROBE_V2 | `PASS` |
| EVIDENCE | `/root/dev-infra-evidence/15-flux-phase-a-20260824T105630Z.txt` |
| EVIDENCE SHA256 | `2e773304741d1eb0c8cc4b6558df21b8422d88c91c66cb09418f50a6373f66e7` |
| OPENBAO | `NOT_EXECUTED` |
| BACKUPS | `NOT_EXECUTED` |
| NEXT_STAGE | `PHASE_B_REQUIRES_SEPARATE_APPROVAL` |
| EXIT_CODE | `0` |

## 当前 frontend 候选

| 字段 | 值 |
| --- | --- |
| Source Commit | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` |
| CI run | `32683635240` |
| publish-image job | `97305929974` |
| Image tag | `sha-da72238` |
| CI provenance | `VERIFIED` |
| Artifact / OCI index digest | `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` |
| linux/amd64 manifest digest | `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` |
| Runtime Image ID | `NOT_VERIFIED` |

run `32683635240` 与 publish-image job `97305929974` 的 provenance 已确认，发布 tag 为 `ghcr.io/unif-code/engineering-platform:sha-da72238`。workflow、CI log 与独立 attestation 已确认 child manifest 的 linux/amd64 身份；该 digest 只作为后续应用阶段输入，当前不得创建应用 Deployment，运行 Image ID 仍为 `NOT_VERIFIED`。

## 当前 backend 可用输入

| 字段 | 值 |
| --- | --- |
| Source Commit | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |
| CI run | `32802909349` |
| verify | `success（Ruff、mypy、lint-imports、Alembic、全量 pytest、OpenAPI）` |
| publish-image job | `97667504061` |
| Image tag | `sha-4aaf721` |
| Immutable image | `ghcr.io/unif-code/engineering-platform-backend@sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857` |
| Runtime Image ID | `NOT_VERIFIED` |
| Deployment | `NOT_EXECUTED` |
| Migration | `NOT_EXECUTED` |
| Account initialization | `NOT_EXECUTED` |

上述 digest 已写入候选清单；migration、健康检查和运行 readback 尚未执行。私有 GHCR
credential 只允许通过服务器 root-owned、mode `0600` 的受保护文件供给，值不得出现在 Git、
命令回显或证据。账号初始化仍未执行；临时密码只允许在受控初始化 TTY 中一次性显示，
不得写入 Git、聊天、日志或长期证据。
临时密码只允许在受控初始化输出中一次性显示，不得写入 Git、日志或长期证据。

## 2026-08-22 frontend 历史证据

此节仅保留已归档的 `2026-08-22` 观察，不代表当前 frontend 候选、可部署制品或运行状态。

| 字段 | 值 |
| --- | --- |
| Source Commit | `c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c` |
| OCI index digest | `sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c` |

| 字段 | frontend | backend |
| --- | --- | --- |
| Repository | `unif-code/engineering-platform` | `unif-code/engineering-platform-backend` |
| Source commit（完整 40 位 SHA） | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |
| CI run URL | `https://github.com/unif-code/engineering-platform/actions/runs/32683635240`（`success`；publish-image job `97305929974`） | `https://github.com/unif-code/engineering-platform-backend/actions/runs/32802909349`（`success`；verify、publish-image 均成功） |
| Image tag `sha-<short-sha>` | `sha-da72238` | `sha-4aaf721` |
| OCI index digest | `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` | `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857` |
| `linux/amd64` manifest digest | `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` | `NOT_SEPARATELY_VERIFIED`（build 固定 `linux/amd64`；部署锁定 OCI index digest） |
| Runtime Image ID | `NOT_VERIFIED` | `NOT_VERIFIED` |
| 启动命令 / 监听端口 | nginx / 80 | `uvicorn control_plane.app.bootstrap.app:create_app --factory --host 0.0.0.0 --port 8000` |
| Migration | 不适用 | `NOT_EXECUTED` |
| Migration command | 不适用 | `alembic upgrade heads` |
| Account initialization | 不适用 | `NOT_EXECUTED` |
| Smoke 结果 | `/` 登录页：`NOT_EXECUTED` | `/api/v1/me`、`/healthz`、`/readyz`：`NOT_EXECUTED` |

应用 Desired State 只接受 Registry 查询结果或 CI provenance 中的 digest。当前候选已锁定
backend/frontend Deployment、Service、HTTPRoute 与 Alembic migration Job；在合并、CI 与
服务器运行门完成前它们仍为 `NOT_EXECUTED`。账号初始化始终是编排器外的独立数据库写入门。

DEV-002 初始资源合同也必须由应用 owner 验证并随首个清单提交：

| Workload | requests | limits |
| --- | ---: | ---: |
| frontend | `10m / 64Mi` | `250m / 256Mi` |
| backend | `100m / 256Mi` | `1 CPU / 1Gi` |
| Alembic migration Job | `100m / 256Mi` | `1 CPU / 1Gi` |

若真实启动或迁移无法在起始值内稳定完成，只能按运行证据局部上调并同步 DEV-002；不得删除 migration、健康检查或镜像 Digest Gate。
