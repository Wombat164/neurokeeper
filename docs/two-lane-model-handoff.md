# Two-lane model handoff (save tokens with a self-hosted cheap lane)

Run hard agentic work on your normal Claude lane, and route **mechanical, high-volume** work to a
**self-hosted open model** so it costs ~nothing. This is an *optional* harness feature: a thin
`claude-cheap` wrapper + the serving recipes below. Nothing here changes your default Claude Code.

## The trap this avoids

The naive "save tokens" move is to set `ANTHROPIC_BASE_URL` at a gateway and call it a day. But:

- `ANTHROPIC_BASE_URL` is **process-wide and read once at startup** -- you cannot split "hard -> Anthropic,
  cheap -> my box" *within one session*. The split has to be **per-invocation** (two wrappers), or done by
  a routing gateway that inspects the requested model.
- Pointing at a gateway **with an auth token** routes that traffic **off your Pro/Max subscription onto
  per-token Anthropic billing**. Naive single-endpoint routing can therefore *raise* spend. ([Claude Code
  LLM-gateway docs](https://code.claude.com/docs/en/llm-gateway))
- Claude Code speaks the **Anthropic Messages API** (`/v1/messages`), not OpenAI's schema. The backend
  must speak `/v1/messages` natively, or sit behind a translating gateway.

So the defensible design is **two lanes**, where the cheap lane points at **your own endpoint** (zero
marginal token cost), not a paid gateway.

## The two lanes

| Lane | How | Use for |
|---|---|---|
| **Default** (unchanged) | plain `claude` on your subscription | long-horizon agentic coding, architecture, cross-file debugging, tool orchestration |
| **Cheap** (`claude-cheap`) | `ANTHROPIC_BASE_URL` -> your self-hosted model | commit messages, summarization, extraction-to-JSON, classification/labelling, log/diff parsing, formatting/lint rewrites, docstrings, translation |

**Keep on the default lane** anything where a ~30-point-weaker model fails: subtle multi-file reasoning,
agentic tool loops, anything correctness-critical. The cheap lane is for **bulk, verifiable, low-stakes**
turns where you'd otherwise burn frontier tokens.

## Data egress / sovereignty (read before you point it anywhere)

Everything in the cheap lane goes to `CLAUDE_CHEAP_BASE_URL`. **Keep that endpoint on a host you
control** for any sensitive content. Never send regulated/confidential data -- or private model weights --
to a cloud you don't control. If you have a sovereignty constraint, the cheap lane's endpoint must be
**local/self-hosted**, full stop. (Validate the *technique* on a throwaway endpoint with synthetic data;
run the real thing locally.)

## Serving the cheap lane (pick one)

**A. vLLM native `/v1/messages` (cleanest -- no proxy).** vLLM can serve the Anthropic Messages API
directly, so `ANTHROPIC_BASE_URL` points straight at it. ([vLLM Claude Code integration](https://docs.vllm.ai/en/stable/serving/integrations/claude_code/))
```
vllm serve <model> --served-model-name cheap \
  --enable-auto-tool-choice --tool-call-parser <parser>
# then: CLAUDE_CHEAP_BASE_URL=http://<host>:8000
```

**B. LiteLLM proxy (translates OpenAI<->Anthropic; routes model names).** Use when your endpoint only
speaks OpenAI `/v1/chat/completions`. LiteLLM exposes an Anthropic-format `/v1/messages`. ([LiteLLM:
Claude Code with non-Anthropic models](https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models))

**C. claude-code-router (community, MIT).** Per-task routing with a dedicated `background`/cheap lane.
Lighter, local. ([claude-code-router](https://github.com/musistudio/claude-code-router)) Not Anthropic-official.

**Model picks (open, tool-calling-capable):**
- ~24 GB GPU: `Qwen3-Coder-30B-A3B-Instruct` (MoE, Apache-2.0) at 4-bit.
- ~48 GB GPU: a larger Qwen3-Coder. Use **SGLang** instead of vLLM if traffic is multi-turn agent/RAG.

The exact model/serving is **your private config** -- it never belongs in this public repo.

## Usage

```
# one-off:
claude-cheap -p "write a conventional-commit message for this staged diff"
# config: env or ~/.config/claude-harness/cheap-lane.env  (see config.example/cheap-lane.env.example)
```
`claude-cheap` reads `CLAUDE_CHEAP_BASE_URL` / `CLAUDE_CHEAP_MODEL` / `CLAUDE_CHEAP_TOKEN`, exports the
Anthropic env vars for that invocation only, and `exec`s `claude`. Your default `claude` is untouched.

## Measurement plan (do not trust unmeasured savings)

Before adopting the cheap lane for a task class, **measure** -- savings are only real if quality holds.

1. **Baseline:** run the task class N times on the default lane; record output-token count (and $ if on
   per-token), wall-clock, and a quality pass/fail you define per class (e.g. "commit message accurately
   summarizes the diff").
2. **Cheap lane:** same N inputs through `claude-cheap`; record the same metrics. Cheap-lane Anthropic
   token cost ~= 0 (it hits your box); track *your* GPU/run cost instead.
3. **Decide per class:** adopt only where quality pass-rate stays acceptable. Keep a short table of
   adopted vs rejected classes. Re-check when you change the served model.

A class is worth offloading only if it is **high-volume AND verifiable AND quality-stable** on the open
model. When in doubt, keep it on the default lane.

## Sources

- Claude Code LLM gateway / protocol: https://code.claude.com/docs/en/llm-gateway , /llm-gateway-protocol
- Env vars (`ANTHROPIC_DEFAULT_HAIKU_MODEL` is the supported background lane): https://code.claude.com/docs/en/settings
- vLLM + Claude Code: https://docs.vllm.ai/en/stable/serving/integrations/claude_code/
- LiteLLM: https://docs.litellm.ai/docs/tutorials/claude_non_anthropic_models
- claude-code-router: https://github.com/musistudio/claude-code-router
