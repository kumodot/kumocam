"""Map picker: choose coordinates by clicking an OpenStreetMap (Leaflet)
map that opens in the user's default web browser.

A tiny local HTTP server (127.0.0.1, random port) serves the map page and
receives the clicked coordinates back, so the app needs no embedded
browser engine (Qt WebEngine added ~300 MB to the packaged build).
The map tiles need an internet connection; coordinates can always be
pasted manually instead.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout,
)

_MAP_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KumoCam - pick a location</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
      crossorigin="anonymous">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin="anonymous"></script>
<style>
  html, body, #map { height: 100%; margin: 0; }
  .bar { position: absolute; top: 10px; left: 54px; right: 10px; z-index: 1000;
         display: flex; gap: 10px; align-items: center; }
  .hint { background: rgba(20,22,26,0.92); color: #e6e8ee; padding: 8px 14px;
          border-radius: 8px; font: 14px sans-serif; }
  #send { display: none; background: #14b8a6; color: #06281f; border: 0;
          padding: 9px 18px; border-radius: 8px; font: 600 14px sans-serif;
          cursor: pointer; }
  #send:hover { background: #2dd4bf; }
</style>
</head><body>
<div id="map"></div>
<div class="bar">
  <span class="hint" id="hint">Click the map to choose the location</span>
  <button id="send">Use this location</button>
</div>
<script>
  var map = L.map('map').setView([__LAT__, __LON__], __ZOOM__);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors'
  }).addTo(map);
  var marker = null, picked = null;
  __MARKER_INIT__
  function setPicked(latlng) {
    picked = latlng;
    if (marker) { marker.setLatLng(latlng); }
    else { marker = L.marker(latlng).addTo(map); }
    document.getElementById('hint').textContent =
      latlng.lat.toFixed(6) + ', ' + latlng.lng.toFixed(6);
    document.getElementById('send').style.display = 'inline-block';
  }
  map.on('click', function(e) { setPicked(e.latlng); });
  document.getElementById('send').addEventListener('click', function() {
    if (!picked) return;
    fetch('/pick?lat=' + picked.lat.toFixed(6) + '&lon=' + picked.lng.toFixed(6))
      .then(function() {
        document.body.innerHTML =
          '<div style="font:16px sans-serif; padding:40px; color:#222">' +
          'Location sent to KumoCam - you can close this tab.</div>';
      });
  });
</script>
</body></html>"""


class _PickerServer:
    """Serves the map page and captures the picked coordinates."""

    def __init__(self, initial: Optional[Tuple[float, float]]):
        self.result: Optional[Tuple[float, float]] = None

        if initial:
            lat, lon, zoom = initial[0], initial[1], 13
            marker_init = f"setPicked(L.latLng({lat}, {lon}));"
        else:
            lat, lon, zoom = 20.0, 0.0, 2
            marker_init = ""
        html = (_MAP_HTML
                .replace("__LAT__", str(lat))
                .replace("__LON__", str(lon))
                .replace("__ZOOM__", str(zoom))
                .replace("__MARKER_INIT__", marker_init)).encode("utf-8")

        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (http.server API)
                url = urlparse(self.path)
                if url.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                elif url.path == "/pick":
                    try:
                        q = parse_qs(url.query)
                        outer.result = (float(q["lat"][0]), float(q["lon"][0]))
                    except (KeyError, ValueError, IndexError):
                        pass
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok")
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):  # silence request logging
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except OSError:
            pass


class MapPickerDialog(QDialog):
    """Modal dialog: opens the map in the default browser and waits for the
    picked location. After exec(), `coords` holds (lat, lon) or None."""

    def __init__(self, initial: Optional[Tuple[float, float]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pick location on map")
        self.setMinimumWidth(420)
        self.coords: Optional[Tuple[float, float]] = None

        self._server = _PickerServer(initial)

        layout = QVBoxLayout(self)
        info = QLabel(
            "The map opened in your web browser.\n\n"
            "Click a point on the map, then press \"Use this location\" "
            "there - the coordinates come back here automatically.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.lbl_status = QLabel("Waiting for the map...")
        layout.addWidget(self.lbl_status)

        btn_reopen = QPushButton("Open the map again")
        btn_reopen.clicked.connect(self._open_browser)
        layout.addWidget(btn_reopen)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(300)

        self._open_browser()

    def _open_browser(self):
        QDesktopServices.openUrl(QUrl(self._server.url))

    def _poll(self):
        if self._server.result is not None:
            self.coords = self._server.result
            self.lbl_status.setText(
                f"Selected: {self.coords[0]:.6f}, {self.coords[1]:.6f}")
            self.accept()

    def done(self, result: int):  # stop server however the dialog closes
        self._timer.stop()
        self._server.stop()
        super().done(result)
