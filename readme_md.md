# CodeScribe (v2.1)

> **100% Local AI Documentation Generator** for Python source code using Ollama, LM Studio, or custom local LLM endpoints.

CodeScribe is a lightweight, zero-dependency Python GUI application designed to automatically generate high-quality project documentation (`README.md`), Google-style docstrings with type hints, and structured code audits using your own local Large Language Models.

## 🌟 Key Features

* **Save Online Tokens & Costs:** Stop wasting expensive cloud AI tokens (ChatGPT, Claude, etc.) just to document your code. CodeScribe connects to your local LLM (via Ollama or LM Studio) to handle heavy documentation tasks entirely for free.

* **Automatic Bilingual Interface:** Automatically adapts its GUI language (English or German) based on your system's locale, with full manual language selection for the generated output.

* **Smart Context Window Management:** Automatically calculates the required prompt tokens and adjusts Ollama's `num_ctx` dynamically so large code files aren't silently truncated.

* **Real-time Output Streaming:** Live response streaming with instant cancellation options, progress tracking, and automatic Python syntax validation for generated docstrings.

* **Zero External Dependencies:** Built entirely with Python's standard library (`tkinter`, `urllib`, `ast`, etc.). No `pip install` required.

## 🚀 Quick Start

### Prerequisites

* Python 3.8+ installed on your system.

* A local LLM server running (e.g., [Ollama](https://ollama.com/) or [LM Studio](https://lmstudio.ai/)).

### Running CodeScribe

Simply run the script via your terminal or double-click the file:

```
python CodeScribe_2_1.py
```

## 💡 Recommended Local Models

You can download fast, high-performance coding models directly via Ollama:

* **Default / Best Quality:**

  ```
  ollama pull qwen2.5-coder:7b
  ```

* **Ultra-Fast & Low VRAM (< 1 GB):**

  ```
  ollama pull qwen2.5-coder:1.5b
  ```

* **DeepSeek Alternative:**

  ```
  ollama pull deepseek-coder:6.7b
  ```

## 🛡️ Disclaimer & Privacy Notice

### ⚠️ Experimental Software & Use at Your Own Risk

This project is currently **experimental**. **Use this software entirely at your own risk.** The author takes no responsibility for any unintended code changes, data loss, incomplete documentation, or improper script execution resulting from using generated output. Always back up your code and carefully review all AI-generated text before using it in production environments.

### 100% Local & Private (Default Operation)

When connected to a local endpoint (such as `http://localhost:11434` or `http://127.0.0.1:1234`), **100% of your source code remains strictly on your local machine**. No telemetry, tracking, or external cloud transmissions take place.

### ⚠️ Endpoint Safety Warning

CodeScribe allows custom API URLs. **Please double-check the endpoint URL you enter.**

* If you enter a remote server address or external URL (e.g., a custom remote server or public API bridge), **your source code will be transmitted to that specified destination**.

* CodeScribe will warn you before sending code to any non-loopback IP address.

## 👤 Author & License

Created with ❤️ by [**ABUKICK**](https://github.com/ABUKICK).

Licensed under the [MIT License](LICENSE).