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
        ex = state.export
        self.filename = pn.widgets.TextInput.from_param(ex.param.filename, name="File name")
        self.stl = pn.widgets.FileDownload(callback=self._stl, filename=self._stl_name(),
                                           label="Download STL", button_type="primary", embed=False)
        self.project_name = pn.widgets.TextInput.from_param(ex.param.project_filename, name="Project file name")
        self.include_photo = pn.widgets.Checkbox.from_param(ex.param.include_photo, name="Include the photo")
        self.save = pn.widgets.FileDownload(callback=self._project, filename=self._project_name(),
                                            label="Save project", button_type="default", embed=False)
        ex.param.watch(self._sync_names, ["filename", "project_filename"])
        self.load = pn.widgets.FileInput(accept=".json")
        self.load.param.watch(self._on_load, "value")

    @staticmethod
    def _named(name: str, default: str, ext: str) -> str:
        name = name.strip() or default
        return name if name.lower().endswith(ext) else name + ext

    def _stl_name(self):
        return self._named(self.state.export.filename, "pegtrace_holder.stl", ".stl")

    def _project_name(self):
        return self._named(self.state.export.project_filename, "pegtrace_project.json", ".json")

    def _sync_names(self, _=None):
        self.stl.filename = self._stl_name()
        self.save.filename = self._project_name()

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
            if self.load.filename:  # saving again keeps the loaded file's name
                self.state.export.project_filename = self.load.filename
            if self.state.photo is None:
                show(self.alert, "Project loaded, without a photo: the outline and all settings are back, so "
                     "you can go on from the Orientation step.", "success")
            else:
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
            help_text("The STL stands the holder upright, as it hangs (the pegs print horizontally). A ring "
                      "holder's sloped underside is one flat face: lay it on the bed in your slicer to print "
                      "it at an angle. Turn it however you prefer."),
            self.filename, self.stl,
            pn.layout.Divider(),
            "### Project",
            help_text("Save the photo, reference points, outline and all settings to a file, or load one. "
                      "Leave out the photo for a much smaller file that still makes the same holder."),
            self.project_name, self.include_photo,
            pn.Row(self.save, self.load),
            self.alert,
            width=520,
        )
