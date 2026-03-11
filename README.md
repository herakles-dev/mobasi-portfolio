# Founding Engineer Portfolio — Mobasi Application

**D. Michael Piscitelli** | Chicago, IL | hello@herakles.dev | [herakles.dev](https://herakles.dev)

Self-hosted Linux platform. 90 containers. 95 AI agents across 8 team formations. A plug-and-play framework that runs across any LLM provider. Everything orchestrated through Claude Code on bare metal. This repo curates the work most relevant to Mobasi's Founding Engineer role.

---

## Featured Projects

### V11 Agent Orchestration Framework
**The same core problem you're solving with 150 forensic tools.** Task decomposition from natural language, routing to the right specialist, parallel execution with dependency awareness, quality enforcement at every step.

- 95 agents organized into 8 team formations
- Parallel wave execution with dependency-aware scheduling
- File ownership enforcement (no two agents touch the same file — chain of custody)
- 12 enforcement hooks with 5,700+ production executions
- 5-level autonomy system (graduated trust based on risk)
- Adversarial verification between agents
- Typed artifact handoffs with trace IDs

**Architecture docs:** [herakles-agentic-architecture](https://github.com/herakles-dev/herakles-agentic-architecture)
**V11 showcase:** [claude-orchestrator-showcase](https://github.com/herakles-dev/claude-orchestrator-showcase)

---

### Nova Forge — Model-Portable AI Framework
Production framework running across AWS Bedrock, OpenRouter, and Anthropic behind a single interface. Provider failover, retry logic, structured output parsing. The reliability that SOC 2 certification demands.

**18,000+ LOC | 723 tests | 3 LLM providers**

**Source:** [nova-forge](https://github.com/herakles-dev/nova-forge)

---

### 3-Body Problem — GPU Compute
GPU-accelerated N-body gravitational simulation using NVIDIA Warp. Real-time 3D rendering, audio-reactive visualization, chaos analysis. Shows systems-level thinking and compute pipeline design.

**Source:** [3-body-problem](https://github.com/herakles-dev/3-body-problem)

---

### GPU Bridge — Lambda Labs Orchestration
Full-service GPU cloud computing platform. Claude Code orchestrates Lambda Labs A100 instances via SSH for AI inference jobs. 14 services ready, $15-300 per job with 95-99% margins. Production GPU compute pipelines.

*(Private — architecture available on request)*

---

### Rust Experience
- **Math Visualization Server** — Axum, Tokio, Rayon for parallel computation, jemalloc allocator. 22,500+ lines of Rust.
- **Strudel Desktop App** — Tauri framework for a live-coding music platform.
- **Manifold Visualizer** — WebGPU/WGSL compute shaders for mathematical surface rendering: [Source](https://github.com/herakles-dev/manifold-visualizer)

---

### HackerOne Security Cluster
12-agent autonomous bug bounty hunting platform. Intel gathering, subdomain enumeration, API fuzzing, race condition testing, GraphQL exploitation, mobile analysis, automated reporting. Findings require 3x reproduction and CVSS scoring.

*(Private — architecture available on request)*

---

## Breadth of Work

Every project below was built through Claude Code on the same self-hosted platform.

| Project | What It Is | Link |
|---------|-----------|------|
| **Athenaeum** | Semantic library — ingest, deduplicate, chunk, embed, cluster, serve. FastAPI + pgvector + Next.js. | [Source](https://github.com/herakles-dev/athenaeum) |
| **Claude Trader Pro** | AI crypto trading — multi-timeframe analysis, auto-execution, OctoBot integration. | [Source](https://github.com/herakles-dev/claude-trader-pro) |
| **TOS Analyzer** | AI Terms of Service analysis — risk scoring, dark pattern detection. Gemini Vision. | [Source](https://github.com/herakles-dev/tos-analyzer) |
| **Observability Stack** | Production monitoring — Grafana, Prometheus, Loki, OpenTelemetry, Fail2ban. | [Source](https://github.com/herakles-dev/observability-showcase) |
| **Iolaus + Zeus** | Dual-interface AI platform — voice/chat orchestration + web terminal. | [Showcase](https://github.com/herakles-dev/iolaus-zeus-showcase) |
| **CK Reynolds Tax** | Client SaaS — 55 API routes, 2FA, IRS compliant. Next.js, Supabase. | [Showcase](https://github.com/herakles-dev/ckreynolds-tax-showcase) |
| **Claude-Gemini Bridge** | Co-processor CLI — delegates reasoning to Gemini API with caching. | [Source](https://github.com/herakles-dev/claude-gemini) |
| **Claude-Pi Bridge** | Co-processor CLI — delegates deterministic tasks with safety firewall. | [Source](https://github.com/herakles-dev/claude-pi) |
| **Portfolio Showcase** | Full platform overview — 33 services, SSO, observability. | [Source](https://github.com/herakles-dev/portfolio-showcase) |

---

## Platform Stats

| Metric | Count |
|--------|-------|
| Running containers | 90 |
| Registered services | 26 |
| AI agents | 95 (69 active) |
| Docker-compose projects | 42 |
| SSL-enabled domains | 44+ |
| Rust lines of code | 22,500+ |
| Total tests (top 3 projects) | 1,488 |
| Claude Code hours | 1,600+ |

---

## Code Samples

Selected source files from the platform, browsable directly in this repo:

| File | What It Shows |
|------|---------------|
| [`samples/agent-loop/claude_loop_engine.py`](samples/agent-loop/claude_loop_engine.py) | Autonomous agent protocol (excerpt) — 7-step INSPECT→PLAN→VALIDATE→EXECUTE→VERIFY→LOG→DECIDE, GDB-style debug with breakpoints and goal override |
| [`samples/agent-loop/orchestrator.py`](samples/agent-loop/orchestrator.py) | Multi-phase workflow (excerpt) — intelligence loading, recon coordination, human-in-the-loop checkpoints, state persistence |
| [`samples/agent-loop/evidence_collector.py`](samples/agent-loop/evidence_collector.py) | Forensic evidence packaging — ReproductionStep dataclass, multi-modal capture (screenshots, HTTP, cURL), submission-ready bundles |
| [`samples/rust-compute/math_engine.rs`](samples/rust-compute/math_engine.rs) | SIMD compute (excerpt) — AVX2/AVX512/FMA runtime detection via raw_cpuid, Rayon thread pool, RK4 ODE integration, parallel trajectory |
| [`samples/rust-compute/cache.rs`](samples/rust-compute/cache.rs) | 3-tier predictive cache — L1 hot (moka), L2 zstd-compressed, L3 memory-mapped, background precomputation with trend analysis |
| [`samples/rust-compute/pipeline.rs`](samples/rust-compute/pipeline.rs) | Async pipeline — crossbeam channels, DashMap concurrent cache, LZ4 streaming compression, adaptive performance scheduling |
| [`samples/enforcement/guard-write-gates.sh`](samples/enforcement/guard-write-gates.sh) | Chain-of-custody enforcement — formation-registry file ownership, blocks concurrent agent writes, schema validation |
| [`samples/enforcement/track-autonomy.sh`](samples/enforcement/track-autonomy.sh) | Trust escalation — 5-level autonomy (A0→A4), JSONL audit with diff hashing, flock-safe concurrent writes |

Full Rust source (22,500 LOC) and security lab architecture available on request.

---

## Server

Intel i7-8700 (6C/12T) | 128GB RAM | 906GB storage | Debian Linux | Bare metal, purchased at auction. Built and operated independently.

---

*Everything on this page was built through Claude Code with me directing.*
