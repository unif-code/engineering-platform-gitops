# DEV 单节点稳态容量测量

GitOps commit / PR：
执行人：
采样窗口（含时区，至少 15 分钟）：
节点：

## CPU / 内存

| 对象 | CPU request | CPU steady | CPU peak | Memory request | Memory steady | Memory peak |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Node total / allocatable | | | | | | |
| platform | | | | | | |
| cnpg-system | | | | | | |
| monitoring | | | | | | |
| minio | | | | | | |
| flux-system | | | | | | |
| kube-system | | | | | | |

## 磁盘

| 路径 / PVC | Provisioned | Used | Available | 使用率 | 增长观察 |
| --- | ---: | ---: | ---: | ---: | --- |
| `/var/lib/containerd` | | | | | |
| `/var/lib/engineering-platform/local-path` | | | | | |
| MinIO 300Gi | | | | | |
| PostgreSQL 100Gi | | | | | |
| Prometheus 30Gi | | | | | |
| Grafana 10Gi | | | | | |
| Alertmanager 5Gi | | | | | |

## 原始输出与结论

```text
待运维回填 kubectl top、requests/limits、df/du 与 PVC 输出。
```

- [ ] CPU、内存和磁盘均保留可解释余量。
- [ ] 无 MemoryPressure / DiskPressure / PIDPressure。
- [ ] 容量不足时已停止验收并关联扩容/缩配决策。
