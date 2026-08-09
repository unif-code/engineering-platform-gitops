# DEV Cluster Bootstrap 记录

> 仅记录 bootstrap 阶段获准的带外命令。后续 Desired State 只能通过本仓 PR 变更。

执行人：  
执行时间（含时区）：  
服务器标识：  
GitOps commit / PR：  

## containerd 与内核前置

命令与输出：

```text
待运维回填。
```

判定：

- [ ] `containerd --version` 为 `2.3.1`。
- [ ] `SystemdCgroup = true`，cgroup v2 生效。
- [ ] `overlay`、`br_netfilter` 已加载，`net.ipv4.ip_forward = 1`。

## kubeadm 单节点

命令与输出：

```text
待运维回填。
```

判定：

- [ ] Kubernetes 为 `v1.36.3`，节点为 `Ready`。
- [ ] 使用稳定端点 `dev-cp.unif.internal:6443`。
- [ ] 未部署 kube-proxy，Cilium `1.20.0` Ready。
- [ ] Gateway API Standard CRD `v1.6.1` 已安装。
- [ ] local-path-provisioner 已安装且 `local-path` 不是默认 StorageClass。

`kubectl get nodes -o wide`：

```text
待运维回填。
```

## Flux bootstrap

命令与输出：

```text
待运维回填。
```

判定：

- [ ] Flux CLI / Controller 为 `v2.9.3`。
- [ ] Git deploy key 为只读。
- [ ] 仅 source/kustomize/helm/notification 四个 Controller。
- [ ] `kustomize-controller` 与 `helm-controller` 启用 `--no-cross-namespace-refs=true`。
- [ ] `flux check` 通过。
