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
| `Fast` | url-test | 近距离地区（港/日/新/台/韩）里选延迟最低 |
| `AI-USA` | url-test | 只筛美国节点，AI 服务专用 |
| `香港智能` | url-test | 只筛香港节点 |
| `PROXY` | select | 手动干预入口，不被规则引用 |

## 设计目标

四条核心诉求，规则严格对应：

| 诉求 | 实现方式 |
|---|---|
| AI 走美国 | `ai-proxy-rules/global.list` → `AI-USA` |
| 国内走直连 | `China_Domain` + `icloud` + `apple` + `GEOIP,CN` → `DIRECT` |
| 其他走最快 | `FINAL,Fast`（`gfw` / `greatfire` / `tld-not-cn` / `Telegram` 也指向 `Fast`） |
| 早报走香港 | `zaobao.com` / `zaobao.com.sg` → `香港智能` |

已用 33 个代表性域名做过完整匹配链模拟，全部符合预期。

### 两个有意为之的决定

**不挂全量 Google 规则集。** AI 规则集已完整收录 Gemini、AI Studio、NotebookLM、Jules、Labs 等 Google AI 域名，再挂 698 条的 `Google.list` 只会把 Gmail、Drive、Maps、blogspot 一并绕去美国，与「AI 走美国」的诉求不符。桌面配置里的 `GEOSITE,google → AI-USA` 按同一标准看也是过宽的。

**`PROXY` 组不被任何规则引用。** 它是 `select` 类型，留作需要临时手动指定线路时的入口。所有自动分流都直接指向 `Fast` / `AI-USA` / `香港智能` / `DIRECT`，语义明确。

**`Fast` 只让近距离地区参与竞速。** 原先用 `.*` 匹配全部 41 个节点，其中含 12 个美国节点。`url-test` 只按延迟排序，而延迟低不代表带宽大——实际使用中跨太平洋节点常被选中，导致刷 X、看视频卡顿（实测 x.com 被分到「美国西雅图2」）。收窄到港/日/新/台/韩 16 个节点后，`Fast` 才真正接近「最快」的本意。

代价：这五个地区节点全部不可用时 `Fast` 无节点可选。此时可用 `PROXY` 组手动切到 `AI-USA`。

**三个 url-test 组都排除了机场自带的策略组名。** 订阅里除节点外还有「🇭🇰 香港智能」「🌐 全球智能」「AI专用」等机场预设分组，以及 `updates.cdn-apple.com` 这类非节点条目。纯关键词匹配会把它们收进来，而手册明确不建议在 `url-test` 里嵌套其他分组。故正则末尾统一加了 `^((?!(智能|专用)).)*$` 负向断言。

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
| Google 全量 | `GEOSITE,google` → AI-USA | 无此规则 | 与「AI 走美国」诉求不符，见上方说明 |
| 兜底策略 | `MATCH,PROXY`（select 组） | `FINAL,Fast`（直接指向最快） | 语义更贴合「其他走最快」 |
| `Fast` 节点范围 | 同为港/日/新/台/韩 16 个 | 同左 | 已同步，两端一致 |

### 关于机场自带的策略组

机场的 Clash YAML 订阅里带 4 个自己的策略组：`Ghelper`、`🌐 全球智能`（25 节点）、`🇭🇰 香港智能`（8 节点）、`AI专用`（19 节点）。**两端都没有使用它们**，原因：

- **手机端拿不到。** base64 订阅（`/subs/shadowrocket/`）只含 34 行纯节点 URI，不含任何策略组——这个结构承载不了 mihomo 的 `proxy-groups`。
- **桌面端也拿不到。** `proxy-providers` 只导入订阅的 `proxies` 段，`proxy-groups` 不会被引入。所以两端的 `filter` / `policy-regex-filter` 都不存在误收机场策略组的风险（负向断言 `(?!(智能|专用))` 属于冗余防护，保留以防订阅格式变化）。
- **即便能用也不合适。** `AI专用` 含英国、法国、日本、新加坡，19 个里只有 11 个美国节点，与「AI 走美国」的诉求不符；`全球智能` 含美国节点，正是会导致刷 X 卡顿的那类配置；三个组的 `interval` 都是 7200s，节点质量波动要等最多两小时才切换（我们是 300s）。
| 进程分流 | `applications` (PROCESS-NAME) | 无 | iOS 没有进程级分流，无解 |
| DNS | 公司内网 DNS | 公共 DoH | 内网 DNS 在外网不通 |

改桌面规则时记得同步改这里（反之亦然）。想彻底消除差异，需要改成「单一真源 + GitHub Actions 生成两端产物」的方案。

## 上游规则集

- [VPSDance/ai-proxy-rules](https://github.com/VPSDance/ai-proxy-rules) —— AI 服务域名
- [Loyalsoldier/surge-rules](https://github.com/Loyalsoldier/surge-rules) —— 桌面 clash-rules 的 Surge 格式平行仓库
- [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) —— iOS 场景规则集
