# PotteryPythonApp - Agent Guidelines

## Project Context
This is a PyQt5-based desktop application for 3D pottery sherd analysis. It loads STL files (3D point clouds), aligns them based on user-picked points, extracts top/bottom layers to fit a 2D circle, and then extracts a 2D profile (cross-section) of the pottery sherd.

## Core Dependencies
- **PyQt5**: GUI framework.
- **pyvista / pyvistaqt**: 3D rendering and interaction.
- **trimesh**: STL loading and processing.
- **matplotlib**: 2D profile rendering and plotting (including Lasso).
- **numpy / scipy**: Math operations, least squares circle fitting, point cloud manipulations.

## Project Layout (since 2026-10-19)
- `studio/` – **Pottery Studio**, the current program: `pottery_studio.py` + `RunStudio.bat`.
- `core/` – `pottery_processor.py`, the shared calculations used by every version (studio and legacy).
- `beta_amit/` – Amit's beta: `pottery_studio_beta.py` + `RunStudioBeta.bat` + a **frozen copy** of `pottery_studio.py` / `pottery_processor.py` (the code inside `PotteryStudioBetaAmit.exe`). Do not update the frozen copy unless the user asks for a new beta.
- `legacy/` – the old programs `main.py`, `profile_test.py`, `profile_test2.py` with their `.bat` launchers (the launchers add `..\core` to `PYTHONPATH`).
- `docs/` – `studio_plan.md`, `licensing_plan.md`, `handles_plan.md`.
- `media/` – images and videos (git-ignored, not uploaded).
- Each `.bat` sits in its version's folder and starts its script by full path, so it works from any working directory (also drag-and-drop of an STL).

## Code Architecture
- `legacy/main.py`: Contains the `PotteryApp` class. Handles all UI layout, Qt signals, styling, and plotting (both 3D and 2D).
- `core/pottery_processor.py`: Contains pure mathematical and algorithmic logic for alignment (`align_by_3_points`), layer extraction, circle fitting (`fit_circle_2d`), and profile extraction (`extract_profile`), plus the Pottery Studio geometry.

## Important Rules for Future Edits
1. **Separation of Concerns**: UI logic stays in `main.py`. Math/Algorithm logic stays in `pottery_processor.py`. Do NOT put heavy math inside the `PotteryApp` class.
2. **PyQt5 Conventions**: Always use `QtWidgets` from `PyQt5`. Do not mix with `PySide2/6` or `PyQt6`. Keep the light greens stylesheet consistent.
3. **Point Cloud Format**: Point clouds are passed around as `Nx3 numpy arrays`. 
4. **Error Handling**: Use `try-except` blocks for picking and heavy math operations. Show errors via `QMessageBox.information` or `QMessageBox.critical` rather than crashing the app.
5. **No Placeholders**: When adding features, fully implement them.
6. **Matplotlib Canvas**: Make sure to call `self.canvas.draw()` after updating `self.ax`.
7. **Maintain Existing Workflows**: Do not break the Lasso tool, Texture Drawing, or the 3D picking workflows when modifying the UI or updating the 2D plot.
8. **Live Preview Rendering**: `redraw_profile` is responsible for rendering the final output scheme (filled profiles, smoothed lines, scale bars, rim lines). `save_image` should simply save the matplotlib canvas to a file without recalculating the drawing.
9. **Whole Vessel Mode vs Sherd Mode**: The app supports two drawing modes. `Sherd` mode relies on Delaunay Triangulation for standard double-wall profiles. `Whole Vessel` mode applies algorithmic inner-wall completion using `shapely` offsetting, because full vessels are often scanned only on the exterior and the top inner rim.
10. **Geometric Processing (Shapely)**: When drawing facades (left side) and handle cross-sections, the application uses `shapely.concave_hull` on a downsampled 2D point cloud (1mm resolution) to generate accurate contours with inner voids (like handle holes) without performance degradation.
11. **Rim Thickness Calculation**: For Whole Vessels, inner thickness is estimated dynamically using PCA/Linear Regression on the top 1.5 cm of the rim to measure true perpendicular thickness, which is then used to generate a flat inner base.
12. **Pottery Studio**: `studio/pottery_studio.py` (launched by `studio/RunStudio.bat`) is the full-process GUI planned in `docs/studio_plan.md`. Do not modify `legacy/main.py` or `legacy/profile_test2.py`. Keep `docs/studio_plan.md` up to date (status table and decisions log) whenever a stage is completed or a decision changes.
