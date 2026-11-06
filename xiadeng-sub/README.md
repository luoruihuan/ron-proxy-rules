# 虾蹬精选订阅（VM 版）

> 架构：`设备 → 小火箭 → Hy2-vm2-main（前置） → 虾蹬精选静态住宅（落地） → 目标网站`
> 服务位置：`ron-vm1`（<VM_IP>，Oracle Phoenix，系统级 systemd 常驻）

> **本目录是脱敏版**：订阅地址 token、VM 公网 IP、Bright Data 账号密码均已替换为占位符。
> 线上运行副本在 VM 上（`~/xiadeng/`），`config.json` 内含真实凭据，权限 `600`，**不入库**。

## 一、订阅地址

```
http://<VM_IP>:8791/<PATH_TOKEN>/sub
```

小火箭里把原来虾蹬那条订阅**换成这个地址**，更新一次即可。

- 只输出 **5 个精选落地节点**（不是 46 个）
- 每个节点的「代理通过」自动指向 `Hy2-vm2-main`
- 上游密码/账号变了也自动同步，不用管

## 二、网络放行（已完成）

`ron-vm1` 的 8791 端口已放行并持久化：

- iptables：`-A INPUT -p tcp --dport 8791 -j ACCEPT`（写入 `/etc/iptables/rules.v4`，重启不丢）
- OCI 安全组：Ingress TCP 8791 已添加（控制台操作）

> ⚠️ 小火箭侧的配套要求：`ron-proxy-rules` 仓库的两份配置都已加入
> `IP-CIDR,<VM2_IP>/32,DIRECT` 与 `IP-CIDR,<VM_IP>/32,DIRECT`。
> 否则切到住宅配置（出口走 Bright Data HTTP 代理）时，SSH(22) 与订阅拉取(8791) 会被代理链拦住。

## 三、精选逻辑（v2）

| 你的要求 | 实现方式 |
|---|---|
| 只挑可用的 | 每 30 分钟做轻量存活探测（~1KB，几乎不耗流量）；全量测速每 12 小时一次，只测前 8 个候选 |
| 没被标识 | 查公开库，`hosting=true` 或 `proxy=true` 的 IP 一律排除（实测已踢掉静态04 和 18） |
| 住宅性优先 | 自动分档：`RingSquared`→1档、`RCN`→2档、其他→3档；档位权重高于速度 |
| 人少 | 做不到精确（Bright Data 不公开并发用户数），用“拥堵度（实测速度/首字节）+ 避开热门编号”近似 |
| 上游新增节点 | 自动纳入（不再依赖硬编码候选池），按 ASN 自动定档 |

### 巡检成本（v1 → v2）

| | v1 | v2 |
|---|---|---|
| 存活检查 | 每 30 分钟 × 18 个 IP × 3MB = **2.6 GB/天（约 78 GB/月）** | 每 30 分钟 × 18 个 IP × ~1KB = 约 26 MB/月 |
| 带宽测速 | 同上（重复） | 每 12 小时 × 8 个 × 1MB × 2 次 ≈ **1 GB/月** |

这个修正很关键：v1 会静默烧掉这类套餐常有的流量配额。

### 关键设计：不每次重排

老名单只要还活着就**保持原样**，只有失效才从备选补位。原因：IP 频繁跳动本身就会触发平台关联告警，**稳定身份比“每次最优”更值钱**。

### 当前入选（2026-11-06 11:41 巡检）

| 节点 | 档 | 运营商 | 速度 | 首字节 |
|---|---|---|---|---|
| 静态38 | 1 | RingSquared CC | 2041 KB/s | 882 ms |
| 静态12 | 1 | RingSquared CC | 1811 KB/s | 863 ms |
| 静态13 | 2 | RCN | 1770 KB/s | 1127 ms |
| 静态14 | 2 | RCN | 1794 KB/s | 1148 ms |
| 静态20 | 2 | RCN | 1832 KB/s | 1085 ms |

备选：静态23 / 24 / 37 / 46 / 40（同档位，失效自动补位）

## 四、上游虾蹬更新时我们要做什么

| 上游变化 | 我们要做什么 |
|---|---|
| 密码 / 账号轮换 | ✅ 不用做，服务每次请求实时拉上游 |
| 端口 / 服务器变更 | ✅ 不用做，自动跟随 |
| `dialer-proxy` 的取值变化 | ✅ 不用做，我们忽略上游这个字段，直接写死 `Hy2-vm2-main` |
| 新增城市 / 新编号 | ✅ 已自动纳入；想让它优先，把编号加进 `config.json` 的 `pool` / `tier` |
| 节点被删除 | ✅ 自动重排 |
| **订阅 URL / token 变更** | ⚠️ 改 `~/xiadeng/config.json` 的 `upstream` → `systemctl restart xiadeng-sub` |
| **yaml 结构大改（字段名/格式）** | ⚠️ 需改代码里的 `parse_statics`。信号：`/status` 里 `upstream_ok=false`，或日志出现「解析不到任何静态节点」 |

## 五、飞书卡片告警

已接入飞书机器人，**只在状态变化时推送**，不刷屏。

| 卡片 | 触发条件 |
|---|---|
| 🧪 蓝色 · 测试 | 手动执行 `--test-alert` |
| ⚠️ 橙色 · 异常 | 入选数不足 `top_n`，或入选节点探测失败 |
| ❌ 红色 · 故障 | 上游连续失败达到 `alert_fail_threshold` 次（默认 2），或一个可用节点都没有 |
| ✅ 绿色 · 已恢复 | 从异常/故障回到正常 |

防骚扰规则：
- 只在**状态跳变**时发（ok→warn、warn→error、→ok）；
- 故障持续存在时，每 `alert_cooldown_minutes`（默认 120 分钟）重提醒一次；
- 单次上游抽风不报警（低于阈值不打扰）。

重要行为：**上游挂掉时订阅仍可用** —— 服务会用 `last_good.yaml` 兜底返回，同时给你发红色告警。

## 六、运维命令（在 VM 上）

```bash
ssh ron-vm1

# 看实时排名和入选名单（JSON）
curl -s http://127.0.0.1:8791/<PATH_TOKEN>/status | python3 -m json.tool

# 立即重排一次（清缓存后拉一次订阅即可触发）
rm -f ~/xiadeng/state.json && systemctl restart xiadeng-sub

# 服务状态 / 日志
systemctl status xiadeng-sub
tail -f ~/xiadeng/service.log

# 改精选数量或候选池
vim ~/xiadeng/config.json      # top_n / pool / tier / recheck_minutes
systemctl restart xiadeng-sub
```

## 七、日常使用建议（重要）

- **日常默认走 `Hy2-vm2-main`**，不要用住宅链。住宅链代价：延迟 +160~200ms、单流约 9 Mbps。
- 只在**撞到风控**（频繁验证码、注册被拒）时，把小火箭首页切到精选里的某个落地节点，用完切回来。
- 国内流量走直连：全局路由保持「配置 / 规则」。
- 住宅订阅是免费的，留着当应急通道零成本。

## 八、为什么选 ron-vm1

| 机器 | 出网速度 | 到 BrightData | 负载 | 结论 |
|---|---|---|---|---|
| **ron-vm1**（<VM_IP>） | 8.9 MB/s | 0.197s | 0.08 极闲 | ✅ **选它**：备用机闲置，与代理主节点隔离，挂了互不影响 |
| ron-vm2（<VM2_IP>） | 15.1 MB/s | 0.155s | 0.17 | 主节点跑着 Hysteria2，别加负担 |
| tokyo（43.163.235.128） | 69 MB/s | 0.076s | 0.65 | 备选：国内拉取最快，但负载较高、可能另有业务 |
| huawei（124.70.216.247） | 241 KB/s | 0.888s | 0.10 | ❌ 国际带宽太差，46 个 IP 需要巡检会极慢 |

## 九、本机残留（2026-11-06 清理后）

本机只剩**服务源码 + 本文档**，其余（本地转换服务、检测脚本、A/B 调试工具、配置备份、含凭据的临时文件）已全部移入垃圾桶：

```
xiadeng-sub/README.md         本文档
xiadeng-sub/xiadeng_sub.py VM 服务的源码备份（线上运行副本在 ron-vm1:~/xiadeng/）
```

相关但独立保留的：

- `~/Desktop/others/ron-proxy-rules` —— 你自己的小火箭配置仓库（oracle / residential 两份）
- 小火箭节点库备份：`ServerManager.bak-20261106-175154`（在 App Group Container 内，46 节点全绑 Hy2 的那一版）

**不要再放回本机的**：任何包含虾蹬订阅 token、Bright Data 账号密码、或服务 `config.json` 的文件。线上那份 `config.json` 权限是 `600`。
