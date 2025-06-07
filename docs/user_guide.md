# Cerebro User Guide

This guide has been split into separate pages. Select a topic in the Docs tab to view it.

- [Getting Started](getting_started.md)
- [Application Tabs](app_tabs.md)
- [Configuration](configuration.md)
- [Plugins](plugins.md)

The application notifies you when an update is available and you can check manually from the Help menu.

## Fine-tuning a Model

Fine-tuning allows you to specialize a base model with your own examples. Ensure
Ollama is installed and that you have pulled the model you want to adapt. Place
your training pairs in `train.jsonl` and create a `Modelfile` similar to:

```bash
FROM llama3
ADAPTER ./train.jsonl
```

Run `ollama create my-model -f Modelfile` and then `ollama run my-model` to test
the result. Start the Ollama server and choose `my-model` within Cerebro.
