import sys
import os
import numpy as np
import trimesh
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QSlider, QTabWidget, QMessageBox, QComboBox)
from PyQt5.QtCore import Qt
import pyvista as pv
from pyvistaqt import QtInteractor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.widgets import LassoSelector
from matplotlib.path import Path

from shapely.geometry import LineString, Polygon, MultiPoint
from shapely import concave_hull
from shapely.validation import make_valid

import pottery_processor

class PotteryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Pottery Sherd Analysis")
        self.resize(1200, 800)
        
        self.points = None
        self.aligned_points = None
        self.stl_file_path = ""
        self.base_points = None
        self.rim_points = None
        self.rim_center_3d = None
        self.rim_normal = None
        self.is_flipped = False
        self.xc = 0.0
        self.yc = 0.0
        self.R = 0.0
        self.profile_2d = None
        self.facade_2d = None
        self.handle_sections = []
        self.picked_points = []
        
        self._apply_stylesheet()
        self._init_ui()
        
    def _apply_stylesheet(self):
        # A sleek, modern "light greens" variety theme
        style = """
        QMainWindow {
            background-color: #eef7f0;
        }
        QWidget {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
            font-size: 10pt;
            color: #1a3320;
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
        QPushButton:disabled {
            background-color: #f5fcf6;
            color: #b0c4b3;
            border: 2px solid #dbe8dd;
        }
        QComboBox {
            background-color: #ffffff;
            border: 2px solid #a3cfa9;
            border-radius: 6px;
            padding: 6px 10px;
            font-weight: bold;
            color: #2b5434;
        }
        QComboBox:hover {
            border-color: #7bc085;
        }
        QComboBox::drop-down {
            border: none;
            width: 30px;
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
            padding: 8px 20px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            color: #55755b;
            font-weight: bold;
        }
        QTabBar::tab:selected {
            background: #ffffff;
            border-bottom-color: #ffffff;
            color: #1a3320;
        }
        QTabBar::tab:hover:!selected {
            background: #e6f2e8;
        }
        QSlider::groove:horizontal {
            border: 1px solid #b8d9be;
            height: 6px;
            background: #e1efe3;
            border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #4caf50;
            border: 2px solid #ffffff;
            width: 16px;
            height: 16px;
            margin: -6px 0;
            border-radius: 8px;
        }
        QSlider::handle:horizontal:hover {
            background: #3d8c40;
        }
        QLabel {
            font-weight: bold;
            margin-top: 8px;
            margin-bottom: 2px;
            color: #2b5434;
        }
        """
        self.setStyleSheet(style)
        
    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        # Left Control Panel
        control_panel = QVBoxLayout()
        
        self.btn_load = QPushButton("1. Load STL")
        self.btn_load.clicked.connect(self.load_stl)
        control_panel.addWidget(self.btn_load)
        
        self.combo_type = QComboBox()
        self.combo_type.addItems(["Vessel Type: Sherd", "Vessel Type: Whole Vessel"])
        self.combo_type.setEnabled(False)
        self.combo_type.currentIndexChanged.connect(self.on_type_changed)
        control_panel.addWidget(self.combo_type)
        
        self.label_thickness = QLabel("Wall Thickness (Whole): 5mm")
        self.label_thickness.setVisible(False)
        control_panel.addWidget(self.label_thickness)
        self.slider_thickness = QSlider(Qt.Horizontal)
        self.slider_thickness.setRange(10, 200) # 1.0 to 20.0 mm
        self.slider_thickness.setValue(50) # 5.0 mm default
        self.slider_thickness.setVisible(False)
        self.slider_thickness.valueChanged.connect(self.update_profile)
        control_panel.addWidget(self.slider_thickness)
        
        self.label_cutoff = QLabel("Inner Base Cutoff Z: 10%")
        self.label_cutoff.setVisible(False)
        control_panel.addWidget(self.label_cutoff)
        self.slider_cutoff = QSlider(Qt.Horizontal)
        self.slider_cutoff.setRange(0, 100)
        self.slider_cutoff.setValue(10)
        self.slider_cutoff.setVisible(False)
        self.slider_cutoff.valueChanged.connect(self.update_profile)
        control_panel.addWidget(self.slider_cutoff)

        
        self.btn_align = QPushButton("2. Align (Pick 3 Points on Base/Rim)")
        self.btn_align.clicked.connect(self.start_alignment_picking)
        self.btn_align.setEnabled(False)
        control_panel.addWidget(self.btn_align)
        
        self.btn_flip = QPushButton("Flip Upside Down")
        self.btn_flip.clicked.connect(self.flip_upside_down)
        self.btn_flip.setEnabled(False)
        control_panel.addWidget(self.btn_flip)
        
        self.label_circle = QLabel("3. Circle Layer Extraction")
        control_panel.addWidget(self.label_circle)
        
        self.combo_layer = QComboBox()
        self.combo_layer.addItems(["Extract Top Layer (Rim is UP)", "Extract Bottom Layer (Base is UP)"])
        self.combo_layer.setEnabled(False)
        control_panel.addWidget(self.combo_layer)
        
        self.btn_extract_circle = QPushButton("Auto-Fit Circle (Horizontal)")
        self.btn_extract_circle.clicked.connect(self.extract_circle)
        self.btn_extract_circle.setEnabled(False)
        control_panel.addWidget(self.btn_extract_circle)
        
        self.btn_pick_rim_3d = QPushButton("Pick 3 Points on Rim (Tilted/3D)")
        self.btn_pick_rim_3d.clicked.connect(self.start_rim_picking)
        self.btn_pick_rim_3d.setEnabled(False)
        control_panel.addWidget(self.btn_pick_rim_3d)
        
        self.label_angle = QLabel("4. Profile Angle: 0")
        control_panel.addWidget(self.label_angle)
        
        self.slider_angle = QSlider(Qt.Horizontal)
        self.slider_angle.setRange(0, 360)
        self.slider_angle.setValue(0)
        self.slider_angle.setEnabled(False)
        self.slider_angle.valueChanged.connect(self.update_profile)
        control_panel.addWidget(self.slider_angle)
        
        self.btn_clean_handle = QPushButton("5. Enable Lasso (Clean Noise)")
        self.btn_clean_handle.clicked.connect(self.toggle_lasso)
        self.btn_clean_handle.setEnabled(False)
        control_panel.addWidget(self.btn_clean_handle)
        
        self.btn_lasso_handle = QPushButton("Lasso Handle (Generate Section)")
        self.btn_lasso_handle.clicked.connect(self.toggle_lasso_handle)
        self.btn_lasso_handle.setEnabled(False)
        control_panel.addWidget(self.btn_lasso_handle)
        
        self.btn_texture = QPushButton("6. Draw Texture Line")
        self.btn_texture.clicked.connect(self.toggle_texture_drawing)
        self.btn_texture.setEnabled(False)
        control_panel.addWidget(self.btn_texture)
        
        self.btn_save = QPushButton("7. Save Scheme Image")
        self.btn_save.clicked.connect(self.save_image)
        self.btn_save.setEnabled(False)
        control_panel.addWidget(self.btn_save)
        
        # Save & Load Picked Points & Profile Angle
        points_btn_layout = QHBoxLayout()
        self.btn_save_points = QPushButton("Save Points & Angle")
        self.btn_save_points.clicked.connect(self.save_points_and_angle)
        self.btn_save_points.setEnabled(False)
        points_btn_layout.addWidget(self.btn_save_points)
        
        self.btn_load_points = QPushButton("Load Points & Angle")
        self.btn_load_points.clicked.connect(self.load_points_and_angle)
        self.btn_load_points.setEnabled(True)
        points_btn_layout.addWidget(self.btn_load_points)
        
        control_panel.addLayout(points_btn_layout)
        
        control_panel.addStretch()
        
        # Right View Area
        self.tabs = QTabWidget()
        
        # 3D View Tab
        self.view_3d_widget = QWidget()
        v3d_layout = QVBoxLayout(self.view_3d_widget)
        self.plotter = QtInteractor(self.view_3d_widget)
        v3d_layout.addWidget(self.plotter.interactor)
        self.tabs.addTab(self.view_3d_widget, "3D View")
        
        # 2D View Tab
        self.view_2d_widget = QWidget()
        v2d_layout = QVBoxLayout(self.view_2d_widget)
        self.fig = Figure()
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)
        v2d_layout.addWidget(self.canvas)
        self.tabs.addTab(self.view_2d_widget, "2D Profile")
        
        main_layout.addLayout(control_panel, 1)
        main_layout.addWidget(self.tabs, 4)
        
        self.lasso = None
        self.lasso_mode = None
        self.drawing_texture = False
        self.texture_lines = []
        self.current_texture_line = None
        self.temp_texture_line = None
        self.canvas.mpl_connect('button_press_event', self.on_click_texture)
        self.canvas.mpl_connect('button_release_event', self.on_release_texture)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion_texture)

    def load_stl(self, file_path=None):
        if not file_path or not isinstance(file_path, str):
            file_path, _ = QFileDialog.getOpenFileName(self, "Open STL", "", "STL Files (*.stl)")
        if not file_path: return
        
        mesh = trimesh.load(file_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
            
        self.stl_file_path = file_path
        self.points = mesh.vertices
        self.aligned_points = self.points.copy()
        self.base_points = None
        self.rim_points = None
        self.rim_center_3d = None
        self.rim_normal = None
        self.is_flipped = False
        
        self.update_3d_view()
        self.btn_align.setEnabled(True)
        self.btn_flip.setEnabled(True)
        self.combo_layer.setEnabled(True)
        self.btn_extract_circle.setEnabled(True)
        self.btn_pick_rim_3d.setEnabled(True)
        self.combo_type.setEnabled(True)
        self.btn_save_points.setEnabled(True)
        self.btn_load_points.setEnabled(True)
        
    def update_3d_view(self, show_points=None):
        self.plotter.clear()
        pts = show_points if show_points is not None else self.aligned_points
        cloud = pv.PolyData(pts)
        self.plotter.add_mesh(cloud, color='lightblue', point_size=2)
        self.plotter.add_axes()
        self.plotter.reset_camera()
        
    def start_alignment_picking(self):
        self.picking_mode = 'align'
        self.picked_points = []
        try:
            self.plotter.disable_picking()
        except:
            pass
            
        self.plotter.clear_button_widgets()
        self.plotter.add_text("Click (or press 'P') 3 points on the BASE.", position='upper_left', name='pick_msg')
        self._setup_point_picking()
        
    def start_rim_picking(self):
        self.picking_mode = 'rim_3d'
        self.picked_points = []
        try:
            self.plotter.disable_picking()
        except:
            pass
            
        self.plotter.clear_button_widgets()
        self.plotter.add_text("Click (or press 'P') 3 points on the RIM.", position='upper_left', name='pick_msg')
        self._setup_point_picking()
        
    def _setup_point_picking(self):
        def callback(*args):
            try:
                # Handle different PyVista versions which might pass (mesh, idx) or just (point)
                if len(args) == 2:
                    mesh, idx = args
                    pt = mesh.points[idx]
                else:
                    pt = np.array(args[0])
                
                self.picked_points.append(pt)
                self.plotter.add_mesh(pv.PolyData([pt]), color='red', point_size=10, name=f'pt_{len(self.picked_points)}')
                
                if len(self.picked_points) == 3:
                    self.plotter.remove_actor('pick_msg')
                    try:
                        self.plotter.disable_picking()
                    except:
                        pass
                    if self.picking_mode == 'align':
                        self.align_cloud()
                    elif self.picking_mode == 'rim_3d':
                        self.calc_rim_3d()
            except Exception as e:
                print(f"Picking error: {e}")
                
        # Enable left_clicking so the user doesn't have to press 'P'
        self.plotter.enable_point_picking(callback=callback, show_message=False, color='red', point_size=10, left_clicking=True)

    def align_cloud(self):
        p1, p2, p3 = self.picked_points
        self.base_points = np.array([np.array(p) for p in self.picked_points])
        self.aligned_points = pottery_processor.align_by_3_points(self.aligned_points, p1, p2, p3)
        self.update_3d_view()
        QMessageBox.information(self, "Aligned", "Cloud aligned to Z axis. Use Flip if upside down.")
        self.picked_points = []
        self.btn_save_points.setEnabled(True)
        
    def calc_rim_3d(self):
        p1, p2, p3 = self.picked_points
        try:
            c, r, n = pottery_processor.circle_from_3_points_3d(p1, p2, p3)
            self.xc, self.yc = c[0], c[1]
            self.R = r
            self.rim_center_3d = c
            self.rim_normal = n
            self.rim_points = np.array([np.array(p) for p in self.picked_points])
            
            self.plotter.add_mesh(pv.PolyData([c]), color='green', point_size=15, name='rim_center')
            QMessageBox.information(self, "Rim Extracted", f"3D Rim configured!\nDiameter: {(r*2/10.0):.1f} cm")
            
            self.slider_angle.setEnabled(True)
            self.btn_clean_handle.setEnabled(True)
            self.btn_lasso_handle.setEnabled(True)
            self.btn_texture.setEnabled(True)
            self.btn_save.setEnabled(True)
            self.btn_save_points.setEnabled(True)
            self.update_profile()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to compute 3D circle: {e}")
        self.picked_points = []
        
    def flip_upside_down(self):
        if self.aligned_points is not None:
            self.aligned_points[:, 2] = -self.aligned_points[:, 2]
            self.is_flipped = not getattr(self, 'is_flipped', False)
            if self.rim_points is not None:
                self.rim_points[:, 2] = -self.rim_points[:, 2]
            if hasattr(self, 'rim_center_3d') and self.rim_center_3d is not None:
                self.rim_center_3d[2] = -self.rim_center_3d[2]
            if hasattr(self, 'rim_normal') and self.rim_normal is not None:
                self.rim_normal[2] = -self.rim_normal[2]
            self.update_3d_view()
            if self.profile_2d is not None:
                self.update_profile()
            
    def on_type_changed(self):
        is_whole = (self.combo_type.currentIndex() == 1)
        self.label_thickness.setVisible(is_whole)
        self.slider_thickness.setVisible(is_whole)
        self.label_cutoff.setVisible(is_whole)
        self.slider_cutoff.setVisible(is_whole)
        self.update_profile()
        
    def extract_circle(self):
        if self.aligned_points is None: return
        
        self.rim_normal = None # Clear any previous 3D rim normal
        
        zmin, zmax = self.aligned_points[:, 2].min(), self.aligned_points[:, 2].max()
        if self.combo_layer.currentIndex() == 0:
            slice_z = zmax - 5.0 
        else:
            slice_z = zmin + 5.0
            
        top_pts = pottery_processor.extract_horizontal_slice(self.aligned_points, slice_z, thickness=5.0)
        
        if len(top_pts) < 10:
            QMessageBox.warning(self, "Error", "Not enough points in layer to fit circle.")
            return
            
        self.xc, self.yc, self.R = pottery_processor.fit_circle_2d(top_pts[:, :2])
        self.rim_center_3d = np.array([self.xc, self.yc, slice_z])
        self.rim_points = None
        
        self.tabs.setCurrentIndex(1)
        self.ax.clear()
        self.ax.plot(top_pts[:, 0], top_pts[:, 1], '.', label='Top Layer Points')
        theta = np.linspace(0, 2*np.pi, 100)
        x_fit = self.xc + self.R * np.cos(theta)
        y_fit = self.yc + self.R * np.sin(theta)
        self.ax.plot(x_fit, y_fit, 'r-', label='Fitted Circle')
        self.ax.plot(self.xc, self.yc, 'rx')
        self.ax.set_aspect('equal')
        self.ax.legend()
        self.ax.set_title("Circle Fit (Top View)")
        self.canvas.draw()
        
        self.slider_angle.setEnabled(True)
        self.slider_angle.setValue(0)
        self.btn_clean_handle.setEnabled(True)
        self.btn_lasso_handle.setEnabled(True)
        self.btn_texture.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_save_points.setEnabled(True)
        self.update_profile()

    def update_profile(self):
        if self.aligned_points is None: return
        angle = self.slider_angle.value()
        self.label_angle.setText(f"4. Profile Angle: {angle}")
        
        self.profile_2d = pottery_processor.extract_profile(self.aligned_points, self.xc, self.yc, angle, thickness=2.0, side='right')
        self.facade_2d = pottery_processor.extract_facade_projection(self.aligned_points, self.xc, self.yc, angle)
        self.texture_lines = [] # Reset texture lines when angle changes
        self.handle_sections = [] # Reset handle sections
        
        self.redraw_profile()
        
    def redraw_profile(self):
        self.ax.clear()
        if self.profile_2d is None or len(self.profile_2d) == 0:
            self.canvas.draw()
            return
            
        # 1. Right side: Fill the profile (Cross-section)
        right_profile = self.profile_2d.copy()
        facade_pts = self.facade_2d.copy() if self.facade_2d is not None else np.empty((0, 2))
        is_whole_vessel = (self.combo_type.currentIndex() == 1)
        
        # Use global zmin/zmax for calculations
        zmin_global = self.profile_2d[:, 1].min()
        zmax_global = self.profile_2d[:, 1].max()
        if len(facade_pts) > 0:
            zmin_global = min(zmin_global, facade_pts[:, 1].min())
            zmax_global = max(zmax_global, facade_pts[:, 1].max())
            
        # Generate the filled profile shape via pottery_processor
        final_shape = None
        try:
            if is_whole_vessel:
                # Pass slider value as fallback (slider is in tenths of mm)
                slider_thickness = self.slider_thickness.value() / 10.0
                final_shape, computed_thickness, error_msg = pottery_processor.generate_whole_vessel_profile(
                    right_profile, fallback_thickness=slider_thickness)
                if error_msg:
                    print(f"Whole Vessel error: {error_msg}")
                    QMessageBox.warning(self, "Whole Vessel Profile", 
                                       f"Profile generation issue:\n{error_msg}\n\n"
                                       f"Showing raw points as fallback.")
                if computed_thickness > 0:
                    self.label_thickness.setText(f"Wall Thickness (Auto): {computed_thickness:.1f}mm")
            else:
                final_shape = pottery_processor.generate_sherd_profile(right_profile)
        except Exception as e:
            print("Profile generation error:", e)

        # Render the filled shape (with None guard)
        if final_shape is not None and not final_shape.is_empty:
            try:
                polys = [final_shape] if final_shape.geom_type == 'Polygon' else (
                    list(final_shape.geoms) if final_shape.geom_type == 'MultiPolygon' else [])
                for poly in polys:
                    x, y = poly.exterior.xy
                    self.ax.fill(x, y, color='black')
                    self.ax.plot(x, y, 'k-', lw=0.5)
                    for interior in poly.interiors:
                        x, y = interior.xy
                        self.ax.fill(x, y, color='white')
                        self.ax.plot(x, y, 'k-', lw=0.5)
            except Exception as e:
                print("Shape rendering error:", e)
                self.ax.plot(right_profile[:, 0], right_profile[:, 1], 'k.', markersize=2)
        else:
            # Fallback: draw raw point cloud if shape generation failed
            self.ax.plot(right_profile[:, 0], right_profile[:, 1], 'k.', markersize=2)

        # Calculate Rim Line (Connecting Line) and Center Z
        z_center = zmax_global
        left_peak_x, right_peak_x = 0, 0
        left_peak_z, right_peak_z = zmax_global, zmax_global
        rim_diameter_cm = 0
        
        def rim_z_func(x): return zmax_global
        
        if len(self.profile_2d) > 0 and len(facade_pts) > 0:
            if hasattr(self, 'rim_normal') and self.rim_normal is not None:
                cz = self.rim_center_3d[2]
                nx, ny, nz = self.rim_normal
                angle_rad = np.radians(self.slider_angle.value())
                cos_t = np.cos(angle_rad)
                sin_t = np.sin(angle_rad)
                
                if abs(nz) > 1e-6:
                    def rim_z(x_2d):
                        return cz - (nx * cos_t + ny * sin_t) * x_2d / nz
                    rim_z_func = rim_z
                    
                    left_peak_x = -self.R
                    right_peak_x = self.R
                    left_peak_z = rim_z(left_peak_x)
                    right_peak_z = rim_z(right_peak_x)
                    rim_diameter_cm = (self.R * 2.0) / 10.0
            else:
                # Fallback to connecting outer 2D points (user requested exact connection)
                right_peak_idx = np.argmax(self.profile_2d[:, 1])
                right_peak_x = self.profile_2d[right_peak_idx, 0]
                right_peak_z = self.profile_2d[right_peak_idx, 1]
                
                # Find leftmost outer edge in the top 20% of the vessel
                top_threshold = zmax_global - (zmax_global - zmin_global) * 0.2
                top_facade = facade_pts[facade_pts[:, 1] > top_threshold]
                
                if len(top_facade) > 0:
                    left_peak_idx = np.argmin(top_facade[:, 0]) # Leftmost! Not highest!
                    left_peak_x = top_facade[left_peak_idx, 0]
                    left_peak_z = top_facade[left_peak_idx, 1]
                else:
                    left_peak_idx = np.argmax(facade_pts[:, 1])
                    left_peak_x = facade_pts[left_peak_idx, 0]
                    left_peak_z = facade_pts[left_peak_idx, 1]
                
                def rim_z(x_2d):
                    if right_peak_x == left_peak_x: return right_peak_z
                    return left_peak_z + (x_2d - left_peak_x) * (right_peak_z - left_peak_z) / (right_peak_x - left_peak_x)
                rim_z_func = rim_z
                    
                if hasattr(self, 'R') and self.R > 0:
                    rim_diameter_cm = (self.R * 2.0) / 10.0
                else:
                    rim_diameter_cm = (right_peak_x - left_peak_x) / 10.0

            z_center = rim_z(0)
            
            # Draw rim line
            self.ax.plot([left_peak_x, right_peak_x], [left_peak_z, right_peak_z], 'k-', lw=1.2)
            
            # Draw Rim Text
            text_z = max(left_peak_z, right_peak_z)
            self.ax.text(right_peak_x, text_z + (zmax_global - zmin_global) * 0.02, 
                         f"Rim Diameter: {rim_diameter_cm:.1f} cm", 
                         ha='right', va='bottom', fontsize=10, color='black')
        
        # Draw center line (only up to the rim line!)
        self.ax.plot([0, 0], [zmin_global, z_center], 'k-.', lw=1)
        
        # 2. Left side: External Boundary Line (Facade) with Clipping!
        if len(facade_pts) > 3:
            try:
                facade_rounded = np.round(facade_pts * 1.0) / 1.0
                facade_unique = np.unique(facade_rounded, axis=0)
                
                mp = MultiPoint(facade_unique)
                hull = concave_hull(mp, ratio=0.1, allow_holes=True)
                polys = [hull] if hull.geom_type == 'Polygon' else (list(hull.geoms) if hull.geom_type == 'MultiPolygon' else [])
                
                # Clip box: Excludes the center line (stops at x=-0.1) and top line (stops at rim_z)
                min_x = facade_pts[:, 0].min() - 100.0
                z_bottom = zmin_global - 1000.0
                top_left_z = rim_z_func(min_x)
                # Prevent self-intersecting bowtie polygon
                if top_left_z <= z_bottom:
                    top_left_z = z_bottom + 1.0
                
                clip_box = Polygon([
                    (min_x, z_bottom),
                    (-0.1, z_bottom),
                    (-0.1, rim_z_func(-0.1)),
                    (min_x, top_left_z)
                ])
                
                for poly in polys:
                    ext_line = LineString(poly.exterior.coords)
                    clipped_ext = ext_line.intersection(clip_box)
                    if clipped_ext.geom_type == 'LineString':
                        x, y = clipped_ext.xy
                        self.ax.plot(x, y, 'k-', lw=1.5)
                    elif clipped_ext.geom_type == 'MultiLineString':
                        for l in clipped_ext.geoms:
                            x, y = l.xy
                            self.ax.plot(x, y, 'k-', lw=1.5)
                            
                    for interior in poly.interiors:
                        int_line = LineString(interior.coords)
                        clipped_int = int_line.intersection(clip_box)
                        if clipped_int.geom_type == 'LineString':
                            x, y = clipped_int.xy
                            self.ax.plot(x, y, 'k-', lw=1.0)
                        elif clipped_int.geom_type == 'MultiLineString':
                            for l in clipped_int.geoms:
                                x, y = l.xy
                                self.ax.plot(x, y, 'k-', lw=1.0)
            except Exception as e:
                print("Facade hull error:", e)
                self.ax.plot(facade_pts[:, 0], facade_pts[:, 1], 'k.', markersize=0.5)
                
        # Draw Handle Sections
        for hs in self.handle_sections:
            hull = hs['hull']
            cx, cz = hs['cx'], hs['cz']
            self.ax.plot([cx, cx], [cz, hs['source_cz']], 'k--', lw=0.5)
            polys = [hull] if hull.geom_type == 'Polygon' else (list(hull.geoms) if hull.geom_type == 'MultiPolygon' else [])
            for poly in polys:
                x, y = poly.exterior.xy
                x = np.array(x) + cx
                y = np.array(y) + cz
                self.ax.fill(x, y, color='black')
                
        # Draw texture lines
        for line in self.texture_lines:
            self.ax.plot([line[0][0], line[1][0]], [line[0][1], line[1][1]], 'k-', lw=1.5)
        
        # Scale bar (10cm = 100 units)
        import matplotlib.patches as patches
        bar_width = 100
        bar_x = -bar_width / 2
        bar_y = zmin_global - (zmax_global - zmin_global) * 0.1
        bar_h = max((zmax_global - zmin_global) * 0.015, 1.0)
        
        for i in range(10):
            color = 'k' if i % 2 == 0 else 'w'
            rect = patches.Rectangle((bar_x + i*10, bar_y), 10, bar_h, facecolor=color, edgecolor='k', linewidth=1)
            self.ax.add_patch(rect)
            
        self.ax.text(bar_x, bar_y - bar_h*1.5, "0", ha='center', fontsize=12)
        self.ax.text(bar_x + 100, bar_y - bar_h*1.5, "10cm", ha='center', fontsize=12)
        
        self.ax.set_aspect('equal')
        
        max_abs_x = max(np.abs(right_profile[:, 0]).max(), np.abs(facade_pts[:, 0]).max() if len(facade_pts) > 0 else 0) * 1.1
        self.ax.set_xlim(-max_abs_x, max_abs_x)
        self.ax.set_ylim(bar_y - bar_h*4.0, zmax_global + (zmax_global - zmin_global)*0.1)
        
        self.ax.axis('off')
        
        self.canvas.draw()
        
    def toggle_lasso_handle(self):
        if self.lasso is None:
            self.drawing_texture = False
            self.btn_texture.setText("6. Draw Texture Line")
            self.btn_clean_handle.setText("5. Enable Lasso (Clean Noise)")
            
            self.lasso_mode = 'handle_section'
            self.lasso = LassoSelector(self.ax, self.on_lasso_select)
            self.btn_lasso_handle.setText("Disable Lasso (Handle)")
        else:
            self.lasso.disconnect_events()
            self.lasso = None
            self.lasso_mode = None
            self.btn_lasso_handle.setText("Lasso Handle (Generate Section)")

    def toggle_lasso(self):
        if self.lasso is None:
            self.drawing_texture = False
            self.btn_texture.setText("6. Draw Texture Line")
            self.btn_lasso_handle.setText("Lasso Handle (Generate Section)")
            
            self.lasso_mode = 'clean'
            self.lasso = LassoSelector(self.ax, self.on_lasso_select)
            self.btn_clean_handle.setText("Disable Lasso")
        else:
            self.lasso.disconnect_events()
            self.lasso = None
            self.lasso_mode = None
            self.btn_clean_handle.setText("5. Enable Lasso (Clean Noise)")
            
    def on_lasso_select(self, verts):
        p = Path(verts)
        
        if self.lasso_mode == 'clean':
            if self.profile_2d is not None and len(self.profile_2d) > 0:
                ind = p.contains_points(self.profile_2d)
                self.profile_2d = self.profile_2d[~ind]
                
            if self.facade_2d is not None and len(self.facade_2d) > 0:
                ind = p.contains_points(self.facade_2d)
                self.facade_2d = self.facade_2d[~ind]
                
        elif self.lasso_mode == 'handle_section':
            if self.facade_2d is not None and len(self.facade_2d) > 0:
                ind = p.contains_points(self.facade_2d)
                handle_pts = self.facade_2d[ind]
                if len(handle_pts) > 0:
                    z_centroid = np.mean(handle_pts[:, 1])
                    slice_3d = pottery_processor.extract_horizontal_slice(self.aligned_points, z_centroid, thickness=2.0)
                    
                    if len(slice_3d) > 3:
                        angle_rad = np.radians(self.slider_angle.value())
                        dir_vec = np.array([np.cos(angle_rad), np.sin(angle_rad)])
                        xy_points = slice_3d[:, :2] - np.array([self.xc, self.yc])
                        x_proj = np.dot(xy_points, dir_vec)
                        z_proj = slice_3d[:, 2]
                        
                        proj_pts = np.column_stack((x_proj, z_proj))
                        ind_slice = p.contains_points(proj_pts)
                        handle_3d = slice_3d[ind_slice]
                        
                        if len(handle_3d) > 3:
                            hx = handle_3d[:, 0] - np.mean(handle_3d[:, 0])
                            hy = handle_3d[:, 1] - np.mean(handle_3d[:, 1])
                            plot_cx = np.mean(handle_pts[:, 0])
                            plot_cz = np.mean(handle_pts[:, 1]) + 20
                            
                            mp = MultiPoint(np.column_stack((hx, hy)))
                            hull = concave_hull(mp, ratio=0.2)
                            self.handle_sections.append({'hull': hull, 'cx': plot_cx, 'cz': plot_cz, 'source_cz': z_centroid})
                            
        self.redraw_profile()
        
    def toggle_texture_drawing(self):
        self.drawing_texture = not self.drawing_texture
        if self.drawing_texture:
            if self.lasso is not None:
                self.lasso.disconnect_events()
                self.lasso = None
                self.btn_clean_handle.setText("5. Enable Lasso (Remove Handle)")
            self.btn_texture.setText("Stop Drawing")
        else:
            self.btn_texture.setText("6. Draw Texture Line")

    def on_click_texture(self, event):
        if not self.drawing_texture or event.inaxes != self.ax: return
        self.current_texture_line = [(event.xdata, event.ydata), (event.xdata, event.ydata)]
        self.temp_texture_line, = self.ax.plot([event.xdata, event.xdata], [event.ydata, event.ydata], 'b--')
        self.canvas.draw()
        
    def on_motion_texture(self, event):
        if not self.drawing_texture or self.current_texture_line is None or event.inaxes != self.ax: return
        self.current_texture_line[1] = (event.xdata, event.ydata)
        if self.temp_texture_line is not None:
            self.temp_texture_line.set_data([self.current_texture_line[0][0], self.current_texture_line[1][0]], 
                                            [self.current_texture_line[0][1], self.current_texture_line[1][1]])
            self.canvas.draw()
        
    def on_release_texture(self, event):
        if not self.drawing_texture or self.current_texture_line is None or event.inaxes != self.ax: return
        self.current_texture_line[1] = (event.xdata, event.ydata)
        self.texture_lines.append(self.current_texture_line)
        self.current_texture_line = None
        if self.temp_texture_line is not None:
            self.temp_texture_line.remove()
            self.temp_texture_line = None
        self.redraw_profile()
        
    def save_image(self):
        if self.profile_2d is None or len(self.profile_2d) == 0: return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Image", "pottery_scheme.png", "Images (*.png *.pdf)")
        if not file_path: return
        
        # Clear title for clean save
        title = self.ax.get_title()
        self.ax.set_title("") 
        
        self.fig.savefig(file_path, bbox_inches='tight', dpi=300)
        
        # Restore title
        self.ax.set_title(title)
        self.canvas.draw()
        
        QMessageBox.information(self, "Saved", f"Image saved to {file_path}")

    def save_points_and_angle(self):
        if self.base_points is None and self.rim_points is None and getattr(self, 'R', 0) <= 0:
            QMessageBox.warning(self, "No Points", "No Base or Rim points have been picked yet.\nPlease pick points first.")
            return
            
        default_dir = os.path.dirname(self.stl_file_path) if self.stl_file_path else ""
        if self.stl_file_path:
            base_name = os.path.splitext(os.path.basename(self.stl_file_path))[0]
            default_name = os.path.join(default_dir, f"{base_name}_points.txt")
        else:
            default_name = os.path.join(default_dir, "picked_points.txt")
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Points & Profile Angle", default_name,
            "Text Files (*.txt);;JSON Files (*.json);;All Files (*)"
        )
        if not file_path:
            return
            
        rim_fit = None
        if hasattr(self, 'R') and self.R > 0:
            c = self.rim_center_3d if hasattr(self, 'rim_center_3d') and self.rim_center_3d is not None else [self.xc, self.yc, 0.0]
            n = self.rim_normal if hasattr(self, 'rim_normal') and self.rim_normal is not None else [0.0, 0.0, 1.0]
            rim_fit = {
                'center': [float(c[0]), float(c[1]), float(c[2])],
                'radius': float(self.R),
                'normal': [float(n[0]), float(n[1]), float(n[2])]
            }
            
        vessel_type = "Whole Vessel" if self.combo_type.currentIndex() == 1 else "Sherd"
        wall_thickness = self.slider_thickness.value() / 10.0
        cutoff_z = self.slider_cutoff.value()
        angle = self.slider_angle.value()
        
        if file_path.endswith('.json'):
            import json
            data = {
                'stl_path': self.stl_file_path,
                'profile_angle': angle,
                'vessel_type': vessel_type,
                'is_flipped': getattr(self, 'is_flipped', False),
                'wall_thickness': wall_thickness,
                'cutoff_z': cutoff_z,
                'base_points': self.base_points.tolist() if self.base_points is not None else None,
                'rim_points': self.rim_points.tolist() if self.rim_points is not None else None,
                'rim_fit': rim_fit
            }
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        else:
            txt = pottery_processor.format_points_data(
                stl_path=self.stl_file_path,
                profile_angle=angle,
                base_points=self.base_points,
                rim_points=self.rim_points,
                rim_fit=rim_fit,
                vessel_type=vessel_type,
                is_flipped=getattr(self, 'is_flipped', False),
                wall_thickness=wall_thickness,
                cutoff_z=cutoff_z
            )
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(txt)
                
        QMessageBox.information(self, "Saved", f"Points and profile angle saved to:\n{file_path}")

    def load_points_and_angle(self):
        default_dir = os.path.dirname(self.stl_file_path) if self.stl_file_path else ""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Points & Profile Angle", default_dir,
            "Text/JSON Files (*.txt *.json);;All Files (*)"
        )
        if not file_path:
            return
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        data = pottery_processor.parse_points_data(content)
        
        # If no STL is loaded, try to load from data['stl_path']
        if self.points is None:
            stl_to_load = data.get('stl_path', '')
            if stl_to_load and os.path.exists(stl_to_load):
                reply = QMessageBox.question(
                    self, "Load STL?",
                    f"No STL is currently open.\nWould you like to open the associated STL file?\n{stl_to_load}",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.Yes:
                    self.load_stl(stl_to_load)
                else:
                    return
            else:
                QMessageBox.warning(self, "No STL Loaded", "Please load an STL model first before loading points.")
                return
                
        # Check if loaded on different STL
        if data.get('stl_path') and self.stl_file_path:
            saved_name = os.path.basename(data['stl_path'])
            curr_name = os.path.basename(self.stl_file_path)
            if saved_name.lower() != curr_name.lower():
                reply = QMessageBox.question(
                    self, "STL Mismatch Warning",
                    f"This points file was saved for:\n'{saved_name}'\n\nCurrently open STL is:\n'{curr_name}'\n\nApply points anyway?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

        # Restore Base Points & Alignment
        if data.get('base_points') is not None and len(data['base_points']) == 3:
            self.base_points = np.array(data['base_points'])
            p1, p2, p3 = self.base_points
            self.aligned_points = pottery_processor.align_by_3_points(self.points.copy(), p1, p2, p3)
        else:
            self.aligned_points = self.points.copy()
            
        # Restore Flip
        if data.get('is_flipped', False):
            self.aligned_points[:, 2] = -self.aligned_points[:, 2]
            self.is_flipped = True
        else:
            self.is_flipped = False
            
        self.update_3d_view()
        
        # Restore Rim Points / Fit
        if data.get('rim_points') is not None and len(data['rim_points']) == 3:
            self.rim_points = np.array(data['rim_points'])
            p1, p2, p3 = self.rim_points
            try:
                c, r, n = pottery_processor.circle_from_3_points_3d(p1, p2, p3)
                self.xc, self.yc = c[0], c[1]
                self.R = r
                self.rim_center_3d = c
                self.rim_normal = n
                self.plotter.add_mesh(pv.PolyData([c]), color='green', point_size=15, name='rim_center')
                for idx, pt in enumerate(self.rim_points):
                    self.plotter.add_mesh(pv.PolyData([pt]), color='red', point_size=10, name=f'pt_{idx+1}')
            except Exception as e:
                print(f"Error computing circle from rim points: {e}")
        elif data.get('rim_fit') is not None:
            rf = data['rim_fit']
            c = rf.get('center', [0, 0, 0])
            self.xc, self.yc = c[0], c[1]
            self.R = rf.get('radius', 0.0)
            self.rim_center_3d = np.array(c)
            self.rim_normal = np.array(rf.get('normal', [0, 0, 1]))
            self.plotter.add_mesh(pv.PolyData([self.rim_center_3d]), color='green', point_size=15, name='rim_center')
            
        # Restore Vessel Type
        vtype = data.get('vessel_type', 'Sherd')
        if "whole" in vtype.lower():
            self.combo_type.setCurrentIndex(1)
        else:
            self.combo_type.setCurrentIndex(0)
            
        # Restore Sliders
        if 'wall_thickness' in data:
            self.slider_thickness.setValue(int(data['wall_thickness'] * 10))
        if 'cutoff_z' in data:
            self.slider_cutoff.setValue(int(data['cutoff_z']))
            
        # Enable UI controls
        self.slider_angle.setEnabled(True)
        self.btn_clean_handle.setEnabled(True)
        self.btn_lasso_handle.setEnabled(True)
        self.btn_texture.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_save_points.setEnabled(True)
        
        # Restore Angle & Trigger Profile Update
        angle = data.get('profile_angle', 0)
        self.slider_angle.setValue(angle)
        self.update_profile()
        
        QMessageBox.information(self, "Loaded", f"Points and parameters loaded successfully!\nProfile Angle: {angle}°")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = PotteryApp()
    window.show()
    sys.exit(app.exec_())
