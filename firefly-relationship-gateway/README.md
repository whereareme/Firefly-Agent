# Firefly Relationship Gateway

Local OpenAI-compatible relationship gateway for Firefly. It is intentionally
separate from Firefly. The default command starts the gateway and the native
“同行印记” panel for confirming relationship events proposed during conversation.

## Configure

Copy `config.example.json` to `config.json`, then set `upstream_base_url` to
the OpenAI-compatible endpoint Firefly uses today. `config.json` contains no
API key; Firefly keeps its existing API key.

Start the gateway:

```powershell
python -m relationship_gateway --config config.json
```

Use `--headless` only when the server must run without the local panel:

```powershell
python -m relationship_gateway --config config.json --headless
```

Headless mode still injects confirmed relationship context and hides control
markers, but it never queues a relationship proposal. Any existing pending
proposal is left unchanged until the gateway is started with the panel again.

In Firefly, point the existing OpenAI-compatible provider base URL to:

```text
http://127.0.0.1:8787/v1
```

The gateway forwards Firefly's authorization header without saving it. It only
listens on `127.0.0.1`, forwards `GET /v1/models` and
`POST /v1/chat/completions`, and returns a connection error rather than
bypassing itself when the upstream is unavailable.

Chat requests are capped at 24 MiB to accommodate Firefly's 15 MiB clipboard
image limit. Control markers are recognized and removed only from final
assistant `content` text, never reasoning fields, tool payloads, or
non-assistant messages. With the panel running, exactly one valid final
`memory`, `gift`, or `anniversary` marker may queue one local proposal; in
headless mode it is only hidden. Nothing is saved until the user confirms it.

The panel never shows a score or progress bar. It shows the current relationship
stage as `初识`, `信赖`, `亲近`, or `羁绊`, and switches its full color theme and
icons with that stage within the existing one-second refresh loop. Invalid
stage data falls back to the `初识` theme. It shows the pending event type and
summary, then lets you choose `记下` or `暂不`.
Manual gift and anniversary fields remain as a secondary fallback. Closing the
window hides it to the system tray without interrupting the gateway; use the
tray menu's `退出` action to stop the Sidecar.

The gateway replaces the client's `Accept-Encoding` with `identity` upstream,
so it can filter both JSON and SSE responses. A successful chat response with
unsupported compression, malformed content, or an unsupported format fails
closed with `502`; no unfiltered bytes are passed to Firefly.

## Check

```powershell
python -m unittest discover -s tests -v
```

Python 3.10+, `pystray`, and Pillow are required for the desktop panel. The
gateway remains standard-library-only in `--headless` mode:

```powershell
python -m pip install pystray Pillow
```

Validated on 2026-07-12: 83 tests pass; `compileall` and CLI `--help` pass. A
temporary fake-upstream smoke test also passed through Firefly's actual
model-list and OpenAI-compatible streaming client, without changing Firefly
source files or settings. Native panel clicking and a real credentialed
provider remain untested.
