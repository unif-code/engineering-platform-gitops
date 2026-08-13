# Kubernetes 本地 DEB Cache 安装设计

## 背景

Ubuntu 24.04 的 APT 2.8.3 在收到位于任意临时目录的绝对 `.deb` 路径时，
会先将路径解析成 package selection。与 `--no-download` 同时使用时，APT 只
从 `Dir::Cache::archives` 查找已经下载的 archive，不会继续消费原路径，因而
以 exit 100 和 `Unable to fetch some archives` 停止。

服务器只读验证证明：删除 `--no-download` 后，同一组四个本地 `.deb` 可以生成
精确的四个 `Inst` 和四个 `Conf`；把四个已验证 `.deb` 放入私有
`Dir::Cache::archives` 后，使用精确 `package=version` 与 `--no-download` 也会
生成同一精确 transaction，且 cache 在 simulation 前后不变。

## 决策

Stage 40 保留禁止 APT 补下载的安装合同，但把 APT 的本地输入改为它真实支持的
private archives cache：

1. 继续从唯一批准的 signed Packages index 获取四个精确版本。
2. 继续在独立 root-only download directory 中逐包校验 filename、size、SHA-256、
   package、version、architecture 与 dependency contract。
3. 把每个已验证 `.deb` 以 `0600` regular file 发布到本次 root-only APT workspace
   的 `Dir::Cache::archives`，目标 basename 必须是批准的四个 filename。
4. cache 在每次发布前后都只能包含已经批准的集合；发布完成后四个 cache 文件
   必须重新通过 size、SHA-256、owner、mode 与 non-symlink Gate。
5. simulation 与真实 install 都使用四个精确 `package=version` selection，并保留
   `--no-download`、`--no-install-recommends` 与同一隔离 `APT_CONFIG`。
6. simulation 必须仍是精确四个 `Inst` 与四个 `Conf`，不得出现第五个 package、
   remove、purge、upgrade、错误版本或错误 architecture。
7. simulation 后、真实 install 前，再次完整验证 download directory、private cache、
   CNI ancestry、binary shadow、kubelet mutable inputs 与 base dependencies。

## 失败分类

- cache 发布 I/O 失败：`STOP_APPLY_FAILED`。
- cache 发布前的 path/type/owner/mode 或 no-clobber 竞态异常：`STOP_UNKNOWN_STATE`。
- 已发布 cache 的 path、内容、集合、size 或 digest 漂移：
  `STOP_SUPPLY_CHAIN_MISMATCH`。
- APT simulation/installation 非零：维持既有 `STOP_APPLY_FAILED`。
- simulation transaction 不精确：维持既有 `STOP_SUPPLY_CHAIN_MISMATCH`。

## 测试合同

fixture 必须复现 APT 2.8.3 的关键区别：外部绝对 `.deb` 加 `--no-download` 失败；
只有当 private archives cache 中存在精确四包且 argv 使用精确
`package=version` 时，simulation/installation 才成功。既有 archive race 回归必须
证明 simulation 后新增第五个 cache entry 会 fail closed；成功路径必须证明没有
外部 `.deb` argv、未固定版本或第五包。cache 的 regular/non-symlink、mode、owner、
size 与 digest 由同一个 `cached_debs_are_exact()` Gate 在 publication 后、simulation
后及真实 install 前重复执行。
