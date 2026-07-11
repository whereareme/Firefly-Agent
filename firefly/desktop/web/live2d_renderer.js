const statusBox = document.querySelector("#status");

const MOTION_SCENARIOS = {
  "其他组#3:回正": "清除墨镜效果，回到默认附件状态",
  "其他组#3:墨镜（点击）": "待机小互动，戴墨镜",
  "其他组#2:回正": "清除猫耳效果，回到默认附件状态",
  "其他组#2:猫耳（点击）": "待机小互动，猫耳效果",
  "表情组:回正": "默认待机或动作结束回正",
  "表情组:使一颗心免于哀伤（点击）": "右键星火旋律，播放长音乐动作",
  "表情组:点燃星海（点击）": "待机随机互动，精神一点的回应氛围",
  "表情组:难受（按键）": "难过、不顺利、低落",
  "表情组:鄙夷（按键）": "不满、吐槽、轻微嫌弃",
  "表情组:生气（按键）": "明显不满或生气",
  "表情组:疑问（按键）": "疑问、思考、等待理解",
  "表情组:哭泣（按键）": "哭泣、委屈、失败感较强",
  "表情组:流汗（按键）": "出错、权限失败、尴尬",
  "表情组:呆愣（按键）": "待机随机互动，发呆或愣住",
  "表情组:嘻嘻（按键）": "成功、开心、轻松回应",
  "Tick2:笑一笑（待机）": "待机随机互动，轻微笑",
  "Tick2:一起看（待机）": "思考或陪伴式待机",
  "Tick2:很可爱（待机）": "待机随机互动，轻松可爱",
  "Start:初始化": "模型初始化",
};

window.fireAgentLive2DState = { ready: false, error: "", modelName: "", live2dKeys: [], lastMood: "", lastActionPlayed: false, lastFocus: null, motionScenarios: MOTION_SCENARIOS };
let live2DModel = null;
let live2DConfig = null;
let live2DMood = "idle";
let idleTimer = null;
let moodResetTimer = null;
let live2DAudio = null;
let live2DAudioTimer = null;
let live2DAudioToken = 0;
let starfireTracks = [];
let starfireIndex = -1;
let starfireMode = "sequence";
let suppressMotionSoundOnce = false;

const MOOD_ACTIONS = {
  idle: { expression: "expression00.exp3", motions: [["表情组", ["回正"]]], persistent: true },
  resetSunglasses: { expression: "expression00.exp3", motions: [["其他组#3", ["回正"]]] },
  resetCat: { expression: "expression00.exp3", motions: [["其他组#2", ["回正"]]] },
  comfort: { expression: "expression00.exp3", motions: [["表情组", ["使一颗心免于哀伤（点击）"]]] },
  music: { expression: "expression00.exp3", motions: [["表情组", ["使一颗心免于哀伤（点击）"]]], resetMs: 205000 },
  ignite: { expression: "expression00.exp3", motions: [["表情组", ["点燃星海（点击）"]]] },
  thinking: { expression: "expression6.exp3", motions: [["表情组", ["疑问（按键）", "呆愣（按键）"]], ["Tick2", ["一起看（待机）"]]], persistent: true },
  happy: { expression: "expression10.exp3", motions: [["表情组", ["嘻嘻（按键）"]], ["Tick2", ["笑一笑（待机）", "很可爱（待机）"]]] },
  smile: { expression: "expression00.exp3", motions: [["Tick2", ["笑一笑（待机）"]]] },
  watch: { expression: "expression00.exp3", motions: [["Tick2", ["一起看（待机）"]]] },
  cute: { expression: "expression00.exp3", motions: [["Tick2", ["很可爱（待机）"]]] },
  question: { expression: "expression6.exp3", motions: [["表情组", ["疑问（按键）", "呆愣（按键）"]]] },
  daze: { expression: "expression9.exp3", motions: [["表情组", ["呆愣（按键）"]]] },
  sad: { expression: "expression3.exp3", motions: [["表情组", ["难受（按键）", "哭泣（按键）"]]] },
  angry: { expression: "expression5.exp3", motions: [["表情组", ["生气（按键）", "鄙夷（按键）"]]] },
  disdain: { expression: "expression4.exp3", motions: [["表情组", ["鄙夷（按键）"]]] },
  sweat: { expression: "expression8.exp3", motions: [["表情组", ["流汗（按键）", "呆愣（按键）"]]] },
  cry: { expression: "expression7.exp3", motions: [["表情组", ["哭泣（按键）", "难受（按键）"]]] },
  sunglasses: { expression: "expression1.exp3", motions: [["其他组#3", ["墨镜（点击）"]]] },
  cat: { expression: "expression2.exp3", motions: [["其他组#2", ["猫耳（点击）"]]] },
  start: { motions: [["Start", ["初始化"]]] },
};

function setStatus(text) {
  statusBox.textContent = text || "";
}

function setState(patch) {
  window.fireAgentLive2DState = { ...window.fireAgentLive2DState, ...patch };
}

async function api(path) {
  const response = await fetch(path);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

function fitLive2D(model, stage) {
  const width = stage.clientWidth || 1;
  const height = stage.clientHeight || 1;
  model.scale.set(1);
  const bounds = model.getLocalBounds ? model.getLocalBounds() : { x: 0, y: 0, width: model.width, height: model.height };
  const modelWidth = bounds.width || model.width || 1;
  const modelHeight = bounds.height || model.height || 1;
  const scale = Math.min(width / modelWidth, height / modelHeight) * 0.96;
  model.scale.set(scale);
  model.x = (width - modelWidth * scale) / 2 - bounds.x * scale;
  model.y = height - modelHeight * scale - bounds.y * scale + 8;
}

function bindMotion(model, config) {
  model.interactive = false;
  model.buttonMode = false;
}

function motionDurationMs(group, name) {
  const seconds = live2DConfig?.motionDurations?.[`${group}:${name}`] || 0;
  return seconds > 0 ? seconds * 1000 : 0;
}

function assetUrl(path) {
  const base = `${live2DConfig?.assetRoot || "/assets/live2d/"}${live2DConfig?.modelDirectory || ""}/`;
  return base + path.split("/").map((part) => encodeURIComponent(part)).join("/");
}

function stopLive2DSound() {
  live2DAudioToken += 1;
  window.clearTimeout(live2DAudioTimer);
  if (live2DAudio) {
    live2DAudio.onended = null;
    live2DAudio.pause();
    live2DAudio = null;
  }
}

function setStarfireTracks(tracks, mode) {
  starfireTracks = Array.isArray(tracks) ? tracks.filter((track) => track && track.url) : starfireTracks;
  starfireMode = mode === "random" ? "random" : "sequence";
  if (starfireIndex >= starfireTracks.length) starfireIndex = -1;
}

function nextStarfireIndex(step = 1) {
  if (!starfireTracks.length) return -1;
  if (starfireMode === "random") return Math.floor(Math.random() * starfireTracks.length);
  return (starfireIndex + step + starfireTracks.length) % starfireTracks.length;
}

function playStarfireIndex(index) {
  if (!starfireTracks.length || index < 0) return false;
  starfireIndex = index % starfireTracks.length;
  const track = starfireTracks[starfireIndex];
  stopLive2DSound();
  suppressMotionSoundOnce = true;
  live2DMood = "music";
  stopLive2DMotion();
  playMoodAction("music");
  window.clearTimeout(moodResetTimer);
  setState({ starfireTrack: track.title || "" });
  live2DAudio = new Audio(track.url);
  live2DAudio.volume = 0.7;
  live2DAudio.onended = () => playStarfireIndex(nextStarfireIndex(1));
  live2DAudio.play().catch((error) => console.warn("星火旋律播放失败", error));
  return true;
}

function playStarfire(payload = {}) {
  setStarfireTracks(payload.tracks, payload.mode);
  const command = payload.command || "next";
  if (command === "sequence") return playStarfireIndex(0);
  if (command === "random") return playStarfireIndex(nextStarfireIndex(1));
  if (command === "previous") return playStarfireIndex(nextStarfireIndex(-1));
  return playStarfireIndex(nextStarfireIndex(1));
}

function stopLive2DMotion() {
  const manager = live2DModel?.internalModel?.motionManager;
  if (manager && typeof manager.stopAllMotions === "function") {
    manager.stopAllMotions();
  }
}

function playMotionSound(group, name) {
  if (suppressMotionSoundOnce) {
    suppressMotionSoundOnce = false;
    return;
  }
  const key = `${group}:${name}`;
  const sound = live2DConfig?.motionSounds?.[key];
  if (!sound) return;
  stopLive2DSound();
  const token = live2DAudioToken;
  live2DAudioTimer = window.setTimeout(() => {
    if (token !== live2DAudioToken) return;
    live2DAudio = new Audio(assetUrl(sound));
    live2DAudio.volume = 0.7;
    live2DAudio.play().catch((error) => console.warn("Live2D 音频播放失败", error));
  }, live2DConfig?.motionSoundDelays?.[key] || 0);
}

function playMotion(group, index) {
  if (!live2DModel || typeof live2DModel.motion !== "function") return false;
  try {
    const motions = live2DConfig?.motionGroups?.[group] || [];
    const name = motions[index] || "";
    const manager = live2DModel.internalModel?.motionManager;
    const finished = manager && typeof manager.once === "function"
      ? new Promise((resolve) => manager.once("motionFinish", resolve))
      : null;
    const result = live2DModel.motion(group, index);
    const started = result && typeof result.then === "function"
      ? result.catch(() => false)
      : Promise.resolve(result !== false);
    started.then((ok) => {
      if (ok) playMotionSound(group, name);
    }).catch(() => undefined);
    return { started, finished, durationMs: motionDurationMs(group, name) };
  } catch (error) {
    console.warn(error);
    return false;
  }
}

function playMotionByName(group, names) {
  const motions = live2DConfig?.motionGroups?.[group] || [];
  const index = motions.findIndex((motion) => names.includes(motion));
  return index >= 0 ? playMotion(group, index) : false;
}

function playRandomNamedMotion(group, names) {
  const available = names.filter((name) => (live2DConfig?.motionGroups?.[group] || []).includes(name));
  if (!available.length) return false;
  return playMotionByName(group, [available[Math.floor(Math.random() * available.length)]]);
}

function playExpression(name) {
  if (!live2DModel || typeof live2DModel.expression !== "function") return false;
  try {
    const result = live2DModel.expression(name);
    if (result && typeof result.catch === "function") result.catch(() => undefined);
    return true;
  } catch (error) {
    console.warn(error);
    return false;
  }
}

function playAccessoryMotion(group, names, expression) {
  const moved = playMotionByName(group, names);
  const expressed = playExpression(expression);
  return moved || expressed;
}

function playIdleAction() {
  const actions = [
    () => playAccessoryMotion("表情组", ["点燃星海（点击）"], "expression00.exp3"),
    () => playAccessoryMotion("表情组", ["呆愣（按键）"], "expression9.exp3"),
    () => playRandomNamedMotion("Tick2", ["笑一笑（待机）", "一起看（待机）", "很可爱（待机）"]),
    () => playAccessoryMotion("其他组#2", ["猫耳（点击）"], "expression2.exp3"),
    () => playAccessoryMotion("其他组#3", ["墨镜（点击）"], "expression1.exp3"),
  ];
  const outcome = normalizeActionResult(actions[Math.floor(Math.random() * actions.length)]());
  if (outcome.played) resetMoodLater(resetDelayMs({}, outcome.motion), outcome.motion);
  return outcome.played;
}

function scheduleIdleMotion() {
  window.clearTimeout(idleTimer);
  idleTimer = window.setTimeout(() => {
    if (live2DMood === "idle") {
      playIdleAction();
    }
    scheduleIdleMotion();
  }, 30000 + Math.random() * 90000);
}

function playMoodAction(mood) {
  const action = MOOD_ACTIONS[mood] || MOOD_ACTIONS.idle;
  let moved = false;
  let motion = null;
  for (const [group, names] of action.motions || []) {
    motion = playMotionByName(group, names);
    moved = Boolean(motion);
    if (moved) break;
  }
  const expressed = action.expression ? playExpression(action.expression) : false;
  const played = expressed || moved;
  setState({ lastMood: mood, lastActionPlayed: played });
  return { played, motion };
}

function normalizeActionResult(result) {
  if (result && typeof result === "object" && "started" in result) return { played: true, motion: result };
  return { played: Boolean(result), motion: null };
}

function resetDelayMs(action, motion) {
  return action.resetMs || Math.max(4500, (motion?.durationMs || 0) + 500);
}

function resetMoodLater(delay = 4500, motion = null) {
  window.clearTimeout(moodResetTimer);
  const token = Symbol("mood-reset");
  resetMoodLater.token = token;
  const reset = () => {
    if (resetMoodLater.token !== token) return;
    resetMoodLater.token = null;
    window.clearTimeout(moodResetTimer);
    moodResetTimer = null;
    if (live2DMood !== "thinking") {
      live2DMood = "idle";
      playMoodAction("idle");
    }
  };
  moodResetTimer = window.setTimeout(() => {
    reset();
  }, delay);
  if (motion?.finished && motion?.started) {
    motion.started.then((started) => {
      if (started) motion.finished.then(reset).catch(() => undefined);
    }).catch(() => undefined);
  }
}

window.fireAgentLive2D = {
  focus(x, y) {
    if (!live2DModel || typeof live2DModel.focus !== "function") return false;
    live2DModel.focus(x, y);
    setState({ lastFocus: { x, y } });
    return true;
  },
  resetFocus() {
    const controller = live2DModel?.internalModel?.focusController;
    if (controller && typeof controller.focus === "function") {
      controller.focus(0, 0, true);
      setState({ lastFocus: null });
      return true;
    }
    const stage = document.querySelector("#stage");
    if (!stage || !live2DModel || typeof live2DModel.focus !== "function") return false;
    live2DModel.focus(stage.clientWidth / 2, stage.clientHeight / 2, true);
    setState({ lastFocus: null });
    return true;
  },
  setMood(mood) {
    const nextMood = MOOD_ACTIONS[mood] ? mood : "idle";
    const action = MOOD_ACTIONS[nextMood] || MOOD_ACTIONS.idle;
    if (nextMood !== "music") stopLive2DSound();
    if (nextMood === "idle") stopLive2DMotion();
    live2DMood = nextMood;
    const outcome = playMoodAction(nextMood);
    window.clearTimeout(moodResetTimer);
    if (!action.persistent && outcome.played) resetMoodLater(resetDelayMs(action, outcome.motion), outcome.motion);
    return outcome.played;
  },
  music(payload) {
    return playStarfire(payload);
  },
};

function getLive2DModelClass() {
  return (
    window.PIXI?.live2d?.Live2DModel ||
    window.Live2DModel ||
    window.PIXI?.Live2DModel ||
    null
  );
}

async function initLive2D() {
  const config = await api("/api/live2d/config");
  if (!config.enabled) {
    const missing = (config.missingAssets || []).slice(0, 3).join(", ");
    const error = missing ? `Live2D 资源缺失：${missing}` : "未找到 Live2D 模型资源";
    setState({ error });
    setStatus(error);
    return;
  }
  if (!window.PIXI || !window.PIXI.live2d) {
    setState({ error: "Live2D 渲染库未加载" });
    setStatus("Live2D 渲染库未加载");
    return;
  }
  if (!window.Live2DCubismCore) {
    setState({ error: "Cubism Core 未加载" });
    setStatus("Cubism Core 未加载");
    return;
  }
  if (window.PIXI?.live2d?.config) {
    window.PIXI.live2d.config.sound = false;
  }
  const Live2DModel = getLive2DModelClass();
  if (!Live2DModel || typeof Live2DModel.from !== "function") {
    const keys = window.PIXI?.live2d ? Object.keys(window.PIXI.live2d).join(", ") : "none";
    const error = `Live2DModel 未加载：${keys}`;
    setState({ error, live2dKeys: window.PIXI?.live2d ? Object.keys(window.PIXI.live2d) : [] });
    setStatus(error);
    return;
  }

  const stage = document.querySelector("#stage");
  const canvas = document.querySelector("#firefly-live2d");
  const app = new PIXI.Application({ view: canvas, resizeTo: stage, backgroundAlpha: 0, antialias: true, autoStart: true });
  const model = await Live2DModel.from(config.modelUrl);
  live2DModel = model;
  live2DConfig = config;
  app.stage.addChild(model);
  fitLive2D(model, stage);
  bindMotion(model, config);
  if (window.ResizeObserver) {
    new ResizeObserver(() => fitLive2D(model, stage)).observe(stage);
  } else {
    window.addEventListener("resize", () => fitLive2D(model, stage));
  }
  setState({ ready: true, error: "", modelName: config.modelName, live2dKeys: Object.keys(window.PIXI.live2d || {}) });
  scheduleIdleMotion();
  setStatus("");
}

initLive2D().catch((error) => {
  console.warn(error);
  setState({ error: error.message || String(error) });
  setStatus(`Live2D 加载失败：${error.message}`);
});
