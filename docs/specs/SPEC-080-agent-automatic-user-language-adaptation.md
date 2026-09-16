---
id: SPEC-080
title: Agent Automatic User Language Adaptation
status: complete
priority: high
created: 2026-09-14
tags: [agent, i18n, localization, chat]
assigned: agent
---

# Context & Objectives

Nego-Lah serves a trilingual Malaysian marketplace (English, Bahasa Melayu, Simplified Chinese). While the frontend supports language selection and persists `preferred_language` to Supabase user metadata (`PUT /user/{user_id}/language`), the conversational AI agent previously relied on open-ended bilingual prompt cues without explicitly enforcing the user's active language preference.

**Objective:**
Ensure the negotiation agent automatically converses in the user's preferred language setting (`en` -> English / Manglish, `ms` -> Bahasa Melayu, `zh` -> Simplified Chinese), dynamically adapting to their account settings and client locale.

# Acceptance Criteria

- [x] **Language Resolution:** The system resolves the user's active language from the chat request payload (`language`) or from user metadata / Redis cache (`preferred_language`), defaulting to `en` if unset.
- [x] **Context Injection:** `agent.context` tracks `current_user_language`, and `_build_messages` injects explicit language directives into the turn's system context for `en`, `ms`, and `zh`.
- [x] **Persona Guidance:** `SELLER_PERSONA` in `agent/config.py` explicitly guides trilingual adaptation while preserving the savvy, friendly seller personality.
- [x] **Client Synchronization:** `frontend/app/pages/chat.vue` includes the active `locale.value` in chat stream requests.
- [x] **Test Coverage Gate:** Unit tests assert language directive injection and language preference resolution; backend test coverage remains >=88%.

# Technical Design & Contracts

```python
# ContextVar in agent/context.py
current_user_language: contextvars.ContextVar[str]  # default "en"
get_user_language() -> str
set_context(user_id=None, item_id=None, language=None)

# Directives in agent/bot.py
LANGUAGE_DIRECTIVES = {
    "ms": "SYSTEM LANGUAGE DIRECTIVE: User's preferred language is Bahasa Melayu (ms)...",
    "zh": "SYSTEM LANGUAGE DIRECTIVE: User's preferred language is Simplified Chinese (zh)...",
    "en": "SYSTEM LANGUAGE DIRECTIVE: User's preferred language is English (en)...",
}
```

# TDD Scenarios

- [x] **S1: Directive formatting:** `_build_messages` injects the correct language directive when `language='ms'`, `'zh'`, or `'en'`.
- [x] **S2: ContextVar isolation:** `set_context` isolates `current_user_language` across execution tasks.
- [x] **S3: Language resolution:** `get_user_preferred_language` resolves language from user metadata and falls back to `en`.

# Implementation Files

- `backend/agent/context.py`
- `backend/agent/config.py`
- `backend/agent/bot.py`
- `backend/routes/user.py`
- `backend/routes/chat.py`
- `frontend/app/pages/chat.vue`
- `backend/tests/test_user_language.py`
- `backend/tests/test_agent_bot.py`
