"""
Pottery Studio - full-process GUI for archaeological pottery schemes.
Plan and decisions: studio_plan.md. All math lives in pottery_processor.py.
"""
import sys
import os
import numpy as np
import trimesh
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTabWidget, QMessageBox, QRadioButton, QButtonGroup,
                             QCheckBox, QGroupBox, QTextEdit, QScrollArea,
                             QSpinBox, QDoubleSpinBox, QComboBox, QGridLayout)
from PyQt5.QtCore import Qt, QTimer
import pyvista as pv
from pyvistaqt import QtInteractor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from matplotlib.figure import Figure
from shapely.geometry import Point, LineString

import pottery_processor

RIM_COLOR = '#d9534f'
BASE_COLOR = '#2e6fd8'
PICK_COLOR = '#f0ad4e'
CLAY_COLOR = '#d8c3a5'
SLICE_COLOR = '#4caf50'

STEP_NAMES = [
    "Step 1: Raw Points & Handle Selection",
    "Step 2: Profile Boundary (Concave Hull)",
    "Step 3: Outer / Inner Wall Splitting",
    "Step 4: Automatic Thickness Measurement",
    "Step 5: Inner Wall Offset & Base Floor Clip",
    "Step 6: Solid Polygon Assembly",
]


def _polygons(geom):
    """List of Polygons in a shapely geometry (Polygon / MultiPolygon / collection)."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'Polygon':
        return [geom]
    return [g for g in getattr(geom, 'geoms', []) if g.geom_type == 'Polygon']


class PotteryStudio(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pottery Studio")
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(int(screen.width() * 0.8), int(screen.height() * 0.85))

        # Loaded data (raw STL coordinates)
        self.stl_file_path = ""
        self.mesh_raw = None          # pyvista PolyData
        self.points_raw = None        # Nx3
        self.rim_points_raw = None    # 3x3, picked on the tip of the rim
        self.base_points_raw = None   # 3x3, picked on the tip of the base

        # Alignment (derived from the chosen plane)
        self.align_R = None
        self.align_center = None
        self.aligned_points = None
        self.rim_circle = None        # (center, radius, normal) in aligned coordinates
        self.base_circle = None

        # UI state
        self.alignment_choice = None  # 'rim' / 'base' chosen by the user, None = default by vessel type
        self.axis_choice = None       # 'rim' / 'base' / 'centers' chosen by the user, None = default by vessel type
        self.picking_target = None    # 'rim' / 'base' while picking
        self.pick_buffer = []         # picked points (display coordinates)

        # Profile (right side)
        self.frame = None             # slicing frame (pottery_processor.slice_frame)
        self.axis_mode = None         # 'rim' / 'base' / 'centers' actually used
        self.profile_uv = None        # right-side slice points, uv coordinates
        self.solid_poly = None        # 6-step pipeline result (uv)
        self.diag = {}
        self.left_lines_uv = []       # left external view for non-symmetrical vessels (uv lines)
        self.dirty_views = set()      # tabs that need redrawing when shown

        # Recompute the profile shortly after the last angle/ratio change (keeps the spinbox responsive)
        self.profile_timer = QTimer(self)
        self.profile_timer.setSingleShot(True)
        self.profile_timer.setInterval(120)
        self.profile_timer.timeout.connect(self.update_profile)

        self._apply_stylesheet()
        self._init_ui()
        self._update_controls()

    # ------------------------------------------------------------------ UI
    def _apply_stylesheet(self):
        # Light greens theme, consistent with main.py
        style = """
        QMainWindow {
            background-color: #eef7f0;
        }
        QWidget {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            font-size: 10pt;
            color: #1a3320;
        }
        QScrollArea, QScrollArea > QWidget > QWidget {
            background-color: #eef7f0;
            border: none;
        }
        QPushButton {
            background-color: #ffffff;
            border: 2px solid #a3cfa9;
            border-radius: 6px;
            padding: 8px 12px;
            font-weight: 600;
            color: #2b5434;
        }
        QPushButton:hover {
            background-color: #e1f2e3;
            border-color: #7bc085;
        }
        QPushButton:pressed {
            background-color: #c0e6c5;
        }
        QPushButton:checked {
            background-color: #fff3d6;
            border-color: #f0ad4e;
            color: #7a4b00;
        }
        QPushButton:disabled {
            background-color: #f5fcf6;
            color: #b0c4b3;
            border: 2px solid #dbe8dd;
        }
        QGroupBox {
            background-color: #f7fbf8;
            border: 1px solid #c9decb;
            border-radius: 8px;
            margin-top: 14px;
            padding: 10px 8px 8px 8px;
            font-weight: bold;
            color: #2b5434;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
        }
        QGroupBox:disabled {
            color: #b0c4b3;
        }
        QRadioButton, QCheckBox {
            font-weight: 600;
            color: #2b5434;
            spacing: 6px;
            padding: 2px 0;
        }
        QRadioButton:disabled, QCheckBox:disabled {
            color: #b0c4b3;
        }
        QTabWidget::pane {
            border: 1px solid #c9decb;
            background: #ffffff;
            border-radius: 8px;
            margin-top: -1px;
        }
        QTabBar::tab {
            background: #f0f7f1;
            border: 1px solid #c9decb;
            padding: 0.4em 1.4em;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            color: #55755b;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            border-bottom-color: #ffffff;
            color: #1a3320;
        }
        QTabBar::tab:hover:!selected {
            background: #e6f2e8;
        }
        QLabel {
            color: #2b5434;
        }
        QLabel#status {
            font-weight: normal;
            color: #55755b;
            padding-left: 4px;
        }
        QLabel#hint {
            font-weight: normal;
            font-style: italic;
            color: #6b8a70;
        }
        QTextEdit {
            background: #ffffff;
            border: none;
            font-family: Consolas, 'Courier New', monospace;
            font-size: 9pt;
        }
        QSpinBox, QDoubleSpinBox, QComboBox {
            background-color: #ffffff;
            border: 2px solid #a3cfa9;
            border-radius: 6px;
            padding: 3px 6px;
            font-weight: bold;
            color: #2b5434;
        }
        QSpinBox:disabled, QDoubleSpinBox:disabled {
            color: #b0c4b3;
            border-color: #dbe8dd;
        }
        QPushButton#small {
            padding: 4px 6px;
        }
        QLabel#stepInfo {
            font-weight: bold;
            background: #eaf6ec;
            padding: 4px 10px;
            border-radius: 4px;
        }
        """
        self.setStyleSheet(style)

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)

        # ---------- Left control panel ----------
        panel_widget = QWidget()
        panel = QVBoxLayout(panel_widget)
        panel.setContentsMargins(4, 4, 8, 4)

        # 1. Load STL
        self.btn_load = QPushButton("Load STL")
        self.btn_load.clicked.connect(self.load_stl)
        panel.addWidget(self.btn_load)
        self.lbl_file = QLabel("No file loaded")
        self.lbl_file.setObjectName("status")
        self.lbl_file.setWordWrap(True)
        panel.addWidget(self.lbl_file)

        # 2. Vessel type + symmetry
        self.grp_type = QGroupBox("Vessel Type")
        type_layout = QVBoxLayout(self.grp_type)
        self.rb_sherd = QRadioButton("Sherd")
        self.rb_whole = QRadioButton("Whole Vessel")
        self.rb_sherd.setChecked(True)
        self.type_group = QButtonGroup(self)
        self.type_group.addButton(self.rb_sherd)
        self.type_group.addButton(self.rb_whole)
        self.type_group.buttonClicked.connect(self.on_vessel_type_changed)
        type_layout.addWidget(self.rb_sherd)
        type_layout.addWidget(self.rb_whole)
        self.chk_symmetrical = QCheckBox("Symmetrical")
        self.chk_symmetrical.setChecked(True)
        self.chk_symmetrical.toggled.connect(self.on_symmetry_changed)
        type_layout.addWidget(self.chk_symmetrical)
        # Checked: both walls were scanned -> use them as they are; unchecked: complete the inner wall
        self.chk_inner_scanned = QCheckBox("Inner Wall Fully Scanned")
        self.chk_inner_scanned.setChecked(True)   # default for a Sherd
        self.chk_inner_scanned.toggled.connect(self.on_inner_scanned_changed)
        type_layout.addWidget(self.chk_inner_scanned)
        panel.addWidget(self.grp_type)

        # 3. Rim / base planes
        self.grp_planes = QGroupBox("Planes")
        planes_layout = QVBoxLayout(self.grp_planes)
        self.btn_rim_plane = QPushButton("Set Rim Plane")
        self.btn_rim_plane.setCheckable(True)
        self.btn_rim_plane.clicked.connect(lambda: self.toggle_picking('rim'))
        planes_layout.addWidget(self.btn_rim_plane)
        self.lbl_rim = QLabel("Rim: not set")
        self.lbl_rim.setObjectName("status")
        planes_layout.addWidget(self.lbl_rim)
        self.btn_base_plane = QPushButton("Set Base Plane")
        self.btn_base_plane.setCheckable(True)
        self.btn_base_plane.clicked.connect(lambda: self.toggle_picking('base'))
        planes_layout.addWidget(self.btn_base_plane)
        self.lbl_base = QLabel("Base: not set")
        self.lbl_base.setObjectName("status")
        planes_layout.addWidget(self.lbl_base)
        hint = QLabel("Click 3 points on the tip of the rim / base.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        planes_layout.addWidget(hint)
        panel.addWidget(self.grp_planes)

        # 4. Alignment plane
        self.grp_align = QGroupBox("Alignment Plane")
        align_layout = QVBoxLayout(self.grp_align)
        self.rb_align_rim = QRadioButton("Rim")
        self.rb_align_base = QRadioButton("Base")
        self.align_group = QButtonGroup(self)
        self.align_group.addButton(self.rb_align_rim)
        self.align_group.addButton(self.rb_align_base)
        self.align_group.buttonClicked.connect(self.on_alignment_clicked)
        align_layout.addWidget(self.rb_align_rim)
        align_layout.addWidget(self.rb_align_base)
        self.lbl_align = QLabel("Not aligned")
        self.lbl_align.setObjectName("status")
        self.lbl_align.setWordWrap(True)
        align_layout.addWidget(self.lbl_align)
        panel.addWidget(self.grp_align)

        # Symmetry axis (the line the profile is sliced around and mirrored across)
        self.grp_axis = QGroupBox("Symmetry Axis")
        axis_layout = QVBoxLayout(self.grp_axis)
        self.rb_axis = {
            'rim': QRadioButton("Perpendicular to Rim"),
            'base': QRadioButton("Perpendicular to Base"),
            'centers': QRadioButton("Base Center → Rim Center"),
        }
        self.axis_group = QButtonGroup(self)
        for mode, rb in self.rb_axis.items():
            self.axis_group.addButton(rb)
            axis_layout.addWidget(rb)
        self.axis_group.buttonClicked.connect(self.on_axis_clicked)
        panel.addWidget(self.grp_axis)

        # 5. Profile (right side)
        self.grp_profile = QGroupBox("Profile")
        profile_layout = QVBoxLayout(self.grp_profile)
        angle_grid = QGridLayout()
        angle_grid.addWidget(QLabel("Angle:"), 0, 0)
        self.spin_angle = QSpinBox()
        self.spin_angle.setRange(0, 359)
        self.spin_angle.setWrapping(True)
        self.spin_angle.setSuffix("°")
        self.spin_angle.valueChanged.connect(self.schedule_profile_update)
        angle_grid.addWidget(self.spin_angle, 0, 1, 1, 3)
        for col, delta in enumerate((-5, -1, 1, 5)):
            text = f"◀ {delta}°" if delta < 0 else f"+{delta}° ▶"
            btn = QPushButton(text)
            btn.setObjectName("small")
            btn.clicked.connect(lambda _=False, d=delta: self.change_angle(d))
            angle_grid.addWidget(btn, 1, col)
        profile_layout.addLayout(angle_grid)
        ratio_row = QHBoxLayout()
        ratio_row.addWidget(QLabel("Hull Ratio:"))
        self.spin_ratio = QDoubleSpinBox()
        self.spin_ratio.setRange(0.01, 0.25)
        self.spin_ratio.setSingleStep(0.01)
        self.spin_ratio.setValue(0.03)
        self.spin_ratio.valueChanged.connect(self.schedule_profile_update)
        ratio_row.addWidget(self.spin_ratio)
        profile_layout.addLayout(ratio_row)
        self.lbl_profile = QLabel("Set a plane to see the profile.")
        self.lbl_profile.setObjectName("status")
        self.lbl_profile.setWordWrap(True)
        profile_layout.addWidget(self.lbl_profile)
        panel.addWidget(self.grp_profile)

        panel.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(panel_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Width from the content, so labels are never cut (fonts scale with Windows display settings)
        scroll.setMinimumWidth(panel_widget.sizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 6)

        # ---------- Right view area ----------
        self.tabs = QTabWidget()
        # Bold via the font (not the stylesheet) so Qt sizes the tabs for bold text
        tab_font = self.tabs.tabBar().font()
        tab_font.setBold(True)
        self.tabs.tabBar().setFont(tab_font)

        self.view_3d_widget = QWidget()
        v3d_layout = QVBoxLayout(self.view_3d_widget)
        self.plotter = QtInteractor(self.view_3d_widget)
        self.plotter.set_background('white')
        v3d_layout.addWidget(self.plotter.interactor)
        self.tabs.addTab(self.view_3d_widget, "3D View")

        # Scheme (final drawing, live preview)
        self.fig_scheme, self.canvas_scheme, tab = self._make_canvas_tab()
        self.ax_scheme = self.fig_scheme.add_subplot(111)
        self.tabs.addTab(tab, "Scheme")

        # Step Inspector (one pipeline step, large)
        self.tab_step = QWidget()
        step_layout = QVBoxLayout(self.tab_step)
        step_ctrl = QHBoxLayout()
        btn_prev = QPushButton("◀ Previous Step")
        btn_prev.clicked.connect(lambda: self.combo_step.setCurrentIndex(max(self.combo_step.currentIndex() - 1, 0)))
        step_ctrl.addWidget(btn_prev)
        self.combo_step = QComboBox()
        self.combo_step.addItems(STEP_NAMES)
        self.combo_step.currentIndexChanged.connect(self.render_selected_step)
        step_ctrl.addWidget(self.combo_step, stretch=1)
        btn_next = QPushButton("Next Step ▶")
        btn_next.clicked.connect(lambda: self.combo_step.setCurrentIndex(
            min(self.combo_step.currentIndex() + 1, self.combo_step.count() - 1)))
        step_ctrl.addWidget(btn_next)
        step_layout.addLayout(step_ctrl)
        self.lbl_step_info = QLabel("")
        self.lbl_step_info.setObjectName("stepInfo")
        step_layout.addWidget(self.lbl_step_info)
        self.fig_step = self._make_figure()
        self.canvas_step = FigureCanvas(self.fig_step)
        step_layout.addWidget(NavigationToolbar2QT(self.canvas_step, self.tab_step))
        step_layout.addWidget(self.canvas_step, stretch=1)
        self.ax_step = self.fig_step.add_subplot(111)
        self.tabs.addTab(self.tab_step, "Step Inspector")

        # All 6 steps side by side
        self.fig_grid, self.canvas_grid, tab = self._make_canvas_tab()
        self.tabs.addTab(tab, "All Steps Grid")

        self.tabs.currentChanged.connect(self._render_dirty_views)

        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.tabs.addTab(self.txt_log, "Log")

        main_layout.addWidget(scroll, 1)
        main_layout.addWidget(self.tabs, 4)

    def _make_figure(self):
        """Figure whose DPI follows the screen's text scaling, so chart text matches the UI text size."""
        dpi = QApplication.primaryScreen().logicalDotsPerInch() * 0.9
        return Figure(facecolor='white', dpi=dpi)

    def _make_canvas_tab(self):
        """A tab with a matplotlib canvas and its navigation toolbar (zoom/pan)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        fig = self._make_figure()
        canvas = FigureCanvas(fig)
        layout.addWidget(NavigationToolbar2QT(canvas, tab))
        layout.addWidget(canvas, stretch=1)
        return fig, canvas, tab

    def log(self, msg):
        self.txt_log.append(msg)
        print(msg)

    # ------------------------------------------------------------------ State helpers
    def vessel_type(self):
        return 'whole' if self.rb_whole.isChecked() else 'sherd'

    def plane_points_raw(self, plane):
        return self.rim_points_raw if plane == 'rim' else self.base_points_raw

    def effective_alignment_plane(self):
        """The plane used for alignment: the user's choice or the vessel-type default,
        falling back to the other plane if the preferred one is not set."""
        preferred = self.alignment_choice or ('base' if self.vessel_type() == 'whole' else 'rim')
        other = 'rim' if preferred == 'base' else 'base'
        if self.plane_points_raw(preferred) is not None:
            return preferred
        if self.plane_points_raw(other) is not None:
            return other
        return None

    def to_display(self, pts_raw):
        """Raw STL coordinates -> current display coordinates (aligned if available)."""
        if self.align_R is None:
            return np.asarray(pts_raw, dtype=float)
        return pottery_processor.apply_alignment(pts_raw, self.align_R, self.align_center)

    def to_raw(self, pts_display):
        """Current display coordinates -> raw STL coordinates."""
        pts = np.asarray(pts_display, dtype=float)
        if self.align_R is None:
            return pts
        return np.dot(pts - self.align_center, self.align_R) + self.align_center

    # ------------------------------------------------------------------ Load
    def load_stl(self, file_path=None):
        if not file_path or not isinstance(file_path, str):
            file_path, _ = QFileDialog.getOpenFileName(self, "Open STL", "", "STL Files (*.stl)")
        if not file_path:
            return
        self._stop_picking()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            mesh = trimesh.load(file_path)
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.dump(concatenate=True)
            self.mesh_raw = pv.wrap(mesh)
            self.points_raw = np.asarray(mesh.vertices, dtype=float)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Load STL", f"Failed to load the STL file:\n{e}")
            return
        QApplication.restoreOverrideCursor()

        self.stl_file_path = file_path
        self.rim_points_raw = None
        self.base_points_raw = None
        self.alignment_choice = None
        self.lbl_file.setText(os.path.basename(file_path))
        self.log(f"Loaded {file_path}: {len(self.points_raw):,} vertices, "
                 f"size {np.ptp(self.points_raw, axis=0).round(1)} mm")
        self.update_alignment(reset_camera=True)

    # ------------------------------------------------------------------ Vessel type
    def on_vessel_type_changed(self, _button=None):
        # Changing the vessel type restores its default alignment plane and symmetry axis
        self.alignment_choice = None
        self.axis_choice = None
        # Default: a sherd is scanned on both walls, a whole vessel usually only outside
        self.chk_inner_scanned.blockSignals(True)
        self.chk_inner_scanned.setChecked(self.vessel_type() == 'sherd')
        self.chk_inner_scanned.blockSignals(False)
        self.log(f"Vessel type: {'Whole Vessel' if self.vessel_type() == 'whole' else 'Sherd'}")
        if self.points_raw is not None:
            self.update_alignment(reset_camera=True)
        else:
            self._update_controls()

    def on_symmetry_changed(self, checked):
        self.log(f"Symmetrical: {'yes' if checked else 'no'}")
        if self.frame is not None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self.update_left_side()
            finally:
                QApplication.restoreOverrideCursor()
            self.dirty_views.add('scheme')
            self._render_dirty_views()

    def on_inner_scanned_changed(self, checked):
        self.log(f"Inner wall fully scanned: {'yes – scanned walls are used' if checked else 'no – inner wall is completed'}")
        if self.aligned_points is not None:
            self.update_profile()

    def on_alignment_clicked(self, button):
        self.alignment_choice = 'rim' if button is self.rb_align_rim else 'base'
        self.update_alignment(reset_camera=True)

    def on_axis_clicked(self, button):
        self.axis_choice = next(mode for mode, rb in self.rb_axis.items() if rb is button)
        self.log(f"Symmetry axis: {button.text()}")
        self.update_profile()

    # ------------------------------------------------------------------ Picking
    def toggle_picking(self, target):
        if self.picking_target == target:
            self._stop_picking()
            self.log(f"{target.capitalize()} picking cancelled.")
            self.redraw_3d()
            return
        self._stop_picking()
        self.picking_target = target
        self.pick_buffer = []
        self.tabs.setCurrentIndex(0)
        self._update_controls()
        self.redraw_3d()
        try:
            self.plotter.enable_surface_point_picking(
                callback=self._on_point_picked, left_clicking=True,
                show_message=False, show_point=False)
        except Exception as e:
            self._stop_picking()
            QMessageBox.critical(self, "Picking", f"Could not start point picking:\n{e}")

    def _stop_picking(self):
        self.picking_target = None
        self.pick_buffer = []
        try:
            self.plotter.disable_picking()
        except Exception:
            pass
        self._update_controls()

    def _on_point_picked(self, point, *args):
        if self.picking_target is None or point is None:
            return
        try:
            self.pick_buffer.append(np.array(point, dtype=float))
            n = len(self.pick_buffer)
            color = RIM_COLOR if self.picking_target == 'rim' else BASE_COLOR
            self.plotter.add_mesh(pv.Sphere(radius=self._marker_size(), center=point),
                                  color=color, name=f'pick_{n}', pickable=False)
            self._show_pick_message()
            if n == 3:
                target = self.picking_target
                pts_raw = self.to_raw(np.array(self.pick_buffer))
                self._stop_picking()
                self.set_plane(target, pts_raw)
        except Exception as e:
            self._stop_picking()
            QMessageBox.critical(self, "Picking", f"Picking error:\n{e}")

    def set_plane(self, target, pts_raw):
        """Stores 3 picked points (raw coordinates) for the rim or base plane."""
        try:
            pottery_processor.circle_through_3_points(*pts_raw)
        except ValueError:
            QMessageBox.warning(self, "Set Plane",
                                "The 3 points are on one line. Please pick 3 points spread around the tip.")
            self.redraw_3d()
            return
        if target == 'rim':
            self.rim_points_raw = np.array(pts_raw)
        else:
            self.base_points_raw = np.array(pts_raw)
        coords = "; ".join(f"({p[0]:.3f}, {p[1]:.3f}, {p[2]:.3f})" for p in pts_raw)
        self.log(f"{target.capitalize()} plane set from 3 points (STL coordinates): {coords}")
        self.update_alignment(reset_camera=True)

    def _show_pick_message(self):
        name = "RIM" if self.picking_target == 'rim' else "BASE"
        n = len(self.pick_buffer)
        self.plotter.add_text(f"Click 3 points on the tip of the {name}  ({n}/3)",
                              position='upper_left', font_size=12, color='black', name='pick_msg')

    def _marker_size(self):
        if self.points_raw is None:
            return 1.0
        return max(float(np.ptp(self.points_raw, axis=0).max()) * 0.008, 0.5)

    # ------------------------------------------------------------------ Alignment
    def update_alignment(self, reset_camera=False):
        """Recomputes the alignment from the effective plane and redraws everything."""
        plane = self.effective_alignment_plane()
        self.align_R = self.align_center = None
        self.aligned_points = None
        self.rim_circle = self.base_circle = None

        if plane is not None and self.points_raw is not None:
            try:
                R, c = pottery_processor.alignment_transform(
                    *self.plane_points_raw(plane), points=self.points_raw, plane=plane)
                self.align_R, self.align_center = R, c
                self.aligned_points = pottery_processor.apply_alignment(self.points_raw, R, c)
            except Exception as e:
                QMessageBox.critical(self, "Alignment", f"Alignment failed:\n{e}")

        if self.points_raw is not None:
            try:
                if self.rim_points_raw is not None:
                    self.rim_circle = pottery_processor.circle_through_3_points(*self.to_display(self.rim_points_raw))
                if self.base_points_raw is not None:
                    self.base_circle = pottery_processor.circle_through_3_points(*self.to_display(self.base_points_raw))
            except Exception as e:
                QMessageBox.warning(self, "Planes", f"Could not compute a plane circle:\n{e}")

        self._update_controls()
        self._update_info()
        self.update_profile(redraw_3d=False)
        self.redraw_3d(reset_camera=reset_camera)

    def _update_info(self):
        if self.rim_circle is not None:
            self.lbl_rim.setText(f"Rim: ✓  Ø {self.rim_circle[1] * 2 / 10:.1f} cm")
        else:
            self.lbl_rim.setText("Rim: not set")
        if self.base_circle is not None:
            self.lbl_base.setText(f"Base: ✓  Ø {self.base_circle[1] * 2 / 10:.1f} cm")
        else:
            self.lbl_base.setText("Base: not set")

        plane = self.effective_alignment_plane()
        if self.aligned_points is None or plane is None:
            self.lbl_align.setText("Not aligned – set a plane first.")
            return
        lines = [f"Aligned to the {plane} plane.",
                 f"Height: {np.ptp(self.aligned_points[:, 2]) / 10:.1f} cm"]
        if self.rim_circle is not None and self.base_circle is not None:
            tilt = np.degrees(np.arccos(np.clip(abs(np.dot(self.rim_circle[2], self.base_circle[2])), 0, 1)))
            lines.append(f"Rim ↔ base tilt: {tilt:.1f}°")
        self.lbl_align.setText("\n".join(lines))

    # ------------------------------------------------------------------ Controls
    def _update_controls(self):
        loaded = self.points_raw is not None
        picking = self.picking_target is not None

        self.btn_load.setEnabled(not picking)
        self.grp_type.setEnabled(loaded and not picking)

        self.btn_rim_plane.setEnabled(loaded and self.picking_target in (None, 'rim'))
        self.btn_base_plane.setEnabled(loaded and self.picking_target in (None, 'base'))
        self.btn_rim_plane.setChecked(self.picking_target == 'rim')
        self.btn_base_plane.setChecked(self.picking_target == 'base')
        self.btn_rim_plane.setText("Cancel Rim Picking" if self.picking_target == 'rim' else "Set Rim Plane")
        self.btn_base_plane.setText("Cancel Base Picking" if self.picking_target == 'base' else "Set Base Plane")

        # Only planes that are set can be used for alignment
        self.grp_align.setEnabled(loaded and not picking)
        self.rb_align_rim.setEnabled(self.rim_points_raw is not None)
        self.rb_align_base.setEnabled(self.base_points_raw is not None)
        plane = self.effective_alignment_plane() if loaded else None
        self.align_group.setExclusive(False)
        self.rb_align_rim.setChecked(plane == 'rim')
        self.rb_align_base.setChecked(plane == 'base')
        self.align_group.setExclusive(True)

        self.grp_profile.setEnabled(self.aligned_points is not None and not picking)

        # Axis modes need their planes; the effective mode is shown checked
        available = self._available_axis_modes()
        self.grp_axis.setEnabled(self.aligned_points is not None and not picking)
        effective = self.effective_axis_mode()
        self.axis_group.setExclusive(False)
        for mode, rb in self.rb_axis.items():
            rb.setEnabled(mode in available)
            rb.setChecked(mode == effective)
        self.axis_group.setExclusive(True)

    # ------------------------------------------------------------------ 3D view
    def redraw_3d(self, reset_camera=False):
        # clear_actors() keeps the lights (plotter.clear() removes them -> flat, unshaded model)
        self.plotter.clear_actors()
        if self.mesh_raw is None:
            self.plotter.render()
            return

        mesh = self.mesh_raw.copy()
        if self.align_R is not None:
            mesh.points = self.to_display(self.mesh_raw.points)
        self.plotter.add_mesh(mesh, color=CLAY_COLOR, smooth_shading=True, name='vessel')

        r = self._marker_size()
        for plane_pts, circle, color, name in ((self.rim_points_raw, self.rim_circle, RIM_COLOR, 'rim'),
                                               (self.base_points_raw, self.base_circle, BASE_COLOR, 'base')):
            if plane_pts is None:
                continue
            for i, p in enumerate(self.to_display(plane_pts)):
                self.plotter.add_mesh(pv.Sphere(radius=r, center=p), color=color,
                                      name=f'{name}_pt{i}', pickable=False)
            if circle is not None:
                self.plotter.add_mesh(self._circle_polyline(*circle), color=color, line_width=3,
                                      name=f'{name}_circle', pickable=False)
                self.plotter.add_mesh(pv.Sphere(radius=r * 0.8, center=circle[0]), color=color,
                                      name=f'{name}_center', pickable=False)

        self._draw_slice_3d()

        # Points picked so far (display coordinates)
        if self.picking_target is not None:
            color = RIM_COLOR if self.picking_target == 'rim' else BASE_COLOR
            for i, p in enumerate(self.pick_buffer):
                self.plotter.add_mesh(pv.Sphere(radius=r, center=p), color=color,
                                      name=f'pick_{i + 1}', pickable=False)
            self._show_pick_message()

        self.plotter.add_axes()
        if reset_camera:
            if self.align_R is not None:
                self.plotter.view_xz()   # side view: the alignment plane is horizontal
            else:
                self.plotter.reset_camera()
        self.plotter.render()

    def _draw_slice_3d(self):
        """Symmetry axis and the right-side slicing half-plane (updated on every angle change)."""
        for name in ('slice_plane', 'axis_line'):
            self.plotter.remove_actor(name)
        if self.frame is None or self.aligned_points is None:
            return
        fr = self.frame
        v = np.dot(self.aligned_points - fr['origin'], fr['a'])
        v0, v1 = v.min() - 5, v.max() + 5
        u1 = (self.profile_uv[:, 0].max() if self.profile_uv is not None and len(self.profile_uv) else 50) + 15
        corners = pottery_processor.uv_to_3d([[0, v0], [u1, v0], [u1, v1], [0, v1]], fr)
        quad = pv.PolyData(corners, faces=[4, 0, 1, 2, 3])
        self.plotter.add_mesh(quad, color=SLICE_COLOR, opacity=0.25, name='slice_plane', pickable=False)
        axis_pts = pottery_processor.uv_to_3d([[0, v0], [0, v1]], fr)
        self.plotter.add_mesh(pv.Line(axis_pts[0], axis_pts[1]), color='black', line_width=3,
                              name='axis_line', pickable=False)

    @staticmethod
    def _circle_polyline(center, radius, normal, n=120):
        normal = np.asarray(normal, dtype=float)
        ref = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        b1 = np.cross(normal, ref)
        b1 /= np.linalg.norm(b1)
        b2 = np.cross(normal, b1)
        t = np.linspace(0, 2 * np.pi, n)
        pts = center + radius * (np.outer(np.cos(t), b1) + np.outer(np.sin(t), b2))
        return pv.lines_from_points(pts)

    # ------------------------------------------------------------------ Profile
    def change_angle(self, delta):
        self.spin_angle.setValue((self.spin_angle.value() + delta) % 360)

    def schedule_profile_update(self, *args):
        self.profile_timer.start()

    def _available_axis_modes(self):
        modes = set()
        if self.rim_points_raw is not None:
            modes.add('rim')
        if self.base_points_raw is not None:
            modes.add('base')
        if self.rim_points_raw is not None and self.base_points_raw is not None:
            modes.add('centers')
        return modes

    def effective_axis_mode(self):
        """The user's axis choice, or the default by vessel type (Sherd -> perpendicular to rim,
        Whole -> perpendicular to base), falling back to the plane that is set."""
        available = self._available_axis_modes()
        if self.axis_choice in available:
            return self.axis_choice
        preferred = 'base' if self.vessel_type() == 'whole' else 'rim'
        if preferred in available:
            return preferred
        other = 'rim' if preferred == 'base' else 'base'
        return other if other in available else None

    def update_profile(self, redraw_3d=True):
        """Slices the aligned cloud at the current angle and runs the 6-step pipeline."""
        self.frame = None
        self.profile_uv = None
        self.solid_poly = None
        self.diag = {}
        self.axis_mode = self.effective_axis_mode() if self.aligned_points is not None else None

        if self.axis_mode is not None:
            try:
                axis_pt, axis_dir = pottery_processor.build_symmetry_axis(
                    self.axis_mode, self.rim_circle, self.base_circle)
                self.frame = pottery_processor.slice_frame(axis_pt, axis_dir, self.spin_angle.value())
                self.profile_uv = pottery_processor.extract_axis_profile(self.aligned_points, self.frame)
                # Inner wall fully scanned: use the scanned walls as they are (no synthetic inner wall)
                self.solid_poly, self.diag, err = pottery_processor.run_6step_pipeline(
                    self.profile_uv, hull_ratio=self.spin_ratio.value(),
                    complete_inner_wall=not self.chk_inner_scanned.isChecked())
            except Exception as e:
                err = f"Profile error: {e}"
            if err:
                if self.profile_uv is not None and len(self.profile_uv) < 10:
                    err = "The slice misses the vessel at this angle – rotate the angle."
                self.lbl_profile.setText(f"⚠ {err}")
                self.log(f"Angle {self.spin_angle.value()}°: {err}")
            elif self.diag.get('skipped_steps'):
                self.lbl_profile.setText(f"{len(self.profile_uv):,} slice points\n"
                                         f"Scanned walls used (Steps 3–5 not needed)")
            else:
                self.lbl_profile.setText(
                    f"{len(self.profile_uv):,} slice points\n"
                    f"Wall thickness: {self.diag.get('measured_thickness', 0):.1f} mm")
        else:
            self.lbl_profile.setText("Set a plane to see the profile.")

        self.update_left_side()
        self.dirty_views = {'scheme', 'step', 'grid'}
        self._render_dirty_views()
        if redraw_3d:
            self._draw_slice_3d()
            self.plotter.render()

    def _render_dirty_views(self, *args):
        """Redraws only the visible 2D tab; the others are redrawn when they are opened."""
        current = self.tabs.currentIndex()
        for key, index, render in (('scheme', 1, self.render_scheme),
                                   ('step', 2, self.render_selected_step),
                                   ('grid', 3, self.render_grid_view)):
            if key in self.dirty_views and current == index:
                render()

    # ------------------------------------------------------------------ Left side
    def rim_points_uv(self):
        """Left and right ends of the rim line (uv).
        Right end: where the rim circle crosses the slicing plane (or the top of the profile if no rim plane).
        Left end: the mirror of the right end for a symmetrical vessel, else the real rim crossing."""
        if self.frame is None:
            return None, None
        ip = None
        if self.rim_circle is not None:
            ip = pottery_processor.circle_slice_intersections(*self.rim_circle, self.frame)
        if ip is not None:
            right, left = ip[1], ip[0]
        else:
            polys = _polygons(self.solid_poly)
            if not polys:
                return None, None
            coords = np.array(max(polys, key=lambda p: p.area).exterior.coords)
            right = coords[np.argmax(coords[:, 1])]
            left = None
        if self.chk_symmetrical.isChecked() or left is None:
            left = np.array([-right[0], right[1]])
        return np.asarray(left, dtype=float), np.asarray(right, dtype=float)

    def update_left_side(self):
        """Non-symmetrical vessels: outline of the real left half (computed per angle).
        Symmetrical vessels are mirrored at drawing time and need nothing here."""
        self.left_lines_uv = []
        if self.frame is None or self.chk_symmetrical.isChecked():
            return
        try:
            rim_v = pottery_processor.rim_line_v(*self.rim_points_uv())
            self.left_lines_uv = pottery_processor.half_view_outline(self.aligned_points, self.frame, rim_v=rim_v)
        except Exception as e:
            self.log(f"Left side error: {e}")

    def left_side_lines_uv(self):
        """Lines of the left (external) side of the scheme, in uv."""
        if not self.chk_symmetrical.isChecked():
            return self.left_lines_uv
        polys = _polygons(self.solid_poly)
        if not polys:
            return []
        main = max(polys, key=lambda p: p.area)
        outer = self.diag.get('outer_coords')
        if outer is None or self.diag.get('skipped_steps'):
            outer = pottery_processor.outer_wall_coords(main)
        return [LineString(pottery_processor.mirror_uv(outer))]

    # ------------------------------------------------------------------ Scheme
    def render_scheme(self):
        """Final drawing (drawing coordinates: alignment plane horizontal)."""
        self.dirty_views.discard('scheme')
        ax = self.ax_scheme
        ax.clear()
        ax.axis('off')
        if self.frame is None or self.profile_uv is None or len(self.profile_uv) == 0:
            self.canvas_scheme.draw()
            return
        fr = self.frame

        # Right side: filled cross-section
        polys = _polygons(self.solid_poly)
        for poly in polys:
            d = pottery_processor.geometry_uv_to_drawing(poly, fr)
            ax.fill(*d.exterior.xy, color='black')
            for interior in d.interiors:
                ax.fill(*interior.xy, color='white')
        if not polys:
            pts = pottery_processor.uv_to_drawing(self.profile_uv, fr)
            ax.plot(pts[:, 0], pts[:, 1], 'k.', markersize=1)

        # Left side: external view (outline only)
        v_bottom = self.profile_uv[:, 1].min()
        for line in self.left_side_lines_uv():
            d = pottery_processor.uv_to_drawing(np.array(line.coords), fr)
            ax.plot(d[:, 0], d[:, 1], 'k-', lw=1.2)
            v_bottom = min(v_bottom, np.array(line.coords)[:, 1].min())

        # Rim line across both sides (possibly tilted)
        rim_left, rim_right = self.rim_points_uv()
        v_top = self.profile_uv[:, 1].max()
        if rim_left is not None:
            seg = pottery_processor.uv_to_drawing([rim_left, rim_right], fr)
            ax.plot(seg[:, 0], seg[:, 1], 'k-', lw=1.2)
            v_top = pottery_processor.rim_line_v(rim_left, rim_right)(0.0)

        # Symmetry axis (dash-dot) from the bottom up to the rim line
        axis_seg = pottery_processor.uv_to_drawing([[0, v_bottom], [0, v_top]], fr)
        ax.plot(axis_seg[:, 0], axis_seg[:, 1], 'k-.', lw=1)

        ax.set_aspect('equal')
        self.canvas_scheme.draw()

    def render_selected_step(self, *args):
        """Renders a single pipeline step in the Step Inspector (uv coordinates: axis at u = 0)."""
        self.dirty_views.discard('step')
        ax = self.ax_step
        ax.clear()
        diag = self.diag
        if not diag:
            self.lbl_step_info.setText("")
            self.canvas_step.draw()
            return
        step = self.combo_step.currentIndex()
        empty = np.empty((0, 2))
        info = ""

        if diag.get('skipped_steps') and 2 <= step <= 4:
            ax.text(0.5, 0.5, "Not used:\nthe inner wall is fully scanned,\nso it is not completed.",
                    transform=ax.transAxes, ha='center', va='center', fontsize=12, color='#55755b')
            ax.set_axis_off()
            ax.set_title(STEP_NAMES[step], fontsize=12, fontweight='bold')
            self.lbl_step_info.setText("Inner wall fully scanned: Steps 3–5 are skipped; Step 6 shows the scanned section.")
            self.canvas_step.draw()
            return

        if step == 0:
            raw = diag.get('raw_points', empty)
            cln = diag.get('cleaned_points', empty)
            rej = diag.get('rejected_points', empty)
            if len(rej) > 0:
                ax.plot(rej[:, 0], rej[:, 1], 'r.', markersize=5, label=f'Handle ({len(rej)} pts)')
            ax.plot(cln[:, 0], cln[:, 1], 'b.', markersize=3, label=f'Vessel body ({len(cln)} pts)')
            info = f"Total points: {len(raw)} | Body kept: {len(cln)} | Handle: {len(rej)}"
        elif step == 1:
            coords = diag.get('coords', empty)
            cln = diag.get('cleaned_points', empty)
            ax.plot(cln[:, 0], cln[:, 1], '.', color='#b0c8d8', markersize=2, label='Points')
            if len(coords) > 0:
                ax.plot(coords[:, 0], coords[:, 1], 'g-', lw=2.5, label='Concave hull')
                ax.plot(coords[:, 0], coords[:, 1], 'ko', markersize=3, label=f'Hull vertices ({len(coords)})')
            info = f"Concave hull vertices: {len(coords)} | Ratio: {self.spin_ratio.value():.2f}"
        elif step == 2:
            out_c = diag.get('outer_coords', empty)
            inn_c = diag.get('inner_coords', empty)
            if len(out_c) > 0:
                ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=3, label=f'Outer wall ({len(out_c)} pts)')
            if len(inn_c) > 0:
                ax.plot(inn_c[:, 0], inn_c[:, 1], 'r-', lw=3, label=f'Scanned inner wall ({len(inn_c)} pts)')
            if 'rim_peak' in diag:
                ax.plot(*diag['rim_peak'], 'm*', markersize=14, label='Rim peak')
            if 'bottom_center' in diag:
                ax.plot(*diag['bottom_center'], 'cD', markersize=10, label='Bottom center')
            info = f"Outer wall: {len(out_c)} pts | Inner wall: {len(inn_c)} pts"
        elif step == 3:
            out_c = diag.get('outer_coords', empty)
            inn_c = diag.get('inner_coords', empty)
            s_pts = diag.get('inner_sampled_pts', empty)
            dists = diag.get('distances', [])
            if len(out_c) > 0:
                ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2, label='Outer wall')
            if len(inn_c) > 0:
                ax.plot(inn_c[:, 0], inn_c[:, 1], 'k--', lw=1, alpha=0.5, label='Inner wall')
            if len(s_pts) > 0:
                ax.plot(s_pts[:, 0], s_pts[:, 1], 'ro', markersize=5, label=f'Sampled points ({len(s_pts)})')
                line = diag.get('outer_line')
                if line is not None:
                    for pt in s_pts:
                        proj = line.interpolate(line.project(Point(pt)))
                        ax.plot([pt[0], proj.x], [pt[1], proj.y], 'r:', lw=1.2)
            rng = f"{min(dists):.1f} – {max(dists):.1f} mm" if dists else "N/A"
            info = (f"Thickness: {diag.get('measured_thickness', 0):.2f} mm "
                    f"(median of {len(dists)} points, range {rng})")
        elif step == 4:
            out_c = diag.get('outer_coords', empty)
            off_c = diag.get('inner_offset_coords', empty)
            bz = diag.get('inner_base_z', 0.0)
            if len(out_c) > 0:
                ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2, label='Outer wall')
            if len(off_c) > 0:
                ax.plot(off_c[:, 0], off_c[:, 1], 'g-', lw=3, label='Synthetic inner wall')
            ax.axhline(bz, color='orange', linestyle='--', lw=2, label='Base floor level')
            info = f"Offset: {diag.get('measured_thickness', 0):.2f} mm inwards | Floor at {bz:.1f} mm"
        elif step == 5:
            for poly in _polygons(diag.get('solid_poly')):
                ax.fill(*poly.exterior.xy, color='#222222', alpha=0.85)
                ax.plot(*poly.exterior.xy, 'k-', lw=1.5)
            ring = diag.get('ring', empty)
            if len(ring) > 0:
                ax.plot(ring[:, 0], ring[:, 1], 'm--', lw=1, alpha=0.6, label=f'Assembly ring ({len(ring)} nodes)')
            sp = diag.get('solid_poly')
            info = f"Polygon area: {sp.area if sp is not None else 0:.1f} mm²"

        ax.axvline(0, color='k', linestyle='-.', lw=1, label='Symmetry axis')
        ax.set_title(STEP_NAMES[step], fontsize=12, fontweight='bold')
        ax.set_xlabel("distance from axis (mm)")
        ax.set_ylabel("along axis (mm)")
        ax.set_aspect('equal')
        ax.grid(True, linestyle=':', alpha=0.6)
        ax.legend(loc='best', fontsize=9)
        self.lbl_step_info.setText(info)
        self.canvas_step.draw()

    def render_grid_view(self):
        """All 6 pipeline steps side by side."""
        self.dirty_views.discard('grid')
        self.fig_grid.clear()
        diag = self.diag
        if not diag:
            self.canvas_grid.draw()
            return
        axes = self.fig_grid.subplots(2, 3)
        empty = np.empty((0, 2))
        out_c = diag.get('outer_coords', empty)

        ax = axes[0, 0]
        ax.set_title("1. Raw points & handle", fontsize=10, fontweight='bold')
        rej = diag.get('rejected_points', empty)
        cln = diag.get('cleaned_points', empty)
        if len(rej) > 0:
            ax.plot(rej[:, 0], rej[:, 1], 'r.', markersize=2)
        if len(cln) > 0:
            ax.plot(cln[:, 0], cln[:, 1], 'b.', markersize=2)

        ax = axes[0, 1]
        ax.set_title(f"2. Concave hull (ratio={self.spin_ratio.value():.2f})", fontsize=10, fontweight='bold')
        coords = diag.get('coords', empty)
        if len(coords) > 0:
            ax.plot(coords[:, 0], coords[:, 1], 'g-', lw=2)
            ax.plot(coords[:, 0], coords[:, 1], 'k.', markersize=3)

        ax = axes[0, 2]
        ax.set_title("3. Outer vs inner split", fontsize=10, fontweight='bold')
        inn_c = diag.get('inner_coords', empty)
        if len(out_c) > 0:
            ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2)
        if len(inn_c) > 0:
            ax.plot(inn_c[:, 0], inn_c[:, 1], 'r-', lw=2)
        if 'rim_peak' in diag:
            ax.plot(*diag['rim_peak'], 'm*', markersize=8)
        if 'bottom_center' in diag:
            ax.plot(*diag['bottom_center'], 'cD', markersize=6)

        ax = axes[1, 0]
        ax.set_title(f"4. Thickness: {diag.get('measured_thickness', 0):.2f} mm", fontsize=10, fontweight='bold')
        s_pts = diag.get('inner_sampled_pts', empty)
        if len(out_c) > 0:
            ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=1.5)
        if len(s_pts) > 0:
            ax.plot(s_pts[:, 0], s_pts[:, 1], 'ro', markersize=3)

        ax = axes[1, 1]
        ax.set_title("5. Offset & base clip", fontsize=10, fontweight='bold')
        off_c = diag.get('inner_offset_coords', empty)
        if len(out_c) > 0:
            ax.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=1.5)
        if len(off_c) > 0:
            ax.plot(off_c[:, 0], off_c[:, 1], 'g-', lw=2)
        if 'inner_base_z' in diag:
            ax.axhline(diag['inner_base_z'], color='orange', linestyle='--')

        ax = axes[1, 2]
        ax.set_title("6. Solid polygon", fontsize=10, fontweight='bold')
        for poly in _polygons(diag.get('solid_poly')):
            ax.fill(*poly.exterior.xy, color='black', alpha=0.85)

        if diag.get('skipped_steps'):
            for ax, title in ((axes[0, 2], "3. Outer vs inner split"), (axes[1, 0], "4. Thickness"),
                              (axes[1, 1], "5. Offset & base clip")):
                ax.set_title(f"{title}\n(not used – inner wall scanned)", fontsize=10, fontweight='bold', color='#8aa58f')
                ax.set_axis_off()

        for ax in axes.flat:
            ax.axvline(0, color='gray', linestyle='-.', lw=0.8)
            ax.set_aspect('equal')
            ax.grid(True, linestyle=':', alpha=0.5)
        self.fig_grid.tight_layout()
        self.canvas_grid.draw()

    def closeEvent(self, event):
        try:
            self.plotter.close()
        except Exception:
            pass
        super().closeEvent(event)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PotteryStudio()
    window.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        window.load_stl(sys.argv[1])
    sys.exit(app.exec_())
