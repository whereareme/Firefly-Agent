# Firefly Asset Attribution

This directory contains the desktop assets bundled for the Firefly app.

| Path | Source | License / use policy |
| --- | --- | --- |
| `live2d/firefly/**` | `Scighost/Firefly`, commit `2d92ce5b2394cd993828b91afad6545156f14927`; upstream credits `bilibili@是依七哒` | Personal learning and technical research only; no commercial use. |
| `live2d/Core/live2dcubismcore.min.js` | Live2D Cubism Core | Live2D proprietary software license: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html |
| `desktop/web/vendor/pixi.min.js` | PixiJS `6.5.10` | MIT. |
| `desktop/web/vendor/pixi-live2d-display*.min.js` | `pixi-live2d-display` `0.4.0` | Bundled runtime adapter for local Live2D rendering; keep upstream license notice when replacing. |
| `ui/*.svg`, `ui/firefly_avatar.png` | Firefly desktop UI package | Project-local UI assets for this app. |

Packaging policy: keep third-party runtime files vendored only when the desktop app needs offline startup. When replacing assets, update this file and `live2d/README.md`.
