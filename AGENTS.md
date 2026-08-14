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
- 本地提交前运行受影响的 focused tests 和 `./scripts/validate-fast.sh`；普通 push 后必须等待 GitHub `validation-gate` 全部通过，才可继续服务器部署或验收。
- `./scripts/validate.sh` 保留为人工完整顺序验证入口，不再要求每次本地提交运行；提交历史保持线性并使用 Conventional Commits。

## Codex 原生记忆

- 平台共享记忆位于同级 `engineering-platform-docs/memories_1.sqlite`，同步规则以该仓 `MEMORIES.md` 为准。
- 仅当用户明确发送 `【同步记忆】` 时，进入同级 `engineering-platform-docs` 运行 `npm run memory:sync`；禁止直接复制或覆盖任一 SQLite 文件。
- 共享记忆同步进本机 Codex 原生数据库后由 Codex 自身消费，不在成员仓展开、复制或提交记忆正文。
- 记忆与事实冲突时，以当前用户指令、本仓当前 Git/代码、docs 架构文档和可执行测试为准。
