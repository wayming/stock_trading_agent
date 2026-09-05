# News Analysis Workflow — Graph Flow

## Pipeline Overview
```mermaid
%%{init: {"flowchart": {"defaultRenderer": "elk"}}, "themeVariables": {"fontSize": "15px"}}}%%
flowchart TB

    %% ═══════════════ Styles ═══════════════

    classDef entry fill:#2e7d32,color:#fff,stroke:#1b5e20
    classDef router fill:#e65100,color:#fff,stroke:#bf360c
    classDef analysis fill:#1565c0,color:#fff,stroke:#0d47a1
    classDef debate fill:#00838f,color:#fff,stroke:#006064
    classDef judge fill:#6a1b9a,color:#fff,stroke:#4a148c
    classDef terminal fill:#546e7a,color:#fff,stroke:#37474f
    classDef skip fill:#c62828,color:#fff,stroke:#b71c1c 

    %% ═══════════════ 1. Entry & Identification ═══════════════

    subgraph A ["1. Entry & Target Identification"]
        direction LR

        receive_news["receive_news<br/>加载配置 & 接收新闻"]:::entry
        classify_news["classify_news<br/>Flash 分类<br/>(Noise / Company / Industry / Macro)"]:::entry
        identify_stock["identify_stock<br/>分析最受益 / 强相关<br/>做多标的"]:::analysis
        end1((END)):::terminal
        next1((NEXT PHASE)):::entry
        process_symbol_gate{"成功找到标的?"}:::router
        receive_news --> classify_news

        classify_news -- "Industry / Macro" --> identify_stock
        classify_news -- "Noise" --> end1
        classify_news -- "有 Symbol" --> process_symbol_gate
        
        identify_stock --> process_symbol_gate
    
        process_symbol_gate -- "否" --> end1
        process_symbol_gate -- "是" --> next1

    end
    A --> B

    %% ═══════════════ 2. Fast Screening Gate ═══════════════

    subgraph B ["2. Long-Only Gate"]
        direction LR

        bull_bear_classifier["bull_bear_classifier<br/>单轮偏多 / 偏空分类<br/>(Fast Model)"]:::analysis
        end2((END)):::terminal
        next2((NEXT PHASE)):::entry
        bullish_gate{"是否看多<br/>(Bullish)?"}:::router

        bull_bear_classifier --> bullish_gate

        bullish_gate -- "否 (Bearish / Neutral)" --> end2
        bullish_gate -- "是 (Bullish)" --> next2
    end
    B --> C

    %% ═══════════════ 3. Data Enrichment ═══════════════

    subgraph C ["3. Data Enrichment (Bullish Only)"]
        direction LR

        fetch_mcp_fundamentals["fetch_mcp_fundamentals<br/>调取 MCP 基本面 / 财务指标"]:::analysis
        fetch_news_context["fetch_news_context<br/>搜索近 6 个月<br/>相关历史新闻"]:::analysis
        data_aggregator["data_aggregator<br/>打包完整 Context 简报"]:::analysis

        fetch_mcp_fundamentals --> data_aggregator
        fetch_news_context --> data_aggregator

    end
    C --> D

    %% ═══════════════ 4. Multi-Agent Debate ═══════════════

    subgraph D ["4. Debate Pipeline"]
        direction TB

        debate_coordinator["debate_coordinator<br/>接收丰富 Context<br/>控制 Debate"]:::debate

        bull_advocate["bull_advocate<br/>构建多头逻辑<br/>与催化剂"]:::debate
        conservative_bull["conservative_bull<br/>挑战乐观预期<br/>评估下行风险"]:::debate
        neutral_reality_check["neutral_reality_check<br/>结合基本面做<br/>Reality Check"]:::debate
        route_debate_agents["route_debate<br/>指定 Agent<br/>追问 / 反驳"]:::debate

        continue_debate_gate{"是否继续辩论?"}:::router
        next4((NEXT PHASE)):::entry

        debate_coordinator --"发言"a--> bull_advocate
        debate_coordinator --"发言"--> conservative_bull
        debate_coordinator --"发言"--> neutral_reality_check

        debate_coordinator --> continue_debate_gate
        continue_debate_gate -- "是" --> route_debate_agents
        continue_debate_gate -- "READY / Max rounds" --> next4
        route_debate_agents --> debate_coordinator

    end
    D --> E

    %% ═══════════════ 5. Final Decision ═══════════════

    subgraph E ["5. Final Decision & Trade Execution"]
        direction LR

        final_judge["final_judge<br/>独立裁决<br/>确认买入信号与仓位建议"]:::judge
        evaluate_trade["evaluate_trade<br/>生成交易指令<br/>(BUY / NONE)"]:::terminal

        final_judge --> evaluate_trade

    end
    
    E --> END((END)):::terminal
  
```

## 节点详解

### 1. `receive_news`
**文件**: [`nodes/setup.py`](nodes/setup.py)

- 从数据库加载 LLM 配置（API URL、Key、Model、MCP URL 等）
- 初始化 state 中的配置字段
- 如果 `llm_enabled=false`，清空所有 LLM URL，后续全部走 keyword fallback

### 2. `classify_news`
**文件**: [`nodes/filtering.py`](nodes/filtering.py)

- 用 **flash model**（快速模型）对新闻做四分类：
  - **Noise**（价格波动/市场回顾）→ 跳过
  - **Macro**（宏观经济/货币政策/地缘政治）→ 跳过
  - **Company**（公司具体事件）→ 继续分析
  - **Industry**（行业/板块事件）→ 需要先识别最佳标的
- 失败回退：LLM 不可用时新闻直接通过

### 3. `route_after_classify`
**文件**: [`nodes/filtering.py`](nodes/filtering.py)

条件路由，三条路径：

| 条件 | 目标 |
|---|---|
| Noise 或 Macro | `skip_to_end` |
| 有 symbol | `build_prompt` |
| 仅有 exchange | `identify_stock` |

### 4. `identify_stock`
**文件**: [`nodes/stock_identification.py`](nodes/stock_identification.py)

- 仅给出交易所（无具体股票代码）时调用
- LLM 根据新闻内容，在指定交易所中选出 **最受益的一只股票**
- 选中标准：最直接的盈利受益 + 最大市值 + 最高流动性
- 找不到合适标的 → 标记 `_filtered=True`

### 5. `route_after_identify`
**文件**: [`nodes/stock_identification.py`](nodes/stock_identification.py)

| 条件 | 目标 |
|---|---|
| 找到股票 | `build_prompt` |
| 未找到 | `skip_to_end` |

### 6. `skip_to_end`
**文件**: [`nodes/skip.py`](nodes/skip.py)

- 快速出口：不调用 LLM，直接返回 `neutral` + `confidence=0.3`
- 根据分类/识别阶段给出的理由生成上下文合理的说明

### 7. `build_prompt`
**文件**: [`nodes/prompt_building.py`](nodes/prompt_building.py)

- 构建 system prompt 和 user message
- 初始化对话历史 `state["messages"]`

### 8. `fetch_news_context`
**文件**: [`nodes/news_context.py`](nodes/news_context.py)

- 调用**独立的 context LLM**（可配置不同模型）搜索该股票近 6 个月的：
  - ✅ 正面事件（业绩超预期、合同、产品发布等）
  - ❌ 负面事件（监管罚款、业绩不及预期、产品召回等）
- 结果注入到对话的 user message 中，供 agent_node 参考

### 9. `agent_node`
**文件**: [`nodes/agent_loop.py`](nodes/agent_loop.py)

- 核心 LLM 调用节点，**可重入**（循环中每次回到这里都重新调用 LLM）
- 带 MCP 工具定义（`list_metrics`、`get_data_period`、`get_financials`）
- 如果 LLM 返回 `tool_calls` → 路由到 `execute_tools`
- 如果 LLM 返回纯文本 → 路由到 `parse_response`（退出循环）
- 无 LLM 时走 keyword fallback

### 10. `execute_tools`
**文件**: [`nodes/agent_loop.py`](nodes/agent_loop.py)

- 遍历所有待执行的 tool_calls
- 调用 MCP 工具（通过 [`tools/mcp_executor.py`](tools/mcp_executor.py)）
- 将结果追加到对话历史，`round_count += 1`
- 无条件回到 `agent_node`

### 11. `should_continue`
**文件**: [`nodes/agent_loop.py`](nodes/agent_loop.py)

循环控制逻辑：

| 条件 | 路由 |
|---|---|
| `tool_calls` 存在 且 `round_count < 5` | `execute_tools` |
| 否则 | `parse_response` |

### 12. `parse_response`
**文件**: [`nodes/output.py`](nodes/output.py)

- 从 LLM 原始响应中提取 JSON
- 验证 sentiment 值在 `SentimentLevel` 枚举中
- 解析出 `sentiment`、`confidence_score`、`reasoning`、`selected_symbol`

### 13. `evaluate_trade`
**文件**: [`nodes/output.py`](nodes/output.py)

情感 → 交易动作映射：

| Sentiment | TradeAction |
|---|---|
| 超级利好 | `BUY` |
| 超级利空 | `SHORT` |
| 其他 | `NONE` |

## 关键设计决策

### 双 LLM 分层架构

| 层 | 模型 | 用途 |
|---|---|---|
| Flash（快速） | `llm_flash_model` | 新闻分类 + 标的识别（低延迟、低成本） |
| Main（主力） | `llm_model` | 深度分析 + MCP 工具调用 |
| Context（上下文） | `context_llm_model` | 历史新闻检索 |

### Agent 工具循环

```python
MAX_TOOL_ROUNDS = 5  # 防止无限循环
```

LLM 可以在一次分析中多次调用 MCP 工具（比如先 `list_metrics`，再根据结果用特定指标调 `get_financials`），每次工具结果都追加到对话历史中送回 LLM，形成 ReAct 风格的推理循环。

### 快速跳过路径

Noise 和 Macro 类新闻不进入分析管线，在 `classify_news` 阶段就被拦截，直接走 `skip_to_end` → `evaluate_trade` → `END`，节省 LLM 调用成本。
