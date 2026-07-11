const state = {
  history: [],
  files: [],
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || response.statusText);
  }
  return payload;
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function appendMessage(role, content, sources = []) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  const text = document.createElement("div");
  text.className = "message-text";
  text.textContent = String(content || "");
  node.appendChild(text);
  const webSources = role === "assistant" ? webSourcesForDisplay(sources) : [];
  if (webSources.length) {
    node.appendChild(createMessageSourceList(webSources));
  }
  $("#chat-log").appendChild(node);
  node.scrollIntoView({ block: "end", behavior: "smooth" });
}

function renderPersona(persona) {
  const lines = [persona.identity, ...(persona.speaking_style || []).slice(0, 2)];
  $("#persona-card").textContent = lines.filter(Boolean).join("\n");
}

function renderFiles(items) {
  const container = $("#file-list");
  container.innerHTML = "";
  setText("#file-count", String(items.length));
  if (!items.length) {
    container.innerHTML = '<div class="muted">暂无本地资料</div>';
    return;
  }
  for (const item of items) {
    const node = document.createElement("button");
    node.type = "button";
    node.className = "file-item";
    node.innerHTML = `<strong></strong><p></p>`;
    node.querySelector("strong").textContent = item.path;
    node.querySelector("p").textContent = item.snippet || `${item.content_type || "file"} · ${Math.ceil((item.size || 0) / 1024)} KB`;
    node.addEventListener("click", () => previewFile(item));
    container.appendChild(node);
  }
}

async function previewFile(item) {
  const key = item.file_id ? `file_id=${encodeURIComponent(item.file_id)}` : `path=${encodeURIComponent(item.path)}`;
  const payload = await api(`/api/files?${key}`);
  const preview = payload.content.length > 520 ? `${payload.content.slice(0, 520)}...` : payload.content;
  renderSources([{ path: payload.path, snippet: preview }], "文件预览");
}

function renderSources(sources, title = "") {
  const box = $("#source-box");
  const items = Array.isArray(sources) ? sources : [];
  const displayItems = title ? items : items.filter((source) => isWebSource(source));
  if (!displayItems.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = "";
  const heading = document.createElement("h3");
  heading.textContent = title || "网站来源";
  box.appendChild(heading);
  for (const source of displayItems) {
    const item = document.createElement("p");
    if (isWebSource(source)) {
      const url = source.url || source.absolute_path || source.path || "";
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = source.title || source.domain || url;
      const meta = document.createElement("span");
      meta.textContent = source.domain || url;
      item.appendChild(link);
      item.appendChild(document.createElement("br"));
      item.appendChild(meta);
      const excerpt = source.snippet ? String(source.snippet).split("\n")[0].slice(0, 120) : "";
      if (excerpt) {
        const small = document.createElement("small");
        small.textContent = excerpt;
        item.appendChild(document.createElement("br"));
        item.appendChild(small);
      }
    } else {
      item.textContent = `${source.path || "来源"}: ${source.snippet || ""}`;
    }
    box.appendChild(item);
  }
}

function isWebSource(source) {
  if (!source || source.content_type !== "web") return false;
  const url = source.url || source.absolute_path || source.path || "";
  return /^https?:\/\//i.test(url);
}

function webSourcesForDisplay(sources) {
  return (Array.isArray(sources) ? sources : []).filter((source) => isWebSource(source)).slice(0, 5);
}

function createMessageSourceList(sources) {
  const container = document.createElement("div");
  container.className = "message-sources";

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "message-source-toggle";
  toggle.innerHTML = `
    <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="8.5"></circle>
      <path d="M3.5 12h17"></path>
      <path d="M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5s-1.2 6.1-3.6 8.5"></path>
      <path d="M12 3.5C9.6 5.9 8.4 8.7 8.4 12s1.2 6.1 3.6 8.5"></path>
    </svg>
  `.trim();
  toggle.title = "网络来源";
  toggle.setAttribute("aria-label", "网络来源");
  toggle.setAttribute("aria-expanded", "false");

  const list = document.createElement("div");
  list.className = "message-source-list";
  list.hidden = true;

  for (const source of sources) {
    const url = source.url || source.absolute_path || source.path || "";
    const item = document.createElement("p");
    item.className = "message-source-item";

    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = source.title || source.domain || url;

    const meta = document.createElement("span");
    meta.textContent = source.domain || url;

    item.appendChild(link);
    item.appendChild(document.createElement("br"));
    item.appendChild(meta);

    const excerpt = source.snippet ? String(source.snippet).split("\n")[0].slice(0, 120) : "";
    if (excerpt) {
      const small = document.createElement("small");
      small.textContent = excerpt;
      item.appendChild(document.createElement("br"));
      item.appendChild(small);
    }

    list.appendChild(item);
  }

  toggle.addEventListener("click", () => {
    const expanded = toggle.getAttribute("aria-expanded") !== "true";
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.classList.toggle("is-open", expanded);
    toggle.title = expanded ? "收起来源" : "网络来源";
    toggle.setAttribute("aria-label", expanded ? "收起来源" : "网络来源");
    list.hidden = !expanded;
  });

  container.appendChild(toggle);
  container.appendChild(list);
  return container;
}

async function loadHealth() {
  const health = await api("/api/health");
  setText("#health-pill", health.ok ? "运行中" : "异常");
}

async function loadPersona() {
  const persona = await api("/api/persona");
  renderPersona(persona);
}

async function loadFiles() {
  const payload = await api("/api/files");
  state.files = payload.files || [];
  renderFiles(state.files);
}

async function searchFiles(query) {
  if (!query.trim()) {
    renderFiles(state.files);
    return;
  }
  const payload = await api(`/api/search?q=${encodeURIComponent(query)}&limit=12`);
  renderFiles(payload.hits || []);
}

async function initLive2D() {
  const config = await api("/api/live2d/config");
  setText("#live2d-pill", config.enabled ? "资源就绪" : "待接入");
  if (!config.enabled) {
    if (config.missingAssets && config.missingAssets.length) {
      setText("#live2d-pill", "资源缺失");
      renderSources(config.missingAssets.map((path) => ({ path, snippet: "Live2D 依赖文件缺失" })), "Live2D 状态");
    }
    return;
  }

  const fallback = $("#live-fallback");
  if (!window.PIXI || !window.PIXI.live2d) {
    setText("#live2d-pill", "渲染库未加载");
    return;
  }
  if (!window.Live2DCubismCore) {
    setText("#live2d-pill", "核心未加载");
    return;
  }

  try {
    const stage = $("#live-stage");
    const canvas = $("#firefly-live2d");
    const app = new PIXI.Application({ view: canvas, resizeTo: stage, backgroundAlpha: 0, antialias: true, autoStart: true });
    const model = await PIXI.live2d.Live2DModel.from(config.modelUrl);
    app.stage.addChild(model);
    fitLive2D(model, stage);
    bindLive2DInteraction(model, config);
    if (window.ResizeObserver) {
      new ResizeObserver(() => fitLive2D(model, stage)).observe(stage);
    } else {
      window.addEventListener("resize", () => fitLive2D(model, stage));
    }
    fallback.hidden = true;
    setText("#live2d-pill", "已加载");
    renderSources(
      [
        {
          path: config.modelDirectory,
          snippet: `${config.textureCount || 0} 张贴图 · ${Object.keys(config.motionGroups || {}).length} 个动作组`,
        },
      ],
      "Live2D"
    );
  } catch (error) {
    setText("#live2d-pill", "加载失败");
    console.warn(error);
  }
}

function fitLive2D(model, stage) {
  const width = stage.clientWidth || 1;
  const height = stage.clientHeight || 1;
  model.scale.set(1);
  const bounds = model.getLocalBounds ? model.getLocalBounds() : { x: 0, y: 0, width: model.width, height: model.height };
  const modelWidth = bounds.width || model.width || 1;
  const modelHeight = bounds.height || model.height || 1;
  const scale = Math.min(width / modelWidth, height / modelHeight) * 0.9;
  model.scale.set(scale);
  model.x = (width - modelWidth * scale) / 2 - bounds.x * scale;
  model.y = height - modelHeight * scale - bounds.y * scale + 8;
}

function bindLive2DInteraction(model, config) {
  const groups = Object.keys(config.motionGroups || {}).filter((group) => (config.motionGroups[group] || []).length);
  const preferredGroups = groups.filter((group) => group.includes("表情") || group.includes("其他"));
  const usableGroups = preferredGroups.length ? preferredGroups : groups;
  if (!usableGroups.length || typeof model.motion !== "function") return;

  model.interactive = true;
  model.buttonMode = true;
  model.on("pointertap", () => {
    const group = usableGroups[Math.floor(Math.random() * usableGroups.length)];
    const motions = config.motionGroups[group] || [];
    const index = motions.length ? Math.floor(Math.random() * motions.length) : undefined;
    try {
      const result = model.motion(group, index);
      if (result && typeof result.catch === "function") result.catch(() => undefined);
    } catch (error) {
      console.warn(error);
    }
  });
}

async function sendMessage(event) {
  event.preventDefault();
  const input = $("#message-input");
  const button = $("#send-button");
  const message = input.value.trim();
  if (!message) return;

  input.value = "";
  button.disabled = true;
  appendMessage("user", message);

  try {
    const payload = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, history: state.history }),
    });
    appendMessage("assistant", payload.reply, payload.sources);
    setText("#model-pill", `${payload.provider} / ${payload.model}`);
    renderSources([]);
    state.history.push({ role: "user", content: message }, { role: "assistant", content: payload.reply });
    state.history = state.history.slice(-12);
  } catch (error) {
    appendMessage("assistant", `请求失败：${error.message}`);
  } finally {
    button.disabled = false;
    input.focus();
  }
}

function bindEvents() {
  $("#chat-form").addEventListener("submit", sendMessage);
  $("#file-search").addEventListener("input", (event) => searchFiles(event.target.value));
}

async function init() {
  bindEvents();
  appendMessage("assistant", "我在。资料、设定和模型接口都已经准备好，告诉我你想从哪里开始。");
  await Promise.all([loadHealth(), loadPersona(), loadFiles(), initLive2D()]);
}

init().catch((error) => {
  setText("#health-pill", "异常");
  appendMessage("assistant", `初始化失败：${error.message}`);
});
