# TopxAI Cookbook

This cookbook demonstrates how to use TopxAI with the Agno framework. TopxAI is an LLM API
gateway (`https://ai.topxea.com`) with an OpenAI-compatible Chat Completions endpoint at
`https://ai.topxea.com/v1`.

> **Prerequisites**: Fork and clone this repository if needed

## Quick Start

### 1. Create and activate a virtual environment

```shell
python3 -m venv ~/.venvs/aienv
source ~/.venvs/aienv/bin/activate
```

### 2. Export your `TOPXAI_API_KEY`

Get your API key from: https://ai.topxea.com/keys

```shell
export TOPXAI_API_KEY=***
```

### 3. Install libraries

```shell
uv pip install -U openai ddgs agno
```

### 4. Run basic Agent

```shell
python cookbook/90_models/topxai/basic.py
```

### 5. Run Agent with Tools

```shell
python cookbook/90_models/topxai/tool_use.py
```

## Model Ids

Text model ids currently served:

- `kimi-k3.1-pro` (default)
- `claude-fable-5-1`, `claude-opus-5-5`, `claude-sonnet-5-5`
- `gpt-6.1-sol`, `gpt-6-astra`
- `grok-4.7`
- `deepseek-flash-Abliterated`
- `GLM-5.3-Abliterated`

Each route has a fixed price in USD, paid from prepaid credit. The pricing page lists the
current ids and prices, so check it rather than hardcoding the list above.

## Resources & Support

### Official Links
- [Website](https://ai.topxea.com)
- [Documentation](https://ai.topxea.com/docs)
- [Connect your SDK](https://ai.topxea.com/docs/connect-your-sdk)
- [Pricing](https://ai.topxea.com/pricing)
- [Get API Key](https://ai.topxea.com/keys)

### API Reference
- **Base URL**: `https://ai.topxea.com/v1`
