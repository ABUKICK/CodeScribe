# CodeScribe v2.3

**CodeScribe** is a lightweight, 100% local GUI tool designed to automatically generate documentation (READMEs, in-code comments, and code audits) for source code and Roblox Luau scripts using local Large Language Models (LLMs) such as Ollama or LM Studio.

It runs completely without cloud dependencies, telemetry, or external API keys—keeping your data strictly private on local servers.

## 🚀 Key Differences Between v2.1 and v2.3

If you are upgrading or migrating from Version 2.1 to Version 2.3, here are the major new features and optimizations:

1. **Universal Language Selection & Dropdown**
   * **v2.1:** Primarily focused on Python files.
   * **v2.3:** Offers a manual dropdown menu for a wide variety of programming languages (Python, Luau/Roblox, JavaScript, TypeScript, C#, C/C++, Java, Go, Rust, PHP, SQL, Bash, etc.) alongside automatic language detection.

2. **Roblox Special Mode (Luau)**
   * **v2.1:** No game-engine-specific script recognition.
   * **v2.3:** Detects Roblox services (`ReplicatedStorage`, `TweenService`, etc.) and automatically switches to a specialized script documentation mode tailored for Luau.

3. **Direct Code Priting & Clipboard Tab**
   * **v2.1:** Only allowed selecting physical `.py` files.
   * **v2.3:** Includes a dedicated tab for pasting code snippets directly from the clipboard (ideal for quick notes or code fragments).

4. **Integrated Quick Security Check**
   * **v2.1:** No automatic pre-scan of the source code.
   * **v2.3:** Automatically warns you before sending code if sensitive data like Discord webhooks, tokens, or API keys are detected.

## ✨ Core Features

* **Three Documentation Modes:**
  * *Professional README.md / Script Documentation*
  * *In-Code Comments & Docstrings*
  * *Summary / Code Audit* (Purpose, structure, and optimization potential)
* **Flexible Endpoints:** Full compatibility with Ollama and OpenAI-compatible local servers (e.g., LM Studio).
* **Context Management:** Automatic context window scaling for Ollama or manual specification.

## 🛠️ Requirements & Installation

* **Python 3.8+** (relies entirely on the Python standard library like `tkinter`, `urllib`, `ast`, `threading`).
* A local LLM server (**Ollama** or **LM Studio**).

Launch the application via terminal or by double-clicking:
```bash
python CodeScribe.py
```

## ⚠️ Important Disclaimer & Limitations (Please Read Carefully!)

**CodeScribe is an experimental, lightweight utility tool. Please keep the following risks and limitations in mind:**

* **Use at Your Own Risk:** The software is provided "as is" without warranty of any kind. The developer assumes no liability for faulty code analyses, incorrect translations, data loss, or damage to your projects and files.
* **AI Errors & Hallucinations:** Local language models can make mistakes, misinterpret code, invent functions, or provide incomplete outputs. **Always** carefully review any generated text and modified code before saving it or using it in production.
* **Translation Limitations:** Depending on the model used, instructions regarding the target language (e.g., forced English or German) might not always be executed perfectly, and fragments of the source language may remain in the output. Smaller models are generally more prone to these deviations than state-of-the-art models.
* **Sensitive Data:** Despite the built-in security scan, never submit sensitive passwords, production API keys, or proprietary secrets to local or external endpoints.

## 📄 License

This project is open source and available under the **MIT License**.