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

import pottery_processor

class PotteryApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D Pottery Sherd Analysis")
        self.resize(1200, 800)
        
        self.points = None
        self.aligned_points = None
        self.xc = 0.0
        self.yc = 0.0
        self.R = 0.0
        self.profile_2d = None
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
        
        self.btn_extract_circle = QPushButton("Auto-Fit Circle")
        self.btn_extract_circle.clicked.connect(self.extract_circle)
        self.btn_extract_circle.setEnabled(False)
        control_panel.addWidget(self.btn_extract_circle)
        
        self.label_angle = QLabel("4. Profile Angle: 0")
        control_panel.addWidget(self.label_angle)
        
        self.slider_angle = QSlider(Qt.Horizontal)
        self.slider_angle.setRange(0, 360)
        self.slider_angle.setValue(0)
        self.slider_angle.setEnabled(False)
        self.slider_angle.valueChanged.connect(self.update_profile)
        control_panel.addWidget(self.slider_angle)
        
        self.btn_clean_handle = QPushButton("5. Enable Lasso (Remove Handle)")
        self.btn_clean_handle.clicked.connect(self.toggle_lasso)
        self.btn_clean_handle.setEnabled(False)
        control_panel.addWidget(self.btn_clean_handle)
        
        self.btn_texture = QPushButton("6. Draw Texture Line")
        self.btn_texture.clicked.connect(self.toggle_texture_drawing)
        self.btn_texture.setEnabled(False)
        control_panel.addWidget(self.btn_texture)
        
        self.btn_save = QPushButton("7. Save Scheme Image")
        self.btn_save.clicked.connect(self.save_image)
        self.btn_save.setEnabled(False)
        control_panel.addWidget(self.btn_save)
        
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
        self.drawing_texture = False
        self.texture_lines = []
        self.current_texture_line = None
        self.canvas.mpl_connect('button_press_event', self.on_click_texture)
        self.canvas.mpl_connect('button_release_event', self.on_release_texture)
        self.canvas.mpl_connect('motion_notify_event', self.on_motion_texture)

    def load_stl(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open STL", "", "STL Files (*.stl)")
        if not file_path: return
        
        mesh = trimesh.load(file_path)
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
            
        self.points = mesh.vertices
        self.aligned_points = self.points.copy()
        
        self.update_3d_view()
        self.btn_align.setEnabled(True)
        self.btn_flip.setEnabled(True)
        self.combo_layer.setEnabled(True)
        self.btn_extract_circle.setEnabled(True)
        
    def update_3d_view(self, show_points=None):
        self.plotter.clear()
        pts = show_points if show_points is not None else self.aligned_points
        cloud = pv.PolyData(pts)
        self.plotter.add_mesh(cloud, color='lightblue', point_size=2)
        self.plotter.add_axes()
        self.plotter.reset_camera()
        
    def start_alignment_picking(self):
        self.picked_points = []
        try:
            self.plotter.disable_picking()
        except:
            pass
            
        self.plotter.clear_button_widgets()
        self.plotter.add_text("Click (or press 'P') 3 points on the base or rim.", position='upper_left', name='pick_msg')
        
        def callback(*args):
            try:
                # Handle different PyVista versions which might pass (mesh, idx) or just (point)
                if len(args) == 2:
                    mesh, idx = args
                    pt = mesh.points[idx]
                else:
                    pt = np.array(args[0])
                
                self.picked_points.append(pt)
                # PyVista might already draw a point, but we draw our own just to be sure
                self.plotter.add_mesh(pv.PolyData(pt), color='red', point_size=10, render_points_as_spheres=True, name=f'pick_{len(self.picked_points)}')
                
                if len(self.picked_points) == 3:
                    self.plotter.remove_actor('pick_msg')
                    try:
                        self.plotter.disable_picking()
                    except:
                        pass
                    self.align_cloud()
            except Exception as e:
                print(f"Picking error: {e}")
                
        # Enable left_clicking so the user doesn't have to press 'P'
        self.plotter.enable_point_picking(callback=callback, show_message=False, color='red', point_size=10, left_clicking=True)

    def align_cloud(self):
        p1, p2, p3 = self.picked_points
        self.aligned_points = pottery_processor.align_by_3_points(self.aligned_points, p1, p2, p3)
        self.update_3d_view()
        QMessageBox.information(self, "Aligned", "Cloud aligned to Z axis. Use Flip if upside down.")
        self.picked_points = []
        
    def flip_upside_down(self):
        if self.aligned_points is not None:
            self.aligned_points[:, 2] = -self.aligned_points[:, 2]
            self.update_3d_view()
            
    def extract_circle(self):
        if self.aligned_points is None: return
        
        if self.combo_layer.currentIndex() == 0:
            top_pts = pottery_processor.extract_top_layer(self.aligned_points, 0.05)
        else:
            top_pts = pottery_processor.extract_bottom_layer(self.aligned_points, 0.05)
            
        if len(top_pts) < 3: return
        
        self.xc, self.yc, self.R = pottery_processor.fit_circle_2d(top_pts[:, :2])
        
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
        self.btn_texture.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.update_profile()

    def update_profile(self):
        if self.aligned_points is None: return
        angle = self.slider_angle.value()
        self.label_angle.setText(f"4. Profile Angle: {angle}")
        
        self.profile_2d = pottery_processor.extract_profile(self.aligned_points, self.xc, self.yc, angle, thickness=2.0)
        self.texture_lines = [] # Reset texture lines when angle changes
        
        self.redraw_profile()
        
    def redraw_profile(self):
        self.ax.clear()
        if self.profile_2d is not None and len(self.profile_2d) > 0:
            # The profile_2d has x >= 0. The user wants the filled profile on the left (-x),
            # and the external boundary line on the right (+x).
            
            # 1. Plot the left profile (internal and profile)
            left_profile = self.profile_2d.copy()
            left_profile[:, 0] = -left_profile[:, 0]
            self.ax.plot(left_profile[:, 0], left_profile[:, 1], 'k.', markersize=2)
            
            # 2. Plot the right profile (external line only)
            # To get the external contour, we can take the maximum X for each Z bin,
            # or simply plot the convex hull/boundary of the right side.
            # A simple approach: sort by Z, then find max X for bins.
            # But the easiest representation of just the external side is plotting the alpha shape.
            # For a line drawing, we'll plot the points, but lighter, or we can extract the outer edge.
            # Let's plot the right profile points as light gray so the user can see it,
            # but we will extract the external line properly during 'save_image'.
            self.ax.plot(self.profile_2d[:, 0], self.profile_2d[:, 1], '.', color='lightgray', markersize=1)
            
            # Draw center line
            zmin, zmax = self.profile_2d[:, 1].min(), self.profile_2d[:, 1].max()
            self.ax.plot([0, 0], [zmin, zmax], 'g-.', alpha=0.5)
            
        for line in self.texture_lines:
            self.ax.plot([line[0][0], line[1][0]], [line[0][1], line[1][1]], 'b-')
            
        self.ax.set_aspect('equal')
        self.ax.set_title(f"Profile at {self.slider_angle.value()} degrees")
        self.ax.set_xlabel("Distance from center")
        self.ax.set_ylabel("Z")
        self.canvas.draw()
        
    def toggle_lasso(self):
        if self.lasso is None:
            self.drawing_texture = False
            self.btn_texture.setText("6. Draw Texture Line")
            
            self.lasso = LassoSelector(self.ax, self.on_lasso_select)
            self.btn_clean_handle.setText("Disable Lasso")
        else:
            self.lasso.disconnect_events()
            self.lasso = None
            self.btn_clean_handle.setText("5. Enable Lasso (Remove Handle)")
            
    def on_lasso_select(self, verts):
        if self.profile_2d is None or len(self.profile_2d) == 0: return
        p = Path(verts)
        # We need to map the lasso selection (which might be on the left side -x)
        # to the right side (+x) where the profile_2d is stored.
        # Check if selection is predominantly on the left side
        verts_arr = np.array(verts)
        if np.mean(verts_arr[:, 0]) < 0:
            # selection was on the left side, mirror the path to right side
            verts_arr[:, 0] = -verts_arr[:, 0]
            p = Path(verts_arr)
            
        ind = p.contains_points(self.profile_2d)
        self.profile_2d = self.profile_2d[~ind]
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
        
    def on_motion_texture(self, event):
        if not self.drawing_texture or self.current_texture_line is None or event.inaxes != self.ax: return
        self.current_texture_line[1] = (event.xdata, event.ydata)
        
        self.redraw_profile()
        # draw temporary line
        self.ax.plot([self.current_texture_line[0][0], self.current_texture_line[1][0]], 
                     [self.current_texture_line[0][1], self.current_texture_line[1][1]], 'b--')
        self.canvas.draw()
        
    def on_release_texture(self, event):
        if not self.drawing_texture or self.current_texture_line is None or event.inaxes != self.ax: return
        self.current_texture_line[1] = (event.xdata, event.ydata)
        self.texture_lines.append(self.current_texture_line)
        self.current_texture_line = None
        self.redraw_profile()
        
    def save_image(self):
        if self.profile_2d is None or len(self.profile_2d) == 0: return
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Image", "pottery_scheme.png", "Images (*.png *.pdf)")
        if not file_path: return
        
        self.ax.clear()
        
        # 1. Left side: Fill the profile
        left_profile = self.profile_2d.copy()
        left_profile[:, 0] = -left_profile[:, 0]
        
        try:
            from scipy.spatial import Delaunay
            import matplotlib.tri as mtri
            
            # Create a nice tight mesh for filling using Delaunay
            triang = mtri.Triangulation(left_profile[:, 0], left_profile[:, 1])
            x_tri = left_profile[triang.triangles, 0]
            y_tri = left_profile[triang.triangles, 1]
            
            a = np.sqrt((x_tri[:,0]-x_tri[:,1])**2 + (y_tri[:,0]-y_tri[:,1])**2)
            b = np.sqrt((x_tri[:,1]-x_tri[:,2])**2 + (y_tri[:,1]-y_tri[:,2])**2)
            c = np.sqrt((x_tri[:,2]-x_tri[:,0])**2 + (y_tri[:,2]-y_tri[:,0])**2)
            max_edge = np.max(np.column_stack((a, b, c)), axis=1)
            
            # Dynamic threshold based on median edge length. 
            threshold = np.median(max_edge) * 3.0
            
            valid_triangles = max_edge < threshold
            triang.set_mask(~valid_triangles)
            
            # Fill the valid triangles with black
            self.ax.tripcolor(triang, facecolors=np.zeros(len(triang.triangles)), cmap='gray', vmin=0, vmax=1)
            
            # Draw the edges of the valid triangles to provide a crisp outline without a convex hull
            self.ax.triplot(triang, 'k-', lw=0.5)
            

        except Exception as e:
            # Fallback if triangulation fails
            self.ax.plot(left_profile[:, 0], left_profile[:, 1], 'k.', markersize=2)

        # 2. Right side: External Boundary Line
        # We find the maximum X for each Z interval
        zmin, zmax = self.profile_2d[:, 1].min(), self.profile_2d[:, 1].max()
        z_bins = np.linspace(zmin, zmax, 150)
        ext_x = []
        ext_z = []
        for i in range(len(z_bins)-1):
            mask = (self.profile_2d[:, 1] >= z_bins[i]) & (self.profile_2d[:, 1] < z_bins[i+1])
            if np.any(mask):
                ext_x.append(self.profile_2d[mask, 0].max())
                ext_z.append((z_bins[i] + z_bins[i+1]) / 2)
                
        # Smooth the external line slightly
        if len(ext_x) > 5:
            from scipy.signal import savgol_filter
            ext_x_smooth = savgol_filter(ext_x, window_length=min(11, len(ext_x)), polyorder=3)
            self.ax.plot(ext_x_smooth, ext_z, 'k-', lw=2)
        else:
            self.ax.plot(ext_x, ext_z, 'k-', lw=2)
            
        # Draw texture lines
        for line in self.texture_lines:
            self.ax.plot([line[0][0], line[1][0]], [line[0][1], line[1][1]], 'k-', lw=1.5)
            
        # Draw center line
        self.ax.plot([0, 0], [zmin, zmax], 'k-.', lw=1)
        
        # Draw rim horizontal line
        top_pts = left_profile[left_profile[:, 1] >= zmax - 1.0]
        if len(top_pts) > 0:
            inner_x = np.max(top_pts[:, 0]) # closest to 0 since negative
            self.ax.plot([inner_x, 0], [zmax, zmax], 'k-', lw=1.0)
            
        top_right_x = self.profile_2d[self.profile_2d[:, 1] >= zmax - 1.0, 0]
        if len(top_right_x) > 0:
            self.ax.plot([0, np.max(top_right_x)], [zmax, zmax], 'k-', lw=1.0)
        
        # Scale bar (10cm = 100 units, assuming units are mm)
        # Black and white 1cm (10 unit) blocks
        import matplotlib.patches as patches
        bar_width = 100
        bar_x = -bar_width / 2
        bar_y = zmin - (zmax - zmin) * 0.1
        bar_h = (zmax - zmin) * 0.015
        
        for i in range(10):
            color = 'k' if i % 2 == 0 else 'w'
            rect = patches.Rectangle((bar_x + i*10, bar_y), 10, bar_h, facecolor=color, edgecolor='k', linewidth=1)
            self.ax.add_patch(rect)
            
        self.ax.text(bar_x, bar_y - bar_h*1.5, "0", ha='center', fontsize=12)
        self.ax.text(bar_x + 100, bar_y - bar_h*1.5, "10cm", ha='center', fontsize=12)
        
        self.ax.set_aspect('equal')
        self.ax.axis('off')
        self.fig.savefig(file_path, bbox_inches='tight', dpi=300)
        self.canvas.draw()
        QMessageBox.information(self, "Saved", f"Image saved to {file_path}")
        
        self.redraw_profile()

if __name__ == '__main__':
    app = QApplication(sys.vars if hasattr(sys, 'vars') else sys.argv)
    window = PotteryApp()
    window.show()
    sys.exit(app.exec_())
