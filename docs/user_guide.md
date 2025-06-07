# Cerebro User Guide

This guide has been split into separate pages. Select a topic in the Docs tab to view it.

- [Getting Started](getting_started.md)
- [Application Tabs](app_tabs.md)
- [Configuration](configuration.md)
- [Plugins](plugins.md)
- [Fine-Tuning](#fine-tuning)

The application notifies you when an update is available and you can check manually from the Help menu.

## Fine-Tuning

The `start_fine_tune()` helper kicks off supervised fine-tuning using Hugging
Face Transformers. It runs training in a background thread and streams logs to
the chat window when a callback is provided. Pass the model name, a dataset of
training examples and a dictionary of parameters such as the number of epochs or
batch size.
