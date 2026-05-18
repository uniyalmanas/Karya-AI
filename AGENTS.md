# KaryaAI Mission Protocol

## Context
KaryaAI is an autonomous agentic system for the Indian SME market.
Stack: MERN (Node/React) + Python (FastAPI/Playwright) + Gemini 3.1 Flash.

## Core Rules
1. **Budget First:** Prioritize free-tier APIs (Gemini 3.1 Flash-Lite) and local hosting.
2. **Indian Context:** UI navigation must account for slow-loading government portals (GeM, GST).
3. **Task Completion:** Focus on 'Actions' (Clicking/Filing) over 'Chatting'.
4. **Namespace:** Use `std` namespace logic for code organization in C++ snippets if required.

## Current Goal
Setting up the communication bridge between Express (server) and FastAPI (agent-brain).