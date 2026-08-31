# ron-proxy-rules

Shadowrocket 分流配置，与桌面 ClashX Meta 的规则保持同源。

## 这个仓库里有什么

- `shadowrocket.conf` —— 手机端唯一配置文件

**不包含**：节点信息、机场订阅链接、任何 token 或密钥。节点由机场订阅在 App 内单独提供，与本配置解耦。

## 配置链接

```
https://raw.githubusercontent.com/luoruihuan/ron-proxy-rules/main/shadowrocket.conf
```

jsdelivr 加速（有缓存延迟，push 后不会立刻生效）：

```
https://cdn.jsdelivr.net/gh/luoruihuan/ron-proxy-rules@main/shadowrocket.conf
```

## 手机端一次性配置

1. **加节点**：Shadowrocket → 首页右上 `+` → 类型选「Subscribe」→ 粘贴机场的 Shadowrocket 格式订阅链接
2. **加配置**：底部「配置」→ 右上 `+` → 粘贴上面的配置链接 → 下载 → 点该配置 → **使用配置**
3. **开自动更新**：设置 → 自动更新
   - 配置：开启后台更新，间隔 1 天
   - 订阅：开启后台更新，间隔 6 小时
4. iOS 设置 → 通用 → 后台 App 刷新 → 允许 Shadowrocket

## 日常维护

改规则 → push → 手机上「配置」里点该配置 → **更新配置**（或等后台自动更新）。

> 注意：`更新配置` 会用远程版本覆盖本地，手机上的手工微调会丢失。所有改动都在这个仓库里做。

## 策略组

| 组名 | 类型 | 说明 |
|---|---|---|
| `Fast` | url-test | 全部节点里选延迟最低 |
| `AI-USA` | url-test | 只筛美国节点，AI 服务专用 |
| `香港智能` | url-test | 只筛香港节点 |
| `PROXY` | select | 手动选择，默认 Fast |

## 自定义线路（与桌面不同，仅手机端）

| 域名 | 策略 | 原因 |
|---|---|---|
| `deepseek.com` | DIRECT | 上游 AI 规则集只收录海外 AI，不含 DeepSeek；桌面走兜底代理 |
| `youtube.com` 等 9 个域名 | Fast | 走最快线路而非锁美国；桌面走 `gfw` → PROXY |

这两组规则桌面端没有，如需一致请在 `config.yaml` 里同步添加。

## 与桌面配置的已知差异

桌面是 `~/.config/clash.meta/config.yaml`（ClashX Meta，本地文件模式）。两端规则同源但不逐条相同：

| 项 | 桌面 | 手机 | 原因 |
|---|---|---|---|
| 广告拦截 | Loyalsoldier `reject` (6.5MB) | blackmatrix7 `Advertising` (27KB) | 手机不适合拉 6.5MB |
| 国内域名直连 | Loyalsoldier `direct` (3MB) | blackmatrix7 `China_Domain` (51KB) | 同上；覆盖面有细微出入，少数长尾国内域名可能落到代理 |
| 国内 IP | `cncidr` 规则集 + `GEOIP,CN` | 仅 `GEOIP,CN` | 精简 |
| 需代理域名 | 含 `proxy` 规则集 (776KB) | 省略 | 兜底本来就是 PROXY，删掉不改变结果 |
| Google | `GEOSITE,google` | blackmatrix7 `Google.list` | Shadowrocket 不支持 GEOSITE |
| 进程分流 | `applications` (PROCESS-NAME) | 无 | iOS 没有进程级分流，无解 |
| DNS | 公司内网 DNS | 公共 DoH | 内网 DNS 在外网不通 |

改桌面规则时记得同步改这里（反之亦然）。想彻底消除差异，需要改成「单一真源 + GitHub Actions 生成两端产物」的方案。

## 上游规则集

- [VPSDance/ai-proxy-rules](https://github.com/VPSDance/ai-proxy-rules) —— AI 服务域名
- [Loyalsoldier/surge-rules](https://github.com/Loyalsoldier/surge-rules) —— 桌面 clash-rules 的 Surge 格式平行仓库
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) —— iOS 场景规则集
