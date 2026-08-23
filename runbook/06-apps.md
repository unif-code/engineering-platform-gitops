# Gateway 应用 Smoke

> 当前状态：`BLOCKED`。frontend OCI digest 已产生；backend 当前 Source Commit 无 image digest；集群没有 platform Namespace、migration Job、frontend/backend Deployment 或 Gateway Route。

| 字段 | 值 |
| --- | --- |
| GitOps commit / PR | 未执行应用 Desired State |
| frontend Source Commit | `c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c` |
| frontend OCI digest | `sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c` |
| backend Source Commit | `647d509bca1bbf9ff0f6ab719d5905d8f836e92f` |
| backend digest | `BLOCKED` |
| 执行状态 | `NOT_EXECUTED` |
| Gateway address | `NOT_AVAILABLE` |
| Hostname | `platform.dev.local` |

最后一次 DEV Runtime 观测时间为 `2026-08-22 16:58 +08:00`。下表是进入应用验收时必须执行的合同，不是当前通过记录。

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
