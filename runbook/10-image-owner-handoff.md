# 应用 Image Owner Handoff

检查时间：`2026-08-23`
状态：`BLOCKED`

只读检查确认：

- frontend 当前 Source Commit 为 `da72238abc87a19c07a5cac96e41d88d5f6bf2d3`，已有 Dockerfile、nginx 80 启动合同和 main image workflow；CI run `32683635240` 与 publish-image job `97305929974` 已 `success`。
- 当前 OCI index digest 已确认为 `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1`；构建日志中的 child manifest `sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c` 尚未独立确认 `linux/amd64` 身份，运行 Image ID 也仍为 `NOT_VERIFIED`。
- backend `engineering-platform-backend` 位于 `647d509bca1bbf9ff0f6ab719d5905d8f836e92f`，已有 Dockerfile、Alembic migrations 和 uvicorn 8000 启动合同；当前 Source Commit 尚无成功 image digest。
- backend 历史 commit `1d627b9` 的 digest `sha256:c77fb2d88a61659fa8c2b5074a4ea3103002698085e578652d999d2e2b45e8d7` 只作历史记录，不进入当前 handoff。
- 最后一次 DEV Runtime 观测没有 platform Namespace、migration Job 或 frontend/backend 工作负载，所有运行 Smoke 均未执行。

因此当前不得生成带猜测 digest 的 Deployment。进入应用 Desired State 前的回执为：

## 当前 frontend 候选

| 字段 | 值 |
| --- | --- |
| Source Commit | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` |
| CI provenance | `VERIFIED` |
| Artifact / OCI index digest | `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` |
| linux/amd64 manifest digest | `NOT_VERIFIED`（candidate：`sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`） |
| Runtime Image ID | `NOT_VERIFIED` |

run `32683635240` 与 publish-image job `97305929974` 的 provenance 已确认，发布 tag 为 `ghcr.io/unif-code/engineering-platform:sha-da72238`。child manifest 仍必须由 Registry/workflow 独立确认 `linux/amd64` 身份；此前不得创建应用 Deployment 或填写运行 Image ID。

## 2026-08-22 frontend 历史证据

此节仅保留已归档的 `2026-08-22` 观察，不代表当前 frontend 候选、可部署制品或运行状态。

| 字段 | 值 |
| --- | --- |
| Source Commit | `c392c6fc7a82a26f1eb4be22c35c6cda00e5d75c` |
| OCI index digest | `sha256:ee548974e159916ba7ca0fafe8bb30d72722a34625ffbce31d6e495324d06c0c` |

| 字段 | frontend | backend |
| --- | --- | --- |
| Repository | `unif-code/engineering-platform` | `unif-code/engineering-platform-backend` |
| Source commit（完整 40 位 SHA） | `da72238abc87a19c07a5cac96e41d88d5f6bf2d3` | `647d509bca1bbf9ff0f6ab719d5905d8f836e92f` |
| CI run URL | `https://github.com/unif-code/engineering-platform/actions/runs/32683635240`（`success`；publish-image job `97305929974`） | 当前 Source Commit 无成功 run |
| Image tag `sha-<short-sha>` | `sha-da72238` | `NOT_AVAILABLE` |
| OCI index digest | `sha256:77c2b01247e2e3e0a09ff159290feaf758b0ebec6a2d08843d927c5153642bd1` | `NOT_AVAILABLE` |
| `linux/amd64` manifest digest | `NOT_VERIFIED`（candidate：`sha256:21248f11379841f12e27d330ffaa8f2be73b92bcbf3628a1855c41b697a10a5c`） | `NOT_AVAILABLE` |
| Runtime Image ID | `NOT_VERIFIED` | `NOT_AVAILABLE` |
| 启动命令 / 监听端口 | nginx / 80 | `uvicorn control_plane.app.bootstrap.app:create_app --factory --host 0.0.0.0 --port 8000` |
| Migration | 不适用 | `alembic upgrade heads`，`NOT_EXECUTED` |
| Smoke 结果 | `/` 登录页：`NOT_EXECUTED` | `/api/v1/me`、`/healthz`、`/readyz`：`NOT_EXECUTED` |

应用 Desired State 只接受 Registry 查询结果或 CI provenance 中的 digest，并将经核验的 `linux/amd64` manifest digest 直接写入 Deployment。frontend platform manifest 与 backend 当前 digest 到齐后，才可提交 backend/frontend Deployment、Service、HTTPRoute 与 Alembic migration Job。

DEV-002 初始资源合同也必须由应用 owner 验证并随首个清单提交：

| Workload | requests | limits |
| --- | ---: | ---: |
| frontend | `10m / 64Mi` | `250m / 256Mi` |
| backend | `100m / 256Mi` | `1 CPU / 1Gi` |
| Alembic migration Job | `100m / 256Mi` | `1 CPU / 1Gi` |

若真实启动或迁移无法在起始值内稳定完成，只能按运行证据局部上调并同步 DEV-002；不得删除 migration、健康检查或镜像 Digest Gate。
