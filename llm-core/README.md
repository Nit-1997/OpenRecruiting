# llm-core

Provider-agnostic LLM access for Python. One calling convention across every
model, including models that cannot do function calling on their own.

Built for [OpenRecruiting](../README.md), but it has nothing to do with
recruiting. If you call more than one model provider, or expect to switch, this
is the part of the repo worth stealing.

```bash
pip install "git+https://github.com/Nit-1997/OpenRecruiting.git@main#subdirectory=llm-core"
```

Pin a commit instead of `main` if you depend on it. Nobody maintains this, so
`main` can move under you.

## Run it in thirty seconds, no API key

`FakeLLM` is a full stand-in for the real client. Same methods, same return
types, no network and no bill. Queue the replies you want and run your code
against them.

```python
import asyncio
from llm_core.fake import FakeLLM

async def main():
    llm = FakeLLM()
    llm.queue_text("Backend engineer, 5 years, Python.")
    llm.queue_tool_call("save_candidate", {"name": "Alex Rivera", "years": 5})

    reply = await llm.complete(
        model="summarise",
        messages=[{"role": "user", "content": "Summarise this CV."}],
    )
    print("text ->", reply.text)

    reply = await llm.complete(
        model="extract",
        messages=[{"role": "user", "content": "Extract the candidate."}],
        tools=[{"type": "function",
                "function": {"name": "save_candidate", "parameters": {}}}],
    )
    for call in reply.tool_calls:
        print("tool ->", call.name, call.arguments)

asyncio.run(main())
```

```
text -> Backend engineer, 5 years, Python.
tool -> save_candidate {'name': 'Alex Rivera', 'years': 5}
```

Installing the package also registers a `fake_llm` pytest fixture through an
entry point, so any test in the process can ask for it without importing a
conftest.

```python
async def test_extracts_the_candidate(fake_llm):
    fake_llm.queue_tool_call("save_candidate", {"name": "Alex Rivera"})
    ...
```

## Talking to a real model

Configuration comes from four environment variables and nothing else.

| Variable | Default | What it does |
|---|---|---|
| `LLM_GATEWAY_URL` | `http://litellm:4000` | Base URL. `/v1` is appended. |
| `LITELLM_MASTER_KEY` | empty | Bearer token. |
| `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout. |
| `LLM_FORCE_JSON_TOOLS` | empty | Comma-separated aliases forced onto emulated tools. |

```python
from llm_core import llm

reply = await llm.complete(
    model="my-alias",
    messages=[{"role": "user", "content": "Hello"}],
)
```

The default points at a [LiteLLM](https://docs.litellm.ai/) gateway, which is
how OpenRecruiting runs it and why models are named by workload
(`intake-jd`, `feedback-condense`) rather than by vendor. Under the hood it is
an `AsyncOpenAI` client, so any OpenAI-compatible endpoint works. Point it at
OpenAI, at Ollama, or at your own proxy. You can also pass `openai_client=` and
skip the environment entirely.

## What it actually solves

**Tools on models that do not support tools.** Ask for a tool call from a model
without function calling and `llm-core` rewrites the request as a JSON
instruction, parses what comes back, and hands you the same `ToolCall` object
the native path returns. Your code cannot tell which path ran.

**Knowing which path to take.** `capabilities.py` reads the gateway's
`/model/info` to find out whether an alias supports function calling, caches the
answer for the process, and caches failures for only 30 seconds so an outage
does not freeze a wrong answer in place. It assumes `True` on any uncertainty,
because silently downgrading a capable model to emulated tools is worse than a
loud failure from a model that genuinely cannot.

**Forcing a tool when it matters.** Left alone, a model asked for one tool may
answer in prose instead. Measured at 8.75% on `claude-haiku-4-5`, it may also
emit prose before the tool call, eating the token budget and truncating the
argument JSON. A truncated call still arrives correctly named with
`arguments={}`, which looks exactly like a real answer of all defaults. Passing
`tool_choice` closes both paths. The reasoning is in the `complete()` docstring.

## Two calls

`complete()` runs one turn and returns an `LLMReply`. `stream_turn()` yields
`('text', str)`, `('tool_call', ToolCall)` and `('done', LLMReply)` events.

## Tests

```bash
pip install -e ".[test]"
python -m pytest
```

The default run is hermetic. The live suite spends real money, so it is opted
into rather than inherited:

```bash
python -m pytest tests/integration -m live_gateway
```
