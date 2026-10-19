# Third-party notices

CodeVigrah itself is MIT-licensed (see [LICENSE](LICENSE)). It contains **no copied third-party source code**.
It uses the following open-source software at run time, which keeps its own license.

## Loaded by the browser from a CDN (not bundled in this repository)

| Project | Version | License | Used for |
|---|---|---|---|
| [D3](https://d3js.org) | 7.8.5 | ISC, Copyright 2010-2023 Mike Bostock | architecture, code map and dependency graph views |
| [Mermaid](https://mermaid.js.org) | 10.9.1 | MIT, Copyright (c) 2014-2022 Knut Sveidqvist | diagrams inside guided-tour chapters |

Both are pinned to an exact version and loaded with [Subresource Integrity](https://developer.mozilla.org/en-US/docs/Web/Security/Subresource_Integrity)
hashes, so the browser refuses a file that does not match. If you ever vendor (copy) them into this repository instead,
include their license texts next to the files.

## Optional Python dependency

| Project | License | Used for |
|---|---|---|
| [Anthropic Python SDK](https://github.com/anthropics/anthropic-sdk-python) (`anthropic`) | MIT | the Anthropic API provider, installed with `pip install "codevigrah[anthropic]"` |

## External tools and services

* **git** is called as a separate program to clone and read repository history.
* **The optional speech server** (`contrib/speech-server/`) is a separate program that you install into its own virtual
  environment. Its dependencies are not part of CodeVigrah and keep their own licenses: kokoro-onnx (MIT), the Kokoro-82M
  model and voices (Apache-2.0), onnxruntime (MIT), piper-tts and espeak-ng (GPL-3.0), and each Piper voice under the license
  in its model card. CodeVigrah talks to it only over HTTP.
* **Claude Code**, **Ollama**, **Groq** and other AI providers are separate products with their own terms. CodeVigrah talks to them
  only when you configure them.

## Ideas and algorithms

Algorithms and ideas are not covered by copyright, but credit is good practice. CodeVigrah implements, from scratch, well-known
techniques: PageRank, Tarjan's strongly connected components, BM25 ranking, dependency structure matrices, and the hotspot and
temporal-coupling analyses popularised by Adam Tornhill's *Your Code as a Crime Scene* (code-maat, CodeScene). The "repo map"
given to the AI as context is inspired by [Aider](https://aider.chat). See "Prior art" in the README.

## Repositories you analyse

CodeVigrah clones the repositories you ask it to analyse into its `workspace/` folder. Their code stays under their own licenses.
The workspace is ignored by git and is never part of this project.
