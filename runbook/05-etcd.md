# etcd 快照与上传验证

GitOps commit / PR：
执行人：
开始 / 结束时间（含时区）：
手工 Job 名称：

## 判定

- [ ] CronJob 使用 UTC `0 */3 * * *`，`concurrencyPolicy=Forbid`。
- [ ] 仅调度到 control-plane，并以只读方式挂载 `/etc/kubernetes/pki/etcd`。
- [ ] `etcdctl snapshot save` 成功。
- [ ] 上传前 `etcdutl snapshot status` 成功，revision / total keys / size 合理。
- [ ] 快照与 `.sha256` 文件出现在 `etcd-backup`。
- [ ] 七天清理命令成功，当前快照未被误删。
- [ ] etcd 与 `mc` Image ID 和 PCS 的 `linux/amd64` digest 一致。

## 原始输出

```text
待运维回填 snapshot、validate、upload 三个 container 的完整日志。
```

结果：`PASS / FAIL`
失败原因 / 决策链接：
