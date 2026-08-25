# Gateway 应用 Smoke

> 当前状态：`BLOCKED`。集群没有 platform Namespace、migration Job、frontend/backend Deployment 或 Gateway Route。

| 字段 | 值 |
| --- | --- |
| GitOps commit / PR | 未执行应用 Desired State |
| backend Source Commit | `4aaf721fa91abd729b33765e4e329b02aa2ece02` |
| backend digest | `sha256:f32c5f67f26f1794022698b4692de5390b81374adf6c82de8e8a748fe1fca857`（可用输入，未部署） |
| 执行状态 | `NOT_EXECUTED` |
| 账号初始化 | `NOT_EXECUTED` |
| Gateway address | `NOT_AVAILABLE` |
| Hostname | `platform.dev.local` |

## 当前 DEV Runtime 观测

`2026-08-24 12:16:47Z` 的 Flux Phase A 历史验收表明四 Controller 基础层已 Ready，
但 Git sync、应用 Desired State、OpenBao 与备份均未执行。它不代表 2026-08-25 实时状态，
应用验收合同仍未执行。
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

CI run `32683635240` 与 publish-image job `97305929974` 均 `success`，发布 tag 为 `ghcr.io/unif-code/engineering-platform:sha-da72238`。workflow 的 `build --platform linux/amd64`、导出 manifest 日志和独立 attestation manifest 共同确认该 digest 为可部署 linux/amd64 manifest；运行 Image ID 仍待部署后核验。

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

当前批准计划尚未进入 backend 部署阶段；本节只登记可用输入，不授权创建 Deployment、
执行 migration、健康检查、运行 readback 或账号初始化。临时密码只允许在受控初始化输出中一次性显示，不得写入 Git、日志或长期证据。

## 2026-08-22 frontend 历史证据

该日期的观察仅作审计历史，不得代表当前 frontend 候选或触发应用 Desired State。

| 字段 | 值 |
| --- | --- |
| Source Commit | `c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c` |
| OCI index digest | `sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c` |

下表是进入应用验收时必须执行的合同，不是当前通过记录。

| 请求 | 预期 | HTTP 状态 | 证据 |
| --- | --- | --- | --- |
| `GET /` | 前端登录页可渲染 | `NOT_EXECUTED`（目标 200） | `NOT_EXECUTED` |
| `GET /healthz` | backend liveness 正常 | `NOT_EXECUTED`（目标 200） | `NOT_EXECUTED` |
| `GET /readyz` | 数据库可达时 backend ready | `NOT_EXECUTED`（目标 200） | `NOT_EXECUTED` |
| 未认证 `GET /api/v1/me` | RFC 9457 Problem Details，不泄露 Principal | `NOT_EXECUTED`（目标 401） | `NOT_EXECUTED` |
| 受控登录后 `GET /api/v1/me` | 返回当前 Principal projection | `NOT_EXECUTED`（目标 200） | `NOT_EXECUTED` |

执行时回填 curl 状态、非敏感响应摘要与浏览器截图链接；不得记录 Session、Cookie、Token、TOTP 或临时凭据。

- [ ] 只存在 Gateway 北向入口，没有 NodePort/额外 Ingress。
- [ ] Gateway TLS 证书 SAN、Serial、有效期与 Secret 一致。
- [ ] Deployment 实际 Image ID 与 GitOps digest 一致。
- [ ] frontend 起始 resources 为 `10m/64Mi` requests、`250m/256Mi` limits；backend 为 `100m/256Mi` requests、`1 CPU/1Gi` limits。
- [ ] Alembic migration Job 为 `100m/256Mi` requests、`1 CPU/1Gi` limits，并在成功后才放行应用 Reconcile。
- [ ] 页面/API Smoke、migration 与运行证据全部通过。
