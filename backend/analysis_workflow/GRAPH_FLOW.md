# News Analysis Workflow — Architecture & Node Specification

## Overview

The **News Analysis Workflow** is a **Long-Only, News-Driven Stock Opportunity Discovery System**.

Its goal is not to predict the direction of every stock mentioned in the news. Instead, it filters a large volume of news and performs deeper analysis only on potential bullish opportunities.

The workflow follows five stages:

1. **Entry & Target Identification** — classify the news and identify a stock target.
2. **Long-Only Gate** — quickly filter out Bearish and Neutral opportunities.
3. **Data Enrichment** — collect fundamentals and historical news context.
4. **Multi-Agent Debate** — challenge the investment thesis from different perspectives.
5. **Final Decision** — independently determine whether the opportunity is strong enough to generate a BUY signal.

The final trading decision is intentionally limited to:

```text
BUY
NONE
```

The core philosophy is:

> **宁可错过机会，也不交易低确定性的新闻。**

---

# Workflow Diagram

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

        debate_coordinator -- "发言" --> bull_advocate

        debate_coordinator -- "发言" --> conservative_bull

        debate_coordinator -- "发言" --> neutral_reality_check

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

---

# Node Specification

# 1. Entry & Target Identification

## 1.1 `receive_news`

### Responsibility

`receive_news` is the entry node of the workflow.

It receives the incoming news and initializes the execution environment.

### Main Responsibilities

* Receive raw news content.
* Load runtime configuration.
* Initialize workflow state.
* Initialize model configuration.
* Initialize MCP configuration.

### Configuration

The node may load:

```text
LLM Provider
API URL
API Key
Main Model
Flash Model
Context Model
MCP Server URL
Workflow Settings
```

### Output

An initialized analysis state containing the news, exchange, symbol, configuration, and fields required by subsequent workflow stages.

---

## 1.2 `classify_news`

### Responsibility

`classify_news` uses a **Flash / Fast Model** to quickly classify the incoming news.

This is a low-cost and low-latency screening step.

### Classification Categories

| Type       | Description    | Route            |
| ---------- | -------------- | ---------------- |
| `Noise`    | 市场噪音、价格波动、市场回顾 | END              |
| `Company`  | 明确公司的具体事件      | 检查 Symbol        |
| `Industry` | 行业、板块或产业事件     | `identify_stock` |
| `Macro`    | 宏观经济、货币政策、地缘政治 | `identify_stock` |

### Noise

Examples:

```text
ASX closes 0.4% higher today.
Technology stocks rose in afternoon trading.
Markets recovered after yesterday's selloff.
```

These usually do not represent a specific stock opportunity and are terminated immediately.

### Company

Examples:

```text
Company X announces a major contract.
Company Y reports better-than-expected earnings.
Company Z receives regulatory approval.
```

If a valid symbol already exists, the workflow proceeds to `process_symbol_gate`.

### Industry

Examples:

```text
Global copper demand is expected to increase.
Lithium supply shortages are worsening.
AI infrastructure spending continues to grow.
```

The workflow must identify the strongest listed beneficiary.

### Macro

Examples:

```text
RBA cuts interest rates.
Oil prices rise due to geopolitical tensions.
Government announces major infrastructure spending.
```

Macro news may create strong opportunities for specific industries or companies, so the workflow attempts to identify the strongest direct beneficiary.

---

## 1.3 `identify_stock`

### Responsibility

`identify_stock` identifies the most suitable stock target when the news does not already contain a clear symbol.

### Input

```text
News
+
Exchange
```

### Selection Objective

The node attempts to identify:

> **最直接受益、最强相关、最适合作为 Long Opportunity 分析对象的股票。**

### Selection Principles

#### Direct Economic Benefit

The selected company should have a clear economic relationship with the event.

The relationship should ideally connect:

```text
News
→ Business Impact
→ Revenue / Earnings Impact
→ Stock Opportunity
```

#### Financial Materiality

The event should potentially affect:

* Revenue
* Margin
* Earnings
* Cash Flow

A company should not be selected merely because it belongs to the same industry.

#### Market Quality

Prefer companies with:

* Strong market position
* High liquidity
* Established operations
* Meaningful market capitalization

Micro-cap or highly speculative companies should not automatically be preferred unless they are clearly the strongest direct beneficiary.

### Output

Successful identification:

```text
selected_symbol
selected_company
selection_reason
```

If no suitable stock is found, no target is produced and the workflow ends.

---

## 1.4 `process_symbol_gate`

### Responsibility

Verify that the workflow has successfully obtained a valid stock target.

### Routing

| Condition        | Route          |
| ---------------- | -------------- |
| Symbol found     | Long-Only Gate |
| Symbol not found | END            |

No downstream stock analysis should proceed without a valid target.

---

# 2. Long-Only Gate

## 2.1 `bull_bear_classifier`

### Responsibility

`bull_bear_classifier` performs a fast directional classification of the news impact on the selected stock.

### Input

```text
News
+
Selected Stock
```

### Output

```text
Bullish
Bearish
Neutral
```

Example:

```json
{
  "direction": "bullish",
  "confidence": 0.72,
  "reason": "The event is expected to improve revenue visibility."
}
```

### Purpose

This node is a **screening node**, not the final investment decision.

It answers:

> **Is this opportunity bullish enough to justify deeper and more expensive analysis?**

The classifier should be fast, inexpensive, and conservative.

---

## 2.2 `bullish_gate`

### Responsibility

Implement the system's Long-Only strategy.

### Routing

| Classification | Route           |
| -------------- | --------------- |
| Bullish        | Data Enrichment |
| Bearish        | END             |
| Neutral        | END             |

### Design Principle

Bearish does not mean SHORT.

It means:

> **Not a Long Opportunity.**

Only Bullish candidates proceed to the expensive downstream pipeline.

---

# 3. Data Enrichment

## 3.1 `fetch_mcp_fundamentals`

### Responsibility

Retrieve structured financial and fundamental data from MCP.

### Possible Data

Depending on available MCP tools, the data may include:

```text
Revenue
Revenue Growth
Net Income
EPS
PE
PB
ROE
ROIC
Debt
Free Cash Flow
Dividend
Market Cap
```

### Design Principle

This node retrieves **facts**, not investment opinions.

The separation is intentional:

```text
MCP → Objective Data

Agents → Interpretation
```

---

## 3.2 `fetch_news_context`

### Responsibility

Retrieve relevant historical news context for the selected stock.

### Search Window

Default:

```text
Previous 6 Months
```

### Positive Context

Examples:

* Earnings Beat
* Major Contract
* Product Launch
* Guidance Upgrade
* Margin Improvement
* Market Expansion

### Negative Context

Examples:

* Earnings Miss
* Guidance Cut
* Regulatory Investigation
* Product Recall
* Management Problems
* Increasing Debt
* Competitive Pressure

### Purpose

Avoid evaluating the current news in isolation.

The system should consider:

```text
Current News
+
Historical Context
```

This helps determine whether apparently bullish news is genuinely significant when viewed against the company's recent history.

---

## 3.3 `data_aggregator`

### Responsibility

Combine all collected information into a unified **Context Brief**.

### Inputs

* Original News
* Selected Stock
* Fundamental Data
* Financial Metrics
* Positive Historical News
* Negative Historical News

### Output

The Context Brief should contain:

```text
Context Brief
├── Original News
├── Stock Information
├── Fundamental Snapshot
├── Financial Metrics
├── Positive Historical Events
├── Negative Historical Events
├── Key Opportunities
└── Key Risks
```

### Purpose

All debate participants should operate from the same factual context.

This prevents agents from reaching conclusions based on inconsistent or incomplete information.

---

# 4. Multi-Agent Debate

## 4.1 `debate_coordinator`

### Responsibility

The `debate_coordinator` controls the debate process.

It is primarily a **process controller**, rather than a Bull or Bear participant.

### Responsibilities

#### Receive Context

The coordinator receives:

* Original News
* Context Brief
* Fundamental Data
* Historical News Context

#### Identify Important Questions

The coordinator identifies:

* Major disagreements
* Unsupported assumptions
* Missing evidence
* Important unresolved risks

#### Generate Follow-Up Questions

Example:

```text
Bull Advocate:
Provide evidence supporting the expected revenue impact.

Conservative Bull:
Estimate downside risk if the financial impact is smaller than expected.

Neutral Reality Check:
Verify whether the assumptions are supported by available fundamentals.
```

#### Control Debate Lifecycle

The coordinator determines whether:

* More evidence is required.
* Important disagreements remain unresolved.
* A specific claim requires further challenge.
* The debate has reached sufficient confidence.
* The maximum number of rounds has been reached.

---

## 4.2 `bull_advocate`

### Responsibility

The `bull_advocate` constructs the strongest possible Long thesis.

Its central question is:

> **If this is a strong BUY opportunity, what is the strongest evidence supporting it?**

### Focus Areas

* Catalysts
* Revenue Upside
* Earnings Upside
* Positive Momentum
* Competitive Advantage
* Market Re-rating
* Structural Growth

### Required Reasoning

The Bull thesis should establish a clear causal chain:

```text
News
→ Business Impact
→ Financial Impact
→ Potential Stock Impact
```

### Output

The agent should provide:

* Main Bull Thesis
* Supporting Evidence
* Catalysts
* Expected Financial Impact
* Potential Upside Drivers

---

## 4.3 `conservative_bull`

### Responsibility

`conservative_bull` represents a cautious Long investor.

It is not a Bear Agent.

Its role is to challenge excessive optimism while remaining focused on determining whether a valid Long thesis exists.

### Key Questions

* Is the upside already priced in?
* Is the news financially material?
* Are market expectations too optimistic?
* What assumptions are required?
* What could invalidate the Bull thesis?
* Is the valuation too expensive?

### Output

The agent should provide:

* Bull Case Strength
* Major Risks
* Required Conditions
* Valuation Concerns
* Thesis Invalidation Conditions

### Purpose

Prevent confirmation bias where every participant automatically accepts bullish news as a BUY opportunity.

---

## 4.4 `neutral_reality_check`

### Responsibility

The `neutral_reality_check` validates facts and reasoning.

Its central question is:

> **Does the available evidence actually support the claims being made?**

### Validation Areas

#### Fundamental Validation

* Does revenue support the claim?
* Does valuation support the thesis?
* Does earnings justify the expected upside?
* Does the company's financial condition support the argument?

#### News Validation

* Is the event actually material?
* Is the expected impact measurable?
* Are important assumptions supported by evidence?

#### Logical Validation

The agent checks whether the reasoning chain contains unsupported jumps:

```text
News
→ Business Impact
→ Financial Impact
→ Stock Impact
```

### Output

The agent should identify:

* Confirmed Facts
* Unsupported Claims
* Missing Evidence
* Key Uncertainties
* Logical Gaps

---

## 4.5 `continue_debate_gate`

### Responsibility

Determine whether the debate has produced sufficient evidence for a final decision.

### Evaluation Criteria

The workflow may consider:

* Major disagreement remains.
* Evidence is insufficient.
* Important assumptions remain untested.
* New questions were generated.
* Critical risks remain unresolved.
* Maximum rounds have been reached.

### Routing

| Condition              | Route                 |
| ---------------------- | --------------------- |
| More analysis required | `route_debate_agents` |
| READY                  | Final Decision        |
| Maximum rounds reached | Final Decision        |

---

## 4.6 `route_debate_agents`

### Responsibility

Select the next agent and define the next question.

### Input

* Current Debate State
* Previous Arguments
* Open Questions
* Unresolved Risks
* Coordinator Decision

### Example

```text
Next Agent:
bull_advocate

Question:
Explain why the contract is financially material.
```

Or:

```text
Next Agent:
neutral_reality_check

Question:
Verify whether the expected earnings impact is supported by the company's financial data.
```

### Design Principle

The debate should be dynamically routed based on unresolved questions.

The system should not use a rigid round-robin sequence.

The coordinator determines:

> **What is the most important unresolved question, and which agent is best positioned to address it?**

---

# 5. Final Decision

## 5.1 `final_judge`

### Responsibility

`final_judge` is an independent decision agent.

It does not participate in the earlier debate as a Bull, Conservative Bull, or Neutral agent.

Its role is to independently evaluate the complete evidence.

### Input

The judge receives:

* Original News
* Full Context Brief
* Fundamental Data
* Historical News
* Debate Transcript
* Open Questions
* Resolved Arguments
* Unresolved Risks

### Evaluation Areas

#### News Importance

How important is the event?

#### Business Impact

Does the event materially affect the company?

#### Financial Impact

Could the event materially affect:

* Revenue
* Margin
* Earnings
* Cash Flow

#### Fundamental Support

Do the company's fundamentals support the thesis?

#### Debate Results

* Which arguments survived challenge?
* Which assumptions were disproven?
* Which risks remain unresolved?

#### Risk

What could invalidate the Long thesis?

### Important Principle

The Final Judge is not a voting system.

This is not valid reasoning:

```text
2 Bull
1 Neutral

Therefore BUY
```

The decision must be based on:

* Evidence Strength
* Financial Materiality
* Fundamental Support
* Catalyst Strength
* Risk
* Uncertainty

### Output

Example:

```json
{
  "decision": "BUY",
  "confidence": 0.82,
  "position_size": "medium",
  "reasoning": "...",
  "key_catalysts": [],
  "key_risks": []
}
```

Possible decisions:

```text
BUY
NONE
```

---

## 5.2 `evaluate_trade`

### Responsibility

Convert the Final Judge's decision into a concrete trading action.

### Input

* Final Decision
* Confidence
* Position Recommendation

### Output

| Judge Decision           | Trade Action |
| ------------------------ | ------------ |
| Strong Long Opportunity  | `BUY`        |
| Insufficient Opportunity | `NONE`       |
| High Uncertainty         | `NONE`       |
| Risks Too High           | `NONE`       |

### Long-Only Rule

The system does not generate:

```text
SHORT
```

The final action space is strictly:

```text
BUY
NONE
```

---

# Key Design Decisions

## 1. Long-Only Opportunity Discovery

The system searches for high-conviction Long opportunities.

It does not attempt to generate a trading action for every directional opinion.

Therefore:

```text
Bearish ≠ SHORT
Neutral ≠ SHORT
```

They simply mean:

> **Not a Long Opportunity.**

---

## 2. Early Filtering

Expensive downstream analysis should only be performed on promising candidates.

The system terminates early when:

* News is Noise.
* No suitable stock can be identified.
* The opportunity is Bearish.
* The opportunity is Neutral.

This reduces unnecessary:

* LLM calls
* MCP calls
* Context searches
* Multi-agent debate rounds

---

## 3. Facts Before Debate

The debate stage should begin only after sufficient factual context has been collected.

The architecture separates:

```text
Data Collection
```

from:

```text
Interpretation and Judgment
```

MCP and news retrieval provide evidence.

Agents interpret and challenge that evidence.

---

## 4. Dynamic Debate Routing

The debate is driven by unresolved questions rather than a fixed speaking order.

The coordinator identifies:

* What remains uncertain.
* What claim needs evidence.
* What assumption needs challenge.
* Which agent should respond next.

This creates targeted reasoning rather than repetitive agent summaries.

---

## 5. Role Separation

Each component has a specific responsibility.

| Component            | Responsibility |
| -------------------- | -------------- |
| Flash Classifier     | 新闻快速分类         |
| Stock Identifier     | 找到最直接受益标的      |
| Bull/Bear Classifier | 快速方向筛选         |
| MCP                  | 提供客观基本面数据      |
| News Context         | 提供历史新闻背景       |
| Bull Advocate        | 构建最强多头逻辑       |
| Conservative Bull    | 挑战过度乐观         |
| Reality Check        | 验证事实与逻辑        |
| Coordinator          | 控制 Debate 流程   |
| Final Judge          | 独立投资裁决         |
| Evaluate Trade       | 生成交易动作         |

This prevents one agent from simultaneously being:

```text
Researcher
Analyst
Critic
Judge
Trader
```

---

## 6. Independent Final Judgment

The Final Judge remains separate from the debate participants.

This reduces:

* Anchoring Bias
* Confirmation Bias
* Majority Voting Bias
* Role Commitment Bias

The final decision should be based on the quality of the evidence, not the number of agents supporting a particular opinion.

---

# Final Philosophy

The system is designed to discover a small number of high-quality opportunities from a large volume of news.

It should not trade simply because a news item appears positive.

A candidate must survive:

* Initial classification
* Stock identification
* Bullish screening
* Fundamental enrichment
* Historical context review
* Multi-agent challenge
* Independent final judgment

Only opportunities that remain sufficiently strong after this process should generate:

```text
BUY
```

All other outcomes should result in:

```text
NONE
```

The core philosophy is:

> **宁可错过机会，也不交易低确定性的新闻。**
