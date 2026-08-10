# Repository Guidelines

本仓是 `engineering-platform` DEV 环境的 GitOps Desired State 与运维证据仓，不存放前端或 backend 业务代码。

## 架构事实源

- 架构文档已独立到同级 `engineering-platform-docs` 仓，成员仓禁止复制架构文档。
- 基础设施、GitOps、Kubernetes 与运维目标契约以 `engineering-platform-docs/architecture/09-infrastructure-operations.md` 为准。
- 版本、容量、端口与阶段参数以 `engineering-platform-docs/architecture/appendix-parameters.md` 为准。
- DEV-001 与 DEV-002 的 canonical source 是 `engineering-platform-docs/architecture/deviations.md`。
- 治理例外先登记后引用：任何 `DEV-xxx` 编号必须先存在于 `engineering-platform-docs/architecture/deviations.md` 的登记条目，才可在本仓 runbook、文档、清单或注释中引用；铸造新编号的一方负责在同一工作批次内完成 docs 仓登记。
- 架构基线号与文档摘要以 `engineering-platform-docs/architecture/baseline-manifest.json` 为准。

## 变更与验证

- 禁止提交 Secret、Token、私钥、kubeconfig 或密码库导出内容。
- Image、Chart 与 Manifest 必须固定版本或 digest，禁止 `latest` 与浮动 tag。
- 【运维】命令必须先给出完整命令并等待服务器回执；证据不得记录敏感值。
- 提交前运行 `./scripts/validate.sh`，并保持线性历史与 Conventional Commits。
