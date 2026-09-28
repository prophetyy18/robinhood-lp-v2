# Current hypothesis

<!-- Rewritten every round. Keep this file short enough to read in a minute.
     History belongs in LOG.md; settled choices belong in DECISIONS.md.
     Verify the shape with: python -m tools.prophet check -->

**Round:** R1
**Tier:** 0 — 探索级。不产生产品代码，只验证常量。worktree 可有可无。
**Rollback:** n/a（无副作用，只读链上）

## Hypothesis

**Change:** 把协议常量写成代码：部署地址与 code hash、5 个事件的 topic0、
PoolId 的 ABI 编码；并写一个探针命令，用它反解 V1 记录的那个 PoolId
**Outcome:** 探针从 `0x6c61…43ed` 反解出 USDG/ZZZ + fee 28001 + spacing 280 +
hooks 0x0，并在链上定位到 Initialize 事件于 block 54938045（0x34669bd）；
任一项不匹配则退出码非 0
**Verify by:** `python -m robinhood_lp_v2.probe`

## 为什么不直接做 MVP

MVP 是"单池单次持仓回放"。但它站在这些常量上。

今天手工查这个池时，我连错两次：第一次 `Initialize` 签名漏了 `currency1`，
第二次把 `PoolId` 写成 `address` 而非 `bytes32`。两次都返回**合法的空结果**，
不是错误。如果那是代码，症状会是"链上没有数据"，然后 debug 半天。

V1 里这些常量全是手抄的散落文档，没有一处代码保证它对。
R1 把它们变成会崩的代码——不是流程洁癖，是修一个已发生的失败模式。

## Slice scope

**In scope:**
- `src/robinhood_lp_v2/` 下的地址、hash、topic0、PoolId 编码
- 探针命令：反解 + 链上定位 Initialize
- 单元测试：PoolId 编码、topic0 计算、已知的反例

**Out of scope:**
- 任何池发现、扫描、历史数据
- 回测、费用积分、LP 度量
- Web 界面
- 签名、私钥、任何写操作

## 已知风险

- **Alchemy Free 的 `eth_getLogs` 只能取 10 个块**。本轮只需定位单个事件，
  用官网端点即可，Alchemy 仅作交叉验证。
- **官网 `blockTimestamp` 恒为 `0x0`**。探针不得依赖它取时间，
  需要时间就走 `eth_getBlockByNumber`。
- **两个 provider 的链高会差几个块**。若交叉验证要求同一 block，
  必须显式钉住块号，不能各取 latest。
- topic0 若从手抄的签名算错，探针会"成功"地报告池不存在。
  所以反解必须**双向**验证：PoolId → PoolKey → 重算 PoolId 必须回到原值。
