/**
 * GCS — супутник, відео-overlay, waypoints
 */
(function () {
  const DEFAULT_CENTER = [50.4501, 30.5234];
  const POLL_MS = 500;
  const TRAIL_MAX = 300;
  const TRAIL_MIN_M = 0.3;

  let map, roverMarker, trailLine, missionLayer, missionRoute;
  let baseLayer, satLayer;
  const trail = [];
  let waypoints = [];
  let wpMarkers = [];
  let sprayer = false;
  let moveTimer = null;
  let mapFollow = true;
  let lastLatLon = null;
  let missionMode = true;
  let cvRunning = false;

  const el = (id) => document.getElementById(id);

  function log(msg, isErr) {
    const p = el("logPanel");
    const line = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    p.textContent = line + p.textContent.slice(0, 2000);
    p.style.color = isErr ? "#f88" : "#9cdcfe";
  }

  async function apiPost(url, body) {
    const opts = { method: "POST", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(JSON.stringify(data));
    return data;
  }

  async function apiPut(url, body) {
    const r = await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(JSON.stringify(data));
    return data;
  }

  function validGps(g) {
    if (!g || g.lat == null || g.lon == null) return false;
    const lat = Number(g.lat);
    const lon = Number(g.lon);
    return !Number.isNaN(lat) && !Number.isNaN(lon) && (Math.abs(lat) > 1e-4 || Math.abs(lon) > 1e-4);
  }

  function haversineM(a, b) {
    const R = 6371000;
    const toRad = (d) => (d * Math.PI) / 180;
    const dlat = toRad(b[0] - a[0]);
    const dlon = toRad(b[1] - a[1]);
    const x =
      Math.sin(dlat / 2) ** 2 +
      Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dlon / 2) ** 2;
    return 2 * R * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x));
  }

  function initMap() {
    map = L.map("map", { zoomControl: true }).setView(DEFAULT_CENTER, 17);

    baseLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OSM",
    });
    satLayer = L.tileLayer(
      "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 19, attribution: "© Esri" }
    );
    satLayer.addTo(map);

    L.control.layers(
      { "Супутник": satLayer, "Схема": baseLayer },
      null,
      { position: "topright" }
    ).addTo(map);

    missionLayer = L.layerGroup().addTo(map);
    missionRoute = L.polyline([], { color: "#ff9800", weight: 3, dashArray: "8 6" }).addTo(map);

    roverMarker = L.marker(DEFAULT_CENTER, { title: "Rover" }).addTo(map);
    trailLine = L.polyline([], { color: "#4fc3f7", weight: 4, opacity: 0.85 }).addTo(map);

    map.on("dragstart", () => { mapFollow = false; });
    map.on("click", onMapClick);
  }

  function wpIcon(n) {
    return L.divIcon({
      className: "wp-marker",
      html: `<span>${n}</span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
  }

  function renderMission() {
    missionLayer.clearLayers();
    wpMarkers = [];
    const latlngs = [];
    waypoints.forEach((wp, i) => {
      const pos = [wp.lat, wp.lon];
      latlngs.push(pos);
      const m = L.marker(pos, { icon: wpIcon(i + 1) }).addTo(missionLayer);
      m.bindPopup(`Точка ${i + 1}<br>${wp.lat.toFixed(6)}, ${wp.lon.toFixed(6)}`);
      m.on("contextmenu", (e) => {
        L.DomEvent.stopPropagation(e);
        removeWaypoint(i);
      });
      m.on("click", () => {
        apiPost("/api/mission/goto", { index: i }).then(() => log(`GOTO → точка ${i + 1}`)).catch((err) => log("GOTO: " + err, true));
      });
      wpMarkers.push(m);
    });
    missionRoute.setLatLngs(latlngs);
    el("hudWps").textContent = String(waypoints.length);
    renderWpList();
  }

  function renderWpList() {
    const ul = el("wpList");
    if (!ul) return;
    ul.innerHTML = "";
    waypoints.forEach((wp, i) => {
      const li = document.createElement("li");
      li.textContent = `${i + 1}. ${wp.lat.toFixed(5)}, ${wp.lon.toFixed(5)}`;
      li.onclick = () => map.setView([wp.lat, wp.lon], 18);
      ul.appendChild(li);
    });
  }

  async function loadMission() {
    try {
      const r = await fetch("/api/mission");
      const d = await r.json();
      waypoints = d.waypoints || [];
      renderMission();
    } catch (e) { /* ignore */ }
  }

  async function onMapClick(e) {
    if (!missionMode) return;
    const wp = { lat: e.latlng.lat, lon: e.latlng.lng };
    try {
      const d = await apiPost("/api/mission/waypoint", wp);
      waypoints = (await (await fetch("/api/mission")).json()).waypoints || [];
      renderMission();
      log(`Waypoint ${d.index + 1} додано`);
    } catch (err) {
      log("Waypoint: " + err, true);
    }
  }

  async function removeWaypoint(idx) {
    try {
      await fetch(`/api/mission/waypoint/${idx}`, { method: "DELETE" });
      waypoints = (await (await fetch("/api/mission")).json()).waypoints || [];
      renderMission();
      log(`Точку ${idx + 1} видалено`);
    } catch (err) {
      log("Видалення: " + err, true);
    }
  }

  function updateMap(gps) {
    if (!validGps(gps)) return;
    const lat = Number(gps.lat);
    const lon = Number(gps.lon);
    const pos = [lat, lon];

    if (!lastLatLon) {
      map.setView(pos, 17);
      trail.push(pos);
      trailLine.setLatLngs(trail);
    }

    roverMarker.setLatLng(pos);
    const last = trail[trail.length - 1];
    if (!last || haversineM(last, pos) >= TRAIL_MIN_M) {
      trail.push(pos);
      if (trail.length > TRAIL_MAX) trail.shift();
      trailLine.setLatLngs(trail);
      const hint = el("mapHint");
      if (hint) hint.style.display = "none";
    }

    if (gps.heading != null && !Number.isNaN(gps.heading)) {
      roverMarker.setIcon(roverIcon(gps.heading));
    }
    if (mapFollow) map.panTo(pos, { animate: true, duration: 0.25 });
    lastLatLon = pos;
  }

  function roverIcon(headingDeg) {
    return L.divIcon({
      className: "rover-arrow",
      html: `<div style="transform:rotate(${headingDeg}deg);font-size:22px;color:#4fc3f7;text-shadow:0 0 4px #000">▲</div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12],
    });
  }

  function updateHud(s) {
    const badge = el("linkBadge");
    const hasGps = validGps(s.gps);
    if (s.connected) {
      badge.textContent = s.armed ? "ARMED · ONLINE" : "DISARMED · ONLINE";
      badge.className = "badge " + (s.armed ? "ok" : "warn");
    } else {
      badge.textContent = "OFFLINE";
      badge.className = "badge off";
    }

    el("hudConnected").textContent = s.connected ? "Так" : "Ні";
    el("hudArmed").textContent = s.armed ? "ARM" : "DISARM";
    const g = s.gps || {};
    el("hudSpeed").textContent = fmt(g.speed);
    el("hudLat").textContent = hasGps ? fmt(g.lat, 6) : "—";
    el("hudLon").textContent = hasGps ? fmt(g.lon, 6) : "—";
    cvRunning = !!s.cv_running;
    el("hudCv").textContent = cvRunning ? "ON" : "OFF";
    el("hudSprayer").textContent = s.sprayer_active ? "ON" : "OFF";
    sprayer = !!s.sprayer_active;
    syncSprayerBtn();
    updateMap(g);

    if (cvRunning) showCvOverlay();
  }

  function fmt(n, d) {
    if (n == null || n === "") return "—";
    return typeof d === "number" ? Number(n).toFixed(d) : String(n);
  }

  async function pollStatus() {
    try {
      const r = await fetch("/api/status");
      const s = await r.json();
      if (!r.ok) throw new Error(s.error || r.status);
      updateHud(s);
    } catch (e) {
      el("linkBadge").textContent = "ПОМИЛКА";
      el("linkBadge").className = "badge off";
    }
  }

  /* --- CV overlay --- */
  function showCvOverlay() {
    const box = el("cvOverlay");
    const img = el("cvVideo");
  if (!box || !img) return;
    box.classList.remove("hidden");
    if (!img.src || img.src.indexOf("/api/cv/stream") === -1) {
      img.src = "/api/cv/stream?t=" + Date.now();
    }
    img.onerror = () => {
      setTimeout(() => { img.src = "/api/cv/stream?t=" + Date.now(); }, 1500);
    };
  }

  function hideCvOverlay() {
    const box = el("cvOverlay");
    const img = el("cvVideo");
    if (box) box.classList.add("hidden");
    if (img) img.removeAttribute("src");
  }

  function initCvDrag() {
    const handle = el("cvDragHandle");
    const box = el("cvOverlay");
    if (!handle || !box) return;
    let dragging = false;
    let ox = 0;
    let oy = 0;
    handle.addEventListener("mousedown", (e) => {
      dragging = true;
      const r = box.getBoundingClientRect();
      ox = e.clientX - r.left;
      oy = e.clientY - r.top;
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      box.style.left = (e.clientX - ox) + "px";
      box.style.top = (e.clientY - oy) + "px";
      box.style.right = "auto";
    });
    window.addEventListener("mouseup", () => { dragging = false; });
    el("btnCvClose").onclick = () => hideCvOverlay();
    el("btnCvMin").onclick = () => box.classList.toggle("minimized");
  }

  function syncSprayerBtn() {
    const b = el("btnSprayer");
    if (!b) return;
    b.textContent = sprayer ? "Оприскувач УВІМК" : "Оприскувач ВИМК";
    b.className = "btn " + (sprayer ? "sprayer-on" : "sprayer-off");
  }

  function bindMoveButtons() {
    document.querySelectorAll(".btn.move").forEach((btn) => {
      const f = parseFloat(btn.dataset.f);
      const l = parseFloat(btn.dataset.l);
      const start = () => {
        sendMove(f, l);
        moveTimer = setInterval(() => sendMove(f, l), 200);
      };
      const end = () => {
        if (moveTimer) clearInterval(moveTimer);
        moveTimer = null;
        apiPost("/api/stop").catch(() => {});
      };
      btn.addEventListener("mousedown", start);
      btn.addEventListener("mouseup", end);
      btn.addEventListener("mouseleave", end);
    });
  }

  async function sendMove(f, l) {
    try {
      await apiPost("/api/move", { forward: f, lateral: l, yaw: 0 });
    } catch (e) { log("move: " + e, true); }
  }

  function bindControls() {
    el("btnArm").onclick = () => apiPost("/api/arm").then(() => log("ARM OK")).catch((e) => log("ARM: " + e, true));
    el("btnDisarm").onclick = () => apiPost("/api/disarm").then(() => log("DISARM")).catch((e) => log("DISARM: " + e, true));
    el("btnStop").onclick = () => apiPost("/api/stop").then(() => log("STOP"));

    el("btnMissionMode").onclick = () => {
      missionMode = !missionMode;
      const b = el("btnMissionMode");
      b.textContent = missionMode ? "Маршрут: ВКЛ" : "Маршрут: ВИМК";
      b.classList.toggle("active", missionMode);
      log(missionMode ? "Клік на карті → додати точку" : "Режим маршруту вимкнено");
    };

    el("btnMissionClear").onclick = () =>
      apiPost("/api/mission/clear").then(() => {
        waypoints = [];
        renderMission();
        log("Маршрут очищено");
      });

    el("btnMissionRun").onclick = () =>
      apiPost("/api/mission/run").then((d) => log(`Їде до точки 1/${d.total}`)).catch((e) => log("Run: " + e, true));

    el("btnCvStart").onclick = async () => {
      if (cvRunning) {
        log("CV вже працює");
        return;
      }
      try {
        const d = await apiPost("/api/cv/start");
        if (d.status === "already_running") {
          log("CV вже запущено");
        } else {
          log("CV запущено — відео зверху карти");
        }
        setTimeout(showCvOverlay, 600);
        pollStatus();
      } catch (e) { log("CV: " + e, true); }
    };

    el("btnCvStop").onclick = () =>
      apiPost("/api/cv/stop").then(() => {
        log("CV stop");
        hideCvOverlay();
        pollStatus();
      });

    el("btnSprayer").onclick = async () => {
      sprayer = !sprayer;
      await apiPost(sprayer ? "/api/sprayer/on" : "/api/sprayer/off");
      syncSprayerBtn();
    };

    el("btnEmergency").onclick = () => {
      if (!confirm("Аварійна зупинка?")) return;
      apiPost("/api/emergency/stop").then(() => log("EMERGENCY", true));
    };
  }

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initCvDrag();
    bindMoveButtons();
    bindControls();
    loadMission();
    pollStatus();
    setInterval(pollStatus, POLL_MS);
    log("Супутник за замовч. · ▶ YOLO = відео поверх карти · клік = waypoint");
  });
})();
