import sys
import os
import numpy as np
import trimesh
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas, NavigationToolbar2QT
from matplotlib.figure import Figure
from matplotlib.widgets import LassoSelector
from matplotlib.path import Path

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QFileDialog,
                             QTabWidget, QMessageBox, QTextEdit, QComboBox,
                             QSizePolicy, QFrame, QSpinBox, QDoubleSpinBox)
from PyQt5.QtCore import Qt

import shapely
from shapely.geometry import Point, LineString, Polygon, MultiPoint, box
from shapely import concave_hull
from shapely.validation import make_valid

import pottery_processor


def run_6step_pipeline_v2(points_2d: np.ndarray, handle_mask: np.ndarray = None, hull_ratio: float = 0.03):
    """
    Executes the 6-step algorithmic pipeline:
      - Handle points are ONLY rejected if specified by user via handle_mask (Lasso).
      - Stray mid-height points right on X=0 are filtered to prevent false central neck snapping.
      - Bottom center is strictly searched in the true bottom zone (lowest 15% of vessel).
      - Concave hull ratio defaults to 0.03 to preserve rounded rim curvature.
    """
    diag = {}
    if points_2d is None or len(points_2d) < 10:
        return None, diag, "Error: Not enough points in 2D profile (need >= 10 points)."

    diag['raw_points'] = points_2d.copy()
    z_min, z_max = np.min(points_2d[:, 1]), np.max(points_2d[:, 1])
    diag['z_min'] = z_min
    diag['z_max'] = z_max

    # ---------------------------------------------------------
    # STEP 1: Handle Filtering & Mid-Axis Noise Cleanup
    # ---------------------------------------------------------
    # 1. User Lasso filter
    if handle_mask is not None and np.any(handle_mask):
        cleaned_points = points_2d[~handle_mask]
        rejected_points = points_2d[handle_mask]
    else:
        cleaned_points = points_2d.copy()
        rejected_points = np.empty((0, 2))

    # 2. Prevent opposite-wall bleed: filter points right on axis (X < 0.8) that are above base zone (Z > z_min + 30)
    axis_spill_mask = (cleaned_points[:, 0] < 0.8) & (cleaned_points[:, 1] > z_min + 30.0)
    cleaned_points = cleaned_points[~axis_spill_mask]

    diag['cleaned_points'] = cleaned_points
    diag['rejected_points'] = rejected_points

    if len(cleaned_points) < 10:
        return None, diag, f"Step 1 Error: Only {len(cleaned_points)} points remain after filtering."

    # ---------------------------------------------------------
    # STEP 2: Profile Boundary via Concave Hull
    # ---------------------------------------------------------
    try:
        mp = MultiPoint(cleaned_points)
        # Using ratio=0.03 preserves the exact rounded flare of the rim without diagonal cutting
        hull = concave_hull(mp, ratio=hull_ratio, allow_holes=False)
        hull = make_valid(hull)

        if hull.geom_type == 'MultiPolygon':
            hull = max(hull.geoms, key=lambda a: a.area)

        if hull.geom_type != 'Polygon' or hull.is_empty:
            return None, diag, f"Step 2 Error: concave_hull returned {hull.geom_type} instead of Polygon."

        coords = np.array(hull.exterior.coords)
        diag['hull'] = hull
        diag['coords'] = coords
    except Exception as e:
        return None, diag, f"Step 2 Exception (Concave Hull): {e}"

    # ---------------------------------------------------------
    # STEP 3: Outer/Inner Wall Splitting
    # ---------------------------------------------------------
    try:
        rim_idx = np.argmax(coords[:, 1])
        rim_z = coords[rim_idx, 1]
        rim_x = coords[rim_idx, 0]
        diag['rim_peak'] = (rim_x, rim_z)

        # Search for true bottom center strictly in the lowest 15% of the vessel
        z_bottom_zone = z_min + 0.15 * (rim_z - z_min)
        bottom_indices = np.where(coords[:, 1] < z_bottom_zone)[0]
        if len(bottom_indices) == 0:
            # Fallback to lowest 25%
            z_bottom_zone = z_min + 0.25 * (rim_z - z_min)
            bottom_indices = np.where(coords[:, 1] < z_bottom_zone)[0]

        if len(bottom_indices) == 0:
            return None, diag, "Step 3 Error: No vertices found in the base zone."

        bottom_center_idx = bottom_indices[np.argmin(coords[bottom_indices, 0])]
        diag['bottom_center'] = (coords[bottom_center_idx, 0], coords[bottom_center_idx, 1])

        idx1, idx2 = rim_idx, bottom_center_idx
        if idx1 < idx2:
            path1 = coords[idx1:idx2 + 1]
            path2 = np.vstack((coords[idx2:], coords[:idx1 + 1]))
        else:
            path1 = coords[idx2:idx1 + 1]
            path2 = np.vstack((coords[idx1:], coords[:idx2 + 1]))

        if np.mean(path1[:, 0]) > np.mean(path2[:, 0]):
            outer_coords, inner_coords = path1, path2
        else:
            outer_coords, inner_coords = path2, path1

        # Ensure outer_coords flows upwards (Bottom to Rim)
        if abs(outer_coords[0, 1] - rim_z) < abs(outer_coords[-1, 1] - rim_z):
            outer_coords = outer_coords[::-1]

        # Ensure inner_coords flows downwards (Rim to Base)
        if abs(inner_coords[-1, 1] - rim_z) < abs(inner_coords[0, 1] - rim_z):
            inner_coords = inner_coords[::-1]

        outer_line = LineString(outer_coords)
        diag['outer_coords'] = outer_coords
        diag['inner_coords'] = inner_coords
        diag['outer_line'] = outer_line
    except Exception as e:
        return None, diag, f"Step 3 Exception (Wall Splitting): {e}"

    # ---------------------------------------------------------
    # STEP 4: Automatic Perpendicular Thickness Measurement
    # ---------------------------------------------------------
    try:
        inner_pts = [p for p in inner_coords if p[1] > rim_z - 20.0]
        if len(inner_pts) < 5:
            inner_pts = [p for p in inner_coords if p[1] > rim_z - 10.0]

        distances = [Point(p).distance(outer_line) for p in inner_pts]
        thickness = float(np.median(distances)) if len(distances) > 0 else 5.0
        diag['inner_sampled_pts'] = np.array(inner_pts) if len(inner_pts) > 0 else np.empty((0, 2))
        diag['distances'] = distances
        diag['measured_thickness'] = thickness
    except Exception as e:
        return None, diag, f"Step 4 Exception (Thickness Measurement): {e}"

    # ---------------------------------------------------------
    # STEP 5: Synthetic Inner Wall Offset
    # ---------------------------------------------------------
    try:
        synthetic_inner = outer_line.offset_curve(thickness)
        inner_base_z = z_min + thickness
        diag['inner_base_z'] = inner_base_z
        diag['synthetic_inner'] = synthetic_inner

        clip_box = box(-1000, inner_base_z, 1000, rim_z + 1000)
        clipped_inner = synthetic_inner.intersection(clip_box)

        if clipped_inner.geom_type == 'MultiLineString':
            clipped_inner = max(clipped_inner.geoms, key=lambda geom: geom.length)

        if clipped_inner.is_empty or not hasattr(clipped_inner, 'coords'):
            return None, diag, "Step 5 Error: Clipped inner offset curve is empty."

        inner_offset_coords = np.array(clipped_inner.coords)

        # Ensure inner offset flows downwards from Rim to Base
        if inner_offset_coords[0, 1] < inner_offset_coords[-1, 1]:
            inner_offset_coords = inner_offset_coords[::-1]

        diag['inner_offset_coords'] = inner_offset_coords
    except Exception as e:
        return None, diag, f"Step 5 Exception (Inner Wall Offset): {e}"

    # ---------------------------------------------------------
    # STEP 6: Base Closure & Topology Resolution
    # ---------------------------------------------------------
    try:
        ring = []
        p_bottom_center = outer_coords[0]
        ring.append([0, p_bottom_center[1]])
        ring.append([p_bottom_center[0], p_bottom_center[1]])
        ring.extend(outer_coords.tolist())
        ring.extend(inner_offset_coords.tolist())
        p_inner_bottom = inner_offset_coords[-1]
        ring.append([0, p_inner_bottom[1]])
        ring.append([0, p_bottom_center[1]])

        diag['ring'] = np.array(ring)

        solid_poly = make_valid(Polygon(ring).buffer(0))
        if solid_poly.is_empty:
            return None, diag, "Step 6 Error: Resulting polygon is empty after buffer(0)."

        diag['solid_poly'] = solid_poly
        return solid_poly, diag, None
    except Exception as e:
        return None, diag, f"Step 6 Exception (Base Closure): {e}"


class ProfileTest2App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Profile Test 2 - Interactive Angle & Lasso & Fine Rim Contour")
        self.resize(1500, 950)

        self.stl_file_path = ""
        self.points_file_path = ""
        self.points_data = None
        self.raw_mesh_points = None
        self.aligned_points = None
        self.profile_2d = None
        self.handle_mask = None
        self.solid_poly = None
        self.diag = {}
        self.rim_fit_info = (0.0, 0.0, 0.0)

        # Lasso tools
        self.lasso_active = False
        self.lasso_selector = None

        self._apply_stylesheet()
        self._init_ui()
        self.showMaximized()

    def _apply_stylesheet(self):
        self.setStyleSheet("""
        QMainWindow {
            background-color: #f1f8f3;
        }
        QWidget {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            font-size: 10pt;
            color: #1a3320;
        }
        QFrame#topBarFrame {
            background-color: #ffffff;
            border: 1px solid #c0dfc6;
            border-radius: 8px;
            padding: 4px;
        }
        QPushButton {
            background-color: #ffffff;
            border: 2px solid #95cca0;
            border-radius: 6px;
            padding: 6px 14px;
            font-weight: bold;
            color: #234c2c;
        }
        QPushButton:hover {
            background-color: #e5f6e8;
            border-color: #63ba72;
        }
        QPushButton:pressed {
            background-color: #c4ecd0;
        }
        QPushButton:disabled {
            background-color: #f7faf7;
            color: #afc7b4;
            border-color: #dceada;
        }
        QPushButton#btnLasso:checked {
            background-color: #ffebee;
            border-color: #e57373;
            color: #c62828;
        }
        QSpinBox, QDoubleSpinBox, QComboBox {
            background-color: #ffffff;
            border: 2px solid #95cca0;
            border-radius: 6px;
            padding: 4px 8px;
            font-weight: bold;
            color: #234c2c;
        }
        QTabWidget::pane {
            border: 2px solid #c0dfc6;
            background: #ffffff;
            border-radius: 8px;
            margin-top: -1px;
        }
        QTabBar::tab {
            background: #e2f2e5;
            border: 1px solid #c0dfc6;
            padding: 10px 22px;
            font-weight: bold;
            font-size: 11pt;
            color: #2f5e38;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            border-bottom-color: #ffffff;
            color: #132e18;
        }
        QTabBar::tab:hover:!selected {
            background: #d4ebd8;
        }
        QTextEdit {
            background: #ffffff;
            border: 1px solid #c0dfc6;
            border-radius: 6px;
            font-family: Consolas, 'Courier New', monospace;
            font-size: 10pt;
            padding: 8px;
        }
        """)

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(6)

        # ---------------------------------------------------------
        # TOP BAR
        # ---------------------------------------------------------
        top_frame = QFrame()
        top_frame.setObjectName("topBarFrame")
        top_bar = QHBoxLayout(top_frame)
        top_bar.setContentsMargins(8, 6, 8, 6)
        top_bar.setSpacing(8)

        self.btn_load_points = QPushButton("1. Load Points (.txt/.json)")
        self.btn_load_points.clicked.connect(self.load_points_file)
        top_bar.addWidget(self.btn_load_points)

        self.btn_load_stl = QPushButton("2. Select STL (Override)")
        self.btn_load_stl.clicked.connect(self.load_stl_file)
        top_bar.addWidget(self.btn_load_stl)

        # Angle Controls (Interactive rotation)
        lbl_angle = QLabel("Angle:")
        lbl_angle.setStyleSheet("font-weight: bold; color: #234c2c;")
        top_bar.addWidget(lbl_angle)

        self.btn_angle_minus5 = QPushButton("◀ -5°")
        self.btn_angle_minus5.clicked.connect(lambda: self.change_angle(-5))
        self.btn_angle_minus5.setEnabled(False)
        top_bar.addWidget(self.btn_angle_minus5)

        self.btn_angle_minus1 = QPushButton("◀ -1°")
        self.btn_angle_minus1.clicked.connect(lambda: self.change_angle(-1))
        self.btn_angle_minus1.setEnabled(False)
        top_bar.addWidget(self.btn_angle_minus1)

        self.spin_angle = QSpinBox()
        self.spin_angle.setRange(0, 360)
        self.spin_angle.setValue(0)
        self.spin_angle.setSuffix("°")
        self.spin_angle.valueChanged.connect(self.on_angle_changed)
        self.spin_angle.setEnabled(False)
        top_bar.addWidget(self.spin_angle)

        self.btn_angle_plus1 = QPushButton("+1° ▶")
        self.btn_angle_plus1.clicked.connect(lambda: self.change_angle(1))
        self.btn_angle_plus1.setEnabled(False)
        top_bar.addWidget(self.btn_angle_plus1)

        self.btn_angle_plus5 = QPushButton("+5° ▶")
        self.btn_angle_plus5.clicked.connect(lambda: self.change_angle(5))
        self.btn_angle_plus5.setEnabled(False)
        top_bar.addWidget(self.btn_angle_plus5)

        # Concave Hull Ratio Control
        lbl_ratio = QLabel("Hull Ratio:")
        lbl_ratio.setStyleSheet("font-weight: bold; color: #234c2c; margin-left: 5px;")
        top_bar.addWidget(lbl_ratio)

        self.spin_ratio = QDoubleSpinBox()
        self.spin_ratio.setRange(0.01, 0.25)
        self.spin_ratio.setSingleStep(0.01)
        self.spin_ratio.setValue(0.03) # Default 0.03 for beautiful curved rim
        self.spin_ratio.valueChanged.connect(self.run_pipeline)
        self.spin_ratio.setEnabled(False)
        top_bar.addWidget(self.spin_ratio)

        # Lasso Handle Selection Button
        self.btn_lasso = QPushButton("✂️ Lasso Handle")
        self.btn_lasso.setObjectName("btnLasso")
        self.btn_lasso.setCheckable(True)
        self.btn_lasso.clicked.connect(self.toggle_lasso)
        self.btn_lasso.setEnabled(False)
        top_bar.addWidget(self.btn_lasso)

        self.btn_clear_lasso = QPushButton("Clear Handle")
        self.btn_clear_lasso.clicked.connect(self.clear_lasso)
        self.btn_clear_lasso.setEnabled(False)
        top_bar.addWidget(self.btn_clear_lasso)

        self.btn_save_img = QPushButton("Save Image")
        self.btn_save_img.clicked.connect(self.save_current_image)
        self.btn_save_img.setEnabled(False)
        top_bar.addWidget(self.btn_save_img)

        self.lbl_status = QLabel("Ready. Load a points file to begin.")
        self.lbl_status.setStyleSheet("font-weight: bold; font-size: 10pt; color: #1b4b24; padding: 4px 10px; background: #e3f5e6; border-radius: 4px;")
        top_bar.addWidget(self.lbl_status, stretch=1)

        main_layout.addWidget(top_frame, stretch=0)

        # ---------------------------------------------------------
        # TABS WIDGET
        # ---------------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # TAB 1: Final Pottery Scheme
        self.tab_final = QWidget()
        vbox_final = QVBoxLayout(self.tab_final)
        vbox_final.setContentsMargins(8, 8, 8, 8)
        vbox_final.setSpacing(4)

        self.fig_final = Figure(facecolor='white')
        self.canvas_final = FigureCanvas(self.fig_final)
        self.canvas_final.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar_final = NavigationToolbar2QT(self.canvas_final, self.tab_final)
        vbox_final.addWidget(self.toolbar_final)
        vbox_final.addWidget(self.canvas_final, stretch=1)

        self.ax_final = self.fig_final.add_subplot(111)
        self.tabs.addTab(self.tab_final, "🏺 Final Scheme (Right Side Profile)")

        # TAB 2: Step-by-Step Inspector
        self.tab_step = QWidget()
        vbox_step = QVBoxLayout(self.tab_step)
        vbox_step.setContentsMargins(8, 8, 8, 8)
        vbox_step.setSpacing(6)

        step_ctrl = QHBoxLayout()
        self.btn_prev_step = QPushButton("◀ Previous Step")
        self.btn_prev_step.clicked.connect(self.prev_step)
        step_ctrl.addWidget(self.btn_prev_step)

        self.combo_step = QComboBox()
        self.combo_step.addItems([
            "Step 1: Raw Points & Lasso Handle Selection",
            "Step 2: Profile Boundary (Concave Hull)",
            "Step 3: Outer / Inner Wall Splitting",
            "Step 4: Automatic Thickness Measurement",
            "Step 5: Inner Wall Offset & Base Floor Clip",
            "Step 6: Solid Polygon Topology Assembly"
        ])
        self.combo_step.currentIndexChanged.connect(self.render_selected_step)
        step_ctrl.addWidget(self.combo_step, stretch=1)

        self.btn_next_step = QPushButton("Next Step ▶")
        self.btn_next_step.clicked.connect(self.next_step)
        step_ctrl.addWidget(self.btn_next_step)

        self.lbl_step_info = QLabel("Step Info")
        self.lbl_step_info.setStyleSheet("font-weight: bold; color: #234c2c; background: #eaf6ec; padding: 6px 12px; border-radius: 4px;")
        step_ctrl.addWidget(self.lbl_step_info)

        vbox_step.addLayout(step_ctrl)

        self.fig_step = Figure(facecolor='white')
        self.canvas_step = FigureCanvas(self.fig_step)
        self.canvas_step.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar_step = NavigationToolbar2QT(self.canvas_step, self.tab_step)
        vbox_step.addWidget(self.toolbar_step)
        vbox_step.addWidget(self.canvas_step, stretch=1)

        self.ax_step = self.fig_step.add_subplot(111)
        self.tabs.addTab(self.tab_step, "🔍 Step-by-Step Inspector (Large View)")

        # TAB 3: All 6 Steps Comparative Grid
        self.tab_grid = QWidget()
        vbox_grid = QVBoxLayout(self.tab_grid)
        vbox_grid.setContentsMargins(8, 8, 8, 8)
        vbox_grid.setSpacing(4)

        self.fig_grid = Figure(facecolor='white')
        self.canvas_grid = FigureCanvas(self.fig_grid)
        self.canvas_grid.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.toolbar_grid = NavigationToolbar2QT(self.canvas_grid, self.tab_grid)
        vbox_grid.addWidget(self.toolbar_grid)
        vbox_grid.addWidget(self.canvas_grid, stretch=1)

        self.tabs.addTab(self.tab_grid, "📊 All 6 Steps (Overview Grid)")

        # TAB 4: Diagnostics Log
        self.tab_log = QWidget()
        vbox_log = QVBoxLayout(self.tab_log)
        vbox_log.setContentsMargins(12, 12, 12, 12)
        lbl_log_title = QLabel("Pipeline Execution & Calculation Log:")
        lbl_log_title.setStyleSheet("font-weight: bold; font-size: 11pt;")
        vbox_log.addWidget(lbl_log_title)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        vbox_log.addWidget(self.txt_log, stretch=1)

        self.tabs.addTab(self.tab_log, "📋 Diagnostics Log")

        main_layout.addWidget(self.tabs, stretch=1)

    def log(self, msg: str):
        self.txt_log.append(msg)
        print(msg)

    def change_angle(self, delta):
        cur = self.spin_angle.value()
        new_val = (cur + delta) % 360
        self.spin_angle.setValue(new_val)

    def on_angle_changed(self, val):
        if self.aligned_points is not None:
            self.run_pipeline()

    def prev_step(self):
        idx = self.combo_step.currentIndex()
        if idx > 0:
            self.combo_step.setCurrentIndex(idx - 1)

    def next_step(self):
        idx = self.combo_step.currentIndex()
        if idx < self.combo_step.count() - 1:
            self.combo_step.setCurrentIndex(idx + 1)

    def toggle_lasso(self):
        if self.btn_lasso.isChecked():
            self.tabs.setCurrentIndex(1)
            self.combo_step.setCurrentIndex(0)
            self.btn_lasso.setText("Drawing Lasso (Click & Drag)")
            self.lasso_active = True
            self.lasso_selector = LassoSelector(self.ax_step, self.on_lasso_select)
            self.lbl_status.setText("Lasso Active: Drag mouse around handle points to reject them.")
        else:
            self.btn_lasso.setText("✂️ Lasso Handle")
            self.lasso_active = False
            if self.lasso_selector:
                self.lasso_selector.disconnect_events()
                self.lasso_selector = None

    def on_lasso_select(self, verts):
        if self.profile_2d is None or len(self.profile_2d) == 0:
            return

        p = Path(verts)
        ind = p.contains_points(self.profile_2d)
        num_selected = int(np.sum(ind))

        if num_selected > 0:
            if self.handle_mask is None:
                self.handle_mask = ind
            else:
                self.handle_mask = self.handle_mask | ind

            self.log(f"Lasso marked {num_selected} points as handle! Total rejected: {int(np.sum(self.handle_mask))}")
            self.btn_clear_lasso.setEnabled(True)
            self.run_pipeline()
        else:
            self.log("Lasso did not enclose any points.")

    def clear_lasso(self):
        self.handle_mask = None
        self.btn_clear_lasso.setEnabled(False)
        self.log("Cleared handle selection. All vessel points restored.")
        self.run_pipeline()

    def load_points_file(self, file_path=None):
        if not file_path or not isinstance(file_path, str):
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Open Points File", "", "Points Files (*.txt *.json);;All Files (*)"
            )
        if not file_path:
            return

        self.points_file_path = file_path
        self.handle_mask = None
        self.btn_clear_lasso.setEnabled(False)
        self.txt_log.clear()
        self.log(f"Loading points file: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.points_data = pottery_processor.parse_points_data(content)
            self.log("Parsed Parameters:")
            self.log(f"  - STL File: {self.points_data.get('stl_path', 'None')}")
            self.log(f"  - Profile Angle: {self.points_data.get('profile_angle', 0)} deg")
            self.log(f"  - Vessel Type: {self.points_data.get('vessel_type', 'Sherd')}")
            self.log(f"  - Is Flipped: {self.points_data.get('is_flipped', False)}")
            self.log(f"  - Base Points: {len(self.points_data['base_points']) if self.points_data.get('base_points') is not None else 0}")
            self.log(f"  - Rim Points: {len(self.points_data['rim_points']) if self.points_data.get('rim_points') is not None else 0}")

            # Update Angle Spinbox
            init_angle = int(self.points_data.get('profile_angle', 0))
            self.spin_angle.blockSignals(True)
            self.spin_angle.setValue(init_angle)
            self.spin_angle.blockSignals(False)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to parse points file:\n{e}")
            return

        stl_path = self.points_data.get('stl_path', '')
        if stl_path and os.path.exists(stl_path):
            self.log(f"Found associated STL file: {stl_path}")
            self.stl_file_path = stl_path
            self._load_mesh_and_process()
        else:
            self.log("STL path not found or does not exist on disk. Please select the STL file.")
            QMessageBox.information(
                self, "Select STL",
                f"STL file specified in points file was not found:\n'{stl_path}'\nPlease select the STL file."
            )
            self.load_stl_file()

    def load_stl_file(self, file_path=None):
        if not file_path or not isinstance(file_path, str):
            file_path, _ = QFileDialog.getOpenFileName(self, "Open STL File", "", "STL Files (*.stl)")
        if not file_path:
            return
        self.stl_file_path = file_path
        self.log(f"Selected STL file: {file_path}")
        self._load_mesh_and_process()

    def _load_mesh_and_process(self):
        if not self.stl_file_path or not os.path.exists(self.stl_file_path):
            return
        try:
            self.log("Loading 3D STL mesh...")
            mesh = trimesh.load(self.stl_file_path)
            if isinstance(mesh, trimesh.Scene):
                mesh = mesh.dump(concatenate=True)
            self.raw_mesh_points = mesh.vertices
            self.log(f"Loaded mesh with {len(self.raw_mesh_points):,} vertices.")

            # Enable controls
            self.btn_angle_minus5.setEnabled(True)
            self.btn_angle_minus1.setEnabled(True)
            self.spin_angle.setEnabled(True)
            self.btn_angle_plus1.setEnabled(True)
            self.btn_angle_plus5.setEnabled(True)
            self.spin_ratio.setEnabled(True)
            self.btn_lasso.setEnabled(True)

            self.run_pipeline()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load STL mesh:\n{e}")

    def run_pipeline(self):
        if self.raw_mesh_points is None:
            return

        # 1. Alignment
        aligned = self.raw_mesh_points.copy()
        if self.points_data and self.points_data.get('base_points') is not None and len(self.points_data['base_points']) == 3:
            p1, p2, p3 = self.points_data['base_points']
            aligned = pottery_processor.align_by_3_points(aligned, p1, p2, p3)

        if self.points_data and self.points_data.get('is_flipped', False):
            aligned[:, 2] = -aligned[:, 2]

        self.aligned_points = aligned

        # 2. Rim Circle & Center
        xc, yc, r = 0.0, 0.0, 0.0
        if self.points_data and self.points_data.get('rim_points') is not None and len(self.points_data['rim_points']) == 3:
            p1, p2, p3 = self.points_data['rim_points']
            try:
                c, r, n = pottery_processor.circle_from_3_points_3d(p1, p2, p3)
                xc, yc = c[0], c[1]
            except Exception as e:
                self.log(f"Error fitting 3D rim: {e}")
        elif self.points_data and self.points_data.get('rim_fit') is not None:
            rf = self.points_data['rim_fit']
            c = rf.get('center', [0, 0, 0])
            xc, yc = c[0], c[1]
            r = rf.get('radius', 0.0)
        else:
            zmax = self.aligned_points[:, 2].max()
            top_pts = pottery_processor.extract_horizontal_slice(self.aligned_points, zmax - 5.0, thickness=5.0)
            if len(top_pts) >= 10:
                xc, yc, r = pottery_processor.fit_circle_2d(top_pts[:, :2])
            else:
                xc, yc, r = 0.0, 0.0, 50.0

        self.rim_fit_info = (xc, yc, r)

        # 3. Extract 2D Profile Slice at current SpinBox angle
        angle = self.spin_angle.value()
        profile_2d = pottery_processor.extract_profile(self.aligned_points, xc, yc, angle, thickness=2.0, side='right')

        if len(profile_2d) < 10:
            self.log(f"ERROR: Slice at angle {angle}° has fewer than 10 points.")
            return

        self.profile_2d = profile_2d

        # 4. Run Pipeline with Hull Ratio & Lasso
        ratio = self.spin_ratio.value()
        solid_poly, diag, err = run_6step_pipeline_v2(profile_2d, handle_mask=self.handle_mask, hull_ratio=ratio)

        self.solid_poly = solid_poly
        self.diag = diag

        if err:
            self.log(f"Pipeline issue: {err}")
            self.lbl_status.setText(f"Issue: {err}")
        else:
            thick = diag.get('measured_thickness', 0.0)
            diam_cm = (r * 2.0 / 10.0) if r > 0 else (profile_2d[:, 0].max() * 2.0 / 10.0)
            has_handle = self.handle_mask is not None and np.any(self.handle_mask)
            handle_str = f" | Handle: {int(np.sum(self.handle_mask))} pts" if has_handle else ""
            self.lbl_status.setText(f"Success! Thickness: {thick:.1f}mm | Angle: {angle}° | Rim Diam: {diam_cm:.1f}cm | Ratio: {ratio}{handle_str}")

        # 5. Render Views
        self.render_final_view()
        self.render_selected_step()
        self.render_grid_view()
        self.btn_save_img.setEnabled(True)

    def render_final_view(self):
        self.ax_final.clear()

        if self.profile_2d is None or len(self.profile_2d) == 0:
            self.canvas_final.draw()
            return

        z_min = self.profile_2d[:, 1].min()
        z_max = self.profile_2d[:, 1].max()
        xc, yc, r = self.rim_fit_info

        # Render solid black polygon
        if self.solid_poly is not None and not self.solid_poly.is_empty:
            polys = [self.solid_poly] if self.solid_poly.geom_type == 'Polygon' else (
                list(self.solid_poly.geoms) if self.solid_poly.geom_type == 'MultiPolygon' else []
            )
            for poly in polys:
                x, y = poly.exterior.xy
                self.ax_final.fill(x, y, color='black')
                self.ax_final.plot(x, y, 'k-', lw=1.0)
                for interior in poly.interiors:
                    x, y = interior.xy
                    self.ax_final.fill(x, y, color='white')
                    self.ax_final.plot(x, y, 'k-', lw=1.0)
        else:
            self.ax_final.plot(self.profile_2d[:, 0], self.profile_2d[:, 1], 'k.', markersize=2)

        # Symmetry Axis line at X=0
        self.ax_final.plot([0, 0], [z_min, z_max], 'k-.', lw=1.2)

        # Top Rim reference line
        max_x = self.profile_2d[:, 0].max()
        self.ax_final.plot([0, max_x], [z_max, z_max], 'k-', lw=1.2)

        # Text labels
        thick = self.diag.get('measured_thickness', 0.0)
        diam_cm = (r * 2.0 / 10.0) if r > 0 else (max_x * 2.0 / 10.0)
        self.ax_final.text(max_x, z_max + (z_max - z_min) * 0.03,
                           f"Rim Diam: {diam_cm:.1f} cm  |  Thickness: {thick:.1f} mm",
                           ha='right', va='bottom', fontsize=12, fontweight='bold')

        # 10cm Scale Bar
        bar_width = 100.0 # 100 mm = 10 cm
        bar_x = 0.0
        bar_y = z_min - (z_max - z_min) * 0.10
        bar_h = max((z_max - z_min) * 0.02, 2.0)

        for i in range(10):
            color = 'k' if i % 2 == 0 else 'w'
            rect = patches.Rectangle((bar_x + i * 10, bar_y), 10, bar_h, facecolor=color, edgecolor='k', lw=1.0)
            self.ax_final.add_patch(rect)

        self.ax_final.text(bar_x, bar_y - bar_h * 1.8, "0", ha='center', fontsize=11, fontweight='bold')
        self.ax_final.text(bar_x + bar_width, bar_y - bar_h * 1.8, "10 cm", ha='center', fontsize=11, fontweight='bold')

        self.ax_final.set_aspect('equal')
        self.ax_final.set_xlim(-15, max_x * 1.2 + 15)
        self.ax_final.set_ylim(bar_y - bar_h * 4.5, z_max + (z_max - z_min) * 0.12)
        self.ax_final.axis('off')

        self.canvas_final.draw()

    def render_selected_step(self):
        """Renders a single step in giant full-screen resolution in Tab 2"""
        self.ax_step.clear()
        step_idx = self.combo_step.currentIndex()

        if not self.diag:
            self.canvas_step.draw()
            return

        z_min = self.diag.get('z_min', 0)
        z_max = self.diag.get('z_max', 100)

        if step_idx == 0:
            # Step 1: Raw Points & Lasso Handle Selection
            raw = self.diag.get('raw_points', np.empty((0, 2)))
            cln = self.diag.get('cleaned_points', np.empty((0, 2)))
            rej = self.diag.get('rejected_points', np.empty((0, 2)))

            if len(rej) > 0:
                self.ax_step.plot(rej[:, 0], rej[:, 1], 'r.', markersize=5, label=f'Lassoed Handle ({len(rej)} pts)')
            self.ax_step.plot(cln[:, 0], cln[:, 1], 'b.', markersize=3, label=f'Vessel Body ({len(cln)} pts)')
            self.ax_step.axvline(0, color='k', linestyle='-.', lw=1, label='Symmetry Axis (X=0)')

            info = f"Total Points: {len(raw)} | Body Kept: {len(cln)} | Handle Lassoed: {len(rej)}"
            self.lbl_step_info.setText(info)
            self.ax_step.set_title("Step 1: Raw 2D Points (Use '✂️ Lasso Handle' to select handle areas)", fontsize=12, fontweight='bold')

        elif step_idx == 1:
            # Step 2: Concave Hull
            coords = self.diag.get('coords', np.empty((0, 2)))
            cln = self.diag.get('cleaned_points', np.empty((0, 2)))
            ratio = self.spin_ratio.value()

            self.ax_step.plot(cln[:, 0], cln[:, 1], '.', color='#b0c8d8', markersize=2, label='Points')
            if len(coords) > 0:
                self.ax_step.plot(coords[:, 0], coords[:, 1], 'g-', lw=2.5, label=f'Concave Hull (ratio={ratio})')
                self.ax_step.plot(coords[:, 0], coords[:, 1], 'ko', markersize=4, label=f'Hull Vertices ({len(coords)})')
            self.ax_step.axvline(0, color='k', linestyle='-.', lw=1)

            self.lbl_step_info.setText(f"Concave Hull vertices: {len(coords)} | Ratio: {ratio}")
            self.ax_step.set_title(f"Step 2: Profile Boundary Extraction via Concave Hull (ratio={ratio})", fontsize=12, fontweight='bold')

        elif step_idx == 2:
            # Step 3: Outer / Inner Split
            out_c = self.diag.get('outer_coords', np.empty((0, 2)))
            inn_c = self.diag.get('inner_coords', np.empty((0, 2)))

            if len(out_c) > 0:
                self.ax_step.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=3, label=f'Outer Wall Curve ({len(out_c)} pts)')
            if len(inn_c) > 0:
                self.ax_step.plot(inn_c[:, 0], inn_c[:, 1], 'r-', lw=3, label=f'Scanned Inner Wall ({len(inn_c)} pts)')

            if 'rim_peak' in self.diag:
                rx, rz = self.diag['rim_peak']
                self.ax_step.plot(rx, rz, 'm*', markersize=14, label=f'Rim Peak (Z={rz:.1f})')
            if 'bottom_center' in self.diag:
                bx, bz = self.diag['bottom_center']
                self.ax_step.plot(bx, bz, 'cD', markersize=10, label=f'Bottom Center (X={bx:.1f}, Z={bz:.1f})')

            self.ax_step.axvline(0, color='k', linestyle='-.', lw=1)
            self.lbl_step_info.setText(f"Outer Wall: {len(out_c)} pts | Scanned Inner Rim: {len(inn_c)} pts")
            self.ax_step.set_title("Step 3: Outer vs Scanned Inner Wall Splitting (Rim Peak & True Base Split)", fontsize=12, fontweight='bold')

        elif step_idx == 3:
            # Step 4: Thickness Measurement
            out_c = self.diag.get('outer_coords', np.empty((0, 2)))
            inn_c = self.diag.get('inner_coords', np.empty((0, 2)))
            s_pts = self.diag.get('inner_sampled_pts', np.empty((0, 2)))
            thick = self.diag.get('measured_thickness', 0.0)
            dists = self.diag.get('distances', [])

            if len(out_c) > 0:
                self.ax_step.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2, label='Outer Wall')
            if len(inn_c) > 0:
                self.ax_step.plot(inn_c[:, 0], inn_c[:, 1], 'k--', lw=1, alpha=0.5, label='Inner Rim Curve')
            if len(s_pts) > 0:
                self.ax_step.plot(s_pts[:, 0], s_pts[:, 1], 'ro', markersize=6, label=f'Sampled Points ({len(s_pts)})')

            if 'outer_line' in self.diag and len(s_pts) > 0:
                line = self.diag['outer_line']
                for pt in s_pts:
                    p = Point(pt)
                    proj_dist = line.project(p)
                    proj_pt = line.interpolate(proj_dist)
                    self.ax_step.plot([pt[0], proj_pt.x], [pt[1], proj_pt.y], 'r:', lw=1.5)

            dist_range = f"{min(dists):.1f} - {max(dists):.1f} mm" if len(dists) > 0 else "N/A"
            self.lbl_step_info.setText(f"Auto-Measured Thickness: {thick:.2f} mm (Median of {len(dists)} points, Range: {dist_range})")
            self.ax_step.set_title(f"Step 4: Automatic Perpendicular Thickness Measurement (Median = {thick:.2f} mm)", fontsize=12, fontweight='bold')

        elif step_idx == 4:
            # Step 5: Inner Wall Offset & Base Floor Clip
            out_c = self.diag.get('outer_coords', np.empty((0, 2)))
            off_c = self.diag.get('inner_offset_coords', np.empty((0, 2)))
            bz = self.diag.get('inner_base_z', 0.0)

            if len(out_c) > 0:
                self.ax_step.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2, label='Outer Wall')
            if len(off_c) > 0:
                self.ax_step.plot(off_c[:, 0], off_c[:, 1], 'g-', lw=3, label='Synthetic Inner Wall (Offset Curve)')

            self.ax_step.axhline(bz, color='orange', linestyle='--', lw=2, label=f'Base Floor Level (Z_min + thickness = {bz:.1f} mm)')
            self.ax_step.axvline(0, color='k', linestyle='-.', lw=1)

            thick = self.diag.get('measured_thickness', 0.0)
            self.lbl_step_info.setText(f"Offset Distance: {thick:.2f} mm inwards | Inner Base Cutoff Z: {bz:.1f} mm")
            self.ax_step.set_title("Step 5: Synthetic Inner Wall Offset (Shapely) & Flat Base Floor Clipping", fontsize=12, fontweight='bold')

        elif step_idx == 5:
            # Step 6: Solid Polygon Assembly
            sp = self.diag.get('solid_poly')
            ring = self.diag.get('ring', np.empty((0, 2)))

            if sp is not None and not sp.is_empty:
                polys = [sp] if sp.geom_type == 'Polygon' else (list(sp.geoms) if sp.geom_type == 'MultiPolygon' else [])
                for p in polys:
                    x, y = p.exterior.xy
                    self.ax_step.fill(x, y, color='#222222', alpha=0.85, label='Solid Ceramic Vessel Body')
                    self.ax_step.plot(x, y, 'k-', lw=1.5)

            if len(ring) > 0:
                self.ax_step.plot(ring[:, 0], ring[:, 1], 'm--', lw=1, alpha=0.6, label=f'Assembly Ring Loop ({len(ring)} nodes)')

            self.ax_step.axvline(0, color='gray', linestyle='-.', lw=1.5, label='Symmetry Axis (X=0)')
            area = sp.area if sp else 0
            self.lbl_step_info.setText(f"Polygon Area: {area:.1f} mm^2 | Topology buffer(0): Valid & Clean")
            self.ax_step.set_title("Step 6: Topology Assembly & Flat Base Closure (buffer(0) validated)", fontsize=12, fontweight='bold')

        self.ax_step.set_aspect('equal')
        self.ax_step.grid(True, linestyle=':', alpha=0.6)
        self.ax_step.legend(loc='upper right', fontsize=10)
        self.canvas_step.draw()

    def render_grid_view(self):
        """Renders all 6 steps in an overview grid in Tab 3"""
        self.fig_grid.clear()
        axes = self.fig_grid.subplots(2, 3)

        # 1. Raw Points & Handle
        ax1 = axes[0, 0]
        ax1.set_title("1. Raw Points & Handle", fontsize=10, fontweight='bold')
        rej = self.diag.get('rejected_points', np.empty((0, 2)))
        cln = self.diag.get('cleaned_points', np.empty((0, 2)))
        if len(rej) > 0: ax1.plot(rej[:, 0], rej[:, 1], 'r.', markersize=2, label='Lassoed Handle')
        if len(cln) > 0: ax1.plot(cln[:, 0], cln[:, 1], 'b.', markersize=2, label='Vessel Body')
        ax1.set_aspect('equal')
        ax1.legend(loc='upper right', fontsize=8)

        # 2. Concave Hull
        ax2 = axes[0, 1]
        ratio = self.spin_ratio.value()
        ax2.set_title(f"2. Concave Hull (ratio={ratio})", fontsize=10, fontweight='bold')
        coords = self.diag.get('coords', np.empty((0, 2)))
        if len(coords) > 0:
            ax2.plot(coords[:, 0], coords[:, 1], 'g-', lw=2, label='Hull')
            ax2.plot(coords[:, 0], coords[:, 1], 'k.', markersize=3)
        ax2.set_aspect('equal')
        ax2.legend(loc='upper right', fontsize=8)

        # 3. Outer vs Inner Split
        ax3 = axes[0, 2]
        ax3.set_title("3. Outer vs Inner Split", fontsize=10, fontweight='bold')
        out_c = self.diag.get('outer_coords', np.empty((0, 2)))
        inn_c = self.diag.get('inner_coords', np.empty((0, 2)))
        if len(out_c) > 0: ax3.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=2, label='Outer')
        if len(inn_c) > 0: ax3.plot(inn_c[:, 0], inn_c[:, 1], 'r-', lw=2, label='Inner')
        if 'rim_peak' in self.diag: ax3.plot(self.diag['rim_peak'][0], self.diag['rim_peak'][1], 'm*', markersize=8)
        if 'bottom_center' in self.diag: ax3.plot(self.diag['bottom_center'][0], self.diag['bottom_center'][1], 'cD', markersize=6)
        ax3.set_aspect('equal')
        ax3.legend(loc='upper right', fontsize=8)

        # 4. Thickness
        ax4 = axes[1, 0]
        thick = self.diag.get('measured_thickness', 0.0)
        ax4.set_title(f"4. Thickness: {thick:.2f} mm", fontsize=10, fontweight='bold')
        if len(out_c) > 0: ax4.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=1.5)
        s_pts = self.diag.get('inner_sampled_pts', np.empty((0, 2)))
        if len(s_pts) > 0: ax4.plot(s_pts[:, 0], s_pts[:, 1], 'ro', markersize=4, label='Sampled')
        ax4.set_aspect('equal')
        ax4.legend(loc='upper right', fontsize=8)

        # 5. Offset & Base Floor Clip
        ax5 = axes[1, 1]
        ax5.set_title("5. Offset & Base Clip", fontsize=10, fontweight='bold')
        off_c = self.diag.get('inner_offset_coords', np.empty((0, 2)))
        bz = self.diag.get('inner_base_z', 0.0)
        if len(out_c) > 0: ax5.plot(out_c[:, 0], out_c[:, 1], 'b-', lw=1.5)
        if len(off_c) > 0: ax5.plot(off_c[:, 0], off_c[:, 1], 'g-', lw=2, label='Offset')
        ax5.axhline(bz, color='orange', linestyle='--', label='Floor')
        ax5.set_aspect('equal')
        ax5.legend(loc='upper right', fontsize=8)

        # 6. Solid Polygon Assembly
        ax6 = axes[1, 2]
        ax6.set_title("6. Solid Polygon Assembly", fontsize=10, fontweight='bold')
        sp = self.diag.get('solid_poly')
        if sp is not None and not sp.is_empty:
            polys = [sp] if sp.geom_type == 'Polygon' else (list(sp.geoms) if sp.geom_type == 'MultiPolygon' else [])
            for p in polys:
                x, y = p.exterior.xy
                ax6.fill(x, y, color='black', alpha=0.85)
                ax6.plot(x, y, 'k-', lw=1)
        ax6.axvline(0, color='gray', linestyle='-.')
        ax6.set_aspect('equal')

        for row in axes:
            for ax in row:
                ax.grid(True, linestyle=':', alpha=0.5)

        self.fig_grid.tight_layout()
        self.canvas_grid.draw()

    def save_current_image(self):
        current_tab = self.tabs.currentIndex()
        default_name = "profile_final_scheme.png" if current_tab == 0 else (
            f"profile_step_{self.combo_step.currentIndex()+1}.png" if current_tab == 1 else "profile_6steps_grid.png"
        )
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Image", default_name, "Images (*.png *.pdf)")
        if not file_path:
            return

        if current_tab == 0:
            self.fig_final.savefig(file_path, bbox_inches='tight', dpi=300)
        elif current_tab == 1:
            self.fig_step.savefig(file_path, bbox_inches='tight', dpi=300)
        else:
            self.fig_grid.savefig(file_path, bbox_inches='tight', dpi=300)

        QMessageBox.information(self, "Saved", f"Image saved successfully to:\n{file_path}")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ProfileTest2App()
    window.show()

    # Optional CLI auto-load
    if len(sys.argv) > 1:
        arg_path = sys.argv[1]
        if os.path.exists(arg_path):
            if arg_path.endswith('.stl'):
                window.load_stl_file(arg_path)
            else:
                window.load_points_file(arg_path)

    sys.exit(app.exec_())
