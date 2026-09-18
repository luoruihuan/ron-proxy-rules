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
| `Fast` | url-test | 四个实测优选节点中自动选择：香港05、香港04、日本5、新加坡 `[CM]` |
| `AI` | url-test | 只筛日本、新加坡节点，AI 服务专用 |
| `香港智能` | url-test | 只筛香港节点 |
| `PROXY` | select | 手动干预入口，不被规则引用 |

## 设计目标

四条核心诉求，规则严格对应：

| 诉求 | 实现方式 |
|---|---|
| AI 走专用线路 | `ai-proxy-rules/global.list` → `AI` |
| 国内走直连 | `China_Domain` + `icloud` + `apple` + `GEOIP,CN` → `DIRECT` |
| 其他走最快 | `FINAL,Fast`（`gfw` / `greatfire` / `tld-not-cn` / `Telegram` 也指向 `Fast`） |
| 早报走香港 | `zaobao.com` / `zaobao.com.sg` → `香港智能` |

已用 33 个代表性域名做过完整匹配链模拟，全部符合预期。

### 两个有意为之的决定

**Google 全量走 AI，YouTube 例外。** 与桌面端对齐：`Google.list`（698 条）指向 `AI`，Gmail、Drive、Maps、Search 等都走 AI 专用线路。YouTube 系 9 个域名在其之前显式指向 `Fast`，且 `Google.list` 本身不含任何 youtube 域名，两者不冲突。

**稳定优先于速度。** 用户明确「节点慢一点也比不能访问好」，故 AI 线路按出口稳定性取舍：

- **AI 组使用 `interval=21600`、`tolerance=100`** — 每 6 小时重新测速，仅在新节点明显更快时切换，减少 Google/AI 服务的出口 IP 抖动。`Fast` 和 `香港智能` 仍使用 300 秒；`Fast` 只在四个实测优选节点间切换。
- **DNS 只用国内 DoH** — 手册明确「DNS 覆写仅针对直连类域名进行解析，代理类域名将经由代理服务器进行解析」。境外域名由节点侧解析，本地配境外 DoH 既不参与解析、也防不了污染。实测 `cloudflare-dns.com` 直连不通、`dns.google` 每次超时 8 秒，并发查询时这些失败连接持续消耗电量和 NE 资源。
- **不启用 `block-quic`** — 原设 `all-proxy` 会让每条连接先尝试 QUIC 再回落 HTTP2/1.1，闲置唤醒后重连更慢。交给系统自行协商。

> 桌面端不同：那里 `fallback` + 境外 DoH 是有效的，因为 mihomo 的 `fallback` 机制会对境外域名主动使用境外 DNS，与 Shadowrocket 的「代理域名交给节点解析」是两套不同设计。

**`PROXY` 组不被任何规则引用。** 它是 `select` 类型，留作需要临时手动指定线路时的入口。所有自动分流都直接指向 `Fast` / `AI` / `香港智能` / `DIRECT`，语义明确。

**`Fast` 只让四个实测优选节点参与竞速。** 当前白名单为 `🇭🇰 香港05`、`🇭🇰香港04`、`🇯🇵 日本5`、`🇸🇬 新加坡[CM]`。它们经过独立、多轮的连通性与实际传输测试；精确名称匹配可避免延迟正常但访问不稳定的其他节点再次进入自动选择。

上游订阅更新后，如果节点被改名或移除，精确白名单不会自动纳入替代节点；届时重新测试并更新名单。这里不增加全节点逃生入口。

**三个 url-test 组都不会命中机场自带的策略组名。** `Fast` 使用精确节点名白名单，`香港智能` 使用负向断言排除「智能」「专用」，`AI` 的地区关键词也不会命中「AI专用」等机场预设组，避免在 `url-test` 里嵌套其他分组。

## 自定义线路（桌面端没有，如需一致请同步）

| 域名 | 策略 | 原因 |
|---|---|---|
| `deepseek.com` | DIRECT | 上游 AI 规则集只收录海外 AI，不含 DeepSeek |
| `youtube.com` 等 9 个域名 | Fast | 显式置于 `gfw` 规则集之前，避免被其覆盖 |

## 与桌面配置的已知差异

桌面是 `~/.config/clash.meta/config.yaml`（ClashX Meta，本地文件模式）。两端规则同源但不逐条相同：

| 项 | 桌面 | 手机 | 原因 |
|---|---|---|---|
| 广告拦截 | Loyalsoldier `reject` (6.5MB) | blackmatrix7 `Advertising` (27KB) | 手机不适合拉 6.5MB |
| 国内域名直连 | Loyalsoldier `direct` (3MB) | blackmatrix7 `China_Domain` (51KB) | 同上；覆盖面有细微出入，少数长尾国内域名可能落到代理 |
| 国内 IP | `cncidr` 规则集 + `GEOIP,CN` | 仅 `GEOIP,CN` | 精简 |
| 需代理域名 | 含 `proxy` 规则集 (776KB) | 省略 | 兜底本来就是代理，删掉不改变结果 |
| Google 全量 | `GEOSITE,google` → AI | `Google.list` → AI | 已同步，两端一致 |
| 兜底策略 | `MATCH,PROXY`（select 组） | `FINAL,Fast`（直接指向最快） | 语义更贴合「其他走最快」 |
| `Fast` 节点范围 | 同为香港05、香港04、日本5、新加坡 `[CM]` | 同左 | 已同步，两端一致 |

### 关于机场自带的策略组

机场的 Clash YAML 订阅里带 4 个自己的策略组：`Ghelper`、`🌐 全球智能`（25 节点）、`🇭🇰 香港智能`（8 节点）、`AI专用`（19 节点）。**两端都没有使用它们**，原因：

- **手机端拿不到。** base64 订阅（`/subs/shadowrocket/`）只含 34 行纯节点 URI，不含任何策略组——这个结构承载不了 mihomo 的 `proxy-groups`。
- **桌面端也拿不到。** `proxy-providers` 只导入订阅的 `proxies` 段，`proxy-groups` 不会被引入。所以两端的 `filter` / `policy-regex-filter` 都不存在误收机场策略组的风险（`Fast` 和 `香港智能` 的负向断言属于冗余防护，保留以防订阅格式变化）。
- **即便能用也不合适。** 机场的 `AI专用` 还包含英国、法国、美国硅谷等范围外节点，不符合当前 AI 分组范围；机场预设组的 `interval` 为 7200s，节点质量波动要等最多两小时才切换，我们的 `AI` 组改为 21600s 以减少出口 IP 抖动。
| 进程分流 | `applications` (PROCESS-NAME) | 无 | iOS 没有进程级分流，无解 |
| DNS | 公司内网 DNS | 公共 DoH | 内网 DNS 在外网不通 |

改桌面规则时记得同步改这里（反之亦然）。想彻底消除差异，需要改成「单一真源 + GitHub Actions 生成两端产物」的方案。

## 上游规则集

- [VPSDance/ai-proxy-rules](https://github.com/VPSDance/ai-proxy-rules) —— AI 服务域名
- [Loyalsoldier/surge-rules](https://github.com/Loyalsoldier/surge-rules) —— 桌面 clash-rules 的 Surge 格式平行仓库
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) —— iOS 场景规则集
