# 服务器基线核验（运维执行并回填）

执行人：  
执行时间（含时区）：  
服务器标识：  

| 检查 | 命令 | 判定 | 实测 |
| --- | --- | --- | --- |
| CPU | `nproc` | ≥16 | |
| 内存 | `free -g` | total ≥62 | |
| 磁盘 | `lsblk` | 系统盘 ≥200G；独立数据盘/目录 ≥500G | |
| 架构 | `uname -m` | x86_64 | |
| Swap | `swapon --show` | 输出为空（`swapoff -a` 并注释 fstab） | |
| 发行版 | `cat /etc/os-release` | systemd 主流发行版 | |
| 时间同步 | `timedatectl` | NTP 同步 active | |

## 原始输出摘录

```text
待运维回填。
```

## 结论

- [ ] 全部通过，可以继续 bootstrap。
- [ ] 存在不达标项，已停止并请求决策。

不达标项 / 决策链接：
