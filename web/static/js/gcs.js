/**
 * GCS — супутник, відео-overlay, waypoints
 */
(function () {
  /** Тенерифе (Канарські острови) — стартова карта GCS */
  const DEFAULT_CENTER = [28.2916, -16.6291];
  const DEFAULT_MAP_ZOOM = 11;
  const LS_SPEED = "gcs_mission_speed_m_s";
  const LS_MISSION = "gcs_mission_backup_v2";
  const LS_API_KEY = "gcs_api_key";

  function authHeaders(extra) {
    const h = { ...(extra || {}) };
    const key = sessionStorage.getItem(LS_API_KEY) || "";
    if (key) h.Authorization = `Bearer ${key}`;
    return h;
  }

  async function gcsFetch(url, opts) {
    const o = opts || {};
    o.headers = authHeaders(o.headers);
    return fetch(url, o);
  }
  /** Координати з config/demo_mission.json — зняти залишки після старого DEMO. */
  const DEMO_ROUTE_WPS = [
    [28.2916, -16.6291],
    [28.29205, -16.62855],
    [28.2925, -16.6280],
    [28.29295, -16.62745],
    [28.2934, -16.6269],
  ];
  const LS_CV_W = "gcs_cv_width";
  const LS_CV_VIDEO_H = "gcs_cv_video_h";
  const POLL_MS = 500;
  const TRAIL_MAX = 300;
  const TRAIL_MIN_M = 0.3;

  let map, roverMarker, trailLine, missionLayer, missionRoute, fleetRoutesLayer, vehicleLayer;
  let baseLayer, satLayer;
  let geofenceLayer = null;
  let geofencePreviewLayer = null;
  let geofenceDrawMode = false;
  let geofenceCornerA = null;
  let geofenceCornerMarker = null;
  // Field boundary (polygon) — for planning rows in complex fields
  let fieldDrawMode = false;
  let fieldPoints = [];
  let fieldLayer = null;
  let fieldPreviewLine = null;
  let fieldActiveId = null;
  let fieldNewMode = false;
  let preflightReadyMission = false;
  let preflightReadyCv = false;
  let preflightBlockReason = "";
  let monitoringBlockReason = "";
  let lastPreflightPayload = null;
  let monitoringCrop = "vineyard";
  let monitoringFindingsLayer = null;
  const monitoringMarkers = {};
  const trail = [];
  let waypoints = [];
  /** Маршрути всіх дронів: vehicle_id → [{lat, lon}, …] */
  const fleetRoutes = {};
  /** vehicle_id → маршрут уже зафіксовано на сервері (реальні GPS) */
  const fleetRouteCommitted = {};
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

  const DEFAULT_SIM_LAT = 28.2916;
  const DEFAULT_SIM_LON = -16.6291;

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

  async function fetchMissionPayload(vid) {
    const r = await fetch(withVehicle("/api/mission", vid));
    return r.json();
  }

  function waypointsFromMissionPayload(d) {
    fleetRouteCommitted[d.vehicle_id || selectedVehicleId] = !!d.route_committed;
    if (
      d.draft &&
      d.draft.waypoints &&
      d.draft.waypoints.length &&
      !d.route_committed
    ) {
      return d.draft.waypoints.map((w) => ({ ...w }));
    }
    return (d.waypoints || []).map((w) => ({ lat: w.lat, lon: w.lon }));
  }

  async function fetchMissionWaypoints(vid) {
    const d = await fetchMissionPayload(vid);
    return waypointsFromMissionPayload(d);
  }

  function missionBlocksRouteSync(m) {
    if (!m) return false;
    const ph = m.phase || "idle";
    return (
      !!m.active ||
      ph === "running" ||
      ph === "returning" ||
      ph === "paused"
    );
  }

  function fleetHasActiveMission(fleet) {
    const vehicles = (fleet && fleet.vehicles) || fleetVehicles || [];
    return vehicles.some((fv) => missionBlocksRouteSync(fv.mission));
  }

  async function fetchFleetFromServer() {
    try {
      const d = await apiGet("/api/fleet");
      fleetVehicles = d.vehicles || fleetVehicles;
      if (d.selected_vehicle_id) selectedVehicleId = d.selected_vehicle_id;
      return d;
    } catch (_) {
      return null;
    }
  }

  async function fleetHasActiveMissionOnServer() {
    const fleet = await fetchFleetFromServer();
    if (fleet && fleetHasActiveMission(fleet)) return true;
    const ids = allFleetIdsWithRoutes();
    for (const vid of ids) {
      try {
        const st = await apiGet(
          `/api/mission/status?vehicle_id=${encodeURIComponent(vid)}`
        );
        if (missionBlocksRouteSync(st)) return true;
      } catch (_) { /* ignore */ }
    }
    return false;
  }

  async function refreshFleetMissionCaches() {
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
  }

  /** Оновити кеш маршрутів флоту (без зміни позицій дронів на карті/симі). */
  async function refreshAllFleetMissions() {
    await refreshFleetMissionCaches();
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
      if (o.error === "preflight_failed") {
        return o.message || "Перевірте «Перед виїздом» (MAVLink, GPS, ARM)";
      }
      if (o.error === "not_autonomous") {
        return o.message || "Увімкніть «Автономний»";
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
    const r = await gcsFetch(useVehicleQuery ? withVehicle(url) : url, opts);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(JSON.stringify(data));
    return data;
  }

  async function apiPut(url, body, optsExtra) {
    const vehicleId = (optsExtra && optsExtra.vehicleId) || selectedVehicleId;
    const r = await gcsFetch(withVehicle(url, vehicleId), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...body, vehicle_id: vehicleId }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(JSON.stringify(data));
    return data;
  }

  async function apiGet(url) {
    const r = await gcsFetch(url);
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
    // Статус місії з сервера — кеш fleetVehicles може бути застарілим після старту іншого дрона.
    try {
      const st = await apiGet(
        `/api/mission/status?vehicle_id=${encodeURIComponent(vid)}`
      );
      if (missionBlocksRouteSync(st)) return;
    } catch (_) {
      try {
        const fv = fleetVehicles.find((x) => x.id === vid);
        if (missionBlocksRouteSync(fv && fv.mission)) return;
      } catch (_e) { /* ignore */ }
    }
    try {
      await apiPost("/api/mission/sync_start", {}, { vehicleId: vid });
    } catch (_) { /* mission_active / sim offline */ }
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
    map = L.map("map", { zoomControl: true }).setView(
      DEFAULT_CENTER,
      DEFAULT_MAP_ZOOM
    );

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

  /**
   * Завантажити маршрут обраного дрона для UI.
   * Не викликає sync_start — інші дрони продовжують місії під час перемикання.
   */
  async function loadMission() {
    try {
      const d = await fetchMissionPayload();
      waypoints = waypointsFromMissionPayload(d);
      fleetRoutes[selectedVehicleId] = waypoints.map((w) => ({ ...w }));
      if (d.record) applyMissionRecordToForm(d.record);
      if (isLegacyDemoRoute(waypoints)) {
        await clearMissionRoute();
        log("Знято старий приклад маршруту — додайте точки на карті");
        return;
      }
      if (fleetVehicles.length > 1) {
        await refreshFleetMissionCaches();
      } else {
        renderMission();
      }
      clearMovementTrail();
      focusMapOnSelected();
    } catch (e) { /* ignore */ }
  }

  async function onMapClick(e) {
    if (fieldDrawMode) {
      const lat = e.latlng.lat;
      const lon = e.latlng.lng;
      fieldPoints.push({ lat, lon });
      renderFieldPreviewLine();
      const btnClr = el("btnFieldClear");
      if (btnClr) btnClr.disabled = fieldPoints.length < 3;
      return;
    }
    if (geofenceDrawMode) {
      handleGeofenceMapClick(e);
      return;
    }
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

  function syncPreflightFromStatus(s) {
    const pf = (s && s.preflight) || {};
    const c = pf.checks || {};
    if (c.mavlink) setPreflightItem("pfMavlink", c.mavlink.ok);
    if (c.gps) setPreflightItem("pfGps", c.gps.ok);
    if (c.armed) setPreflightItem("pfArm", c.armed.ok);
    if (c.emergency_clear) setPreflightItem("pfEmergency", c.emergency_clear.ok);
    if (c.route) setPreflightItem("pfRoute", c.route.ok);
    if (c.geofence) {
      setPreflightItem("pfGeofence", c.geofence.ok);
    } else {
      const geoPos = c.geofence_position ? c.geofence_position.ok : true;
      const geoRoute = c.geofence_route ? c.geofence_route.ok : true;
      setPreflightItem("pfGeofence", geoPos && geoRoute);
    }
    updateGeofenceHint(s.geofence);
    lastPreflightPayload = pf;
    preflightReadyMission = !!pf.ready_for_mission;
    preflightReadyCv = !!pf.ready_for_cv;
    preflightBlockReason = pf.block_reason || "";
    syncMonitoringPreflight(pf);
    const pfBanner = el("preflightBanner");
    if (pfBanner) {
      if (!preflightReadyMission && preflightBlockReason) {
        pfBanner.textContent = preflightBlockReason;
        pfBanner.classList.remove("hidden");
      } else {
        pfBanner.classList.add("hidden");
        pfBanner.textContent = "";
      }
    }
    const resetBtn = el("btnEmergencyReset");
    if (resetBtn) {
      resetBtn.classList.toggle("hidden", !s.emergency_stop);
    }
    if (s.geofence) renderGeofence(s.geofence);
  }

  function updateGeofenceHint(gf) {
    const hint = el("geofenceHint");
    if (!hint) return;
    if (!gf || !gf.enabled) {
      hint.textContent =
        "Геозона не задана (опційно). Для поля: «2 кути на карті» або «За маршрутом».";
      return;
    }
    hint.textContent =
      `Активна: lat ${gf.min_lat.toFixed(5)}…${gf.max_lat.toFixed(5)}, ` +
      `lon ${gf.min_lon.toFixed(5)}…${gf.max_lon.toFixed(5)}`;
  }

  function renderGeofence(gf) {
    if (!map) return;
    if (geofencePreviewLayer) {
      map.removeLayer(geofencePreviewLayer);
      geofencePreviewLayer = null;
    }
    if (!gf || !gf.enabled) {
      if (geofenceLayer) {
        map.removeLayer(geofenceLayer);
        geofenceLayer = null;
      }
      return;
    }
    const southWest = [gf.min_lat, gf.min_lon];
    const northEast = [gf.max_lat, gf.max_lon];
    if (!geofenceLayer) {
      geofenceLayer = L.rectangle([southWest, northEast], {
        color: "#29b6f6",
        weight: 2,
        fillColor: "#29b6f6",
        fillOpacity: 0.07,
        dashArray: "8 6",
        interactive: false,
      });
      geofenceLayer.addTo(map);
    } else {
      geofenceLayer.setBounds([southWest, northEast]);
    }
  }

  function setGeofenceDrawMode(on) {
    geofenceDrawMode = !!on;
    const btn = el("btnGeofenceDraw");
    if (btn) btn.classList.toggle("active", geofenceDrawMode);
    if (!geofenceDrawMode) {
      geofenceCornerA = null;
      if (geofenceCornerMarker && map) {
        map.removeLayer(geofenceCornerMarker);
        geofenceCornerMarker = null;
      }
      const mh = el("mapHint");
      if (mh) mh.textContent = "▲ rover · редагування: клік = додати · перетягнути = змістити · ✕ = зняти";
    } else {
      log("Геозона: клік 1 — перший кут, клік 2 — протилежний кут");
      const mh = el("mapHint");
      if (mh) mh.textContent = "ГЕОЗОНА: клік 1 і 2 — протилежні кути прямокутника";
    }
  }

  async function saveGeofenceBounds(minLat, maxLat, minLon, maxLon) {
    const r = await fetch("/api/geofence", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: true,
        min_lat: minLat,
        max_lat: maxLat,
        min_lon: minLon,
        max_lon: maxLon,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message || d.error || r.status);
    renderGeofence(d);
    updateGeofenceHint(d);
    log("Геозону збережено");
    pollStatus();
    return d;
  }

  async function loadGeofenceConfig() {
    try {
      const r = await fetch("/api/geofence");
      const gf = await r.json();
      if (r.ok) {
        renderGeofence(gf);
        updateGeofenceHint(gf);
      }
    } catch (_) { /* ignore */ }
  }

  function handleGeofenceMapClick(e) {
    const lat = e.latlng.lat;
    const lon = e.latlng.lng;
    if (!geofenceCornerA) {
      geofenceCornerA = { lat, lon };
      if (geofenceCornerMarker && map) map.removeLayer(geofenceCornerMarker);
      geofenceCornerMarker = L.circleMarker([lat, lon], {
        radius: 8,
        color: "#29b6f6",
        fillColor: "#29b6f6",
        fillOpacity: 0.8,
      }).addTo(map);
      log("Геозона: клік 2 — протилежний кут");
      return;
    }
    const a = geofenceCornerA;
    const minLat = Math.min(a.lat, lat);
    const maxLat = Math.max(a.lat, lat);
    const minLon = Math.min(a.lon, lon);
    const maxLon = Math.max(a.lon, lon);
    if (geofencePreviewLayer) map.removeLayer(geofencePreviewLayer);
    geofencePreviewLayer = L.rectangle(
      [
        [minLat, minLon],
        [maxLat, maxLon],
      ],
      { color: "#81d4fa", weight: 2, dashArray: "4 4", fillOpacity: 0.05 }
    ).addTo(map);
    setGeofenceDrawMode(false);
    saveGeofenceBounds(minLat, maxLat, minLon, maxLon).catch((err) =>
      log("Геозона: " + formatApiError(err), true)
    );
    geofenceCornerA = null;
    if (geofenceCornerMarker && map) {
      map.removeLayer(geofenceCornerMarker);
      geofenceCornerMarker = null;
    }
  }

  function assertPreflightForMission() {
    if (preflightReadyMission) return true;
    log(preflightBlockReason || "Перевірте «Перед виїздом»: ARM, GPS, геозона", true);
    return false;
  }

  async function assertPreflightForVehicle(vid) {
    if (vid === selectedVehicleId) {
      return assertPreflightForMission();
    }
    const fv = fleetVehicles.find((x) => x.id === vid);
    const name = (fv && fv.name) || vid;
    try {
      const pf = await apiGet(
        `/api/preflight?vehicle_id=${encodeURIComponent(vid)}&require_route=1`
      );
      if (pf.ready_for_mission) return true;
      log(
        `${name}: ${pf.block_reason || "не готово до старту (preflight)"}`,
        true
      );
      return false;
    } catch (e) {
      log(`${name}: preflight — ` + formatApiError(e), true);
      return false;
    }
  }

  function assertPreflightForCv() {
    if (preflightReadyCv) return true;
    log(preflightBlockReason || "CV: потрібні ARM, GPS і відсутність аварії", true);
    return false;
  }

  function monitoringCvBlockReason(pf) {
    if (!pf) return monitoringBlockReason || "Моніторинг: перевірте ARM, GPS, звʼязок";
    const c = pf.checks || {};
    const keys = ["mavlink", "gps", "armed", "emergency_clear", "geofence"];
    const failed = keys
      .filter((k) => c[k] && c[k].ok === false && !c[k].optional)
      .map((k) => c[k].label);
    if (failed.length) return "Моніторинг: " + failed.join("; ");
    return pf.block_reason || monitoringBlockReason || "Не готово до зйомки";
  }

  function syncMonitoringPreflight(pf) {
    const c = (pf && pf.checks) || {};
    if (c.mavlink) setPreflightItem("mpfMavlink", c.mavlink.ok);
    if (c.gps) setPreflightItem("mpfGps", c.gps.ok);
    if (c.armed) setPreflightItem("mpfArm", c.armed.ok);
    if (c.emergency_clear) setPreflightItem("mpfEmergency", c.emergency_clear.ok);
    monitoringBlockReason = pf && !pf.ready_for_cv ? monitoringCvBlockReason(pf) : "";
    const banner = el("monitoringPreflightBanner");
    if (banner) {
      if (pf && !pf.ready_for_cv && monitoringBlockReason) {
        banner.textContent = monitoringBlockReason;
        banner.classList.remove("hidden");
      } else {
        banner.classList.add("hidden");
        banner.textContent = "";
      }
    }
  }

  function assertPreflightForMonitoring() {
    if (preflightReadyCv) return true;
    log(monitoringCvBlockReason(lastPreflightPayload), true);
    return false;
  }

  async function saveStationMeta() {
    const sid = (el("stationIdInput") && el("stationIdInput").value) || "";
    const op = (el("stationOperatorInput") && el("stationOperatorInput").value) || "";
    const r = await fetch("/api/monitoring/station", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ station_id: sid.trim(), operator: op.trim() }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message || d.error || r.statusText);
    const hint = el("stationHint");
    if (hint) {
      hint.textContent = `Станція: ${d.station_id} · оператор: ${d.operator || "—"}`;
    }
    log(`Станція збережено: ${d.station_id}${d.operator ? " · " + d.operator : ""}`);
    return d;
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
    const hintSize = el("fleetSizeHint");
    if (hintSize && fleet && fleet.message) {
      hintSize.textContent = fleet.message;
    }
    // Пул станції: завжди показуємо список, навіть якщо активний лише 1 дрон.
    if (!fleet) return;
    fleetVehicles = fleet.vehicles || [];
    selectedVehicleId = fleet.selected_vehicle_id || selectedVehicleId;
    box.innerHTML = "";
    const activeIds = new Set(fleet.active_vehicle_ids || []);
    const activeCount = activeIds.size || (fleet.count || 1);
    fleetVehicles.forEach((fv) => {
      const row = document.createElement("div");
      row.className =
        "fleet-btn" + (fv.id === selectedVehicleId ? " active" : "");
      const link = fv.connected ? "●" : "○";
      const mode = fv.control_mode === "manual" ? "ручний" : "авто";
      const ph = missionPhaseLabel(fv.mission);
      const cvMode = (fv.cv_mode || "").toLowerCase();
      const cvInfo = fv.cv || {};
      const vidLabel =
        cvInfo.video_label ||
        (fv.video_file ? fv.video_file.split("/").pop() : "");
      const cvConn = !!cvInfo.connected;
      const cvMissing = !!cvInfo.video_missing;
      const cvOnboard = cvMode === "onboard";
      let cvBtnTitle = cvConn
        ? "Відключити відео"
        : "Підключити відео (імітація камери / згодом камера з дрона)";
      if (cvMissing && !cvConn) {
        cvBtnTitle += ` — ${vidLabel || "файл"} не знайдено (буде синтетичний ряд)`;
      } else if (vidLabel) {
        cvBtnTitle += ` — ${vidLabel}`;
      }
      const cvBadge =
        cvOnboard
          ? '<span class="fleet-cv-badge onboard" title="CV на борту (RPi) — локальний трекер GCS заблоковано">CV: onboard</span>'
          : `<span class="fleet-cv-badge local" title="${vidLabel || "відео не задано"}">${vidLabel ? "📹 " + vidLabel : "немає video_file"}${cvMissing ? " ⚠" : ""}</span>`;
      const cvBtnClass =
        (cvConn ? " on" : "") +
        (cvMissing && !cvConn ? " missing" : "") +
        (cvOnboard ? " disabled" : "");
      const isActive = !!(fv.active || activeIds.has(fv.id));
      const disableDeactivate = isActive && activeCount <= 1;
      row.innerHTML = `
        <label class="fleet-active-toggle" title="У роботі (активний дрон)">
          <input type="checkbox" class="fleet-active" data-vid="${fv.id}" ${isActive ? "checked" : ""} ${disableDeactivate ? "disabled" : ""} />
          Active
        </label>
        <button type="button" class="fleet-select" data-vid="${fv.id}">
          <span class="fleet-link ${fv.connected ? "on" : "off"}">${link}</span>
          <strong>${fv.name}</strong>
          <span class="fleet-phase">${mode} · ${ph} · ${fv.waypoint_count || 0} тч.</span>
          ${cvBadge}
        </button>
        <button type="button" class="fleet-cv-connect${cvBtnClass}" data-vid="${fv.id}" title="${cvBtnTitle}" ${cvOnboard ? "disabled" : ""}>📹</button>
        <button type="button" class="fleet-run" data-vid="${fv.id}" title="Старт маршруту цього дрона">▶</button>`;
      row.querySelector(".fleet-select").onclick = () => selectFleetVehicle(fv.id);
      const cvBtn = row.querySelector(".fleet-cv-connect");
      if (cvBtn && !cvOnboard) {
        cvBtn.onclick = (e) => {
          e.stopPropagation();
          toggleFleetVehicleVideo(fv.id);
        };
      }
      row.querySelector(".fleet-run").onclick = (e) => {
        e.stopPropagation();
        startFleetVehicleMission(fv.id);
      };
      const chk = row.querySelector(".fleet-active");
      if (chk) {
        chk.onchange = async (e) => {
          const on = !!e.target.checked;
          try {
            const d = await apiPost("/api/fleet/active/toggle", { vehicle_id: fv.id, active: on }, { noVehicle: true });
            if (d.message) log(d.message);
            renderFleetSelector(d);
            updateFleetMarkers(d);
            pollStatus();
          } catch (err) {
            e.target.checked = !on;
            log("Флот (active): " + formatApiError(err), true);
          }
        };
      }
      box.appendChild(row);
    });
    const hint = el("fleetHint");
    if (hint) {
      hint.textContent =
        "Active = у роботі · клік = обрати · 📹 = відео дрона · ▶ = маршрут. MP4: assets/videos/ (на диску WSL)";
    }
  }

  async function toggleFleetVehicleVideo(vid) {
    const fv = fleetVehicles.find((x) => x.id === vid);
    const cvInfo = (fv && fv.cv) || {};
    const connected = !!cvInfo.connected;
    try {
      if (connected) {
        const d = await apiPost(
          "/api/fleet/cv/disconnect",
          { vehicle_id: vid },
          { noVehicle: true }
        );
        cvRunning = false;
        hideCvOverlay();
        log(`📹 ${fv ? fv.name : vid}: відео відключено`);
        if (d.vehicle_id && d.vehicle_id !== selectedVehicleId) {
          /* інший дрон */
        }
      } else {
        const d = await apiPost(
          "/api/fleet/cv/connect",
          { vehicle_id: vid },
          { noVehicle: true }
        );
        if (d.status === "error") {
          log(`📹 ${fv ? fv.name : vid}: ` + (d.message || d.error || "помилка"), true);
          return;
        }
        cvRunning = true;
        selectedVehicleId = d.vehicle_id || vid;
        const resolved = d.video_resolved || "";
        log(
          (d.message || `📹 ${fv ? fv.name : vid}: відео підключено`) +
            (resolved ? ` · ${resolved.split("/").pop()}` : "")
        );
        if (d.video_missing && d.will_use_synthetic) {
          log(
            "Увага: файл не знайдено на диску — перевірте assets/videos/ у WSL (ls assets/videos/)",
            true
          );
        }
        showCvOverlay();
      }
      syncCvUi();
      await pollStatus();
    } catch (e) {
      log("Відео: " + formatApiError(e), true);
    }
  }

  async function setVehicleAutonomous(vid) {
    await apiPost(
      "/api/control/mode/autonomous",
      { vehicle_id: vid },
      { vehicleId: vid }
    );
  }

  async function missionWaypointsForVehicle(vid) {
    if (vid === selectedVehicleId) {
      syncWaypointsToCache();
    }
    let wps = fleetRoutes[vid];
    if (!wps || !wps.length) {
      try {
        wps = await fetchMissionWaypoints(vid);
        fleetRoutes[vid] = wps;
      } catch (_) {
        wps = [];
      }
    }
    return wps;
  }

  async function pushMissionWaypointsForVehicle(vid) {
    if (!fleetRouteCommitted[vid]) {
      return;
    }
    let wps;
    if (vid === selectedVehicleId) {
      syncWaypointsToCache();
      wps = waypoints;
    } else {
      wps = fleetRoutes[vid] || [];
    }
    if (!wps.length) return;
    await apiPut(
      "/api/mission",
      {
        waypoints: wps.map((w) => ({ lat: w.lat, lon: w.lon })),
      },
      { vehicleId: vid }
    );
    fleetRoutes[vid] = wps.map((w) => ({ lat: w.lat, lon: w.lon }));
  }

  /**
   * Повний маршрут для одного дрона (флот ▶ = «Старт маршруту»).
   * Завжди /api/fleet/mission/run + waypoints на сервері.
   */
  async function runVehicleMission(vid, opts) {
    const options = opts || {};
    const fv = fleetVehicles.find((x) => x.id === vid);
    const name = (fv && fv.name) || vid;
    const wps = await missionWaypointsForVehicle(vid);
    if (!wps.length) {
      log(`${name}: спочатку додайте точки маршруту (Редагувати: ВКЛ)`, true);
      return null;
    }
    if (wps.length < 2) {
      log(
        `${name}: потрібно ≥2 точки (1 = старт, 2+ = рух по маршруту)`,
        true
      );
      return null;
    }
    const mode =
      fv && fv.control_mode ? fv.control_mode : controlMode;
    if (mode !== "autonomous") {
      try {
        await setVehicleAutonomous(vid);
      } catch (e) {
        log("Автономний: " + formatApiError(e), true);
        return null;
      }
    }
    if (options.checkPreflight !== false) {
      const pfOk = await assertPreflightForVehicle(vid);
      if (!pfOk) return null;
    }
    await pushMissionWaypointsForVehicle(vid);
    try {
      const st = await apiGet(
        `/api/mission/status?vehicle_id=${encodeURIComponent(vid)}`
      );
      if (!missionBlocksRouteSync(st)) {
        await syncVehicleRouteStart(vid);
      }
    } catch (_) {
      await syncVehicleRouteStart(vid);
    }
    if (options.stopCv !== false) {
      try {
        await apiPost("/api/cv/stop", {}, { noVehicle: true });
      } catch (_) { /* ignore */ }
    }
    const speed = getMissionSpeed();
    const draftOnly = !fleetRouteCommitted[vid];
    const payload = {
      vehicle_id: vid,
      waypoints: wps.map((w) => {
        const o = { lat: w.lat, lon: w.lon };
        if (w.role) o.role = w.role;
        if (w.row_index != null) o.row_index = w.row_index;
        return o;
      }),
      speed,
      draft_only: draftOnly,
    };
    const d = await apiPost("/api/fleet/mission/run", payload, { noVehicle: true });
    if (vid === selectedVehicleId) {
      missionPhase = d.phase || "running";
      missionActive = !!d.active;
      missionCanResume = !!d.can_resume;
      syncControlModeUi();
    }
    const spd = d.speed_m_s != null ? d.speed_m_s : speed;
    const label = d.phase === "paused" ? "Продовжено" : "Старт";
    log(`▶ ${name}: ${label} 1→…→${d.total || wps.length} · ${Number(spd).toFixed(1)} м/с`);
    if (options.refreshFleet !== false) {
      await refreshFleetMissionCaches();
    }
    clearMovementTrail();
    await pollStatus();
    return d;
  }

  async function startFleetVehicleMission(vid) {
    try {
      await runVehicleMission(vid, { checkPreflight: true });
    } catch (e) {
      const fv = fleetVehicles.find((x) => x.id === vid);
      log(`Старт ${fv ? fv.name : vid}: ` + formatApiError(e), true);
    }
  }

  // fleetCountInput / btnFleetApply прибрані: оператор керує активними дронами через чекбокси Active.

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
      await loadRowPlanDefaults();
      clearMovementTrail();
      syncControlModeUi();
      log(
        `Обрано: ${d.name || vid} — інші дрони продовжують маршрут без зупинки`
      );
      if (cvRunning) {
        const img = el("cvVideo");
        if (img) img.src = "/api/cv/stream?t=" + Date.now();
      }
      await pollStatus();
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
    const profile = (s.mavlink_profile || "").toLowerCase();
    if (!s.simulator_active && profile === "sim") {
      banner.textContent =
        "Симулятор не запущено. Зупиніть процес і: python main.py --full";
      banner.classList.remove("hidden");
      return;
    }
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

  function readRowPlanForm() {
    return {
      origin_lat: parseFloat(el("planOriginLat")?.value),
      origin_lon: parseFloat(el("planOriginLon")?.value),
      azimuth_deg: parseFloat(el("planAzimuth")?.value) || 0,
      auto_azimuth: !!el("planAutoAzimuth")?.checked,
      row_spacing_m: parseFloat(el("planRowSpacing")?.value) || 1,
      row_length_m: parseFloat(el("planRowLength")?.value) || 50,
      row_count: parseInt(el("planRowCount")?.value, 10) || 5,
      use_zigzag: !!el("planZigzag")?.checked,
      use_field: !!el("planUseField")?.checked,
    };
  }

  function updateFieldHint(cfg) {
    const hint = el("fieldHint");
    if (!hint) return;
    const active = (cfg && cfg.active) || {};
    const poly = active.polygon || [];
    if (!active || !active.enabled || poly.length < 3) {
      hint.textContent =
        "Контур поля: не задано. Додайте точки по краю поля (складна форма підтримується).";
      return;
    }
    hint.textContent = `Контур поля: ${poly.length} точок` + (active.name ? ` · ${active.name}` : "");
  }

  function renderFieldPolygon(cfg) {
    if (!map) return;
    if (fieldLayer) {
      map.removeLayer(fieldLayer);
      fieldLayer = null;
    }
    const active = (cfg && cfg.active) || {};
    const poly = active.polygon || [];
    if (!active || !active.enabled || poly.length < 3) return;
    fieldLayer = L.polygon(
      poly.map((p) => [p.lat, p.lon]),
      {
        color: "#66bb6a",
        weight: 2,
        fillColor: "#66bb6a",
        fillOpacity: 0.08,
        interactive: false,
      }
    ).addTo(map);
  }

  function renderFieldSelect(cfg) {
    const sel = el("fieldSelect");
    if (!sel) return;
    const fields = (cfg && cfg.fields) || [];
    const active = (cfg && cfg.active) || {};
    fieldActiveId = active.id || null;
    sel.innerHTML = "";
    const optNone = document.createElement("option");
    optNone.value = "";
    optNone.textContent = "— (нема поля)";
    sel.appendChild(optNone);
    fields.forEach((f) => {
      const o = document.createElement("option");
      o.value = f.id;
      o.textContent = f.name || f.id;
      if (f.id && f.id === fieldActiveId) o.selected = true;
      sel.appendChild(o);
    });
    const nameInp = el("fieldName");
    if (nameInp && active.name && !fieldNewMode) nameInp.value = active.name;
  }

  async function loadFieldConfig() {
    try {
      const r = await fetch("/api/field");
      const d = await r.json();
      if (!r.ok) return;
      updateFieldHint(d);
      renderFieldPolygon(d);
      renderFieldSelect(d);
      const btnClr = el("btnFieldClear");
      if (btnClr) btnClr.disabled = !((d.active || {}).enabled);
    } catch (_) { /* ignore */ }
  }

  function renderFieldPreviewLine() {
    if (!map) return;
    if (fieldPreviewLine) {
      map.removeLayer(fieldPreviewLine);
      fieldPreviewLine = null;
    }
    if (fieldPoints.length < 1) return;
    fieldPreviewLine = L.polyline(
      fieldPoints.map((p) => [p.lat, p.lon]),
      { color: "#81c784", weight: 2, dashArray: "6 6" }
    ).addTo(map);
  }

  function setFieldDrawMode(on) {
    fieldDrawMode = !!on;
    const btn = el("btnFieldDraw");
    const btnFin = el("btnFieldFinish");
    const btnClr = el("btnFieldClear");
    if (btn) btn.classList.toggle("active", fieldDrawMode);
    if (btnFin) btnFin.disabled = !fieldDrawMode;
    if (btnClr) btnClr.disabled = fieldPoints.length < 3;
    const mh = el("mapHint");
    if (mh) {
      mh.textContent = fieldDrawMode
        ? "ПОЛЕ: кліки по краю поля → «Завершити контур»"
        : "▲ rover · редагування: клік = додати · перетягнути = змістити · ✕ = зняти";
    }
    if (!fieldDrawMode) {
      if (fieldPreviewLine && map) {
        map.removeLayer(fieldPreviewLine);
        fieldPreviewLine = null;
      }
      fieldPoints = [];
    } else {
      fieldPoints = [];
      log("Поле: додавайте точки по контуру. Потім «Завершити контур».");
    }
  }

  async function saveFieldPolygon(points) {
    const name = (el("fieldName")?.value || "").trim();
    const r = await fetch("/api/field", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        enabled: true,
        field_id: fieldNewMode ? null : fieldActiveId,
        name,
        polygon: points,
      }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message || d.error || r.status);
    updateFieldHint(d);
    renderFieldPolygon(d);
    renderFieldSelect(d);
    log("Контур поля збережено");
    return d;
  }

  async function selectFieldOnServer(fieldId) {
    const r = await fetch("/api/field/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field_id: fieldId }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message || d.error || r.status);
    updateFieldHint(d);
    renderFieldPolygon(d);
    renderFieldSelect(d);
    return d;
  }

  async function deleteActiveField() {
    if (!fieldActiveId) throw new Error("Немає активного поля");
    const r = await fetch(`/api/field/${encodeURIComponent(fieldActiveId)}`, {
      method: "DELETE",
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.message || d.error || r.status);
    updateFieldHint(d);
    renderFieldPolygon(d);
    renderFieldSelect(d);
    return d;
  }

  async function loadRowPlanDefaults() {
    const latIn = el("planOriginLat");
    const lonIn = el("planOriginLon");
    if (!latIn || !lonIn) return;
    try {
      const r = await fetch(withVehicle("/api/mission/plan/defaults"));
      const d = await r.json();
      if (!r.ok) return;
      latIn.value = Number(d.origin_lat).toFixed(7);
      lonIn.value = Number(d.origin_lon).toFixed(7);
      if (d.row_spacing_m != null && el("planRowSpacing"))
        el("planRowSpacing").value = String(d.row_spacing_m);
      if (d.row_length_m != null && el("planRowLength"))
        el("planRowLength").value = String(d.row_length_m);
      if (d.row_count != null && el("planRowCount"))
        el("planRowCount").value = String(d.row_count);
    } catch (_) { /* ignore */ }
  }

  function applyPlannedWaypointsToMap(navWps, fitMap) {
    waypoints = (navWps || []).map((w) => ({
      lat: Number(w.lat),
      lon: Number(w.lon),
    }));
    fleetRoutes[selectedVehicleId] = waypoints.map((w) => ({ ...w }));
    renderMission();
    syncMissionUi();
    if (fitMap && waypoints.length && map) {
      const bounds = L.latLngBounds(waypoints.map((w) => [w.lat, w.lon]));
      map.fitBounds(bounds.pad(0.15));
    }
  }

  async function runRowPlan(apply) {
    const body = readRowPlanForm();
    if (!Number.isFinite(body.origin_lat) || !Number.isFinite(body.origin_lon)) {
      log("Задайте опорні координати (RTK)", true);
      return null;
    }
    if (body.use_field && !fieldActiveId) {
      log("Оберіть/створіть поле (контур) або вимкніть «Обрізати по контуру»", true);
      return null;
    }
    body.store_draft = !!apply;
    const d = await apiPost("/api/mission/plan-rows", body);
    if (d.error) throw new Error(d.message || d.error);
    const nav = d.waypoints_nav || d.waypoints || [];
    if (apply) {
      await loadMission();
      applyPlannedWaypointsToMap(waypoints.length ? waypoints : nav, true);
      fleetRouteCommitted[selectedVehicleId] = false;
    } else {
      applyPlannedWaypointsToMap(nav, true);
    }
    const st = d.stats || {};
    log(
      `План рядів: ${st.waypoint_count || nav.length} тч., ` +
        `${st.row_count || body.row_count} рядів, міжряддя ${st.row_spacing_m || body.row_spacing_m} м` +
        (apply
          ? " — чернетка на сервері (GPS після 1-го ряду)"
          : " — лише перегляд")
    );
    return d;
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
    syncPreflightFromStatus(s);
    syncMonitoringFromStatus(s);
    el("hudSpeed").textContent = fmt(gpsHud.speed);
    el("hudLat").textContent = hasGps ? fmt(gpsHud.lat, 6) : "—";
    el("hudLon").textContent = hasGps ? fmt(gpsHud.lon, 6) : "—";
    cvRunning = !!s.cv_running;
    const cvInfo = s.cv || {};
    if (cvRunning) {
      const pl = cvInfo.planner || "hybrid";
      const nav = cvInfo.nav_source || "—";
      const src = cvInfo.source || "";
      let hud = `${pl}/${nav}`;
      if (cvInfo.hazard_stop) {
        hud += " · СТОП";
      } else if (cvInfo.hazard_objects) {
        hud += ` · ⚠ ${cvInfo.hazard_objects}`;
      }
      el("hudCv").textContent = hud;
      const cvHint = el("cvVideoHint");
      if (cvHint) {
        const vf = cvInfo.video_file ? cvInfo.video_file.split("/").pop() : "";
        const veh = cvInfo.vehicle_id || selectedVehicleId || "";
        cvHint.textContent = vf
          ? `${veh ? veh + " · " : ""}${vf} · ${nav}`
          : src
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
    const wasCommitted = !!fleetRouteCommitted[selectedVehicleId];
    if (m.route_committed) {
      fleetRouteCommitted[selectedVehicleId] = true;
    }
    missionPhase = m.phase || "idle";
    missionActive = !!m.active;
    missionCanResume = !!m.can_resume;
    if (m.route_committed && !wasCommitted) {
      loadMission().then(() =>
        log("Маршрут зафіксовано на сервері (реальні GPS після 1-го ряду)")
      );
    }
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
    syncCvButtonsFromMode(s);
  }

  function fmt(n, d) {
    if (n == null || n === "") return "—";
    return typeof d === "number" ? Number(n).toFixed(d) : String(n);
  }

  async function pollStatus() {
    try {
      const r = await gcsFetch("/api/status");
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

  function cvModeFromStatus(s) {
    const cv = (s && s.cv) || {};
    return String(cv.mode || "").toLowerCase();
  }

  function syncCvButtonsFromMode(s) {
    const mode = cvModeFromStatus(s);
    const btnStart = el("btnCvStart");
    const btnStop = el("btnCvStop");
    if (!btnStart || !btnStop) return;
    const onboard = mode === "onboard";
    btnStart.disabled = onboard;
    btnStop.disabled = onboard;
    if (onboard && !cvRunning) {
      btnStart.textContent = "CV на борту (RPi)";
      btnStart.classList.remove("active");
    }
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
      if (s.geofence) renderGeofence(s.geofence);
      if (s.map && map) {
        const lat = Number(s.map.center_lat);
        const lon = Number(s.map.center_lon);
        const zoom = Number(s.map.zoom);
        if (!Number.isNaN(lat) && !Number.isNaN(lon)) {
          map.setView(
            [lat, lon],
            !Number.isNaN(zoom) ? zoom : DEFAULT_MAP_ZOOM
          );
        }
      }
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
      mapFollow = true;
      if (!missionCanResume) {
        focusStartWaypoint(true);
      }
      try {
        await runVehicleMission(selectedVehicleId, { checkPreflight: true });
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
        if (!assertPreflightForCv()) return;
        try {
          const d = await apiPost(
            "/api/cv/start",
            { vehicle_id: selectedVehicleId },
            { noVehicle: true }
          );
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
      apiPost("/api/emergency/stop", {}, { noVehicle: true }).then(() => {
        log("EMERGENCY — зупинено весь флот", true);
        pollStatus();
      });
    };

    const btnEmerReset = el("btnEmergencyReset");
    if (btnEmerReset) {
      btnEmerReset.onclick = () => {
        if (!confirm("Скинути аварійну зупинку? Переконайтесь, що небезпеки немає.")) return;
        apiPost("/api/emergency/reset", {}, { noVehicle: true })
          .then(() => {
            log("Аварію скинуто — можна ARM і старт");
            pollStatus();
          })
          .catch((e) => log("Скинути аварію: " + formatApiError(e), true));
      };
    }

    const btnGfDraw = el("btnGeofenceDraw");
    if (btnGfDraw) {
      btnGfDraw.onclick = () => {
        if (geofenceDrawMode) setGeofenceDrawMode(false);
        else setGeofenceDrawMode(true);
      };
    }
    const btnGfRoute = el("btnGeofenceRoute");
    if (btnGfRoute) {
      btnGfRoute.onclick = async () => {
        if (waypoints.length === 0) {
          log("Спочатку додайте точки маршруту", true);
          return;
        }
        try {
          const r = await fetch("/api/geofence/from-route", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ vehicle_id: selectedVehicleId, padding_m: 25 }),
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.message || d.error || r.status);
          renderGeofence(d);
          updateGeofenceHint(d);
          log("Геозону задано за маршрутом (+25 м)");
          if (d.min_lat != null) {
            map.fitBounds([
              [d.min_lat, d.min_lon],
              [d.max_lat, d.max_lon],
            ]);
          }
          pollStatus();
        } catch (e) {
          log("Геозона: " + formatApiError(e), true);
        }
      };
    }
    const btnGfOff = el("btnGeofenceDisable");
    if (btnGfOff) {
      btnGfOff.onclick = async () => {
        if (!confirm("Вимкнути геозону? Старт маршруту буде заблоковано, поки не задасте знову.")) return;
        try {
          const r = await fetch("/api/geofence", {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: false }),
          });
          const d = await r.json();
          if (!r.ok) throw new Error(d.message || d.error || r.status);
          renderGeofence(d);
          updateGeofenceHint(d);
          log("Геозону вимкнено");
          pollStatus();
        } catch (e) {
          log("Геозона: " + formatApiError(e), true);
        }
      };
    }

    const btnSaveRecord = el("btnSaveMissionRecord");
    if (btnSaveRecord) {
      btnSaveRecord.onclick = () =>
        saveMissionRecordToServer().catch((e) =>
          log("Збереження: " + formatApiError(e), true)
        );
    }
    // btnFleetApply прибрано
    const btnPlanPreview = el("btnPlanRowsPreview");
    if (btnPlanPreview) {
      btnPlanPreview.onclick = () =>
        runRowPlan(false).catch((e) =>
          log("План рядів: " + formatApiError(e), true)
        );
    }
    const btnPlanApply = el("btnPlanRowsApply");
    if (btnPlanApply) {
      btnPlanApply.onclick = () =>
        runRowPlan(true).catch((e) =>
          log("План рядів: " + formatApiError(e), true)
        );
    }
    const btnFieldDraw = el("btnFieldDraw");
    if (btnFieldDraw) {
      btnFieldDraw.onclick = () => setFieldDrawMode(!fieldDrawMode);
    }
    const btnFieldFinish = el("btnFieldFinish");
    if (btnFieldFinish) {
      btnFieldFinish.onclick = async () => {
        if (fieldPoints.length < 3) {
          log("Контур поля: потрібно мінімум 3 точки", true);
          return;
        }
        try {
          await saveFieldPolygon(fieldPoints);
          fieldNewMode = false;
          setFieldDrawMode(false);
          const btnClr = el("btnFieldClear");
          if (btnClr) btnClr.disabled = false;
        } catch (e) {
          log("Контур поля: " + formatApiError(e), true);
        }
      };
    }
    const btnFieldClear = el("btnFieldClear");
    if (btnFieldClear) {
      btnFieldClear.onclick = async () => {
        if (!confirm("Очистити контур поля?")) return;
        try {
          await fetch("/api/field", { method: "DELETE" });
          if (fieldLayer && map) {
            map.removeLayer(fieldLayer);
            fieldLayer = null;
          }
          updateFieldHint({ active: { enabled: false, polygon: [] } });
          log("Контур поля очищено");
          await loadFieldConfig();
        } catch (e) {
          log("Контур поля: " + formatApiError(e), true);
        }
      };
    }

    const selField = el("fieldSelect");
    if (selField) {
      selField.onchange = async () => {
        const id = selField.value || "";
        if (!id) {
          fieldActiveId = null;
          await loadFieldConfig();
          return;
        }
        try {
          await selectFieldOnServer(id);
          log("Поле обрано");
          pollStatus();
        } catch (e) {
          log("Поле: " + formatApiError(e), true);
        }
      };
    }
    const btnFieldNew = el("btnFieldNew");
    if (btnFieldNew) {
      btnFieldNew.onclick = () => {
        fieldNewMode = true;
        if (el("fieldName")) el("fieldName").value = "";
        setFieldDrawMode(true);
        log("Нове поле: намалюйте контур і натисніть «Завершити контур»");
      };
    }
    const btnFieldDelete = el("btnFieldDelete");
    if (btnFieldDelete) {
      btnFieldDelete.onclick = async () => {
        if (!fieldActiveId) {
          log("Немає активного поля для видалення", true);
          return;
        }
        if (!confirm("Видалити активне поле?")) return;
        try {
          await deleteActiveField();
          log("Поле видалено");
          pollStatus();
        } catch (e) {
          log("Поле: " + formatApiError(e), true);
        }
      };
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

  async function logFleetVideosOnDisk() {
    try {
      const d = await apiGet("/api/fleet/cv/videos");
      if (d.count > 0) {
        const names = (d.files || []).map((f) => f.name).join(", ");
        log(`Відео на диску (${d.count}): ${names}`);
      } else {
        log(
          `У ${d.video_dir || "assets/videos"} немає .mp4 — додайте vineyard_demo.mp4 …`,
          true
        );
      }
    } catch (_) { /* ignore */ }
  }

  async function initFleetPanel() {
    try {
      const r = await fetch("/api/fleet");
      const d = await r.json();
      lastFleetCountFromServer = d.count || 1;
      fleetVehicles = d.vehicles || [];
      renderFleetSelector(d);
      await logFleetVideosOnDisk();
      await refreshFleetMissionCaches();
      if (!(await fleetHasActiveMissionOnServer())) {
        await syncAllFleetRouteStarts();
      }
    } catch (_) { /* fleet optional */ }
  }

  function severityClass(sev) {
    const s = (sev || "medium").toLowerCase();
    if (s === "high") return "sev-high";
    if (s === "low") return "sev-low";
    return "sev-medium";
  }

  async function loadMonitoringConfig() {
    try {
      const [r, rs] = await Promise.all([
        gcsFetch("/api/monitoring/config"),
        gcsFetch("/api/monitoring/station"),
      ]);
      const cfg = await r.json();
      if (rs.ok) {
        const st = await rs.json();
        const sidIn = el("stationIdInput");
        const opIn = el("stationOperatorInput");
        if (sidIn) sidIn.value = st.station_id || "";
        if (opIn) opIn.value = st.operator || "";
        const hint = el("stationHint");
        if (hint) {
          hint.textContent = `Станція: ${st.station_id || "—"} · оператор: ${st.operator || "—"}`;
        }
      }
      monitoringCrop = cfg.crop || "vineyard";
      const sel = el("monitoringCrop");
      if (sel && cfg.crops) {
        sel.innerHTML = "";
        cfg.crops.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = c.id;
          opt.textContent = c.name;
          sel.appendChild(opt);
        });
        sel.value = monitoringCrop;
      }
      const rHint = el("monitoringRemoteHint");
      if (rHint && cfg.remote) {
        const rh = cfg.remote;
        rHint.textContent = `Сервер: ${rh.mode || "remote"} · ${rh.base_url || "—"}`;
      }
      const uplHint = el("monitoringUplinkHint");
      if (uplHint && cfg.uplink) {
        const src = cfg.uplink.source || "local";
        if (src === "rpi") {
          const rpi = cfg.uplink.rpi || {};
          uplHint.textContent = `Uplink: RPi → ${rpi.host || "?"}:${rpi.port || 8080} · POST ${rpi.upload_path || "/api/monitoring/upload"}`;
        } else {
          uplHint.textContent = "Uplink: локальні камери на станції (webcam / synthetic)";
        }
      }
      const cHint = el("monitoringCamerasHint");
      if (cHint && cfg.cameras) {
        const L = cfg.cameras.left || {};
        const R = cfg.cameras.right || {};
        const src = (cfg.uplink && cfg.uplink.source) || "local";
        if (src === "rpi") {
          cHint.textContent = `Камери: з RPi (очікування JPEG, timeout ${(cfg.uplink.rpi && cfg.uplink.rpi.wait_timeout_s) || 10} с)`;
        } else {
          cHint.textContent = `Камери: ${L.label || "L"} (${L.type}) · ${R.label || "R"} (${R.type})`;
        }
      }
      const hint = el("monitoringHint");
      if (hint) {
        const src = (cfg.uplink && cfg.uplink.source) || "local";
        hint.textContent =
          src === "rpi"
            ? "RPi знімає ліво/право → Wi‑Fi на станцію → сервер YOLO. Окремо від CV ряду."
            : "Моніторинг: 2 бокові камери → JPEG на сервер аналізу. Камери на станції (webcam/RTSP).";
      }
    } catch (_) { /* monitoring optional */ }
  }

  async function refreshMonitoringFindings() {
    try {
      const r = await fetch(
        `/api/monitoring/findings?vehicle_id=${encodeURIComponent(selectedVehicleId)}&crop=${encodeURIComponent(monitoringCrop)}`
      );
      const d = await r.json();
      renderMonitoringFindings(d.findings || []);
      renderMonitoringOnMap(d.findings || []);
    } catch (_) { /* ignore */ }
  }

  function renderMonitoringFindings(items) {
    const ul = el("monitoringFindingsList");
    if (!ul) return;
    ul.innerHTML = "";
    if (!items.length) {
      const li = document.createElement("li");
      li.textContent = "Знахідок немає";
      li.style.cursor = "default";
      ul.appendChild(li);
      return;
    }
    items.slice(0, 30).forEach((f) => {
      const li = document.createElement("li");
      li.className = severityClass(f.severity);
      const side = f.camera_side ? `[${f.camera_side}] ` : "";
      li.textContent = `${side}${f.label} · ${(f.confidence * 100).toFixed(0)}% · ${f.issue_type}`;
      li.title = f.created_at || "";
      li.onclick = () => {
        if (f.lat != null && f.lon != null) {
          map.setView([f.lat, f.lon], 19);
        }
      };
      ul.appendChild(li);
    });
  }

  function renderMonitoringOnMap(items) {
    if (!map) return;
    if (!monitoringFindingsLayer) {
      monitoringFindingsLayer = L.layerGroup().addTo(map);
    }
    monitoringFindingsLayer.clearLayers();
    Object.keys(monitoringMarkers).forEach((k) => delete monitoringMarkers[k]);
    items.forEach((f) => {
      if (f.lat == null || f.lon == null) return;
      const color =
        f.severity === "high"
          ? "#e53935"
          : f.severity === "low"
            ? "#fdd835"
            : "#fb8c00";
      const m = L.circleMarker([f.lat, f.lon], {
        radius: 8,
        color: "#fff",
        weight: 1,
        fillColor: color,
        fillOpacity: 0.85,
      }).addTo(monitoringFindingsLayer);
      m.bindTooltip(`${f.label} (${(f.confidence * 100).toFixed(0)}%)`);
      monitoringMarkers[f.id] = m;
    });
  }

  async function refreshMonitoringQueue() {
    const qHint = el("monitoringQueueHint");
    if (!qHint) return;
    try {
      const d = await apiGet("/api/monitoring/queue");
      if (!d.enabled) {
        qHint.textContent = "Офлайн-черга: вимкнено";
        return;
      }
      const n = d.total_pending != null ? d.total_pending : 0;
      const failed = d.failed != null ? d.failed : 0;
      qHint.textContent =
        `Офлайн-черга: ${n} очікує (події ${d.pending_events || 0}, знімки ${d.pending_captures || 0})` +
        (failed ? ` · помилок: ${failed}` : "");
      qHint.classList.toggle("warn", n > 0);
    } catch (_) {
      qHint.textContent = "Офлайн-черга: —";
    }
  }

  function syncMonitoringFromStatus(s) {
    const mon = (s && s.monitoring) || {};
    refreshMonitoringQueue();
    const stEl = el("monitoringStatus");
    const surv = mon.surveys && mon.surveys[selectedVehicleId];
    const rHint = el("monitoringRemoteHint");
    if (rHint && mon.remote) {
      const ok = mon.remote.ok ? "OK" : "немає звʼязку";
      rHint.textContent = `Сервер аналізу: ${ok} · ${mon.remote.mode || ""}`;
    }
    if (stEl) {
      if (surv && surv.active) {
        stEl.textContent = `Обстеження: ${surv.index + 1}/${surv.total} · L+R → сервер · ${surv.findings_count || 0} знах.`;
      } else if (surv && surv.phase === "completed") {
        stEl.textContent = surv.message || "Обстеження завершено";
      } else {
        let line = `Усього знахідок: ${mon.findings_total != null ? mon.findings_total : "—"}`;
        const sc = (s && s.spray_coverage) || mon.spray_coverage || {};
        const tot = sc.totals || {};
        if (sc.active && sc.session) {
          line += ` · Spray: ${sc.session.path_length_m || 0} м (активно)`;
        } else if (tot.area_m2 > 0) {
          line += ` · Оброблено: ${tot.area_m2} м² (${tot.area_ha || 0} га)`;
        }
        stEl.textContent = line;
      }
    }
    if (surv && (surv.active || surv.phase === "completed")) {
      refreshMonitoringFindings();
    }
  }

  async function startMonitoringSurvey() {
    if (!assertPreflightForMonitoring()) return;
    const wps = await missionWaypointsForVehicle(selectedVehicleId);
    if (wps.length < 1) {
      log("Моніторинг: додайте точки маршруту", true);
      return;
    }
    if (!isAutonomousMode()) {
      log("Моніторинг: увімкніть «Автономний»", true);
      return;
    }
    try {
      await apiPost(
        "/api/monitoring/crop",
        { crop: monitoringCrop },
        { noVehicle: true }
      );
      const d = await apiPost(
        "/api/monitoring/survey/start",
        {
          vehicle_id: selectedVehicleId,
          crop: monitoringCrop,
          waypoints: wps.map((w) => ({ lat: w.lat, lon: w.lon })),
        },
        { noVehicle: true }
      );
      log(`Моніторинг ▶: ${d.total} точок · ${monitoringCrop}`);
      pollStatus();
      await refreshMonitoringFindings();
    } catch (e) {
      log("Моніторинг: " + formatApiError(e), true);
    }
  }

  async function initApiKeyUi() {
    const wrap = el("apiKeyWrap");
    const inp = el("apiKeyInput");
    const btn = el("btnApiKeySave");
    if (!wrap || !inp) return;
    try {
      const st = await apiGet("/api/security/status");
      if (st.api_key_required) {
        wrap.classList.remove("hidden");
        const saved = sessionStorage.getItem(LS_API_KEY) || "";
        if (saved) inp.value = saved;
      }
      const warn = el("configWarning");
      if (warn) {
        // 🔒 Secure mode: API key без TLS = токен піде по HTTP у відкритому вигляді
        if (st.api_key_required && !st.tls_enabled) {
          warn.textContent =
            "🔒 Secure mode: API key увімкнено, але HTTPS (TLS) вимкнено. " +
            "Увімкніть web.tls.enabled і задайте cert_file/key_file (або запускайте за reverse-proxy з TLS).";
          warn.classList.remove("hidden");
        } else {
          // не прибираємо інші попередження, якщо їх виставив сервер (залишаємо тільки наше)
          if ((warn.textContent || "").includes("Secure mode")) {
            warn.classList.add("hidden");
            warn.textContent = "";
          }
        }
      }
    } catch (_) { /* ignore */ }
    if (btn) {
      btn.onclick = () => {
        sessionStorage.setItem(LS_API_KEY, (inp.value || "").trim());
        log("API key збережено для сесії браузера");
      };
    }
  }

  function bindMonitoringControls() {
    const btnStation = el("btnStationSave");
    if (btnStation) {
      btnStation.onclick = () => {
        saveStationMeta().catch((e) => log("Станція: " + formatApiError(e), true));
      };
    }
    const cropSel = el("monitoringCrop");
    if (cropSel) {
      cropSel.onchange = async () => {
        monitoringCrop = cropSel.value;
        try {
          await apiPost(
            "/api/monitoring/crop",
            { crop: monitoringCrop },
            { noVehicle: true }
          );
          await refreshMonitoringFindings();
        } catch (e) {
          log("Культура: " + formatApiError(e), true);
        }
      };
    }
    const btnStart = el("btnSurveyStart");
    if (btnStart) btnStart.onclick = () => startMonitoringSurvey();
    const btnStop = el("btnSurveyStop");
    if (btnStop) {
      btnStop.onclick = async () => {
        try {
          await apiPost(
            "/api/monitoring/survey/stop",
            { vehicle_id: selectedVehicleId },
            { noVehicle: true }
          );
          log("Обстеження зупинено");
          pollStatus();
        } catch (e) {
          log("Моніторинг стоп: " + formatApiError(e), true);
        }
      };
    }
    const btnSample = el("btnMonitoringSample");
    if (btnSample) {
      btnSample.onclick = async () => {
        if (!assertPreflightForMonitoring()) return;
        try {
          await apiPost(
            "/api/monitoring/crop",
            { crop: monitoringCrop },
            { noVehicle: true }
          );
          const d = await apiPost(
            "/api/monitoring/sample",
            { vehicle_id: selectedVehicleId, crop: monitoringCrop },
            { noVehicle: true }
          );
          const n = (d.findings || []).length;
          log(`Зразок: ${n} знахідок · ${d.message || d.model_status}`);
          await refreshMonitoringFindings();
          pollStatus();
        } catch (e) {
          log("Зразок: " + formatApiError(e), true);
        }
      };
    }
    const btnQueueFlush = el("btnQueueFlush");
    if (btnQueueFlush) {
      btnQueueFlush.onclick = async () => {
        try {
          const d = await apiPost("/api/monitoring/queue/flush", {}, { noVehicle: true });
          log(`Черга: дослано ${d.flushed != null ? d.flushed : 0} елементів`);
          await refreshMonitoringQueue();
        } catch (e) {
          log("Черга: " + formatApiError(e), true);
        }
      };
    }
    const btnClear = el("btnMonitoringClear");
    if (btnClear) {
      btnClear.onclick = async () => {
        if (!confirm("Очистити всі знахідки моніторингу на карті?")) return;
        try {
          await fetch("/api/monitoring/findings", { method: "DELETE" });
          renderMonitoringFindings([]);
          renderMonitoringOnMap([]);
          log("Знахідки моніторингу очищено");
          pollStatus();
        } catch (e) {
          log("Очистити: " + formatApiError(e), true);
        }
      };
    }
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initMap();
    initCvDrag();
    initCvResize();
    bindMoveButtons();
    bindControls();
    bindMonitoringControls();
    initManualSpeed();
    await initMissionSpeed();
    await loadGeofenceConfig();
    await loadFieldConfig();
    await loadMonitoringConfig();
    await refreshMonitoringFindings();
    await initFleetPanel();
    await initApiKeyUi();
    await loadRowPlanDefaults();
    await loadMission();
    try {
      const r = await gcsFetch("/api/control/mode");
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
