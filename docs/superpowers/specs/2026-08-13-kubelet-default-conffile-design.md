# kubelet 官方 default conffile 兼容设计

## 背景与实证

Stage 40 已在 Ubuntu 24.04 主机上完成四个 Kubernetes package 的精确安装与 hold，
但 installed-state CHECK 在 `kubelet_operator_override_is_pristine()` 返回失败。

只读 trace 证明 package、hold、binary provenance、`dpkg --verify` 与全部 CNI payload
均已通过，唯一失败输入是 `/etc/default/kubelet`。服务器证据为：

- regular、non-symlink、root:root、0644、20 bytes；
- 内容精确为 `KUBELET_EXTRA_ARGS=\n`；
- SHA-256 为 `2737f011e1fc6995aeeb6a2071e268e37b1437481bbdb205f5075939f40d7ae7`；
- `dpkg-query -S /etc/default/kubelet` 返回 `kubelet: /etc/default/kubelet`；
- kubelet `${Conffiles}` 中存在唯一记录，MD5 为
  `9ba5cd2e9a1e368fa51e13f1dd6a5ec1`；
- 文件当前 MD5 与 conffile 登记完全相同。

因此该文件是锁定版本 kubelet `1.36.3-1.1` 的未修改官方 conffile，不是 operator
override。

## 决策

### 1. 合规状态

`/etc/default/kubelet` 只允许三种合规形状：

1. 路径完全不存在；
2. regular、non-symlink、root:root、0644 的空文件；
3. 当前 kubelet package 拥有且未修改的官方 conffile。

第三种形状必须同时满足：

- 文件 metadata 精确；
- 内容字节精确为 `KUBELET_EXTRA_ARGS=\n`；
- SHA-256 精确为批准值；
- `dpkg-query -S` 只返回精确 `kubelet: /etc/default/kubelet`；
- `dpkg-query -W -f='${Conffiles}' kubelet` 成功；
- `${Conffiles}` 中 `/etc/default/kubelet` 恰好一条，登记 MD5 精确为批准值；
- 当前文件 MD5 与登记 MD5 相等。

不解析 shell 语义，也不接受其他“等价空值”表示。

### 2. 拒绝状态

以下任意情况必须保持 fail closed：

- symlink、目录、错误 mode 或 owner；
- 内容中有注释、空格、额外换行、额外行或非空参数；
- package ownership 缺失、重复或不是 kubelet；
- conffile 记录缺失、重复、格式错误或 digest 漂移；
- 当前文件 MD5 与 conffile 登记不一致；
- `dpkg-query`、SHA-256 或 MD5 command 失败。

### 3. CHECK、APPLY 与恢复

该 Gate 始终只读。它不会创建、修改或删除 `/etc/default/kubelet`。

- CHECK 在官方 conffile 状态下继续把 `inactive/dead/Result=success` 分类为
  `START_REQUIRED`，返回 apply-required；
- APPLY 仍只 restart kubelet、完整复验并写 success evidence；
- 已安装并 hold 的 package 不重新下载或安装；
- 任一非批准 conffile 状态在 restart 前停止。

## 测试合同

必须先取得 load-bearing RED：fixture 安装精确官方 `/etc/default/kubelet`，提供精确
package ownership 与 `${Conffiles}` 记录；installed CHECK 当前实现因 size 非零返回 50。

GREEN 必须同时覆盖：

- official conffile 的 CHECK apply-required、APPLY resume、重复 APPLY 幂等；
- missing 与 empty file 的既有正向行为不变；
- metadata、内容、ownership、conffile record、digest 与 command failure 全部 STOP；
- CHECK 不 restart、不写 evidence，resume 不执行 APT。

本地只运行 focused regression、`validate-fast.sh` 与 static checks；完整动态 shards 由
普通 push 后 GitHub validation gate 执行。GitHub 全绿前不允许服务器同步或重跑 APPLY。
