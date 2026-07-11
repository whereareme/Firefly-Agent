# Relationship Sidecar Design

## Goal

Add a separate local relationship system for Firefly without changing Firefly source code. It should make the relationship feel like gradual intimacy, never show a score or progress bar, and require the user's confirmation before an important memory can advance the relationship.

## Confirmed Product Decisions

- Relationship direction: gradual intimacy. The default path is `相识 -> 信赖 -> 亲近 -> 确认关系`; intimacy is never automatic.
- Relationship inputs: high-quality conversations, meaningful shared tasks, user-initiated virtual gifts, and user-agreed anniversaries.
- Excluded inputs: message counts, flattery, streaks, daily check-ins, visible points, and score farming.
- Visibility: no relationship level, numeric score, or progress UI inside Firefly. Changes appear through replies, remembered details, and optional Sidecar confirmation prompts.
- Advancement: the model may suggest an important moment, but the Sidecar records it and advances a stage only after the user explicitly selects `记下`.
- Integration: a local OpenAI-compatible relationship gateway. Firefly only changes its configured base URL to the gateway; no Firefly runtime or UI code changes are made.

## Scope

The new system lives as an independent project, such as `firefly-relationship-gateway/`, with its own runtime, tests, local configuration, and data directory. It does not import Firefly internals, write to Firefly's workspace, or modify EverOS memories.

Phase 1 supports Firefly's OpenAI-compatible provider profiles. Native Claude subscription, Codex, and other non-OpenAI protocols remain out of scope until a protocol-specific adapter is needed.

## Architecture

```text
Firefly
  configured base URL: http://127.0.0.1:8787/v1
        |
        v
Relationship Gateway
  - request context injection
  - response control-marker filtering
  - local state and proposal queue
        |
        v
Existing upstream OpenAI-compatible model service
```

The gateway binds to loopback only. It exposes only the endpoints Firefly needs:

- `GET /v1/models`: forward upstream so Firefly can continue fetching models.
- `POST /v1/chat/completions`: forward requests and responses, including streaming server-sent events.

The user changes Firefly's model endpoint to the gateway. The gateway receives the existing authorization header and forwards it to the configured upstream endpoint, so it does not persist the user's upstream API key.

## Local State

The gateway owns `data/relationship.json`, atomically written and backed up before destructive resets.

```json
{
  "version": 1,
  "stage": "acquainted",
  "events": [],
  "pending_proposal": null
}
```

`stage` can only move to its immediate successor. Events contain a generated id, kind (`memory`, `gift`, or `anniversary`), a short user-visible summary, and a timestamp. The gateway rejects oversized summaries, unknown fields, invalid stage transitions, and malformed state data. If the file is unreadable, it preserves the broken file for recovery and starts from the default state.

## Request and Response Flow

1. Firefly sends its normal OpenAI-compatible request to the local gateway.
2. The gateway appends one compact system message containing only the current stage, confirmed event summaries, and relationship boundaries.
3. The gateway forwards the otherwise unchanged request, including messages, model, tools, streaming preference, and authorization header.
4. The injected instruction permits a reserved trailing control marker only when the model recognizes an eligible relationship event. It never permits the model to alter state itself.
5. The gateway buffers and removes that trailing marker, including when it spans streaming chunks. It forwards normal response text unchanged.
6. A valid `memory` proposal enters `pending_proposal`; a user-initiated gift or anniversary becomes an event only when its marker says the user explicitly gave or agreed to it.
7. The independent Sidecar panel presents a pending memory in Firefly's tone with `记下` and `暂不` actions. `记下` saves the event and advances at most one stage. `暂不` clears the proposal without a penalty.
8. On the next request, Firefly receives the updated relationship context naturally through the gateway.

The gateway strips all reserved marker syntax from the visible response, even when the payload is invalid. Invalid payloads do not change state.

## Sidecar Panel

The Sidecar panel is separate from Firefly and intentionally small:

- status: gateway running, upstream reachable, current relationship stage hidden by default;
- pending-important-moment card: `记下` or `暂不`;
- optional local actions to view, export, or reset relationship data;
- no score, progress meter, daily mission, or gift shop.

Virtual gifts and anniversaries are primarily recognized from a user's explicit chat message, so Firefly can respond to them in the same turn. The panel is a fallback for reviewing or managing the saved relationship events, not a replacement chat client.

## Configuration and Startup

The Sidecar has a separate local config for the upstream base URL, selected port, and data directory. Firefly retains its original model name and API key; only its base URL changes to the local gateway.

The Sidecar provides one start command and a health check. If it is not running, Firefly receives a clear connection error. The gateway must not silently bypass itself to the upstream, because that would make relationship behavior appear to vanish unpredictably.

## Privacy and Boundaries

- Bind only to `127.0.0.1`; never expose the gateway on a LAN by default.
- Do not store upstream API keys, entire chats, tool payloads, EverOS data, or Firefly session files.
- Store only relationship state and confirmed short event summaries.
- Do not allow relationship state to weaken Firefly's existing safety, privacy, or task-execution rules.
- Do not advance to intimacy or confirmation without an explicit user confirmation in the Sidecar.

## Verification

- A fake upstream confirms that `models`, `chat/completions`, headers, tool payloads, and streaming chunks are forwarded correctly.
- Request injection adds exactly one relationship context message and preserves the original message order.
- Valid and malformed trailing markers never appear in the returned text; only valid markers can queue an event.
- `记下`, `暂不`, state persistence, corruption recovery, and one-stage-only advancement are covered by focused tests.
- A manual smoke check verifies Firefly can fetch models and chat through the gateway, then verifies a confirmed event appears in the next request's injected context.

## Non-Goals

- No Firefly source, UI, dependency, or workspace-schema changes.
- No visible affinity points, automatic stage advancement, daily reward loops, or gift catalogue.
- No proxy adapters for non-OpenAI protocols in Phase 1.
