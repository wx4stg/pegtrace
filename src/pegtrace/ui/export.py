"""Step 6: download the STL, save/load the project."""

from __future__ import annotations

import io

import panel as pn

from ..state import AppState
from .common import help_text, show, status_alert


class ExportStep:
    title = "6 · Export"

    def __init__(self, state: AppState, on_done=None):
        self.state = state
        self.alert = status_alert()
        self.orientation = pn.widgets.RadioButtonGroup.from_param(state.export.param.orientation,
                                                                  button_type="default")
        self.filename = pn.widgets.TextInput.from_param(state.export.param.filename, name="File name")
        self.stl = pn.widgets.FileDownload(callback=self._stl, filename=state.export.filename,
                                           label="Download STL", button_type="primary", embed=False)
        state.export.param.watch(lambda e: setattr(self.stl, "filename", self._stl_name()), "filename")
        self.save = pn.widgets.FileDownload(callback=self._project, filename="pegtrace_project.json",
                                            label="Save project", button_type="default", embed=False)
        self.load = pn.widgets.FileInput(accept=".json")
        self.load.param.watch(self._on_load, "value")

    def _stl_name(self):
        name = self.state.export.filename.strip() or "pegtrace_holder.stl"
        return name if name.lower().endswith(".stl") else name + ".stl"

    def _stl(self):
        try:
            data = self.state.stl_bytes()
        except Exception as e:
            show(self.alert, str(e), "danger")
            return None
        show(self.alert, f"STL ready ({len(data) / 1024:.0f} KB).", "success")
        return io.BytesIO(data)

    def _project(self):
        return io.StringIO(self.state.to_json())

    def _on_load(self, event):
        if not event.new:
            return
        try:
            self.state.from_json(event.new.decode("utf-8"))
            show(self.alert, "Project loaded.", "success")
        except Exception as e:
            show(self.alert, f"Could not load that project: {e}", "danger")

    def view(self):
        @pn.depends(self.state.param.result, self.state.param.stale)
        def summary(result, stale):
            if result is None:
                return pn.pane.Alert("Nothing to export yet. Finish the earlier steps first.", alert_type="warning")
            sx, sy, sz = result.info["size_mm"]
            text = pn.pane.Markdown(
                f"**Holder:** {result.mode} mode, {sx:.0f} × {sy:.0f} × {sz:.0f} mm, "
                f"{result.info['volume_cm3']:.1f} cm³, {len(result.warnings)} warning(s).")
            if not stale:
                return text
            return pn.Column(text, pn.pane.Alert(
                "The Design settings changed since the holder was last updated. The download uses the new "
                "settings; press *Update holder* on the Design step to check them first.", alert_type="info"))

        return pn.Column(
            "### Export",
            pn.panel(summary),
            help_text("**Print (upright)** stands the holder on its flat bottom so the cradle and shelf need "
                      "no supports; the pegs print horizontally. **As mounted** keeps the board plane as XY."),
            self.orientation, self.filename, self.stl,
            pn.layout.Divider(),
            "### Project",
            help_text("Save the photo, reference points, outline and all settings to a file, or load one."),
            pn.Row(self.save, self.load),
            self.alert,
            width=520,
        )
