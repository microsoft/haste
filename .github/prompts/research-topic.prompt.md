---
description: "Deep-dive research on a technical topic with citations and architecture diagrams"
tools: ["read", "search", "web"]
argument-hint: "Describe the topic to research in depth"
---

Perform an exhaustive technical research investigation on the specified topic.

## Instructions

This prompt is designed for use alongside the Copilot CLI `/research` command.

**In Copilot CLI**, use `/research` directly for the best experience — it produces a full Markdown report with citations:
```
/research How does React implement concurrent rendering?
```

**In VS Code / IDE chat**, use this prompt for a research-style deep-dive:
1. Search the codebase and web for authoritative sources.
2. Prioritize official documentation, RFC specs, and source code over blog posts.
3. Provide:
   - **Architecture overview** with component relationships
   - **Key concepts** with concrete code examples
   - **Trade-offs** and design decisions
   - **Comparison table** (if comparing approaches)
   - **Citations** for every claim
4. Adapt output format to query type:
   - Process/how-to → step-by-step guide
   - Conceptual → narrative + trade-offs
   - Technical → architecture diagrams + code
