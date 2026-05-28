(function () {
  const API_KEY_STORAGE = "fleet_analysis_api_key";

  const $ = (id) => document.getElementById(id);

  function apiKey() {
    return ($("apiKey") && $("apiKey").value.trim()) || "";
  }

  function headers() {
    const h = { Accept: "application/json" };
    const key = apiKey();
    if (key) h.Authorization = "Bearer " + key;
    return h;
  }

  function queryParams() {
    const p = new URLSearchParams();
    const station = $("filterStation")?.value.trim();
    const vehicle = $("filterVehicle")?.value.trim();
    const crop = $("filterCrop")?.value.trim();
    const eventType = $("filterEventType")?.value.trim();
    const limit = $("filterLimit")?.value || "100";
    if (station) p.set("station_id", station);
    if (vehicle) p.set("vehicle_id", vehicle);
    if (crop) p.set("crop", crop);
    if (eventType) p.set("event_type", eventType);
    p.set("limit", limit);
    return p;
  }

  function setStatus(msg, isError) {
    const el = $("statusBar");
    if (!el) return;
    el.textContent = msg;
    el.className = "status-bar" + (isError ? " error" : "");
  }

  async function fetchJson(path) {
    const qs = queryParams().toString();
    const url = path + (qs ? "?" + qs : "");
    const res = await fetch(url, { headers: headers() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const msg = data.message || data.error || res.statusText;
      throw new Error(res.status + ": " + msg);
    }
    return data;
  }

  function esc(s) {
    if (s == null || s === "") return "—";
    const d = document.createElement("div");
    d.textContent = String(s);
    return d.innerHTML;
  }

  function sevClass(sev) {
    const s = (sev || "").toLowerCase();
    if (s === "high") return "sev-high";
    if (s === "medium") return "sev-medium";
    if (s === "low") return "sev-low";
    return "";
  }

  function fmtCoord(lat, lon) {
    if (lat == null || lon == null) return "—";
    const a = Number(lat);
    const b = Number(lon);
    if (!a && !b) return "—";
    return a.toFixed(5) + ", " + b.toFixed(5);
  }

  function renderStats(st) {
    const map = [
      ["statEvents", st.fleet_events, "Події (fleet_events)"],
      ["statCaptures", st.monitoring_captures, "Знімки"],
      ["statDetections", st.monitoring_detections, "Детекції YOLO"],
      ["statStations", st.stations_seen, "Станцій (унік.)"],
    ];
    map.forEach(([id, val]) => {
      const el = $(id);
      if (el) el.textContent = val != null ? val : "—";
    });
  }

  function renderFindings(items) {
    const body = $("findingsBody");
    const meta = $("findingsMeta");
    if (!body) return;
    if (meta) meta.textContent = items.length + " запис(ів)";
    if (!items.length) {
      body.innerHTML =
        '<tr><td colspan="11" class="empty">Немає знахідок за фільтром</td></tr>';
      return;
    }
    body.innerHTML = items
      .map(
        (r) => `<tr>
      <td>${esc(r.created_at)}</td>
      <td>${esc(r.station_id)}</td>
      <td>${esc(r.vehicle_id)}</td>
      <td>${esc(r.crop)}</td>
      <td>${esc(r.label)}</td>
      <td class="${sevClass(r.severity)}">${esc(r.severity)}</td>
      <td>${r.confidence != null ? Number(r.confidence).toFixed(2) : "—"}</td>
      <td>${esc(r.issue_type)}</td>
      <td>${esc(r.camera_side)}</td>
      <td>${esc(r.capture_id)}</td>
      <td class="wrap">${fmtCoord(r.lat, r.lon)}</td>
    </tr>`
      )
      .join("");
  }

  function renderSpray(summary) {
    const body = $("sprayBody");
    const meta = $("sprayMeta");
    if (!body) return;
    const sessions = summary.sessions || [];
    if ($("statSprayArea"))
      $("statSprayArea").textContent =
        summary.total_area_ha != null ? summary.total_area_ha : "—";
    if ($("statSpraySessions"))
      $("statSpraySessions").textContent =
        summary.session_count != null ? summary.session_count : "—";
    if (meta) {
      meta.textContent =
        `${sessions.length} сесій · ${summary.total_path_length_m || 0} м · ` +
        `знахідок біля spray: ${summary.findings_with_spray_context || 0}`;
    }
    if (!sessions.length) {
      body.innerHTML =
        '<tr><td colspan="8" class="empty">Немає завершених сесій spray</td></tr>';
      return;
    }
    body.innerHTML = sessions
      .map(
        (s) => `<tr>
      <td>${esc(s.started_time)}</td>
      <td>${esc(s.ended_time)}</td>
      <td>${esc(s.vehicle_id)}</td>
      <td>${s.duration_s != null ? s.duration_s + " с" : "—"}</td>
      <td>${s.path_length_m != null ? s.path_length_m : "—"}</td>
      <td>${s.area_m2 != null ? s.area_m2 : "—"}</td>
      <td>${s.area_ha != null ? s.area_ha : "—"}</td>
      <td>${esc(s.source || (s.from_payload ? "payload" : "gps"))}</td>
    </tr>`
      )
      .join("");
  }

  function renderOperations(items) {
    const body = $("operationsBody");
    const meta = $("operationsMeta");
    if (!body) return;
    if (meta) meta.textContent = items.length + " запис(ів)";
    if (!items.length) {
      body.innerHTML =
        '<tr><td colspan="8" class="empty">Немає подій за фільтром</td></tr>';
      return;
    }
    body.innerHTML = items
      .map((r) => {
        let payload = "";
        if (r.payload && Object.keys(r.payload).length) {
          try {
            payload = JSON.stringify(r.payload);
          } catch (_) {
            payload = String(r.payload);
          }
        }
        return `<tr>
      <td>${esc(r.time)}</td>
      <td>${esc(r.station_id)}</td>
      <td>${esc(r.vehicle_id)}</td>
      <td>${esc(r.operator)}</td>
      <td>${esc(r.event_type)}</td>
      <td class="wrap">${esc(r.detail)}</td>
      <td>${fmtCoord(r.lat, r.lon)}</td>
      <td class="wrap">${esc(payload || "—")}</td>
    </tr>`;
      })
      .join("");
  }

  async function refresh() {
    setStatus("Завантаження…");
    try {
      const stats = await fetchJson("/api/v1/stats");
      renderStats(stats);

      const findings = await fetchJson("/api/v1/findings");
      renderFindings(findings.findings || []);

      const ops = await fetchJson("/api/v1/operations");
      renderOperations(ops.operations || []);

      const spray = await fetchJson("/api/v1/spray/coverage");
      renderSpray(spray);

      const key = apiKey();
      setStatus(
        "Оновлено " +
          new Date().toLocaleTimeString() +
          (key ? " · Bearer ✓" : " · без API key")
      );
    } catch (e) {
      setStatus("Помилка: " + e.message, true);
    }
  }

  function loadSavedKey() {
    try {
      const k = sessionStorage.getItem(API_KEY_STORAGE);
      if (k && $("apiKey")) $("apiKey").value = k;
    } catch (_) {}
  }

  function saveKey() {
    try {
      const k = apiKey();
      if (k) sessionStorage.setItem(API_KEY_STORAGE, k);
      else sessionStorage.removeItem(API_KEY_STORAGE);
    } catch (_) {}
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadSavedKey();
    $("btnRefresh")?.addEventListener("click", function () {
      saveKey();
      refresh();
    });
    $("apiKey")?.addEventListener("change", saveKey);

    const auto = $("autoRefresh");
    let timer = null;
    auto?.addEventListener("change", function () {
      if (timer) clearInterval(timer);
      timer = null;
      if (auto.checked) timer = setInterval(refresh, 30000);
    });

    refresh();
    if (auto?.checked) setInterval(refresh, 30000);
  });
})();
