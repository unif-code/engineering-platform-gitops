# Kubernetes APT Candidate 解耦设计

## 背景

服务器在 commit `0b037dde798cf7114f0d747436b763aab03636e8` 执行
`bootstrap-all.sh --apply` 时，Stage 40 返回：

```text
RESULT=STOP_UNKNOWN_STATE
REASON=candidate-drift-kubeadm
EXIT_CODE=30
```

隔离 APT audit 证明四个锁定包仍可用：

- `kubeadm`、`kubectl`、`kubelet` Candidate 均为 `1.36.3-1.1`；
- `kubernetes-cni` Candidate 为 `1.9.1-1.1`；
- `kubeadm`、`kubectl`、`kubelet` 的 policy 各列出四个来自同一批准仓库的版本。

现有 `candidate_is_exact()` 除比较 Candidate 外，还要求批准仓库 URL 在完整 policy
输出中恰好出现一次。真实多版本 policy 会让该 URL 出现多次，因此误报 drift。

## 决策

Stage 40 不再把 APT Candidate 作为供应链安全锚点，也不再调用 `apt-cache policy`。
部署只信任钉死的 signed artifact 合同：

1. 隔离 APT configuration 只能加载唯一批准 source；
2. `apt-get update` 必须 fail on any error；
3. `indextargets` 必须只返回唯一、批准 URL、private lists 目录内的 regular Packages
   文件；
4. signed Packages index 中，每个锁定的 package/version/amd64 stanza 必须恰好一条；
5. stanza 的 Filename、Size、SHA256、Depends 与禁止字段必须精确匹配；
6. 下载命令必须显式使用以下版本，不得使用浮动 package name：
   - `kubeadm=1.36.3-1.1`
   - `kubectl=1.36.3-1.1`
   - `kubelet=1.36.3-1.1`
   - `kubernetes-cni=1.9.1-1.1`
7. 下载后的四个 deb 必须再次校验 basename、size、SHA256、dpkg metadata 和 dependency；
8. simulation 与实际 install 只允许四个已验证的本地 deb，并使用同一隔离 APT
   configuration 和 `--no-download`；
9. transaction 必须精确，禁止额外 install/configure/remove/purge/upgrade；
10. 安装后必须立刻 exact hold，并重新验证 package、payload、CNI 和 unit provenance。

仓库发布更新版本不会改变上述锁定选择。只要锁定 stanza 仍唯一存在且所有摘要合同不变，
部署继续；锁定 stanza 缺失、重复或任一 metadata/digest 漂移仍 fail closed。

## 实现边界

- 删除无安全作用的 `candidate_is_exact()` 与四包 Candidate loop；
- Stage 40 不再把 `apt-cache` 列为 required command；
- 不改变锁定版本、digest、repository、keyring 或 install transaction；
- 不修改其他 bootstrap stage；
- 不因本次兼容放宽 second indextarget、unknown source、duplicate stanza 或 extra deb Gate。

## 测试设计

先用真实 Bash Stage 40 entry 建立 load-bearing RED：

1. fake signed Packages index 同时包含一个更新版本和当前锁定版本；
2. fake `apt-cache policy` 呈现服务器同形的多版本输出，并让 Candidate 可前移；
3. 旧实现必须因 Candidate/repository URL 计数 Gate 返回 30；
4. 修复后必须成功，而且 command log 不得出现 `apt-cache policy`；
5. fake `apt-get download` 必须逐包拒绝任何缺失或错误的 `=version` 参数；
6. 现有 locked stanza 缺失/重复、digest drift、second indextarget、extra download、
   non-exact transaction 回归必须继续通过。

最终验证采用受影响 focused tests、完整 `KubernetesInstallTest`、`validate-fast.sh`、
`validate-static.sh` 和 GitHub 全分片 `validation-gate`。服务器只有在新 commit 的 GitHub
门禁成功后才同步并恢复同一条 orchestrator `--apply`。

## 失败处理与恢复

- 本地或 CI 任一 Gate 失败：不推送后续服务器 mutation；
- 服务器 Stage 40 再次非零：立即停止并贴回完整结构化输出；
- orchestrator 依真实 stage 状态恢复，不维护 progress file；
- Stage 40 成功后，orchestrator 可继续 Stage 50、60、90，任一阶段失败即停止。
