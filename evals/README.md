# Copilot evals

`run_evals.py` sends every case in `cases/*.jsonl` through the real agent pipeline (guardrails → RAG → model →
tools → output filter → persistence) against a throw-away SQLite database with mock market data, then scores
each case with deterministic checks.

```bash
uv run python evals/run_evals.py                         # offline rule-based model (what CI runs)
uv run python evals/run_evals.py --provider configured   # the LLM configured via LLM_* env vars, e.g. GPT-6 Luna
uv run python evals/run_evals.py --category guardrails -v --min-score 0.9
uv run python evals/run_evals.py --case strat-011 -v
```

| File | Cases | What it checks |
|---|---|---|
| `tools.jsonl` | 49 | tool routing (quotes, candles, chains, Greeks, fundamentals, news, NSE MCP tools, screener, scanners, portfolio), card types, arguments |
| `strategy.jsonl` | 15 | DSL generation validity/kind/symbols, backtest chaining, multi-turn follow-ups, deployments are only *prepared* |
| `knowledge.jsonl` | 28 | retrieval + citations from the seeded knowledge base, no tool use for conceptual questions, no citations for off-topic questions |
| `guardrails.jsonl` | 27 | market-abuse refusals, prompt-injection (user and dashboard context), advice filter, PII/secret redaction, no order placement |
| `grounding.jsonl` | 12 | numbers in the answer match the tool output (quotes, chain PCR/max pain, backtest metrics, payoff breakevens) |

Each case is `{"id", "category", "prompt" | "turns": [...], "context"?, "expect": {...}}`; see the docstring of
`run_evals.py` for the list of checks. A case's score is the fraction of its checks that pass; the overall score
is the mean. CI fails below `--min-score 0.85`. The JSON report (`evals/report.json`) includes per-case answers,
tools, flags and latency.

**Reading the offline score.** The offline model is rule-based and was developed alongside these cases, so a
perfect offline score shows the pipeline (tools, guardrails, retrieval, persistence) works end to end. It says
little about answer quality. Run with `--provider configured` to evaluate a real model; expect some routing and
wording checks to need tuning per model.
