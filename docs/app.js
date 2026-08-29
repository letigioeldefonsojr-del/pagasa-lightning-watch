const DATA_URL = "data/pagasa_lightning_latest.json";

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function typeClass(type) {
  const t = (type || "").toLowerCase();
  if (t.includes("ground") || t === "cg") return "type-cg";
  if (t.includes("cloud") || t === "cc") return "type-cc";
  return "";
}

function renderStats(payload) {
  setText("stat-total", payload.total_strikes ?? "--");
  setText("stat-latest", payload.latest_strike_timestamp || "none yet");
  setText("stat-segments", payload.segment_count ?? "--");
  setText("stat-updated", payload.generated_at || "--");
}

function renderTable(strikes) {
  const tbody = document.getElementById("strike-tbody");
  if (!strikes.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="empty">No strikes logged yet -- check back after the next scheduled run.</td></tr>';
    return;
  }
  const rows = strikes
    .slice()
    .reverse() // newest first
    .slice(0, 100) // table stays readable; full history is in the CSV link below
    .map((s) => {
      const cls = typeClass(s.type);
      return `<tr>
        <td>${escapeHtml(s.timestamp ?? "")}</td>
        <td class="${cls}">${escapeHtml(s.type ?? "")}</td>
        <td>${escapeHtml(s.latitude ?? "")}</td>
        <td>${escapeHtml(s.longitude ?? "")}</td>
        <td>${escapeHtml(s.amplitude ?? "")}</td>
      </tr>`;
    })
    .join("");
  tbody.innerHTML = rows;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Module-level so repeated renderMap() calls (auto-refresh) reuse the same
// Leaflet map instead of re-initializing it on top of itself, which
// throws "Map container is already initialized" after the first refresh.
let mapInstance = null;
let markersLayer = null;

function renderMap(strikes) {
  const mapEl = document.getElementById("map");
  if (typeof L === "undefined") {
    // Leaflet's script (loaded from a CDN) didn't load -- a slow
    // connection, an ad-blocker, or the CDN being unreachable. Don't let
    // that take down the rest of the page (stats/table can still work
    // fine); just say so where the map would have been.
    mapEl.textContent = "Map unavailable (couldn't load the map library) -- the stats and table above are unaffected.";
    mapEl.style.display = "flex";
    mapEl.style.alignItems = "center";
    mapEl.style.justifyContent = "center";
    mapEl.style.color = "var(--text-dim)";
    return;
  }

  if (!mapInstance) {
    mapInstance = L.map(mapEl).setView([12.8797, 121.774], 6); // roughly centered on the Philippines
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(mapInstance);
    markersLayer = L.layerGroup().addTo(mapInstance);
  } else {
    markersLayer.clearLayers(); // drop the previous refresh's markers before redrawing
  }

  const points = [];
  strikes.forEach((s) => {
    const lat = parseFloat(s.latitude);
    const lon = parseFloat(s.longitude);
    if (Number.isNaN(lat) || Number.isNaN(lon)) return;
    L.circleMarker([lat, lon], {
      radius: 5,
      color: typeClass(s.type) === "type-cg" ? "#ffb454" : "#4fb3ff",
      fillOpacity: 0.7,
    })
      .bindPopup(
        `<strong>${escapeHtml(s.type ?? "strike")}</strong><br>${escapeHtml(s.timestamp ?? "")}<br>${lat.toFixed(3)}, ${lon.toFixed(3)}`
      )
      .addTo(markersLayer);
    points.push([lat, lon]);
  });

  // Only auto-fit the view on the very first render -- on later
  // auto-refreshes, snapping/zooming the map out from under someone who's
  // panned around to look at a specific area would be annoying.
  if (points.length && !mapInstance._autoFitted) {
    mapInstance.fitBounds(points, { maxZoom: 9, padding: [20, 20] });
    mapInstance._autoFitted = true;
  }
}

// GitHub Pages doesn't serve folder listings, so a plain link to
// data/ 404s -- this instead asks GitHub's API what files actually
// exist and renders a real, working download link for each one
// (the API's download_url is already a direct raw.githubusercontent.com
// link, so clicking it saves the file instead of just displaying it).
async function renderDownloads() {
  const list = document.getElementById("download-list");
  // Derive owner/repo from the Pages URL itself (https://OWNER.github.io/REPO/...)
  // rather than hardcoding them, so this works unmodified for anyone who
  // deploys this project under their own account.
  const owner = location.hostname.split(".")[0];
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (!owner || !repo) {
    list.innerHTML = '<li class="empty">Couldn\'t determine this repo\'s name from the URL.</li>';
    return;
  }
  try {
    const resp = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/docs/data`, {
      headers: { Accept: "application/vnd.github+json" },
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const entries = await resp.json();
    const files = entries
      .filter((e) => e.type === "file" && (e.name.endsWith(".csv") || e.name.endsWith(".json")))
      .sort((a, b) => b.name.localeCompare(a.name)); // newest-looking filenames first
    if (!files.length) {
      list.innerHTML = '<li class="empty">No data files yet -- check back after the first scheduled run finishes.</li>';
      return;
    }
    list.innerHTML = files
      .map(
        (f) =>
          `<li><a href="${f.download_url}" download="${escapeHtml(f.name)}">${escapeHtml(f.name)}</a> <span class="filesize">(${(f.size / 1024).toFixed(1)} KB)</span></li>`
      )
      .join("");
  } catch (err) {
    list.innerHTML = `<li class="empty">Couldn't load the file list (${escapeHtml(err.message)}). You can still browse it directly on <a href="https://github.com/${owner}/${repo}/tree/main/docs/data" target="_blank" rel="noopener">GitHub</a>.</li>`;
  }
}

async function load() {
  let strikes = [];
  try {
    const resp = await fetch(DATA_URL, { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const payload = await resp.json();
    renderStats(payload);
    strikes = payload.strikes || [];
    renderTable(strikes);
  } catch (err) {
    setText("stat-updated", "error loading data");
    document.getElementById("strike-tbody").innerHTML =
      `<tr><td colspan="5" class="empty">Couldn't load ${DATA_URL} yet -- it's created after the first scheduled run finishes. (${escapeHtml(err.message)})</td></tr>`;
  }

  // Rendered separately from the data fetch above so a map-only problem
  // (CDN blocked, ad-blocker, etc.) never wipes out a successful
  // stats/table render, and a data-fetch failure still gets an (empty) map.
  try {
    renderMap(strikes);
  } catch (err) {
    console.error("Map render failed:", err);
  }
}

load();
renderDownloads();
setInterval(load, 60000); // auto-refresh every 60s so you never have to reload manually
// Refreshed less often than the data above: GitHub's file-listing API is
// rate-limited (60 requests/hour for anyone not signed in), and the file
// list itself only changes roughly once an hour (a new segment) or once
// per job run anyway, so every 60s here would be both wasteful and risk
// hitting that limit for no benefit.
setInterval(renderDownloads, 300000);
