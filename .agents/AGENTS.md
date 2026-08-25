# PotteryPythonApp - Agent Guidelines

## Project Context
This is a PyQt5-based desktop application for 3D pottery sherd analysis. It loads STL files (3D point clouds), aligns them based on user-picked points, extracts top/bottom layers to fit a 2D circle, and then extracts a 2D profile (cross-section) of the pottery sherd.

## Core Dependencies
- **PyQt5**: GUI framework.
- **pyvista / pyvistaqt**: 3D rendering and interaction.
- **trimesh**: STL loading and processing.
- **matplotlib**: 2D profile rendering and plotting (including Lasso).
- **numpy / scipy**: Math operations, least squares circle fitting, point cloud manipulations.

## Code Architecture
- `main.py`: Contains the `PotteryApp` class. Handles all UI layout, Qt signals, styling, and plotting (both 3D and 2D).
- `pottery_processor.py`: Contains pure mathematical and algorithmic logic for alignment (`align_by_3_points`), layer extraction, circle fitting (`fit_circle_2d`), and profile extraction (`extract_profile`).

## Important Rules for Future Edits
1. **Separation of Concerns**: UI logic stays in `main.py`. Math/Algorithm logic stays in `pottery_processor.py`. Do NOT put heavy math inside the `PotteryApp` class.
2. **PyQt5 Conventions**: Always use `QtWidgets` from `PyQt5`. Do not mix with `PySide2/6` or `PyQt6`. Keep the light greens stylesheet consistent.
3. **Point Cloud Format**: Point clouds are passed around as `Nx3 numpy arrays`. 
4. **Error Handling**: Use `try-except` blocks for picking and heavy math operations. Show errors via `QMessageBox.information` or `QMessageBox.critical` rather than crashing the app.
5. **No Placeholders**: When adding features, fully implement them.
6. **Matplotlib Canvas**: Make sure to call `self.canvas.draw()` after updating `self.ax`.
7. **Maintain Existing Workflows**: Do not break the Lasso tool, Texture Drawing, or the 3D picking workflows when modifying the UI or updating the 2D plot.
8. **Live Preview Rendering**: `redraw_profile` is responsible for rendering the final output scheme (filled profiles, smoothed lines, scale bars, rim lines). `save_image` should simply save the matplotlib canvas to a file without recalculating the drawing.
