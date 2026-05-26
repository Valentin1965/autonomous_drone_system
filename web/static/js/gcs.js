/**
 * GCS — супутник, відео-overlay, waypoints
 */
(function () {
  const DEFAULT_CENTER = [50.4501, 30.5234];
  const LS_SPEED = "gcs_mission_speed_m_s";
  const LS_MISSION = "gcs_mission_backup_v2";
  /** Координати з config/demo_mission.json — зняти залишки після старого DEMO. */
  const DEMO_ROUTE_WPS = [
    [50.4501, 30.5234],
    [50.45055, 30.52395],
    [50.451, 30.5245],
    [50.45145, 30.52505],
    [50.4519, 30.5256],
  ];
  const LS_CV_W = "gcs_cv_width";
  const LS_CV_VIDEO_H = "gcs_cv_video_h";
  const POLL_MS = 500;
  const TRAIL_MAX = 300;
  const TRAIL_MIN_M = 0.3;

  let map, roverMarker, trailLine, missionLayer, missionRoute, fleetRoutesLayer, vehicleLayer;
  let baseLayer, satLayer;
  const trail = [];
  let waypoints = [];
  /** Маршрути всіх дронів: vehicle_id → [{lat, lon}, …] */
  const fleetRoutes = {};
  const fleetRoutePolylines = {};
  let wpMarkers = [];
  let sprayer = false;
  let moveTimer = null;
  let mapFollow = true;
  let lastLatLon = null;
  let lastHeading = 90;
  let missionMode = true;
  let cvRunning = false;
  let missionActive = false;
  let missionPhase = "idle";
  let missionTargetIndex = -1;
  let missionCanResume = false;
  let controlMode = "autonomous";
  let manualDriving = false;
  let missionPresets = { spray_m_s: 0.8, row_m_s: 1.0, transfer_m_s: 1.5 };
  let linkWasConnected = false;
  let offlineBeepEnabled = true;
  let selectedVehicleId = "rover_1";
  let fleetVehicles = [];
  let fleetMulti = false;
  let fleetMinCount = 1;
  let fleetMaxCount = 6;
  let lastFleetCountFromServer = null;
  let fleetMarkerLayer = null;
  const fleetMarkers = {};
  const fleetRoverMarkers = {};
  let missionRecord = {
    work_started_at: null,
    work_finished_at: null,
    spraying: { applied: false, product: "" },
    field_notes: "",
  };

  const DEFAULT_SIM_LAT = 50.4501;
  const DEFAULT_SIM_LON = 30.5234;

  const el = (id) => document.getElementById(id);

  function withVehicle(url, vehicleId) {
    const sep = url.includes("?") ? "&" : "?";
    const vid = vehicleId || selectedVehicleId;
    return `${url}${sep}vehicle_id=${encodeURIComponent(vid)}`;
  }

  function syncWaypointsToCache() {
    fleetRoutes[selectedVehicleId] = waypoints.map((w) => ({
      lat: w.lat,
      lon: w.lon,
    }));
  }

  function fleetVehicleIds() {
    if (fleetVehicles && fleetVehicles.length > 0) {
      return fleetVehicles.map((fv) => fv.id);
    }
    return [selectedVehicleId];
  }

  function vehicleColor(vid) {
    const fv = fleetVehicles.find((x) => x.id === vid);
    return (fv && fv.color) || "#ff9800";
  }

  function vehicleName(vid) {
    const fv = fleetVehicles.find((x) => x.id === vid);
    return (fv && fv.name) || vid;
  }

  function droneNumber(vid) {
    const m = String(vid).match(/_(\d+)$/);
    if (m) return m[1];
    const m2 = String(vid).match(/(\d+)/);
    return m2 ? m2[1] : "?";
  }

  function allFleetIdsWithRoutes() {
    const set = new Set(fleetVehicleIds());
    Object.keys(fleetRoutes).forEach((k) => {
      if (fleetRoutes[k] && fleetRoutes[k].length > 0) set.add(k);
    });
    return [...set];
  }

  function ensureFleetRoutesLayer() {
    if (!map) return;
    if (!fleetRoutesLayer) {
      fleetRoutesLayer = L.layerGroup().addTo(map);
    }
  }

  function fleetRoverIcon(droneNum, color, isSelected, headingDeg) {
    const h =
      headingDeg != null && !Number.isNaN(headingDeg) ? headingDeg : 90;
    const cls = isSelected
      ? "fleet-rover-marker fleet-rover-selected"
      : "fleet-rover-marker";
    return L.divIcon({
      className: cls,
      html:
        `<div class="fleet-rover-badge" style="--rover-color:${color}">` +
        `<span class="fleet-rover-arrow" style="transform:rotate(${h}deg)">▲</span>` +
        `<span class="fleet-rover-num">${droneNum}</span>` +
        `</div>`,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    });
  }

  function wpIconFleet(wpNum, color, active, showDroneNum, droneNum) {
    const cls = active
      ? "wp-marker wp-marker-active wp-marker-fleet"
      : "wp-marker wp-marker-fleet";
    const label = showDroneNum ? `${droneNum}` : `${wpNum}`;
    const sub = showDroneNum ? `<small>${wpNum}</small>` : "";
    return L.divIcon({
      className: cls,
      html:
        `<span class="wp-fleet-dot" style="background:${color};border-color:#fff">` +
        `${label}${sub}</span>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  async function fetchMissionWaypoints(vid) {
    const r = await fetch(withVehicle("/api/mission", vid));
    const d = await r.json();
    return d.waypoints || [];
  }

  async function refreshAllFleetMissions() {
    syncWaypointsToCache();
    const ids = fleetVehicleIds();
    await Promise.all(
      ids.map(async (vid) => {
        if (vid === selectedVehicleId) return;
        try {
          fleetRoutes[vid] = await fetchMissionWaypoints(vid);
        } catch (_) {
          if (!fleetRoutes[vid]) fleetRoutes[vid] = [];
        }
      })
    );
    waypoints = fleetRoutes[selectedVehicleId] || waypoints;
    renderMission();
    await syncAllFleetRouteStarts();
  }

  function log(msg, isErr) {
    const p = el("logPanel");
    const line = `[${new Date().toLocaleTimeString()}] ${msg}\n`;
    p.textContent = line + p.textContent.slice(0, 2000);
    p.style.color = isErr ? "#f88" : "#9cdcfe";
  }

  function formatApiError(err) {
    const raw = String(err && err.message ? err.message : err);
    try {
      const o = JSON.parse(raw);
      if (o.error === "empty mission") {
        return "Маршрут порожній: увімкніть «Редагувати: ВКЛ» і клікніть на карті";
      }
      return o.message || o.error || raw;
    } catch (_) {
      return raw;
    }
  }

  async function apiPost(url, body, optsExtra) {
    const opts = { method: "POST", headers: {} };
    const noVehicle = optsExtra && optsExtra.noVehicle;
    const vehicleId = optsExtra && optsExtra.vehicleId;
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      const payload = { ...(body || {}) };
      if (vehicleId) {
        payload.vehicle_id = vehicleId;
      } else if (!noVehicle) {
        payload.vehicle_id = payload.vehicle_id || selectedVehicleId;
      }
      opts.body = JSON.stringify(payload);
    }
    const useVehicleQuery = !noVehicle && !vehicleId;
    const r = await fetch(useVehicleQuery ? withVehicle(url) : url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(JSON.stringify(data));
    return data;
  }

  async function apiPut(url, body) {
    const r = await fetch(withVehicle(url), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, vehicle_id: selectedVehicleId }),
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

  function roverIcon(headingDeg) {
    const h = headingDeg != null && !Number.isNaN(headingDeg) ? headingDeg : lastHeading;
    return L.divIcon({
      className: "rover-arrow",
      html: `<span class="rover-arrow-inner" style="transform:rotate(${h}deg);display:inline-block">▲</span>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function placeRoverAt(lat, lon, heading, resetTrail) {
    if (!map) return;
    const pos = [Number(lat), Number(lon)];
    if (Number.isNaN(pos[0]) || Number.isNaN(pos[1])) return;

    if (heading != null && !Number.isNaN(heading)) lastHeading = heading;

    if (!vehicleLayer) {
      vehicleLayer = L.layerGroup().addTo(map);
    }
    const vid = selectedVehicleId;
    const num = droneNumber(vid);
    const color = vehicleColor(vid);
    const icon = fleetRoverIcon(num, color, true, lastHeading);
    if (!fleetRoverMarkers[vid]) {
      fleetRoverMarkers[vid] = L.marker(pos, {
        icon,
        zIndexOffset: 3000,
      }).addTo(vehicleLayer);
    } else {
      fleetRoverMarkers[vid].setLatLng(pos);
      fleetRoverMarkers[vid].setIcon(icon);
      fleetRoverMarkers[vid].setZIndexOffset(3000);
    }
    fleetRoverMarkers[vid].bindTooltip(`${vehicleName(vid)} · дрон ${num}`);
    if (roverMarker && vehicleLayer.hasLayer(roverMarker)) {
      vehicleLayer.removeLayer(roverMarker);
    }

    if (!trailLine) {
      trailLine = L.polyline([], {
        color: "#4fc3f7",
        weight: 5,
        opacity: 0.9,
      }).addTo(vehicleLayer);
    } else if (!vehicleLayer.hasLayer(trailLine)) {
      trailLine.addTo(vehicleLayer);
    }

    if (resetTrail) {
      trail.length = 0;
      trail.push(pos);
      trailLine.setLatLngs(trail);
      lastLatLon = pos;
    }
  }

  function rawGpsFromStatus(s) {
    const v = s.mission && s.mission.vehicle;
    if (v && v.lat != null && v.lon != null) return v;
    return s.gps || {};
  }

  function isAutonomousMode() {
    return controlMode === "autonomous";
  }

  function isManualMode() {
    return controlMode === "manual";
  }

  function isMissionBusy() {
    return missionPhase === "running" || missionPhase === "returning";
  }

  /** Додавання / зняття / перетягування точок на карті. */
  function canEditRoute() {
    return isAutonomousMode() && missionMode && !isMissionBusy();
  }

  function isManualPanelEnabled() {
    const panel = el("manualPanel");
    return !!(panel && !panel.classList.contains("panel-disabled"));
  }

  async function ensureManualMode() {
    if (controlMode === "manual") return true;
    try {
      await switchControlMode("manual");
      return controlMode === "manual";
    } catch (e) {
      log("Ручний режим: " + formatApiError(e), true);
      return false;
    }
  }

  function syncControlModeUi() {
    const autoBtn = el("btnModeAutonomous");
    const manBtn = el("btnModeManual");
    const autoPanel = el("autonomousPanel");
    const manPanel = el("manualPanel");
    const modeHint = el("modeHint");
    const hudMode = el("hudControlMode");

    if (autoBtn) autoBtn.classList.toggle("active", isAutonomousMode());
    if (manBtn) manBtn.classList.toggle("active", isManualMode());
    if (autoPanel) autoPanel.classList.toggle("panel-disabled", !isAutonomousMode());
    if (manPanel) {
      manPanel.classList.toggle("panel-disabled", !isManualMode());
      manPanel.setAttribute("aria-disabled", isManualMode() ? "false" : "true");
    }
    if (hudMode) {
      hudMode.textContent = isAutonomousMode() ? "Автономний" : "Ручний";
    }
    if (modeHint) {
      if (isManualMode()) {
        modeHint.textContent = "Ручний: стрілки · STOP · перемкніть «Автономний» для маршруту";
      } else if (missionPhase === "paused") {
        modeHint.textContent = "Маршрут призупинено — «▶ Продовжити» або «Ручний»";
      } else {
        modeHint.textContent = "Автономний: точки на карті · «Ручний» — керування оператором";
      }
    }
    syncMissionUi();
  }

  async function switchControlMode(mode) {
    const prev = controlMode;
    controlMode = mode;
    syncControlModeUi();
    const path = mode === "manual"
      ? "/api/control/mode/manual"
      : "/api/control/mode/autonomous";
    let d;
    try {
      d = await apiPost(path);
    } catch (e) {
      controlMode = prev;
      syncControlModeUi();
      throw e;
    }
    controlMode = d.mode || mode;
    if (d.mission) {
      missionPhase = d.mission.phase || missionPhase;
      missionActive = !!d.mission.active;
      missionCanResume = !!d.mission.can_resume;
    }
    if (mode === "manual") {
      manualDriving = false;
      try {
        await apiPost("/api/arm");
      } catch (_) { /* arm on manual switch */ }
    }
    syncControlModeUi();
    log(d.message || (mode === "manual" ? "Ручний режим" : "Автономний режим"));
    pollStatus();
  }

  function selectedWaypoints() {
    return fleetRoutes[selectedVehicleId] || waypoints;
  }

  function clearMovementTrail() {
    trail.length = 0;
    if (trailLine) trailLine.setLatLngs([]);
    lastLatLon = null;
  }

  async function syncVehicleRouteStart(vid) {
    const wps = fleetRoutes[vid] || (vid === selectedVehicleId ? waypoints : []);
    if (!wps.length) return;
    try {
      await apiPost("/api/mission/sync_start", {}, { vehicleId: vid });
    } catch (_) { /* sim offline */ }
  }

  async function syncAllFleetRouteStarts() {
    const ids = allFleetIdsWithRoutes();
    await Promise.all(
      ids.map((vid) => syncVehicleRouteStart(vid))
    );
  }

  function focusMapOnSelected() {
    const wps = selectedWaypoints();
    if (wps.length > 0) {
      mapFollow = true;
      map.setView([wps[0].lat, wps[0].lon], 18);
      return;
    }
    const fv = fleetVehicles.find((x) => x.id === selectedVehicleId);
    const gps = (fv && fv.gps) || {};
    if (validGps(gps)) {
      map.setView([Number(gps.lat), Number(gps.lon)], 17);
      return;
    }
    if (map && lastLatLon) {
      map.setView(lastLatLon, 17);
    }
  }

  function clearRoverFromMap() {
    trail.length = 0;
    lastLatLon = null;
    if (trailLine) trailLine.setLatLngs([]);
    const vid = selectedVehicleId;
    if (fleetRoverMarkers[vid] && vehicleLayer) {
      vehicleLayer.removeLayer(fleetRoverMarkers[vid]);
      delete fleetRoverMarkers[vid];
    }
    if (roverMarker && vehicleLayer) {
      vehicleLayer.removeLayer(roverMarker);
      roverMarker = null;
    }
  }

  function focusStartWaypoint(resetTrail) {
    const wps = selectedWaypoints();
    if (!wps.length) return;
    const w0 = wps[0];
    mapFollow = true;
    map.setView([w0.lat, w0.lon], 18);
    placeRoverAt(w0.lat, w0.lon, lastHeading, resetTrail);
    lastLatLon = [w0.lat, w0.lon];
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

    vehicleLayer = L.layerGroup().addTo(map);
    fleetRoutesLayer = L.layerGroup().addTo(map);
    missionLayer = L.layerGroup().addTo(map);
    missionRoute = L.polyline([], { color: "#ff9800", weight: 3, dashArray: "8 6", opacity: 0 });

    map.on("dragstart", () => { mapFollow = false; });
    map.on("click", onMapClick);
  }

  function wpIcon(n, active) {
    const cls = active ? "wp-marker wp-marker-active" : "wp-marker";
    return L.divIcon({
      className: cls,
      html: `<span>${n}</span>`,
      iconSize: [26, 26],
      iconAnchor: [13, 13],
    });
  }

  function renderMission() {
    syncWaypointsToCache();
    ensureFleetRoutesLayer();
    missionLayer.clearLayers();
    wpMarkers = [];
    Object.keys(fleetRoutePolylines).forEach((vid) => {
      if (fleetRoutePolylines[vid] && fleetRoutesLayer) {
        fleetRoutesLayer.removeLayer(fleetRoutePolylines[vid]);
      }
      delete fleetRoutePolylines[vid];
    });
    missionRoute.setLatLngs([]);

    const editable = canEditRoute();
    const ids = allFleetIdsWithRoutes();

    ids.forEach((vid) => {
      const wps =
        fleetRoutes[vid] ||
        (vid === selectedVehicleId ? waypoints : []);
      if (!wps.length) return;

      const latlngs = wps.map((wp) => [Number(wp.lat), Number(wp.lon)]);
      const isSel = vid === selectedVehicleId;
      const color = vehicleColor(vid);
      const name = vehicleName(vid);
      const dnum = droneNumber(vid);

      const line = L.polyline(latlngs, {
        color,
        weight: isSel ? 5 : 3.5,
        dashArray: isSel ? null : "12 8",
        opacity: isSel ? 1 : 0.9,
        lineCap: "round",
        lineJoin: "round",
      }).addTo(fleetRoutesLayer);
      line.bindTooltip(`${name} · ${wps.length} тч.`, { sticky: true });
      fleetRoutePolylines[vid] = line;

      wps.forEach((wp, i) => {
        const pos = [wp.lat, wp.lon];
        const active = isSel && i === missionTargetIndex;
        const showDroneOnFirst = i === 0;
        const m = L.marker(pos, {
          icon: wpIconFleet(i + 1, color, active, showDroneOnFirst, dnum),
          draggable: isSel && editable,
          zIndexOffset: isSel ? 500 + i : 100 + i,
        }).addTo(missionLayer);
        const popupHtml = isSel && editable
          ? `<b>Дрон ${dnum} · ${name} · т.${i + 1}</b><br>${wp.lat.toFixed(6)}, ${wp.lon.toFixed(6)}<br>`
            + `<button type="button" class="wp-popup-del" data-idx="${i}">✕ Зняти точку</button>`
          : `<b>Дрон ${dnum} · ${name} · т.${i + 1}</b><br>${wp.lat.toFixed(6)}, ${wp.lon.toFixed(6)}`;
        m.bindPopup(popupHtml);
        if (isSel && editable) {
          m.on("popupopen", () => {
            const root = m.getPopup() && m.getPopup().getElement();
            const btn = root && root.querySelector(".wp-popup-del");
            if (btn) {
              btn.onclick = () => {
                m.closePopup();
                removeWaypoint(i);
              };
            }
          });
          m.on("dragend", () => {
            const ll = m.getLatLng();
            updateWaypointPosition(i, ll.lat, ll.lng);
          });
          m.on("contextmenu", (e) => {
            L.DomEvent.stopPropagation(e);
            removeWaypoint(i);
          });
        } else if (isSel && !isMissionBusy()) {
          m.on("click", () => {
            gotoWaypoint(i);
          });
        }
        wpMarkers.push(m);
      });
    });

    const selWps = fleetRoutes[selectedVehicleId] || waypoints;
    el("hudWps").textContent = String(selWps.length);
    const hudFleet = el("hudFleetRoutes");
    if (hudFleet) {
      const parts = ids.map(
        (vid) => `№${droneNumber(vid)}:${(fleetRoutes[vid] || []).length}`
      );
      hudFleet.textContent = parts.length ? parts.join(" · ") : "—";
    }
    saveMissionBackup();
    renderWpList();
    syncMissionUi();
  }

  function syncMissionUi() {
    const runBtn = el("btnMissionRun");
    const stopBtn = el("btnMissionStop");
    const retBtn = el("btnMissionReturn");
    const hint = el("autonomousPanel") && el("autonomousPanel").querySelector(".hint");
    const n = waypoints.length;
    const busy = isMissionBusy();
    const paused = missionPhase === "paused";
    const editBtn = el("btnMissionMode");
    const editHint = el("editRouteHint");
    const rmLastBtn = el("btnWpRemoveLast");

    if (editBtn) {
      editBtn.textContent = missionMode ? "Редагувати: ВКЛ" : "Редагувати: ВИМК";
      editBtn.classList.toggle("active", missionMode);
      editBtn.disabled = !isAutonomousMode() || busy;
    }
    if (rmLastBtn) {
      rmLastBtn.disabled = !canEditRoute() || n === 0;
    }
    if (editHint) {
      if (!isAutonomousMode()) {
        editHint.textContent = "Редагування — лише в «Автономному» режимі";
        editHint.classList.add("route-locked");
      } else if (busy) {
        editHint.textContent = "Під час руху редагування вимкнено — натисніть «■ Стоп»";
        editHint.classList.add("route-locked");
      } else if (!missionMode) {
        editHint.textContent = "Увімкніть «Редагувати: ВКЛ» — клік, перетяг, ✕";
        editHint.classList.remove("route-locked");
      } else {
        editHint.textContent = "Клік на карті — додати · перетягніть маркер · ✕ — зняти";
        editHint.classList.remove("route-locked");
      }
    }

    if (runBtn) {
      runBtn.textContent = paused ? "▶ Продовжити маршрут" : "▶ Старт маршруту";
      runBtn.disabled =
        !isAutonomousMode() || n === 0 || busy || missionPhase === "at_last";
    }
    if (stopBtn) {
      stopBtn.disabled = !(busy || missionPhase === "at_last" || paused);
    }
    if (retBtn) {
      retBtn.disabled = missionPhase !== "at_last";
    }
    if (hint) {
      if (missionPhase === "at_last") {
        hint.textContent = "Остання точка — натисніть «↩ Повернення» або «■ Стоп»";
      } else if (missionPhase === "returning") {
        hint.textContent = "Повернення до точки 1…";
      } else if (missionPhase === "paused") {
        hint.textContent = "Призупинено — «▶ Продовжити» або перемкніть «Ручний»";
      } else if (missionMode && canEditRoute()) {
        hint.textContent = n === 0
          ? "Клік на карті — перша точка · «▶ Старт маршруту»"
          : `Точок: ${n} · маршрут 1→2→…→${n} · можна змінювати`;
      } else {
        hint.textContent = "Увімкніть «Редагувати: ВКЛ» або зупиніть маршрут";
      }
    }
  }

  function renderWpList() {
    const ul = el("wpList");
    if (!ul) return;
    ul.innerHTML = "";
    if (waypoints.length === 0) {
      const li = document.createElement("li");
      li.className = "wp-empty";
      li.textContent = canEditRoute()
        ? "Немає точок — клікніть на карті"
        : "Немає точок";
      ul.appendChild(li);
      return;
    }
    const editable = canEditRoute();
    waypoints.forEach((wp, i) => {
      const li = document.createElement("li");
      li.className = "wp-item";
      const num = document.createElement("span");
      num.className = "wp-num";
      num.textContent = String(i + 1);
      const coords = document.createElement("span");
      coords.className = "wp-coords";
      coords.textContent = `${wp.lat.toFixed(5)}, ${wp.lon.toFixed(5)}`;
      coords.title = "Показати на карті";
      coords.onclick = () => map.setView([wp.lat, wp.lon], 18);
      li.appendChild(num);
      li.appendChild(coords);
      const actions = document.createElement("span");
      actions.className = "wp-actions";
      if (editable) {
        const del = document.createElement("button");
        del.type = "button";
        del.className = "wp-del";
        del.textContent = "✕";
        del.title = `Зняти точку ${i + 1}`;
        del.onclick = (e) => {
          e.stopPropagation();
          removeWaypoint(i);
        };
        actions.appendChild(del);
      } else if (!isMissionBusy()) {
        const go = document.createElement("button");
        go.type = "button";
        go.textContent = "→";
        go.title = `Їхати до точки ${i + 1}`;
        go.onclick = (e) => {
          e.stopPropagation();
          gotoWaypoint(i);
        };
        actions.appendChild(go);
      }
      li.appendChild(actions);
      ul.appendChild(li);
    });
  }

  async function gotoWaypoint(idx) {
    try {
      await apiPost("/api/mission/goto", { index: idx });
      log(`GOTO → точка ${idx + 1}`);
    } catch (err) {
      log("GOTO: " + formatApiError(err), true);
    }
  }

  async function updateWaypointPosition(idx, lat, lon) {
    if (!canEditRoute()) return;
    try {
      await apiPut(`/api/mission/waypoint/${idx}`, { lat, lon });
      waypoints =
        (await (await fetch(withVehicle("/api/mission"))).json()).waypoints || [];
      fleetRoutes[selectedVehicleId] = waypoints;
      renderMission();
      log(`Точку ${idx + 1} переміщено`);
    } catch (err) {
      log("Зміна точки: " + formatApiError(err), true);
      renderMission();
    }
  }

  async function loadMission() {
    try {
      const r = await fetch(withVehicle("/api/mission"));
      const d = await r.json();
      waypoints = d.waypoints || [];
      fleetRoutes[selectedVehicleId] = waypoints;
      if (d.record) applyMissionRecordToForm(d.record);
      if (isLegacyDemoRoute(waypoints)) {
        await clearMissionRoute();
        log("Знято старий приклад маршруту — додайте точки на карті");
        return;
      }
      if (fleetVehicles.length > 1) {
        await refreshAllFleetMissions();
      } else {
        renderMission();
      }
      if (waypoints.length > 0) {
        await syncAllFleetRouteStarts();
        clearMovementTrail();
        focusMapOnSelected();
        focusStartWaypoint(false);
      } else {
        await syncAllFleetRouteStarts();
        clearMovementTrail();
        focusMapOnSelected();
      }
    } catch (e) { /* ignore */ }
  }

  async function onMapClick(e) {
    if (!isAutonomousMode()) {
      log("Точки на карті — лише в «Автономному» режимі", true);
      return;
    }
    if (isMissionBusy()) {
      log("Зупиніть маршрут (■ Стоп), потім редагуйте точки", true);
      return;
    }
    if (!missionMode) {
      log("Увімкніть «Редагувати: ВКЛ», потім клікніть на карті", true);
      return;
    }
    const wp = { lat: e.latlng.lat, lon: e.latlng.lng };
    try {
      const d = await apiPost("/api/mission/waypoint", wp);
      waypoints =
        (await (await fetch(withVehicle("/api/mission"))).json()).waypoints || [];
      fleetRoutes[selectedVehicleId] = waypoints;
      renderMission();
      log(`Waypoint ${d.index + 1} додано`);
      if (d.index === 0) {
        await syncVehicleRouteStart(selectedVehicleId);
        clearMovementTrail();
        focusStartWaypoint(true);
        log("Точка 1 = старт дрона (без привʼязки до центру карти)");
      }
    } catch (err) {
      log("Waypoint: " + err, true);
    }
  }

  async function removeWaypoint(idx) {
    if (!canEditRoute() && isMissionBusy()) {
      log("Зупиніть маршрут перед видаленням точок", true);
      return;
    }
    if (idx < 0 || idx >= waypoints.length) return;
    const label = idx + 1;
    if (!confirm(`Зняти точку ${label} з маршруту?`)) return;
    try {
      const r = await fetch(withVehicle(`/api/mission/waypoint/${idx}`), { method: "DELETE" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.message || body.error || r.status);
      waypoints =
        (await (await fetch(withVehicle("/api/mission"))).json()).waypoints || [];
      fleetRoutes[selectedVehicleId] = waypoints;
      if (missionPhase === "paused") missionCanResume = true;
      renderMission();
      if (waypoints.length === 0) {
        clearRoverFromMap();
      }
      log(`Точку ${label} знято`);
    } catch (err) {
      log("Видалення: " + formatApiError(err), true);
    }
  }

  function updateMap(gps) {
    if (!validGps(gps)) return;
    const lat = Number(gps.lat);
    const lon = Number(gps.lon);
    const pos = [lat, lon];
    const hdg = gps.heading != null && !Number.isNaN(gps.heading) ? gps.heading : lastHeading;

    placeRoverAt(lat, lon, hdg, false);

    if (isMissionBusy()) {
      const last = trail[trail.length - 1];
      if (!last || haversineM(last, pos) >= TRAIL_MIN_M) {
        trail.push(pos);
        if (trail.length > TRAIL_MAX) trail.shift();
        if (trailLine) trailLine.setLatLngs(trail);
      }
      const hint = el("mapHint");
      if (hint) hint.style.display = "none";
    } else {
      clearMovementTrail();
    }

    if (mapFollow) map.panTo(pos, { animate: true, duration: 0.25 });
    lastLatLon = pos;
  }

  function missionGps(s) {
    return rawGpsFromStatus(s);
  }

  function setPreflightItem(id, ok) {
    const li = el(id);
    if (!li) return;
    li.classList.toggle("ok", !!ok);
    li.dataset.ok = ok ? "1" : "0";
  }

  function playOfflineBeep() {
    if (!offlineBeepEnabled) return;
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.connect(g);
      g.connect(ctx.destination);
      o.frequency.value = 440;
      g.gain.value = 0.08;
      o.start();
      setTimeout(() => {
        o.stop();
        ctx.close();
      }, 200);
    } catch (_) { /* no audio */ }
  }

  function isoToDatetimeLocal(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
      const s = String(iso).replace(" ", "T");
      return s.length >= 16 ? s.slice(0, 16) : s;
    }
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}`
    );
  }

  function datetimeLocalToIso(val) {
    if (!val) return null;
    const d = new Date(val);
    if (Number.isNaN(d.getTime())) return val;
    const pad = (n) => String(n).padStart(2, "0");
    return (
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
      `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
    );
  }

  function applyMissionRecordToForm(rec) {
    missionRecord = rec || missionRecord;
    const ws = el("workStartedAt");
    const wf = el("workFinishedAt");
    const sp = el("sprayingApplied");
    const prod = el("sprayingProduct");
    const notes = el("fieldNotes");
    if (ws) ws.value = isoToDatetimeLocal(missionRecord.work_started_at);
    if (wf) wf.value = isoToDatetimeLocal(missionRecord.work_finished_at);
    const spray = missionRecord.spraying || {};
    if (sp) sp.checked = !!spray.applied;
    if (prod) prod.value = spray.product || "";
    if (notes) notes.value = missionRecord.field_notes || "";
  }

  function readMissionRecordFromForm() {
    return {
      work_started_at: datetimeLocalToIso(el("workStartedAt")?.value),
      work_finished_at: datetimeLocalToIso(el("workFinishedAt")?.value),
      spraying: {
        applied: !!el("sprayingApplied")?.checked,
        product: (el("sprayingProduct")?.value || "").trim(),
      },
      field_notes: (el("fieldNotes")?.value || "").trim(),
    };
  }

  async function saveMissionRecordToServer() {
    const record = readMissionRecordFromForm();
    const d = await apiPut("/api/mission/record", { record });
    missionRecord = d.record || record;
    applyMissionRecordToForm(missionRecord);
    saveMissionBackup();
    log("Дані роботи збережено");
  }

  function missionPhaseLabel(m) {
    if (!m) return "—";
    const ph = m.phase || "idle";
    if (ph === "running" && m.total > 0) return `${(m.index || 0) + 1}/${m.total}`;
    if (ph === "at_last") return "остання";
    if (ph === "paused") return "пауза";
    if (ph === "manual") return ph;
    return ph;
  }

  function renderFleetSelector(fleet) {
    const box = el("fleetSelector");
    const panel = el("fleetPanel");
    if (!box) return;
    if (panel) panel.classList.remove("hidden");
    const countInp = el("fleetCountInput");
    if (countInp && fleet) {
      fleetMinCount = fleet.min_count || 1;
      fleetMaxCount = fleet.max_count || 6;
      countInp.min = String(fleetMinCount);
      countInp.max = String(fleetMaxCount);
      const serverCount = fleet.count || 1;
      if (
        document.activeElement !== countInp &&
        lastFleetCountFromServer !== serverCount
      ) {
        countInp.value = String(serverCount);
        lastFleetCountFromServer = serverCount;
      }
    }
    const hintSize = el("fleetSizeHint");
    if (hintSize && fleet && fleet.message) {
      hintSize.textContent = fleet.message;
    }
    const n = (fleet && fleet.count) || 1;
    if (!fleet || n <= 1) {
      box.innerHTML = "";
      fleetMulti = false;
      fleetVehicles = fleet ? fleet.vehicles || [] : [];
      if (fleet && fleet.selected_vehicle_id) {
        selectedVehicleId = fleet.selected_vehicle_id;
      }
      return;
    }
    fleetMulti = true;
    fleetVehicles = fleet.vehicles || [];
    selectedVehicleId = fleet.selected_vehicle_id || selectedVehicleId;
    box.innerHTML = "";
    fleetVehicles.forEach((fv) => {
      const row = document.createElement("div");
      row.className =
        "fleet-btn" + (fv.id === selectedVehicleId ? " active" : "");
      const link = fv.connected ? "●" : "○";
      const mode = fv.control_mode === "manual" ? "ручний" : "авто";
      const ph = missionPhaseLabel(fv.mission);
      row.innerHTML = `
        <button type="button" class="fleet-select" data-vid="${fv.id}">
          <span class="fleet-link ${fv.connected ? "on" : "off"}">${link}</span>
          <strong>${fv.name}</strong>
          <span class="fleet-phase">${mode} · ${ph} · ${fv.waypoint_count || 0} тч.</span>
        </button>
        <button type="button" class="fleet-run" data-vid="${fv.id}" title="Старт маршруту цього дрона">▶</button>`;
      row.querySelector(".fleet-select").onclick = () => selectFleetVehicle(fv.id);
      row.querySelector(".fleet-run").onclick = (e) => {
        e.stopPropagation();
        startFleetVehicleMission(fv.id);
      };
      box.appendChild(row);
    });
    const hint = el("fleetHint");
    if (hint) {
      hint.textContent =
        "Клік — обрати дрон і його маршрут на карті · ▶ — старт без перемикання · кілька дронів можуть їхати паралельно.";
    }
  }

  async function setVehicleAutonomous(vid) {
    await apiPost(
      "/api/control/mode/autonomous",
      { vehicle_id: vid },
      { vehicleId: vid }
    );
  }

  async function startFleetVehicleMission(vid) {
    const fv = fleetVehicles.find((x) => x.id === vid);
    if (!fv || !(fv.waypoint_count > 0)) {
      log(`${fv ? fv.name : vid}: спочатку додайте точки маршруту`, true);
      return;
    }
    if (fv.control_mode !== "autonomous") {
      try {
        await setVehicleAutonomous(vid);
      } catch (e) {
        log("Автономний: " + formatApiError(e), true);
        return;
      }
    }
    try {
      const d = await apiPost(
        "/api/fleet/mission/run",
        { speed: getMissionSpeed() },
        { vehicleId: vid, noVehicle: true }
      );
      log(`▶ ${fv.name}: маршрут запущено (${d.phase || "running"})`);
      await refreshAllFleetMissions();
      clearMovementTrail();
      pollStatus();
    } catch (e) {
      log(`Старт ${fv.name}: ` + formatApiError(e), true);
    }
  }

  async function applyFleetCount() {
    const inp = el("fleetCountInput");
    if (!inp) return;
    let n = parseInt(inp.value, 10);
    if (Number.isNaN(n)) n = fleetMinCount;
    n = Math.max(fleetMinCount, Math.min(fleetMaxCount, n));
    inp.value = String(n);
    const d = await apiPost("/api/fleet/configure", { count: n }, { noVehicle: true });
    lastFleetCountFromServer = d.count || n;
    if (countInp) countInp.value = String(lastFleetCountFromServer);
    if (d.message) log(d.message);
    renderFleetSelector(d);
    updateFleetMarkers(d);
    selectedVehicleId = d.selected_vehicle_id || selectedVehicleId;
    await loadMission();
    await refreshAllFleetMissions();
    pollStatus();
  }

  async function selectFleetVehicle(vid) {
    if (!vid || vid === selectedVehicleId) return;
    syncWaypointsToCache();
    try {
      const d = await apiPost("/api/fleet/select", { vehicle_id: vid });
      selectedVehicleId = d.selected_vehicle_id || vid;
      controlMode = d.control_mode || controlMode;
      if (d.mission) {
        missionPhase = d.mission.phase || missionPhase;
        missionActive = !!d.mission.active;
        missionCanResume = !!d.mission.can_resume;
      }
      if (d.record) applyMissionRecordToForm(d.record);
      waypoints = fleetRoutes[vid] ? fleetRoutes[vid].map((w) => ({ ...w })) : [];
      await loadMission();
      clearMovementTrail();
      syncControlModeUi();
      log(`Обрано: ${d.name || vid} — маршрути інших дронів лишаються на карті`);
      pollStatus();
    } catch (e) {
      log("Флот: " + formatApiError(e), true);
    }
  }

  function updateFleetRoversOnMap(fleet) {
    if (!map || !fleet || !fleet.vehicles) return;
    if (!vehicleLayer) {
      vehicleLayer = L.layerGroup().addTo(map);
    }
    const seen = new Set();
    fleet.vehicles.forEach((fv) => {
      seen.add(fv.id);
      const gps = fv.gps || (fv.mission && fv.mission.vehicle) || {};
      if (!validGps(gps)) return;
      const pos = [Number(gps.lat), Number(gps.lon)];
      const isSel = fv.id === selectedVehicleId;
      const color = fv.color || vehicleColor(fv.id);
      const num = droneNumber(fv.id);
      const hdg =
        gps.heading != null && !Number.isNaN(gps.heading)
          ? gps.heading
          : 90;
      const icon = fleetRoverIcon(num, color, isSel, hdg);
      const z = isSel ? 3000 : 2100 + parseInt(num, 10) || 0;
      if (!fleetRoverMarkers[fv.id]) {
        fleetRoverMarkers[fv.id] = L.marker(pos, {
          icon,
          zIndexOffset: z,
        }).addTo(vehicleLayer);
      } else {
        fleetRoverMarkers[fv.id].setLatLng(pos);
        fleetRoverMarkers[fv.id].setIcon(icon);
        fleetRoverMarkers[fv.id].setZIndexOffset(z);
      }
      fleetRoverMarkers[fv.id].bindTooltip(`${fv.name} · дрон ${num}`);
    });
    Object.keys(fleetRoverMarkers).forEach((id) => {
      if (!seen.has(id)) {
        vehicleLayer.removeLayer(fleetRoverMarkers[id]);
        delete fleetRoverMarkers[id];
      }
    });
    if (fleetMarkerLayer) {
      fleetMarkerLayer.clearLayers();
    }
    Object.keys(fleetMarkers).forEach((k) => delete fleetMarkers[k]);
    if (roverMarker && vehicleLayer.hasLayer(roverMarker)) {
      vehicleLayer.removeLayer(roverMarker);
    }
  }

  function updateFleetMarkers(fleet) {
    updateFleetRoversOnMap(fleet);
  }

  function updateSimBanner(s) {
    const banner = el("simBanner");
    if (!banner) return;
    if (s.simulator_active) {
      banner.classList.remove("hidden");
      banner.textContent = "Режим симуляції — rover віртуальний (без Pixhawk)";
    } else {
      banner.classList.add("hidden");
    }
  }

  function updateConfigWarning(s) {
    const box = el("configWarning");
    if (!box) return;
    const warns = s.warnings || [];
    if (!warns.length) {
      box.classList.add("hidden");
      box.textContent = "";
      return;
    }
    box.classList.remove("hidden");
    box.textContent = warns.join(" · ");
  }

  function saveMissionBackup() {
    try {
      localStorage.setItem(
        LS_MISSION,
        JSON.stringify({
          format: "gcs_mission_v2",
          saved_at: Date.now(),
          waypoints: waypoints,
          record: readMissionRecordFromForm(),
        })
      );
    } catch (_) { /* quota */ }
  }

  function isLegacyDemoRoute(wps) {
    if (!wps || wps.length !== DEMO_ROUTE_WPS.length) return false;
    return wps.every((wp, i) => {
      const ref = DEMO_ROUTE_WPS[i];
      return (
        Math.abs(Number(wp.lat) - ref[0]) < 0.00015 &&
        Math.abs(Number(wp.lon) - ref[1]) < 0.00015
      );
    });
  }

  async function clearMissionRoute() {
    await apiPost("/api/mission/clear");
    waypoints = [];
    fleetRoutes[selectedVehicleId] = [];
    missionActive = false;
    missionPhase = "idle";
    missionCanResume = false;
    try {
      localStorage.removeItem(LS_MISSION);
      localStorage.removeItem("gcs_mission_backup_v1");
    } catch (_) { /* ignore */ }
    clearRoverFromMap();
    renderMission();
    syncMissionUi();
  }

  async function pushMissionToServer() {
    await apiPut("/api/mission", { waypoints: waypoints });
    renderMission();
  }

  async function downloadMissionJson() {
    await saveMissionRecordToServer();
    const r = await fetch(withVehicle("/api/mission/export"));
    const payload = await r.json();
    if (!r.ok) throw new Error(payload.error || r.status);
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `mission_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    if (payload.record) applyMissionRecordToForm(payload.record);
    else if (payload.work || payload.spraying) {
      applyMissionRecordToForm({
        work_started_at: payload.work?.started_at,
        work_finished_at: payload.work?.finished_at,
        spraying: payload.spraying,
        field_notes: payload.field_notes || "",
      });
    }
    log("Маршрут експортовано (JSON v2)");
  }

  function updateHud(s) {
    const badge = el("linkBadge");
    const profileBadge = el("profileBadge");
    const gpsHud = missionGps(s);
    const hasGps = validGps(gpsHud);
    if (s.mavlink_reconnecting) {
      badge.textContent = "RECONNECT…";
      badge.className = "badge warn";
    } else if (s.connected) {
      badge.textContent = s.armed ? "ARMED · ONLINE" : "DISARMED · ONLINE";
      badge.className = "badge " + (s.armed ? "ok" : "warn");
    } else {
      badge.textContent = "OFFLINE";
      badge.className = "badge off";
    }
    if (profileBadge) {
      const prof = s.mavlink_profile || "—";
      const sim = s.simulator_active ? " + SIM" : "";
      profileBadge.textContent = `${prof}${sim}`;
    }

    el("hudConnected").textContent = s.connected ? "Так" : "Ні";
    const hb = el("hudHeartbeat");
    if (hb) {
      hb.textContent =
        s.heartbeat_age_s != null ? `${s.heartbeat_age_s} с` : "—";
    }
    const gpsSrc = el("hudGpsSource");
    if (gpsSrc) {
      gpsSrc.textContent = s.gps_source || (hasGps ? "ok" : "—");
    }
    el("hudArmed").textContent = s.armed ? "ARM" : "DISARM";
    const batt = el("hudBattery");
    if (batt) {
      batt.textContent =
        s.battery_pct != null ? `${Math.round(s.battery_pct)}%` : "—";
    }
    if (s.vehicle_id) selectedVehicleId = s.vehicle_id;
    if (s.fleet) {
      renderFleetSelector(s.fleet);
      updateFleetMarkers(s.fleet);
    }
    updateSimBanner(s);
    updateConfigWarning(s);
    if (linkWasConnected && !s.connected && !s.mavlink_reconnecting) {
      playOfflineBeep();
      log("Звʼязок втрачено", true);
    }
    linkWasConnected = !!s.connected;
    setPreflightItem("pfMavlink", s.connected && !s.mavlink_reconnecting);
    setPreflightItem("pfGps", hasGps);
    setPreflightItem("pfRoute", waypoints.length > 0);
    el("hudSpeed").textContent = fmt(gpsHud.speed);
    el("hudLat").textContent = hasGps ? fmt(gpsHud.lat, 6) : "—";
    el("hudLon").textContent = hasGps ? fmt(gpsHud.lon, 6) : "—";
    cvRunning = !!s.cv_running;
    const cvInfo = s.cv || {};
    if (cvRunning) {
      const pl = cvInfo.planner || "hybrid";
      const nav = cvInfo.nav_source || "—";
      const src = cvInfo.source || "";
      el("hudCv").textContent = `${pl}/${nav}`;
      const cvHint = el("cvVideoHint");
      if (cvHint) {
        cvHint.textContent = src
          ? `Потік: ${src} · навігація: ${nav}`
          : `Навігація: ${nav}`;
      }
    } else {
      el("hudCv").textContent = "OFF";
      const cvHint = el("cvVideoHint");
      if (cvHint) cvHint.textContent = "Завантаження потоку…";
    }
    const hudSprayer = el("hudSprayer");
    if (hudSprayer) hudSprayer.textContent = s.sprayer_active ? "ON" : "OFF";
    sprayer = !!s.sprayer_active;
    syncSprayerBtn();

    controlMode = s.control_mode || controlMode;
    const m = s.mission || {};
    missionPhase = m.phase || "idle";
    missionActive = !!m.active;
    missionCanResume = !!m.can_resume;
    if (missionPhase === "at_last" && m.total > 0) {
      missionTargetIndex = m.total - 1;
    } else if (missionActive && m.total > 0) {
      missionTargetIndex = m.index ?? 0;
    } else {
      missionTargetIndex = -1;
    }
    const hudMission = el("hudMission");
    if (hudMission) {
      if (missionPhase === "at_last") {
        hudMission.textContent = `остання ${m.total}/${m.total}`;
      } else if (missionPhase === "returning" && m.total > 0) {
        hudMission.textContent = `↩ ${(m.index || 0) + 1}/${m.total}`;
      } else if (missionActive && m.total > 0) {
        hudMission.textContent = `${(m.index || 0) + 1} / ${m.total}`;
      } else if (missionPhase === "completed") {
        hudMission.textContent = "готово";
      } else if (missionPhase === "aborted") {
        hudMission.textContent = "стоп";
      } else if (missionPhase === "paused") {
        hudMission.textContent = "пауза";
      } else {
        hudMission.textContent = "—";
      }
    }
    if (s.fleet) {
      updateFleetRoversOnMap(s.fleet);
    }
    updateMap(missionGps(s));
    syncControlModeUi();
    renderMission();

    syncCvUi();
    if (cvRunning) showCvOverlay();
    else hideCvOverlay();
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

  function syncCvUi() {
    const btn = el("btnCvStart");
    if (!btn) return;
    if (cvRunning) {
      btn.textContent = "CV ряд: ВИМК";
      btn.classList.add("active");
    } else {
      btn.textContent = "CV ряд (hybrid)";
      btn.classList.remove("active");
    }
  }

  async function stopCvTracking() {
    await apiPost("/api/cv/stop", {}, { noVehicle: true });
    cvRunning = false;
    hideCvOverlay();
    syncCvUi();
    log("CV вимкнено — відео сховано");
    pollStatus();
  }

  function getMissionSpeed() {
    const inp = el("missionSpeed");
    if (!inp) return 1.0;
    return parseFloat(inp.value);
  }

  async function initMissionSpeed() {
    const inp = el("missionSpeed");
    const valEl = el("missionSpeedVal");
    if (!inp || !valEl) return;
    let min = 0.3;
    let max = 3;
    let def = 1.0;
    try {
      const r = await fetch("/api/mission/settings");
      const s = await r.json();
      if (s.min_speed_m_s != null) min = s.min_speed_m_s;
      if (s.max_speed_m_s != null) max = s.max_speed_m_s;
      if (s.default_speed_m_s != null) def = s.default_speed_m_s;
      if (s.presets) missionPresets = s.presets;
      inp.min = String(min);
      inp.max = String(max);
      document.querySelectorAll("[data-speed-preset]").forEach((btn) => {
        const key = btn.getAttribute("data-speed-preset");
        const map = { spray: "spray_m_s", row: "row_m_s", transfer: "transfer_m_s" };
        const v = missionPresets[map[key]];
        if (v != null) {
          const labels = { spray: "Обприск", row: "Ряд", transfer: "Перегін" };
          btn.textContent = `${labels[key] || key} ${Number(v).toFixed(1)}`;
        }
      });
    } catch (_) { /* defaults */ }
    const saved = localStorage.getItem(LS_SPEED);
    inp.value = saved != null ? saved : String(def);
    const sync = () => {
      valEl.textContent = parseFloat(inp.value).toFixed(1);
      localStorage.setItem(LS_SPEED, inp.value);
    };
    inp.addEventListener("input", sync);
    sync();
  }

  function applyCvDimensions(widthPx, videoHeightPx) {
    const box = el("cvOverlay");
    const wrap = box && box.querySelector(".cv-video-wrap");
    if (!box || !wrap) return;
    const w = Math.max(240, widthPx);
    const vh = Math.max(120, videoHeightPx);
    box.style.width = `${w}px`;
    wrap.style.height = `${vh}px`;
    localStorage.setItem(LS_CV_W, String(w));
    localStorage.setItem(LS_CV_VIDEO_H, String(vh));
  }

  function restoreCvSize() {
    const w = parseFloat(localStorage.getItem(LS_CV_W) || "360");
    const vh = parseFloat(localStorage.getItem(LS_CV_VIDEO_H) || "240");
    applyCvDimensions(w, vh);
  }

  function initCvResize() {
    const box = el("cvOverlay");
    const handle = el("cvResizeHandle");
    if (!box || !handle) return;
    restoreCvSize();
    let resizing = false;
    let startX = 0;
    let startY = 0;
    let startW = 0;
    let startVideoH = 0;

    const onStart = (clientX, clientY, e) => {
      resizing = true;
      const wrap = box.querySelector(".cv-video-wrap");
      startX = clientX;
      startY = clientY;
      startW = box.offsetWidth;
      startVideoH = wrap ? wrap.offsetHeight : 240;
      if (e) e.preventDefault();
    };

    handle.addEventListener("mousedown", (e) => onStart(e.clientX, e.clientY, e));
    handle.addEventListener(
      "touchstart",
      (e) => {
        const t = e.touches[0];
        onStart(t.clientX, t.clientY, e);
      },
      { passive: false }
    );

    const onMove = (clientX, clientY) => {
      if (!resizing) return;
      const dw = clientX - startX;
      const dh = clientY - startY;
      const maxW = window.innerWidth * 0.92;
      const maxH = window.innerHeight * 0.75;
      applyCvDimensions(
        Math.min(maxW, startW + dw),
        Math.min(maxH, startVideoH + dh)
      );
    };

    window.addEventListener("mousemove", (e) => onMove(e.clientX, e.clientY));
    window.addEventListener("mouseup", () => { resizing = false; });
    window.addEventListener("touchmove", (e) => {
      if (!resizing) return;
      onMove(e.touches[0].clientX, e.touches[0].clientY);
    });
    window.addEventListener("touchend", () => { resizing = false; });
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
    const btnClose = el("btnCvClose");
    const btnMin = el("btnCvMin");
    if (btnClose) btnClose.onclick = () => hideCvOverlay();
    if (btnMin) btnMin.onclick = () => box.classList.toggle("minimized");
  }

  function syncSprayerBtn() {
    const b = el("btnSprayer");
    if (!b) return;
    b.textContent = sprayer ? "Оприскувач УВІМК" : "Оприскувач ВИМК";
    b.className = "btn " + (sprayer ? "sprayer-on" : "sprayer-off");
  }

  function getManualSpeed() {
    const inp = el("manualSpeed");
    return inp ? Math.max(0.1, parseFloat(inp.value)) : 0.5;
  }

  function initManualSpeed() {
    const inp = el("manualSpeed");
    const valEl = el("manualSpeedVal");
    if (!inp || !valEl) return;
    const saved = localStorage.getItem("gcs_manual_speed");
    if (saved) inp.value = saved;
    const sync = () => {
      valEl.textContent = parseFloat(inp.value).toFixed(1);
      localStorage.setItem("gcs_manual_speed", inp.value);
    };
    inp.addEventListener("input", sync);
    sync();
  }

  let activeDpadBtn = null;

  function scaledMoveForBtn(btn) {
    const baseF = parseFloat(btn.dataset.f);
    const baseL = parseFloat(btn.dataset.l);
    const k = getManualSpeed() / 0.5;
    return { f: baseF * k, l: baseL * k };
  }

  function stopDpadDrive() {
    if (!activeDpadBtn) return;
    activeDpadBtn.classList.remove("dpad-active");
    activeDpadBtn = null;
    manualDriving = false;
    if (moveTimer) {
      clearInterval(moveTimer);
      moveTimer = null;
    }
    const rm = fleetRoverMarkers[selectedVehicleId];
    if (rm) {
      const ll = rm.getLatLng();
      lastLatLon = [ll.lat, ll.lng];
    }
    apiPost("/api/halt").catch(() => {});
    pollStatus();
  }

  function bindMoveButtons() {
    const panel = el("manualPanel");
    const dpad = panel && panel.querySelector(".dpad");
    if (!dpad) return;

    dpad.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        e.stopPropagation();
      },
      { passive: false }
    );

    window.addEventListener("pointerup", stopDpadDrive);
    window.addEventListener("pointercancel", stopDpadDrive);
    window.addEventListener("blur", stopDpadDrive);

    dpad.querySelectorAll(".btn.move").forEach((btn) => {
      btn.addEventListener("pointerdown", async (e) => {
        if (e.button !== 0 && e.pointerType === "mouse") return;
        e.preventDefault();
        e.stopPropagation();

        if (!isManualPanelEnabled() && !(await ensureManualMode())) return;
        if (!isManualMode()) return;
        if (missionPhase === "running" || missionPhase === "returning") {
          log("Зачекайте — маршрут зупиняється", true);
          return;
        }

        try {
          btn.setPointerCapture(e.pointerId);
        } catch (_) { /* ignore */ }

        activeDpadBtn = btn;
        btn.classList.add("dpad-active");
        manualDriving = true;
        const { f, l } = scaledMoveForBtn(btn);
        sendMove(f, l);
        if (moveTimer) clearInterval(moveTimer);
        moveTimer = setInterval(() => {
          if (!activeDpadBtn) return;
          const s = scaledMoveForBtn(activeDpadBtn);
          sendMove(s.f, s.l);
        }, 150);
      });

      btn.addEventListener("pointerup", (e) => {
        e.preventDefault();
        e.stopPropagation();
        stopDpadDrive();
      });

      btn.addEventListener("lostpointercapture", stopDpadDrive);
    });

    window.addEventListener("keydown", (e) => {
      if (!isManualMode() || e.repeat) return;
      const map = {
        ArrowUp: dpad.querySelector('.btn.move[data-f="0.5"]'),
        ArrowDown: dpad.querySelector('.btn.move[data-f="-0.3"]'),
        ArrowLeft: dpad.querySelector('.btn.move[data-l="-0.5"]'),
        ArrowRight: dpad.querySelector('.btn.move[data-l="0.5"]'),
      };
      const btn = map[e.key];
      if (!btn) return;
      e.preventDefault();
      btn.classList.add("dpad-active");
      activeDpadBtn = btn;
      manualDriving = true;
      const { f, l } = scaledMoveForBtn(btn);
      sendMove(f, l);
      if (moveTimer) clearInterval(moveTimer);
      moveTimer = setInterval(() => sendMove(f, l), 150);
    });

    window.addEventListener("keyup", (e) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(e.key)) return;
      stopDpadDrive();
    });
  }

  async function sendMove(f, l) {
    try {
      const d = await apiPost("/api/move", { forward: f, lateral: l, yaw: 0 });
      if (d.drive === "simulator") {
        manualDriving = true;
      }
    } catch (e) {
      log("Рух: " + formatApiError(e), true);
    }
  }

  function bindControls() {
    el("btnModeAutonomous").onclick = () =>
      switchControlMode("autonomous").catch((e) => log(formatApiError(e), true));
    el("btnModeManual").onclick = () =>
      switchControlMode("manual").catch((e) => log(formatApiError(e), true));

    el("btnArm").onclick = () => apiPost("/api/arm").then(() => log("ARM OK")).catch((e) => log("ARM: " + e, true));
    el("btnDisarm").onclick = () => apiPost("/api/disarm").then(() => log("DISARM")).catch((e) => log("DISARM: " + e, true));
    el("btnStop").onclick = () => stopAllMotion();

    el("btnMissionMode").onclick = () => {
      missionMode = !missionMode;
      const b = el("btnMissionMode");
      b.textContent = missionMode ? "Маршрут: ВКЛ" : "Маршрут: ВИМК";
      b.classList.toggle("active", missionMode);
      syncMissionUi();
      log(missionMode ? "Редагування увімкнено — клік на карті додає точку" : "Редагування вимкнено");
      syncMissionUi();
    };

    const rmLast = el("btnWpRemoveLast");
    if (rmLast) {
      rmLast.onclick = () => {
        if (waypoints.length > 0) removeWaypoint(waypoints.length - 1);
      };
    }

    async function stopAllMotion() {
      manualDriving = false;
      if (moveTimer) {
        clearInterval(moveTimer);
        moveTimer = null;
      }
      try {
        try {
          await apiPost("/api/cv/stop", {}, { noVehicle: true });
          cvRunning = false;
          hideCvOverlay();
          syncCvUi();
        } catch (_) { /* CV may be off */ }
        await apiPost("/api/mission/stop");
        await apiPost("/api/stop");
        missionActive = false;
        missionPhase = "aborted";
        missionCanResume = false;
        cvRunning = false;
        hideCvOverlay();
        syncMissionUi();
        renderMission();
        log("Зупинено (маршрут + CV + рух)");
        pollStatus();
      } catch (e) {
        log("Стоп: " + formatApiError(e), true);
        pollStatus();
      }
    }

    el("btnMissionClear").onclick = () =>
      clearMissionRoute().then(() => {
        clearMovementTrail();
        focusMapOnSelected();
        log("Маршрут очищено");
        pollStatus();
      });

    el("btnMissionRun").onclick = async () => {
      if (!isAutonomousMode()) {
        log("Увімкніть «Автономний» режим", true);
        return;
      }
      if (waypoints.length === 0) {
        log("Немає точок — клікніть на карті (Маршрут: ВКЛ)", true);
        return;
      }
      mapFollow = true;
      await syncVehicleRouteStart(selectedVehicleId);
      if (!missionCanResume) {
        focusStartWaypoint(true);
      } else {
        clearMovementTrail();
      }
      try {
        await apiPost("/api/cv/stop", {}, { noVehicle: true });
        const speed = getMissionSpeed();
        const d = await apiPost("/api/mission/run", {
          waypoints: waypoints.map((w) => ({ lat: w.lat, lon: w.lon })),
          speed,
        });
        missionPhase = d.phase || "running";
        missionActive = !!d.active;
        missionCanResume = !!d.can_resume;
        syncControlModeUi();
        const spd = d.speed_m_s != null ? d.speed_m_s : speed;
        const label = missionPhase === "paused" ? "Продовжено" : "Старт";
        log(`${label} 1→…→${d.total} · ${Number(spd).toFixed(1)} м/с`);
        pollStatus();
      } catch (e) {
        log("Маршрут: " + formatApiError(e), true);
      }
    };

    const btnMissionStop = el("btnMissionStop");
    if (btnMissionStop) {
      btnMissionStop.onclick = () => stopAllMotion();
    }

    const btnMissionReturn = el("btnMissionReturn");
    if (btnMissionReturn) {
      btnMissionReturn.onclick = async () => {
        if (missionPhase !== "at_last") {
          log("Повернення: спочатку дійдіть до останньої точки", true);
          return;
        }
        mapFollow = true;
        try {
          const d = await apiPost("/api/mission/return", { speed: getMissionSpeed() });
          missionPhase = d.phase || "returning";
          syncMissionUi();
          log(`↩ Повернення (${getMissionSpeed().toFixed(1)} м/с): ${d.total} відрізків`);
          pollStatus();
        } catch (e) {
          log("Повернення: " + formatApiError(e), true);
        }
      };
    }

    const btnCvStart = el("btnCvStart");
    if (btnCvStart) {
      btnCvStart.onclick = async () => {
        if (cvRunning) {
          try {
            await stopCvTracking();
          } catch (e) {
            log("CV: " + formatApiError(e), true);
          }
          return;
        }
        try {
          const d = await apiPost("/api/cv/start", {}, { noVehicle: true });
          if (d.status === "error") {
            log("CV: " + (d.message || "не вдалося запустити"), true);
            return;
          }
          if (d.status === "already_running") {
            cvRunning = true;
            log("CV вже запущено");
          } else {
            cvRunning = true;
            const pl = d.effective_planner || d.planner || "hybrid";
            const src = d.source || "";
            const yoloNote = d.yolo === false ? " (без YOLO, depth)" : "";
            log(
              `CV ряд: ${pl}${yoloNote}${src ? " · " + src : ""} — відео зверху на карті`
            );
          }
          syncCvUi();
          showCvOverlay();
          pollStatus();
        } catch (e) {
          log("CV: " + formatApiError(e), true);
        }
      };
    }

    const btnCvStop = el("btnCvStop");
    if (btnCvStop) {
      btnCvStop.onclick = () =>
        stopCvTracking().catch((e) => log("CV: " + formatApiError(e), true));
    }

    el("btnSprayer").onclick = async () => {
      sprayer = !sprayer;
      await apiPost(sprayer ? "/api/sprayer/on" : "/api/sprayer/off");
      syncSprayerBtn();
    };

    el("btnEmergency").onclick = () => {
      if (!confirm("Аварійна зупинка?")) return;
      apiPost("/api/emergency/stop").then(() => log("EMERGENCY", true));
    };

    const btnSaveRecord = el("btnSaveMissionRecord");
    if (btnSaveRecord) {
      btnSaveRecord.onclick = () =>
        saveMissionRecordToServer().catch((e) =>
          log("Збереження: " + formatApiError(e), true)
        );
    }
    const btnFleetApply = el("btnFleetApply");
    if (btnFleetApply) {
      btnFleetApply.onclick = () =>
        applyFleetCount().catch((e) =>
          log("Флот: " + formatApiError(e), true)
        );
    }
    const btnExport = el("btnMissionExport");
    if (btnExport) {
      btnExport.onclick = () => {
        if (waypoints.length === 0) {
          log("Немає точок для експорту", true);
          return;
        }
        downloadMissionJson().catch((e) =>
          log("Експорт: " + formatApiError(e), true)
        );
      };
    }
    const btnSessionLog = el("btnSessionLog");
    if (btnSessionLog) {
      btnSessionLog.onclick = () => {
        window.location.href = "/api/diagnostics/session-log";
        log("Завантаження логу сесії…");
      };
    }

    const btnPfArm = el("btnPreflightArm");
    if (btnPfArm) {
      btnPfArm.onclick = () =>
        apiPost("/api/arm")
          .then(() => log("Preflight: ARM OK"))
          .catch((e) => log("Preflight ARM: " + formatApiError(e), true));
    }
    const btnPfStop = el("btnPreflightStop");
    if (btnPfStop) {
      btnPfStop.onclick = () =>
        apiPost("/api/stop")
          .then(() => log("Preflight: STOP OK"))
          .catch((e) => log("Preflight STOP: " + formatApiError(e), true));
    }
    document.querySelectorAll("[data-speed-preset]").forEach((btn) => {
      btn.onclick = () => {
        const key = btn.getAttribute("data-speed-preset");
        const map = { spray: "spray_m_s", row: "row_m_s", transfer: "transfer_m_s" };
        const v = missionPresets[map[key]];
        const inp = el("missionSpeed");
        const valEl = el("missionSpeedVal");
        if (inp && v != null) {
          inp.value = String(v);
          if (valEl) valEl.textContent = Number(v).toFixed(1);
          localStorage.setItem(LS_SPEED, inp.value);
          log(`Швидкість: ${Number(v).toFixed(1)} м/с`);
        }
      };
    });

    const btnPfNudge = el("btnPreflightNudge");
    if (btnPfNudge) {
      btnPfNudge.onclick = async () => {
        if (!isManualMode()) {
          try {
            await switchControlMode("manual");
          } catch (e) {
            log("Preflight рух: " + formatApiError(e), true);
            return;
          }
        }
        const spd = parseFloat(el("manualSpeed")?.value || "0.3");
        try {
          await apiPost("/api/arm");
          await apiPost("/api/move", { forward: spd, lateral: 0, yaw: 0 });
          await new Promise((r) => setTimeout(r, 400));
          await apiPost("/api/stop");
          log("Preflight: короткий рух виконано");
          pollStatus();
        } catch (e) {
          log("Preflight рух: " + formatApiError(e), true);
        }
      };
    }
  }

  async function initFleetPanel() {
    try {
      const r = await fetch("/api/fleet");
      const d = await r.json();
      lastFleetCountFromServer = d.count || 1;
      fleetVehicles = d.vehicles || [];
      renderFleetSelector(d);
      await refreshAllFleetMissions();
    } catch (_) { /* fleet optional */ }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    initCvDrag();
    initCvResize();
    bindMoveButtons();
    bindControls();
    initManualSpeed();
    await initMissionSpeed();
    await initFleetPanel();
    await loadMission();
    try {
      const r = await fetch("/api/control/mode");
      const d = await r.json();
      controlMode = d.mode || "autonomous";
      if (d.mission) {
        missionPhase = d.mission.phase || missionPhase;
        missionCanResume = !!d.mission.can_resume;
      }
    } catch (_) { /* ignore */ }
    syncControlModeUi();
    pollStatus();
    setInterval(pollStatus, POLL_MS);
    log("Режими: Автономний (маршрут) · Ручний (стрілки)");
  });
})();
