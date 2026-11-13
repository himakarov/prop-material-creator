"""
ui.py - PySide dialog for Prop Material Creator.

Two inputs, nothing else: pick the prop's geometry in /stage, point at its
textures folder, press Build. The channel map lives in channel_map.json and is
edited by hand, not here.

Launched from the CGA Tools shelf via:
    from prop_material_creator import ui
    ui.show()
"""

import os
import hou

try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    from PySide2 import QtCore, QtWidgets

from . import core
from . import updater


_dialog = None  # keep a reference so the window is not garbage-collected


class PropMaterialDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(PropMaterialDialog, self).__init__(parent)
        self.setWindowTitle("Prop Material Creator")
        self.setMinimumWidth(560)
        self.setMinimumHeight(520)
        self._build_ui()
        self._refresh_stage()

    # -- construction -------------------------------------------------------
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 1. geometry picker
        geo_label = QtWidgets.QLabel("Prop geometry in /stage")
        geo_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(geo_label)

        hint = QtWidgets.QLabel(
            "Pick the mesh (or a GeomSubset) of the prop. The node it lives "
            "under becomes the anchor for the new material nodes.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #999;")
        layout.addWidget(hint)

        self.tree = QtWidgets.QTreeWidget()
        self.tree.setHeaderLabels(["Prim", "Type"])
        self.tree.setColumnWidth(0, 380)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, stretch=1)

        refresh_row = QtWidgets.QHBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("Refresh /stage")
        self.refresh_btn.clicked.connect(self._refresh_stage)
        refresh_row.addWidget(self.refresh_btn)
        refresh_row.addStretch(1)
        layout.addLayout(refresh_row)

        # 2. textures folder
        tex_label = QtWidgets.QLabel("Textures folder")
        tex_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(tex_label)

        tex_row = QtWidgets.QHBoxLayout()
        self.folder_edit = QtWidgets.QLineEdit()
        self.folder_edit.setPlaceholderText(
            "Folder with this prop's textures (body_dif.png, ...)")
        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setMaximumWidth(36)
        browse_btn.clicked.connect(self._browse_folder)
        tex_row.addWidget(self.folder_edit, stretch=1)
        tex_row.addWidget(browse_btn)
        layout.addLayout(tex_row)

        # 3. options
        self.assign_check = QtWidgets.QCheckBox(
            "Assign materials to matching geometry")
        self.assign_check.setChecked(True)
        layout.addWidget(self.assign_check)

        self.controls_check = QtWidgets.QCheckBox(
            "Add intensity controls (per-channel multiply on the material)")
        self.controls_check.setChecked(False)
        layout.addWidget(self.controls_check)

        self.normals_check = QtWidgets.QCheckBox(
            "Generate normals from base color (materials without a normal map)")
        self.normals_check.setChecked(False)
        layout.addWidget(self.normals_check)

        self.alpha_check = QtWidgets.QCheckBox(
            "Use base color alpha as opacity (decals, foliage)")
        self.alpha_check.setChecked(False)
        layout.addWidget(self.alpha_check)

        # 4. build + report
        self.build_btn = QtWidgets.QPushButton("Build")
        self.build_btn.setMinimumHeight(34)
        self.build_btn.clicked.connect(self._on_build)
        layout.addWidget(self.build_btn)

        # update / changelog row
        upd_row = QtWidgets.QHBoxLayout()
        self.update_btn = QtWidgets.QPushButton("Check for updates")
        self.update_btn.clicked.connect(self._on_check_updates)
        self.changelog_btn = QtWidgets.QPushButton("Changelog")
        self.changelog_btn.clicked.connect(self._on_changelog)
        self.version_label = QtWidgets.QLabel("v%s" % updater.local_version())
        self.version_label.setStyleSheet("color: #999;")
        upd_row.addWidget(self.update_btn)
        upd_row.addWidget(self.changelog_btn)
        upd_row.addStretch(1)
        upd_row.addWidget(self.version_label)
        layout.addLayout(upd_row)

        self.report = QtWidgets.QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setMaximumHeight(140)
        self.report.setPlaceholderText("Build report appears here.")
        layout.addWidget(self.report)

    # -- stage tree ---------------------------------------------------------
    def _source_lop(self):
        """The LOP node whose composed stage we read: the user's selected
        /stage node if any, else the /stage display node. The bare /stage
        container has an EMPTY stage - geometry only exists on its child LOPs."""
        for n in hou.selectedNodes():
            try:
                if n.parent() and n.parent().path() == "/stage":
                    return n
            except Exception:
                pass
        stage_node = hou.node("/stage")
        if stage_node is not None:
            disp = stage_node.displayNode()
            if disp is not None:
                return disp
        return None

    def _refresh_stage(self):
        self.tree.clear()
        src = self._source_lop()
        if src is None:
            self._say("No LOP node found in /stage. Create/import your prop "
                      "first, then Refresh.")
            return
        try:
            stage = src.stage()
        except Exception:
            stage = None
        if stage is None:
            self._say("Could not read the stage from %s." % src.path())
            return

        path_to_item = {}
        # pre-select whatever the user already has selected in the network
        selected_paths = set()
        for n in hou.selectedNodes():
            try:
                if n.parent() and n.parent().path() == "/stage":
                    selected_paths.add(n.path())
            except Exception:
                pass

        for prim in stage.Traverse():
            tname = prim.GetTypeName()
            if tname not in ("Mesh", "GeomSubset", "Xform", "Scope"):
                continue
            path = str(prim.GetPath())
            parent_path = path.rsplit("/", 1)[0]
            parent_item = path_to_item.get(parent_path)
            item = QtWidgets.QTreeWidgetItem([prim.GetName() or path, tname])
            item.setData(0, QtCore.Qt.UserRole, path)
            if parent_item is not None:
                parent_item.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
            path_to_item[path] = item

        self.tree.expandAll()

    # -- actions ------------------------------------------------------------
    def _browse_folder(self):
        start = self.folder_edit.text().strip() or hou.text.expandString("$HIP")
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select textures folder", start)
        if chosen:
            self.folder_edit.setText(chosen)

    def _selected_prim_path(self):
        items = self.tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, QtCore.Qt.UserRole)

    def _anchor_for_prim(self, prim_path):
        """Find a /stage LOP node to chain under. Prefer the user's selected
        network node; otherwise use the display node of /stage."""
        for n in hou.selectedNodes():
            try:
                if n.parent() and n.parent().path() == "/stage":
                    return n.path()
            except Exception:
                pass
        stage_node = hou.node("/stage")
        if stage_node is not None:
            disp = stage_node.displayNode()
            if disp is not None:
                return disp.path()
        return None

    def _on_build(self):
        prim_path = self._selected_prim_path()
        folder = self.folder_edit.text().strip()

        if not folder:
            self._say("Pick a textures folder first.")
            return
        if not os.path.isdir(hou.text.expandString(folder)):
            self._say("Folder does not exist:\n%s" % folder)
            return

        anchor_path = self._anchor_for_prim(prim_path)
        if not anchor_path:
            self._say("Select the prop's node in the /stage network "
                      "(SOP Import / Reference) before building.")
            return

        # scope matching to the selected prim's mesh subtree when a specific
        # prim is chosen; empty scope = whole stage.
        scope = prim_path or ""

        # Name the created nodes after the prop. Use the top-level prim of the
        # selected prim's path (e.g. /flashlight_SC/LED_Flashlight_.../body ->
        # the meaningful prop name), preferring the deepest Xform ancestor over
        # the container. Fall back to the folder name inside build().
        prop_name = self._prop_name_from_path(prim_path)

        try:
            result = core.build(
                anchor_path=anchor_path,
                textures_folder=folder,
                scope_path=scope,
                assign=self.assign_check.isChecked(),
                prop_name=prop_name,
                add_controls=self.controls_check.isChecked(),
                generate_normals=self.normals_check.isChecked(),
                alpha_opacity=self.alpha_check.isChecked(),
            )
        except Exception as exc:
            import traceback
            self._say("Build failed:\n%s" % traceback.format_exc())
            return

        self._report_result(result)

    def _prop_name_from_path(self, prim_path):
        """Derive a prop name from a selected prim path. Picks the most
        specific meaningful ancestor: for /flashlight_SC/LED_Flashlight_z5/body
        this returns 'LED_Flashlight_z5' (the asset root under the top group),
        not the material slot 'body'. Returns None to let build() fall back to
        the folder name."""
        if not prim_path:
            return None
        parts = [p for p in prim_path.split("/") if p]
        if not parts:
            return None
        # /top/asset/mesh -> prefer the asset (index 1) when present, else the
        # single top prim. Avoid returning the leaf mesh/subset name.
        if len(parts) >= 2:
            return parts[1]
        return parts[0]

    # -- reporting ----------------------------------------------------------
    def _say(self, text):
        self.report.setPlainText(text)

    def _report_result(self, result):
        if "error" in result:
            lines = ["ERROR: " + result["error"]]
            if result.get("unrecognised"):
                lines.append("Unrecognised files: "
                             + ", ".join(result["unrecognised"]))
            self._say("\n".join(lines))
            return

        lines = []
        lines.append("Created %d material(s): %s"
                     % (len(result["created"]), ", ".join(result["created"])))
        if result.get("preset_created"):
            lines.append("Preset material(s) for untextured slots: "
                         + ", ".join(result["preset_created"]))
        lines.append("Assigned to %d prim(s)." % result["assigned"])
        if result.get("alpha_opacity"):
            lines.append("Opacity from base color alpha: "
                         + ", ".join(result["alpha_opacity"]))
        if result.get("guessed"):
            lines.append("Matched by similar name - please check:")
            for slot, mat in result["guessed"]:
                lines.append("    %s -> %s" % (slot, mat))
        if result.get("unused_materials"):
            lines.append("No geometry matched: "
                         + ", ".join(result["unused_materials"]))
        if result.get("unmatched"):
            lines.append("Geometry with no material: "
                         + ", ".join(result["unmatched"]))
        if result.get("unrecognised"):
            lines.append("Skipped files (no channel): "
                         + ", ".join(result["unrecognised"]))
        if result.get("config_warning"):
            lines.append("Config: " + result["config_warning"])
        lines.append("Material library: " + result["matlib"])
        self._say("\n".join(lines))

    # -- updates ------------------------------------------------------------
    def _on_check_updates(self):
        self._say("Checking for updates...")
        QtWidgets.QApplication.processEvents()
        res = updater.check(download_if_newer=True)
        self._say(res.get("message", "Update check finished."))
        if res.get("status") == "updated":
            self.version_label.setText("v%s (restart)" % res.get("remote", ""))
            try:
                hou.ui.displayMessage(
                    res["message"], title="Prop Material Creator")
            except Exception:
                pass

    def _on_changelog(self):
        self._say(updater.changelog_text())


def show():
    global _dialog
    try:
        parent = hou.qt.mainWindow()
    except Exception:
        parent = None
    _dialog = PropMaterialDialog(parent)
    _dialog.show()
    return _dialog
