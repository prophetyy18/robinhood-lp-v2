# 链上经验存档

> 这份文档只保留**链上与协议知识**——那些只有真金白银才能买到的东西。
>
> 不含流程教训：那些属于开发方法，不属于链上。
> 来源：`prophetyy18/robin-lp`，HEAD `77d292a`（2026-09-27），15 天实测。
> 所有数值来自对仓库的实际读取，非转抄。

---

## 一、部署事实（已验证）

```
chain_id (mainnet)     4663          0x1237
chain_id (testnet)    46630
PoolManager  0x8366a39cc670b4001a1121b8f6a443a643e40951    两网同址（CREATE2）
StateView    0xf3334192d15450cdd385c8b70e03f9a6bd9e673b
```

**2026-09-28 实测的字节码哈希**（官网与 Alchemy 两端点一致）：

| | bytes | keccak256 |
|---|---|---|
| PoolManager (mainnet) | 24,009 | `bd3881180b547f5fe817545743cfb4343e96b1bc6640dcd70c106b0066e95626` |
| StateView (mainnet) | 3,531 | `7d9c591e0956fd89d98feb4ffcfe8bf1f7a62bd485edd979fa21d104b49878a6` |
| PoolManager (testnet) | — | `6eb21c69298b064e37fcf8089a941ae096fe08c0f179b2d399567aef1b10585b` |
| StateView (testnet) | — | `60cd24035661345b74c14895a641420f2598f910e376fb3f115bbd6bf504c8c0` |

同地址不同字节码——CREATE2 只保证地址，不保证代码。**跨链复用地址时必须分别钉代码。**

⚠️ 一个会静默出错的点：Python 标准库的 `hashlib.sha3_256` 是 **SHA3，不是 keccak**。
Uniswap 一律用 keccak256，两者输出完全不同但都不报错。必须用 `pycryptodome.keccak`
或 `eth-hash[pycryptodome]`。

---

## 二、Provider 能力实测（免费方案的真实天花板）

2026-09-16/17 实测，Robinhood Chain mainnet，A=官网公开 RPC，B=Alchemy Free。

| 能力 | A 官网 | B Alchemy Free |
|---|---|---|
| chain_id / 区块头 / receipt | ✓ | ✓ |
| `eth_getLogs` 区块跨度 | 100,000 块 | **最多 10 块** |
| 100 万块前的 `eth_call` 历史状态 | **不可用** | ✓ |
| JSON-RPC 批量 `eth_getBlockByNumber` | ✓ | ✓ |

**这个错配决定整个采集形态**：A 做宽范围扫描，B 做高密度窄范围回填，
或只用于抽样交叉验证。不测一次就写进来，入库跑到一半必然卡死。

### 官网端点还有四个坑

1. **`eth_getLogs` 的 `blockTimestamp` 恒为 `0x0`** —— 不能当时间源，
   必须走 `eth_getBlockByNumber`。
2. **全链范围的五 topic0 OR 查询会超时**（`-32000 log query timed out`）。
3. **单事件类型全范围查询会被拒**（`-32000 logs matched by query exceeds limit of 10000`）。
4. **连续快速调用触发 HTTP 429**，即使不是极端速率也会。

另外一个隐蔽的：urllib 默认 User-Agent 被官网返回 **HTTP 403**，httpx 正常。
传输层的 header 必须显式设置——这类问题不测就永远不知道为什么"官方端点不通"。

### 一条实测有效的查询形态

单个池过滤查询可以覆盖百万区块：

```
filter: [[5 个 topic0], poolId]   区块 54946237..55946237（1,000,001 块）
→ 一次调用返回 3739 事件 / 3266 个不同区块
   Initialize 1 · ModifyLiquidity 578 · Swap 3159 · ProtocolFeeUpdated 1 · Donate 0
```

即：**按池过滤 + 大跨度，胜过按事件类型 + 小跨度。**

---

## 三、Uniswap V4 协议事实

来源：`Uniswap/v4-core` @ `e50237c43811bd9b526eff40f26772152a42daba`

### PoolKey 与 PoolId

```solidity
struct PoolKey {
    Currency currency0;  // address
    Currency currency1;  // address
    uint24     fee;
    int24      tickSpacing;
    IHooks     hooks;    // address
}
PoolId = keccak256(abi.encode(PoolKey))   // 0xa0 = 160 字节 = 5 槽 × 32
```

- **`currency0 < currency1` 按 uint160 无符号比较**。`toId` 本身不校验顺序，
  但规范池要求有序——哈希前必须自己校验。
- ABI 编码规则：`Currency`/`hooks` 左填充到 32 字节；`uint24 fee` 左填充；
  **`int24 tickSpacing` 需要符号扩展到 int256**（右填充 0xff）。这一步最容易错。
- `Currency.wrap(address(0))` 是原生币。

**V4 的池不是合约**——它是 `PoolManager` 里的一个 `PoolId`。所以：

- 不存在"池地址"这种输入形式。任何 20 字节地址都必须明确拒绝，不能猜测或兜底。
- `PoolId` 不可逆。要解出 `PoolKey`，必须扫 `Initialize` 事件。
- 一个 token 可以对应多个 `PoolKey`（不同配对 token / fee / tickSpacing / hooks），
  它们是不同的池，风险不同。

### TickMath

| 常量 | 值 |
|---|---|
| `MIN_TICK` | `-887272` |
| `MAX_TICK` | `887272` |
| `MIN_TICK_SPACING` | `1` |
| `MAX_TICK_SPACING` | `32767` |

```text
maxUsableTick(s) = (MAX_TICK // s) * s
minUsableTick(s) = truncTowardZero(MIN_TICK / s) * s
```

⚠️ **Solidity 向零取整，Python `//` 向下取整**。负数上两者结果不同：

```python
# Python 正确写法
min_usable = -((-MIN_TICK) // spacing) * spacing
```

这个差异不会报错，只会算错。

### LP Fee 常量

| 常量 | 值 |
|---|---|
| `MAX_LP_FEE` | `1_000_000`（100%） |
| `DYNAMIC_FEE_FLAG` | `0x800000`（bit 23，**精确相等**而非范围） |
| `OVERRIDE_FEE_FLAG` | `0x400000`（bit 22，`beforeSwap` 发出） |

`isDynamicFee(fee)` 是 `fee == DYNAMIC_FEE_FLAG`，不是 `>=`。

### Hook 地址有效性

`ALL_HOOK_MASK = (1 << 14) - 1`——地址低 14 位是 hook 权限位。

规则（来自 `Hooks.sol`）：
1. 每个 `*_RETURNS_DELTA_FLAG`（bit 0-3）必须配对应的 action flag（bit 4-11）。
2. `hooks == address(0)` 时，**fee 不能是 dynamic**。
3. `hooks != address(0)` 时，低 14 位必须**全为 0** **或** fee 是 dynamic。

bit 顺序（高位→低位）：
```
13 BEFORE_INITIALIZE       12 AFTER_INITIALIZE
11 BEFORE_ADD_LIQUIDITY    10 AFTER_ADD_LIQUIDITY
 9 BEFORE_REMOVE_LIQUIDITY  8 AFTER_REMOVE_LIQUIDITY
 7 BEFORE_SWAP              6 AFTER_SWAP
 5 BEFORE_DONATE            4 AFTER_DONATE
 3 BEFORE_SWAP_RETURNS_DELTA     2 AFTER_SWAP_RETURNS_DELTA
 1 AFTER_ADD_LIQUIDITY_RETURNS_DELTA   0 AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA
```

---

## 四、LP 度量学：最容易算错的地方

这部分是最贵的经验。以下每一条都对应一类"数字看起来对、但回答的不是你的问题"的失败。

### 费用必须积分，不能估算

```text
fees(L) = L × Σ ΔfeeGrowthInside / 2^128
```

该量对 `L` 线性，所以**一次事件遍历即可得到任意 L 的精确历史费用**，
对 tick 做前缀和后任意候选区间都是 O(1)。

动态费率和 hook 抽成会被自动吸收，因为它们已体现在 `feeGrowthInside` 的增量里。

❌ **禁止**用"自身份额 × 区间总成交量 × 费率"估算历史费用。那是预测模型，不是回放结果。

### 份额分母只能用历史 active liquidity

```text
share = L / (L_active_historical + L)
```

自身的虚拟仓位不存在于历史中，**不得进入历史分母**。
同时也不得假设加入 L 后其它流动性不变而重复计算两次。

### 三个价值量必须分列，不能合并

| 量 | 含义 |
|---|---|
| `marked_pnl` | 按合格 point-in-time 价格证据估值 |
| `liquidatable_pnl` | 按当时可执行退出路径 + 深度 + fee + 滑点 + 税费 + hook + Gas 估算 |
| `lp_service_pnl` | fee + 激励 + hook credit − LVR − 执行成本 |

缺少合格证据时显示 `UNAVAILABLE`，**不得用 spot price 顶替**。
把标记价值当可实现价值报告，是最常见也最难发现的错误。

### LP 没有真实价格序列，所以 LVR 只能是代理

在本项目的单场所条件下不存在独立的参考价格。所以：

- 只能给出**再平衡损失代理**，参照基准是"理想无成本再平衡"路径；
- 必须显式标注为代理、声明基准构造方式；
- **不得声称测量了真实 LVR**，不得跨不同基准比较。

### 盈亏平衡波动率 —— 唯一直接回答"值不值得做"的标量

```text
breakeven_vol 满足  fees(range, window) = LVR_proxy(range, window)
```

应从回放自身产生的费用序列与再平衡成本序列**反解**，而不是套解析近似；
近似公式可以用于交叉检查，但必须同时给出。

当期已实现波动率低于它 → 区间 LP 有正的费用边际；高于 → 费用不足以覆盖库存风险。

### 资金效率只有一个可接受的定义

**每单位最坏单边库存资金产生的费用收入**。

"最坏单边库存"= 价格到达区间任一端后该仓位持有的单侧数量。

不接受其它定义，也**不得把 `liquidityDelta` 直接当作资金**——那是流动性不是钱。

### 统计单位是 episode，不是日历天

LP 的统计单位是**一次完整持仓生命周期**。日历聚合会掩盖收益的时间集中性，
只能作为辅助视图。

任何比较必须报告背后的独立 episode 数量，样本不足时输出 `UNCERTAIN`，
不得用点估计代替。

### 净收益公式里的"只算一次"

```text
PnL_USDG(a, ω) = final_principal_liquidatable_value
               + fees + explicit_incentives + hook_net_credits
               - initial_cash
               - entry_swap_cost - gas - slippage_mev_tax
               - rebalance_cost - exit_cost
```

`gas_usdg` 汇总所有阶段 Gas，其他 entry/rebalance/exit 字段**不得再次包含 Gas**。
每项价值和成本只允许出现一次——报告必须通过对账发现重复或漏计。

---

## 五、计价：USDG 层级与 RELATIVE_ONLY

- **USDG 是唯一主要计价单位**。保留原始 token 整数数量。
- 目标 token 是 LP 期间承担的库存，**不把"依赖 token 上涨"当作策略成立的假设**。
- 主要基准是"保持 USDG 不动"，不是 HODL token。HODL 与理想再平衡基准用于归因，
  不能替代 USDG cash benchmark。

层级：USDG 优先 → 合格 USD 稳定币 → ETH（仅标注的波动计价展示）。

既无 USD 族资产又无合格兑换路径的数据集，只能输出 `RELATIVE_ONLY`。
**`RELATIVE_ONLY` 的结果不得以任何美元符号或 USD 计价字段出现，
不得与 USD 计价结果并列排名。**

---

## 六、准入：技术门槛 vs 项目风险（双轨）

V1 把这两件事拆开，因为它们的失败模式完全不同。

**技术门槛（`ADM-TECH-*`，硬性，失败即阻止）**

关键几条：
- `ADM-TECH-002` **Metadata 不作为身份**——symbol、名字都是展示信息，
  身份必须来自地址 + 代码。
- `ADM-TECH-003` **实际执行代码可确定**——proxied / upgradeable 的要能钉到具体实现。
- `ADM-TECH-004` **行为必须可理解和建模**——未知 hook 结算行为不具备策略资格。
- `ADM-TECH-007/009/010` **身份或权限变化使审批失效**，审批必须绑定当前版本。
- `ADM-POOL-001` **PoolKey 独立身份**——同一个 token 的不同池是不同的审批对象。
- `ADM-HOOK-003` **未知或无法建模的 Hook** 直接不合格。

**项目风险（`ADM-RISK-*`，展示 + 用户决定）**

- `ADM-RISK-001` 已知管理权限**完整展示**（不隐藏）。
- `ADM-RISK-002` **不替用户作项目风险决定**。
- `ADM-RISK-003` Holder 与供应信息 best-effort，**缺失不伪造精确概率**。

配对资产也必须**独立审批**（`ADM-PAIR-001`）——不能因为目标 token 合格
就假定配对 token 也合格。

---

## 七、链上威胁清单（22 条中最关键的）

从 `THREAT_MODEL.md` 提取出对设计影响最大的几条：

| 编号 | 威胁 | 对设计的影响 |
|---|---|---|
| T-01 | RPC 返回伪造数据 | 至少两个独立 provider 交叉验证；记录 source URL / chain ID / block / code hash |
| T-02 | Reorg 使已终局数据失效 | 按终局窗口钉住采集范围，不要边采边用 |
| T-03 | 未知或升级的 hook 改变池经济 | hook 变化使 pool 审批失效，需重新准入 |
| T-08 | 畸形或超大日志导致 DoS | 必须在 RPC 边界限制大小，不是业务层处理 |
| T-11 | 进程内时钟偏移或非单调 | 回放只能用 event time，不能用 wall clock |
| T-16 | USDG 估值被操纵或不可得 | 估值资格与展示资格分离，`UNAVAILABLE` 不许顶替 |
| T-17 | 研究面板的标签泄漏或前视 | 面板构建必须 point-in-time，决策时刻之后的数据一律不可用 |
| T-18 | `RELATIVE_ONLY` 被当成 USD 读取 | 计价层级是类型，不是字段 |
| T-19 | 研究产物或模型获得执行权 | 研究宇宙与执行范围必须类型级隔离，不是运行时开关 |
| T-21 | 数据集版本 / 计价 / 切分边界被改 | 发布的数据集版本不可变 |

T-19 值得单独强调：**"研究范围可以多池，执行范围只能单池"是类型隔离，
不是配置开关。** 一个运行时开关总会被某个 feature flag 打开。

---

## 八、存储与数据可信性

- **原始数据和审计事件只追加**，不覆盖不删除，不用插值补空缺。
- 错误必须保留 chain / PoolKey / block 范围 / endpoint / 尝试次数 / 原因，
  但脱敏密钥。
- 事件位置 `(block_number, transaction_index, log_index)` 必须持久化——
  没有它就无法确定性重建。
- 区块时间从 `eth_getBlockByNumber` 取，不用日志字段。

**一条真实事故**：2026-09-18 的参考运行 `run-680e65f4a59842d98b1712a45280779d`
中，`event_index` 记录 3,739 行 / 3,266 个事件块，而 Parquet 分区里只有
3,737 行 / 3,264 个——**丢了两行，没有任何报错**。

原因是当一个采集区间写入另一个区间已建好的分区单元格时。

结论：**写入必须对账。**"我以为写进去了"不成立，只有计数能证明。

---

## 九、账户与本地存储的对抗威胁

- 本地"只追加"存储可被篡改（T-09）：需要独立校验锚点，不能只信自己的文件。
- 完成的运行可被替换市场状态重放（T-22）：需要把运行与其输入快照绑定。
- 时钟偏移（T-11）：回放与回测只能用 event time，禁止 wall clock 和未播种随机。

---

## 附：验证方式

本文档所有数值来自对 `robin-lp` HEAD `77d292a` 的实际读取：
`PROTOCOL_FACTS.md` / `PROVIDER_FACTS.md` / `LP_METRICS.md` /
`STRATEGY_ECONOMICS.md` / `ASSET_ADMISSION.md` / `THREAT_MODEL.md` 的正文，
以及 protocol-artifacts 下的实测 JSON。

mainnet 字节码哈希是 2026-09-28 在本文档写作时实测的，两个 provider 一致。
