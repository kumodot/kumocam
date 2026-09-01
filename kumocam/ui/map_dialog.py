"""Map picker dialog: click a location on an embedded OpenStreetMap
(Leaflet) map to get coordinates for geotagging.

Uses Qt WebEngine, which ships with the standard PySide6 install. The map
tiles need an internet connection; without one the dialog still opens but
shows a blank map (coordinates can then be pasted instead).
"""

from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:  # pragma: no cover
    WEBENGINE_AVAILABLE = False


_MAP_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin="anonymous">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin="anonymous"></script>
<style>
  html, body, #map { height: 100%; margin: 0; }
  .hint { position: absolute; top: 10px; left: 54px; z-index: 1000;
          background: rgba(255,255,255,0.92); color: #222; padding: 6px 12px;
          border-radius: 6px; font: 14px sans-serif; }
</style>
</head><body>
<div id="map"></div>
<div class="hint">Click the map to set the location</div>
<script>
  var map = L.map('map').setView([__LAT__, __LON__], __ZOOM__);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  var marker = null;
  __MARKER_INIT__
  map.on('click', function(e) {
    if (marker) { marker.setLatLng(e.latlng); }
    else { marker = L.marker(e.latlng).addTo(map); }
    // The dialog reads coordinates from the page title.
    document.title = 'coords:' + e.latlng.lat.toFixed(6) + ',' + e.latlng.lng.toFixed(6);
  });
</script>
</body></html>"""


class MapPickerDialog(QDialog):
    """Modal map dialog. After exec(), `coords` holds (lat, lon) or None."""

    def __init__(self, initial: Optional[Tuple[float, float]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick location on map")
        self.resize(900, 620)
        self.coords: Optional[Tuple[float, float]] = None

        layout = QVBoxLayout(self)
        self.view = QWebEngineView()
        layout.addWidget(self.view, stretch=1)

        self.lbl = QLabel("No location selected yet - click the map.")
        layout.addWidget(self.lbl)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setEnabled(False)
        layout.addWidget(buttons)

        if initial:
            lat, lon, zoom = initial[0], initial[1], 13
            marker_init = (f"marker = L.marker([{lat}, {lon}]).addTo(map);")
            self.coords = (lat, lon)
            self.ok_button.setEnabled(True)
            self.lbl.setText(f"Current location: {lat:.6f}, {lon:.6f}")
        else:
            lat, lon, zoom = 20.0, 0.0, 2
            marker_init = ""

        html = (_MAP_HTML
                .replace("__LAT__", str(lat))
                .replace("__LON__", str(lon))
                .replace("__ZOOM__", str(zoom))
                .replace("__MARKER_INIT__", marker_init))
        self.view.titleChanged.connect(self._title_changed)
        self.view.setHtml(html, QUrl("https://local.map/"))

    def _title_changed(self, title: str):
        if not title.startswith("coords:"):
            return
        try:
            lat_s, lon_s = title[len("coords:"):].split(",")
            self.coords = (float(lat_s), float(lon_s))
            self.ok_button.setEnabled(True)
            self.lbl.setText(f"Selected: {self.coords[0]:.6f}, {self.coords[1]:.6f}")
        except ValueError:
            pass
