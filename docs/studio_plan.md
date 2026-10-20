# Pottery Studio – Work Plan (new full-process GUI)

> Living document. Update it whenever a decision changes or a stage is completed.

## Status
| Stage | Description | Status |
|---|---|---|
| 1 | Geometry functions in `pottery_processor.py` | **Done** (2026-09-28) – see §9 |
| 2 | GUI skeleton: load, planes, alignment, 3D view | **Done** (2026-09-29) – tested by the user: "works perfect" |
| 3 | Right-side 6-step pipeline, angle controls, Inspector & Grid tabs | **Done** (2026-09-29) – waiting for user test, see §11 |
| 4 | Symmetry-axis modes & left side | **Done** (2026-09-29) – axis selector added in stage 3; left side done, waiting for user test, see §13 |
| 5 | Handles: lasso, outline, mirror to left, handle section | **Done** (2026-09-29) – waiting for user test, see §14 |
| 6 | Scale bar, rim diameter, texture lines, save image | **Done** (2026-09-30) – waiting for user test, see §18 |

After each stage: stop and let the user test before continuing.

---

## 1. General approach
- New files: `pottery_studio.py` (the GUI) and `RunStudio.bat` (launcher). Since 2026-10-19 they live in `studio/`; the calculations in `core/` (see §21).
- `main.py` and `profile_test2.py` are **not modified** and must keep working.
- All math lives in `pottery_processor.py` (per `.agents/AGENTS.md`). The GUI file contains only UI, event handling and drawing.
  - Move `run_6step_pipeline_v2` from `profile_test2.py` into `pottery_processor.py` (as a copy; `profile_test2.py` stays unchanged).
  - New functions are **added**; existing functions keep their signatures so `main.py` is not broken.
- Stack: PyQt5 + pyvista/pyvistaqt (3D) + matplotlib (2D scheme) + numpy/scipy/shapely/trimesh.
- **No Save/Load settings** in this app (user decision). Every session starts from Load STL.

## 2. User workflow (left control panel)
1. **Load STL**
2. **Vessel type** – radio buttons (only one selectable): `Sherd` / `Whole Vessel`.
   - Checkbox **Symmetrical** (default: checked).
   - Checkbox **Inner Wall Fully Scanned** (default: checked for Sherd, unchecked for Whole Vessel; reset when the type changes; user may override). Checked → scanned walls are used as they are; unchecked → the inner wall is completed (6-step pipeline).
3. **Set Rim Plane** / **Set Base Plane** – each picks 3 points in the 3D view.
   - The user must pick the 3 points **on the tip (edge) of the rim / base**, so that the circle through them gives a real center and diameter (`circle_from_3_points_3d`).
   - A ✓ indicator shows which planes are set.
4. **Alignment Plane** – radio buttons: `Rim` / `Base`.
   - Default: Sherd → Rim, Whole Vessel → Base (changing the vessel type resets the default; user may override).
   - An option that needs a plane which is not set is disabled.
5. **Profile (right side)** – the full `profile_test2.py` procedure:
   - Angle controls: ◀ -5° / ◀ -1° / angle spinbox / +1° ▶ / +5° ▶.
   - Concave-hull ratio spinbox (default 0.03).
   - **Symmetry axis** mode (see §3): `⟂ Rim` / `⟂ Base` / `Base-center → Rim-center`.
     - Default: Sherd → ⟂ Rim, Whole Vessel → ⟂ Base. Modes needing a missing plane are disabled.
   - ✂️ **Lasso Handle** / **Clear Handle**.
   - **Lasso Clean Noise** (delete stray points, like `main.py`).
   - **Add Handle to Left Side** – enabled only if Symmetrical and a handle is marked.
   - **Draw Handle Section Line** – enabled when a handle is marked (see §5).
6. **Add Texture Lines** – like `main.py` (click-drag straight lines on the scheme).
7. **Save Scheme Image** – PNG/PDF, 300 dpi, saves the canvas as-is (no recalculation).

### Tabs
- **3D View** – pyvista, point picking, shows rim/base points, their circle centers and the symmetry axis.
- **Scheme** – the final drawing (live preview).
- **Step Inspector** – one pipeline step in a large view, with ◀ Previous / Next ▶ (as in `profile_test2`). The handle lasso works here.
- **All Steps Grid** – all 6 steps side by side.
- **Log** – diagnostics.

## 3. Geometry: alignment plane vs. symmetry axis
Two separate concepts:
- **Alignment plane** → defines what is horizontal in the drawing (the chosen plane's normal = drawing "up").
- **Symmetry axis** → a 3D line; the slice is taken around it and the left side is mirrored across it.

Axis definitions (decided):
| Mode | Direction | Passes through |
|---|---|---|
| ⟂ Rim | rim plane normal | rim circle center |
| ⟂ Base | base plane normal | base circle center |
| Base-center → Rim-center | from base center to rim center | both centers |

Implementation outline:
1. Rotate the cloud so the alignment-plane normal is +Z (`alignment_transform`). The up/down direction is chosen automatically (body above a base plane / below a rim plane), so no "Flip Upside Down" button is needed.
2. Transform the rim/base points, centers and normals with the same rotation.
3. Build the axis line in the aligned frame.
4. **Slice around the axis**: the slicing half-plane contains the axis and is rotated by the profile angle around it (generalizes `extract_profile`, which assumes a vertical axis through `(xc, yc)`).
5. Project the slice to 2D drawing coordinates: horizontal = distance within the slice plane, vertical = aligned Z. When the axis is not perpendicular to the alignment plane, it appears **tilted** in the drawing.
6. Mirroring (symmetrical vessels) is a reflection across the 2D axis line, not `x → -x`.
7. Rim line in the scheme: drawn along the actual rim plane (may be tilted), as in `main.py`'s `rim_z` logic.

Implemented in `pottery_processor.py` (stage 1, section "Pottery Studio geometry"):
- Coordinates: **uv** = inside the slicing plane, u = distance from the axis (right side u ≥ 0), v = along the axis. The axis is always u = 0, so the 6-step pipeline and mirroring (u → −u) work unchanged for a tilted axis. uv → **drawing** is a pure rotation (true shape kept; aligned +Z is up).
- `rotation_between`, `alignment_transform(p1,p2,p3, points, plane)`, `apply_alignment` – alignment with automatic up/down.
- `circle_through_3_points` – rim/base circle (center, radius, normal). **Use this, not `circle_from_3_points_3d`** (see §9).
- `build_symmetry_axis(mode, rim_circle, base_circle)` – modes `'rim'`, `'base'`, `'centers'`.
- `slice_frame(axis_point, axis_dir, angle_deg)` – for a vertical axis identical to `extract_profile`.
- `points_to_uv`, `uv_to_3d`, `uv_to_drawing`, `drawing_to_uv`, `geometry_uv_to_drawing`, `mirror_uv`, `reflect_across_line_2d`.
- `extract_axis_profile` (right-side slice), `extract_axis_half` (projection of one half).
- `outline_polygon` (concave hull, 1 mm downsampling, holes allowed), `points_in_polygon` (lasso mask).
- `circle_slice_intersections` – where the rim circle crosses the slicing plane → the (possibly tilted) rim line.
- `handle_section(points, frame, lasso_uv, line_uv)` + `filled_section_polygon` – filled, smoothed section from the user-drawn line.
- `run_6step_pipeline` – copy of `run_6step_pipeline_v2`; also ignores a handle mask of the wrong length instead of crashing.

## 4. Right side – profile
- **Changed 2026-09-29 (user):** inner-wall completion is controlled by the **Inner Wall Fully Scanned** checkbox (default on for Sherd, off for Whole Vessel). On → `run_6step_pipeline(..., complete_inner_wall=False)`: Steps 1–2 only, the concave hull of the slice is the section (Steps 3–5 shown as "not used – inner wall scanned"). Off → full 6 steps with the synthetic inner wall.
  - Pipeline facts (from `run_6step_pipeline_v2`): Step 3 searches the **bottom center in the lowest 15%** of the profile (to split outer/inner walls); Step 4 measures thickness from inner-wall points in the **top 20 mm below the rim**; Step 6 closes the base with a floor to the axis.
  - Risk to verify on real sherds (no base): Step 5 replaces the scanned inner wall with a synthetic offset, and Step 6 draws a floor to the axis that a sherd doesn't have. Check during Stage 3 and report; possible fallback: skip Step 6 floor closure for sherds.
- Axis-spill filter of Step 1 (`x < 0.8` above `z_min + 30`) must be expressed relative to the (possibly tilted) axis.
- **Handle lasso (5a)**:
  - Store the **lasso polygon** (vertices), not a per-point boolean mask. Recompute the mask on every slice. This avoids the `profile_test2` crash when the angle changes after a lasso.
  - Lassoed points are removed from the profile pipeline.
  - The handle is drawn in **external-view style** (outline, not filled): take the 3D points of the right half whose 2D projection falls inside the lasso polygon, build a `concave_hull` (1 mm downsampling, holes allowed for the handle opening) and draw its outline.

## 5. Left side, handles, labels
- **5b – Left side**
  - Symmetrical: mirror of the right side's **outer outline** across the axis line.
  - Not symmetrical: real projection of the other half of the cloud (as `main.py`'s facade, with clipping at the axis and rim line).
- **5c – Add Handle to Left Side**: reflect the handle outline across the axis and draw it on the left side.
- **5e – Labels**
  - 10 cm scale bar (alternating black/white, as `main.py`).
  - Rim diameter text – only when the rim plane was set with 3 points.
  - **Handle section** (only when a handle is lassoed):
    - Cut **perpendicular to the direction the handle runs** (user decision).
    - The **user draws the section line** across the handle on the scheme (button **Draw Handle Section Line**, click-drag like texture lines). This replaces automatic centerline detection – simpler and more accurate (user decision).
    - Method: the drawn 2D line + the viewing direction (perpendicular to the drawing plane) define a 3D cutting plane. Take the handle's 3D points within a thin slab (±1–2 mm) of that plane, project them onto the plane, and build a filled `concave_hull`.
    - Draw it filled black **above the handle**, with a dashed leader line to the section line.
    - Only **one** handle section, for the handle on the **right side** of the scheme. Redrawing the line replaces the previous section.
- **6 – Texture lines** and **7 – Save** as in `main.py`.

## 6. Test data
Folder: `C:\Users\lenovo\Desktop\AmitDagan\models\` – the user approved loading these two STL files from there for testing (use only the files the user names):
- **Whole vessel with handle:** `bilbil23.stl` (35 MB).
- **Sherd without handle:** `ImageToStl.com_lmlk+sj (1).stl` (24.5 MB).

## 7. Error handling & conventions
- Follow `.agents/AGENTS.md`: try/except around picking and heavy math, errors via `QMessageBox`, light-green stylesheet, `canvas.draw()` after updates, no placeholders.

## 8. Decisions log
| # | Question | Decision |
|---|---|---|
| 1 | Sherd profile method | ~~6-step pipeline~~ → **changed 2026-09-29**: "Inner Wall Fully Scanned" checkbox – default on for Sherd (scanned walls, Steps 1–2 only), off for Whole Vessel (inner wall completed); user can override |
| 2 | Axis anchor points | ⟂ Rim through rim center, ⟂ Base through base center; user picks 3 points on the tip of the rim/base |
| 3 | Only one plane set | Disable options that need the missing plane |
| 4 | Handle section orientation | Perpendicular to the direction the handle runs; the user draws the section line across the handle |
| 4b | Number of handle sections | One only, for the handle on the right side of the scheme |
| 7 | Test files | `bilbil23.stl` (whole vessel + handle), `ImageToStl.com_lmlk+sj (1).stl` (sherd, no handle) |
| 8 | Fix old `circle_from_3_points_3d` | Yes – fixed 2026-09-29 |
| 9 | Default axis for Whole Vessel | Stays ⟂ Base, even when the neck is off-axis; user switches to `centers` manually |
| 10 | Handle seen side-on | User's responsibility to choose the angle |
| 12 | Missing wall under a removed handle | ~~Draw Wall Line~~ (built, then **removed** 2026-09-29 at the user's request) → **two angles**: the handle is lassoed at its own angle; the section is taken at the nearest angle without the handle (all real scan data, no completion); the handle is drawn rotated onto it |
| 13 | Collapsible groups | **No folding** (user, 2026-09-30): the panel looks fine as it is |
| 14 | One or two angles for the handle | User chooses with the checkbox **"Section at a Nearby Angle (without the handle)"** in the Handle group – **default off = one angle** (2026-09-30) |
| 15 | Scale bar | Always 10 cm (user, 2026-09-30) |
| 16 | Texture lines | Straight lines only, with **Undo Last Line** |
| 17 | Text in the scheme | Only the rim diameter |
| 18 | Saved file name | STL file name + `_scheme` (e.g. `bilbil23_scheme.png`), default folder = the STL's folder |
| 19 | Startup check | Pottery Studio (like the beta) starts only if `C:\p` exists, else "ERROR - call Paz Burstein 0523423548 for technical support" (2026-10-20) |
| 20 | `.exe` | `MainPottery\PotteryStudio\PotteryStudio.exe`; GitHub gets the code only (2026-10-20) |
| 11 | Button labels & controls | Exactly as specified in §2 (e.g. "Load STL", "Set Rim Plane", "Set Base Plane", radio buttons, "Add Texture Lines", "Save Scheme Image") – **not** the numbered labels of the old GUIs ("1. Load STL", "2. Align (Pick 3 Points on Base/Rim)", ...) |

## 9. Findings from stage 1 (2026-09-28)
- **Bug in the existing `circle_from_3_points_3d`**: its center was not equidistant from the 3 points (radius was only correct to the first point). This affected `main.py` ("Pick 3 Points on Rim") and `profile_test2.py` (rim center → slicing center and diameter). **Fixed on 2026-09-29** with the user's approval; it now gives the same result as `circle_through_3_points`.
- **Tests**: synthetic tests (random pose, tilted rim 15°, torus handle) all pass – alignment, auto up/down, axis modes, uv/drawing round-trip, mirror = reflection across tilted axis, rim line ⟂ axis, handle section of a 16 mm tube = 16 × 16 mm.
- **bilbil23.stl** (simulated 3-point picks on rim/base tips): rim Ø 8.0 cm, base Ø 5.7 cm, rim plane tilted 12.7° from base plane. Rim & centers axis modes give a clean profile (thickness 3.4–4.1 mm); pipeline < 1 s per slice.
  - With the ⟂ Base axis the neck is far off the axis, so the slice misses the neck. (Correction, stage 2: the simulated base clicks were not on the tip of the foot – the base circle was ~4 cm off-center – so the "~85 mm" offset was exaggerated by the test. Re-check with real clicks.) For this bilbil the user chooses the `centers` mode manually; the **default stays ⟂ Base for Whole Vessel** (user decision).
- **Handle section (stage 1 note)**: correct only when the profile angle shows the handle side-on (handle in the drawing plane); the lasso must enclose the whole handle, otherwise the section is partial. This is the user's responsibility (user decision) – show a short hint next to the Draw Handle Section Line button.
| 5 | Save/Load settings | Not included |
| 6 | Noise-cleaning lasso | Included |

## 10. Stage 2 notes (2026-09-29)
- Files: `pottery_studio.py` (class `PotteryStudio`), `RunStudio.bat` (optional argument: an STL path to load at start).
- Left panel: **Load STL** · **Vessel Type** (radio Sherd / Whole Vessel + **Symmetrical** checkbox) · **Planes** (**Set Rim Plane** / **Set Base Plane**, each shows ✓ and Ø when set; while picking the button reads "Cancel … Picking") · **Alignment Plane** (radio Rim / Base + height and rim↔base tilt).
- Tabs: **3D View** (shaded mesh; rim = red points/circle/center, base = blue) and **Log**.
- Picked points are stored in raw STL coordinates, so re-picking after alignment and switching the alignment plane both work.
- Alignment radio: default by vessel type; the user's choice is kept until the vessel type changes; a plane that is not set is disabled; if the preferred plane is missing, the other set plane is used.
- Collinear picks are rejected with a message. Loading a new STL resets the planes.
- Display: the user's screen is 4K with 250% text scaling (logical DPI 240, device pixel ratio 1). Sizes must be derived from the screen/font (window = 80% of the screen, panel width from its content, tab padding in `em`), never fixed pixels.
- Tested by driving the window from a script (simulated clicks through the picking callback). Real mouse clicking in the 3D view still needs the user's test.

## 11. Stage 3 notes (2026-09-29)
- Left panel: new **Profile** group – Angle spinbox (0–359°, wraps) + ◀ -5° / ◀ -1° / +1° ▶ / +5° ▶, Hull Ratio (default 0.03), status (axis, slice points, wall thickness or the pipeline error).
- Tabs: 3D View · **Scheme** · **Step Inspector** · **All Steps Grid** · Log.
  - 3D View shows the symmetry axis (black line) and the right-side slicing half-plane (translucent green); it follows the angle.
  - Scheme (drawing coordinates, alignment plane horizontal): filled profile, dash-dot axis up to the rim line, rim line from the axis to the right rim point (possibly tilted).
  - Step Inspector / Grid show the 6 steps in uv coordinates (axis vertical at u = 0).
- Axis: until stage 4 adds the selector, the default by vessel type is used (Sherd → ⟂ Rim, Whole → ⟂ Base; the other plane if the preferred one is missing).
- Performance: ~0.5 s per angle on bilbil23 (367k vertices). Angle/ratio changes are debounced (120 ms) so fast clicking computes once; only the visible 2D tab is redrawn.
- Chart DPI follows the screen text scaling (logical DPI × 0.9) so chart text is readable on the 4K/250% screen.
- **bilbil23 results** (accurate simulated base picks on the foot's resting ring – base Ø 8.4 cm; the neck leans ~6°, rim center 29 mm off the ⟂ Base axis):
  - ⟂ Base axis: at many angles both neck walls fall on the right side of the axis → the pipeline takes the far neck wall as the "inner wall" → wrong thickness (2.6–48.8 mm). Expected for this vessel; the user will use the `centers` axis (stage 4 selector).
  - `centers` axis: clean profile at every angle, thickness 3.5–4.8 mm.
  - The pipeline's base closure draws the ring foot with a small fork (inherited from `run_6step_pipeline_v2`). Revisit if the user wants.
- **Sherd (`ImageToStl.com_lmlk+sj (1).stl`)**: could not simulate reliable rim clicks – the long flat top edge is almost straight (probably a break), and 3 points on a short rim arc give an unstable plane/diameter (e.g. 55 cm and a 35° tilt from points 4 cm apart). **Needs the user's test with real clicks.** Possible improvement to discuss: fit the rim plane/circle from many rim points instead of exactly 3.

- **Stage 3 follow-up (2026-09-29):** added the **Symmetry Axis** group (radio: Perpendicular to Rim / Perpendicular to Base / Base Center → Rim Center; default by vessel type, reset when the type changes; modes needing a missing plane are disabled). The Log now records the 3 clicked points of each plane in STL coordinates, so a user's setup can be reproduced. If the slice misses a sherd at the current angle, the status says to rotate the angle.
- The simulated sherd rim clicks were placed on the wrong edge (user: "you placed the points wrong way"). Use the user's real clicks from the Log for sherd tests.

## 12. Step 4 thickness fix (2026-09-29, found by the user on `jug80223.stl`)
- Problem: the jug's thickness came out 0.2–0.6 mm at most angles although Step 3 split the walls correctly. Two causes in the original Step 4 (median distance of inner-wall hull vertices in the top 20 mm to the outer wall):
  1. Hull vertices crowd on the rounded lip, where inner and outer walls meet (distance ~0) → median pulled to ~0.
  2. The jug's narrow neck is scanned inside only ~5–10 mm below the rim; below that the hull's "inner" side runs along the outer wall (distance ~0).
- Fix in `run_6step_pipeline` (Studio copy only; `profile_test2.py` unchanged): resample the inner wall every 0.5 mm; use samples 1.5–20 mm below the rim peak; ignore samples < 1 mm from the outer wall (not a real inner wall); fall back to all samples if fewer than 3 remain.
- Results (12 angles): jug80223 (⟂ Rim) 3.2–4.7 mm (was 0.2–4.6); bilbil23 (centers) 3.5–5.2 mm (unchanged); synthetic 6 mm wall 5.4 mm (unchanged).
- Note: jug80223 is scanned upside down (rim at the bottom) and has a rounded base – no base ring to click, so it uses the rim plane only.

## 13. Stage 4 notes – left side (2026-09-29)
- **Symmetrical** (checkbox on): left side = mirror (u → −u, i.e. across the possibly tilted axis) of the right profile's **outer wall** – `diag['outer_coords']` for a completed profile, else `outer_wall_coords(polygon)` (outline between lowest and highest point, the side farther from the axis). Drawn as an outline (not filled).
- **Not symmetrical**: left side = `half_view_outline(...)` – concave hull (ratio 0.1, 1 mm grid, holes kept) of the real left half's projection (u ≤ 0), clipped at the axis and below the rim line. Computed per angle (~0.7 s on bilbil23, 0.1 s on jug80223); toggling the checkbox recomputes only the left side.
- **Rim line** across both sides: right end = rim circle ∩ slicing plane (or the profile's top point without a rim plane); left end = mirror of the right end (symmetrical) or the real crossing (not symmetrical).
- Axis (dash-dot) from the lowest drawn point up to the rim line.
- Tested: bilbil23 (Whole, centers axis, tilted in the drawing) – mirror follows the tilted axis; non-symmetrical view shows the real handle with its opening. jug80223 (Whole, ⟂ Rim) – both modes OK.
- Possible polish (not done): the non-symmetrical outline is slightly faceted on small vessels (1 mm grid) – could be smoothed.

## 14. Stage 5 notes – handle & noise (2026-09-29)
> The handle part below (one angle, handle masked out of the slice) is **superseded by §16** (two angles). Noise cleaning is unchanged.
- Left panel: **Handle** group (hint "Rotate the angle until the handle is seen side-on, then lasso it." · **Lasso Handle** · **Clear Handle** · **Add Handle to Left Side** (toggle; reads "Remove Handle from Left Side" when on; enabled only if Symmetrical and a handle is marked) · **Draw Handle Section Line** (enabled when a handle is marked) · status with the section size). **Clean Noise** group (**Lasso Clean Noise** · **Restore Removed Points (n)**).
- The lassos work on the **Scheme** (drawing coordinates) and the **Step Inspector** (uv); both are converted to uv. Lassos are re-attached after every redraw (`ax.clear()` detaches them).
- Handle: the lasso polygon is stored in uv (not a point mask) → the pipeline's handle mask is recomputed for every slice; small angle changes keep the handle. Changing the planes, the alignment, the vessel type or the symmetry axis clears the handle (logged), since uv would no longer match.
  - External view: `handle_outline()` = concave hull (holes kept) of right-half points inside the lasso, drawn as an outline **before** the filled section so the section covers the handle roots.
  - Left copy: mirror (u → −u) of the handle outline.
  - Section line: click-drag on the Scheme → uv → `handle_section()`; filled black, drawn **above the handle** (top of the handle outline + gap), with t along the drawn line and s perpendicular; dashed leader to the line's midpoint; a short cut mark on the handle. Only one section; drawing again replaces it. If the line misses the handle, the status says so and the line is shown faintly in red.
- Noise: removes points in the lasso – right side within the 2 mm profile slab; left side (non-symmetrical only) the whole left half's projection. Stored as a keep-mask over the vertices (survives angle/axis/alignment changes; reset on Load STL).
- Tested on bilbil23 (Whole Vessel, centers axis, angle 98° = handle side-on): handle lasso → 5,170 slice points excluded from the profile, wall thickness unchanged (4.5 mm), neck wall continues behind the handle; section 8.2 × 19.0 mm (strap handle); +2° keeps the handle (7.7 × 19.2 mm); noise lasso 711 points removed and restored; axis change clears the handle.

## 15. Complete Wall – drawn wall lines (REMOVED 2026-09-29)
- Built for jug80223 (broken handle stump covering the outer wall), then **removed completely at the user's request** (GUI group, `wall_line_points()` and all related code): drawing the outer wall to evaluate the wall where a handle sits was not accurate enough. Replaced by the two-angle handle procedure (§16).

## 16. Two-angle handle procedure (2026-09-29, replaces §15; user's idea)
- **Handle angle:** the user sets the angle where the handle is seen side-on and lassos it (Scheme or Step Inspector → Step 1). The handle's 3D points = right-half points inside the lasso (`handle_mask3d`), its outline is computed once at that angle.
- **Section angle:** right after the lasso the Angle moves automatically to the nearest angle whose 2 mm slice misses the handle: `handle_free_angle()` = the handle's angular extent around the axis (each point widened by the slab half-width at its radius) + 5° margin, on the closer side. The user may adjust it (hint: keep it close to the handle).
- **Section:** built from all points **except the handle's** (`active_points(exclude_handle=True)`) → the whole cross-section and its thickness are real scan data at the section angle; nothing is completed or drawn by hand.
- **Handle drawing:** both slicing frames rotate around the same axis, so the handle's uv at its own angle is exactly the handle rotated onto the section plane → the stored outline is drawn with the current frame. The section line is drawn on the Scheme at the section angle and converted to the shared uv; `handle_section()` uses the handle frame. Add Handle to Left Side mirrors the same outline.
- **Status** (Handle group): "Handle at 82° · section at 106° (+24°)"; warns "The section cuts through the handle – move the Angle a little further…" when > 20 handle points are within the slice; section size.
- A new lasso replaces the handle (the old one is cleared first). Clear Handle keeps the current angle. Planes/alignment/type/axis changes clear the handle (logged).
- Step Inspector Step 1 shows the handle outline in red ("Handle (from 82°)") – it is not part of the slice.
- Tested: jug80223 (⟂ Rim) stump at 82° → section 106°, thickness 3.0 mm (was 1.1 mm with the stump removed at 82°), full wall from the rim; warning at 84°. bilbil23 (centers) handle at 98° → section 77°, thickness 4.9 mm, handle section 8.2 × 19.0 mm (same as before), left copy OK; +3° keeps everything.
- Known, accepted: on a hand-made vessel the rotated handle's roots may miss the section wall by ~1 mm (jug stump); where the lasso cut the handle root the outline has a straight edge.

## 17. One / two angles – user's choice (2026-09-30)
- Handle group: checkbox **Section at a Nearby Angle (without the handle)**, **unchecked by default**.
  - **Off (one angle, default):** after the lasso the Angle stays at the handle angle; the section is built from that slice without the handle's points (same result as the original stage-5 method). Status: "Handle and section at 82°". No "cuts through the handle" warning (the section is at the handle on purpose).
  - **On (two angles, §16):** after the lasso the Angle moves to the nearest angle without the handle (`handle_free_angle`).
  - Toggling after a lasso moves the Angle between the handle angle and that nearest free angle; the handle (lasso, section line, left copy) is kept.
- The nearest free angle is computed at lasso time (`handle_free`) and reset with the handle.
- Tested on jug80223: lasso at 82° → stays 82° (thickness 1.1 mm, wall missing under the stump) → checkbox on → 106° (3.0 mm) → off → back to 82°. bilbil23 with the checkbox on → 77°, section 8.2 × 19.0 mm.

## 18. Stage 6 notes – finishing the scheme (2026-09-30)
- Left panel: **Finish Scheme** group – **Add Texture Lines** (toggle; click-drag straight lines on the Scheme, as many as needed, click the button again to stop), **Undo Last Line**, **Save Scheme Image**.
- Texture lines are stored in uv (they stay on the vessel if the drawing's tilt changes); kept on angle changes; cleared (logged) when the planes/alignment/type/axis change and on Load STL; not cleared by Clear Handle.
- **Rim diameter**: "Rim Diameter: X cm" above the right end of the rim line, only when the rim plane is set (3 points).
- **Scale bar**: 10 cm, alternating black/white centimetres, under the vessel, centred on the bottom of the axis, labels "0" and "10 cm".
- The scheme's limits include the labels (text is not part of matplotlib's automatic limits).
- **Save Scheme Image**: dialog with default `<STL name>_scheme.png` in the STL's folder; PNG or PDF (extension added from the chosen filter if typed without one); 300 dpi, `bbox_inches='tight'`, white background; saves the scheme as drawn, without helper markings (faint red invalid section line, handle lasso preview); any active drawing tool is switched off first.
- Tested on bilbil23 (Whole, centers axis, two angles, handle + section + left copy, 3 texture lines → undo → 2): PNG 823 × 1648 px at 300 dpi and PDF saved; default name `bilbil23_scheme.png` in the models folder; scale bar consistent with the vessel height (27.9 cm ≈ 2.8 bar lengths).
- Note: the saved image is not at a fixed print scale (e.g. 1:1); the scale bar gives the scale. A fixed-scale export could be added if needed.

## 19. Usage note – vessels scanned inside (2026-10-16)
- `ImageToStl.com_scan.stl` is a **chalice** (bowl on a solid stem and a hollow, open foot), scanned inside and out. With Whole Vessel's default (Inner Wall Fully Scanned **off**) the 6-step completion draws a wrong base (it expects a base reaching the axis; here the "bottom center" was found ~30 mm from the axis).
- Fix = check **Inner Wall Fully Scanned** → correct section at all tested angles (bowl, floor, solid stem to the axis, hollow foot). No code change.
- Idea (not done): detect a scanned inner wall automatically and suggest the checkbox, or warn when the completion clearly does not fit the shape.

## 20. "Inner Wall Fully Scanned" – filled section from the mesh cut (2026-10-18)
- Problem (user, chalice `ImageToStl.com_scan.stl`): with the box checked the right side was not black. The concave hull (ratio 0.03) of the slice points collapsed into thin strips along the two surfaces (area 355 mm² instead of ~2,100 mm²): the scan is a shell (points only on the surfaces), and on a large vessel the hull's relative threshold was smaller than the 6 mm wall.
- New method `scanned_section()` / `run_scanned_profile()` (user's idea: close the shape with the axis line, then remove it):
  1. cut the **mesh** with the slicing plane (exact section lines; no ±2 mm smearing), keep the right side (u ≥ 0);
  2. add the **symmetry axis as a line** from the bottom up to the rim line – closes the right half where clay reaches the axis (solid stem/base);
  3. draw everything on a 0.2 mm grid, close tiny scan gaps (2 px);
  4. "paint the air" from the image border (open hollows – inside of a bowl, hollow foot – are reached through their openings); what the paint does not reach = clay = black;
  5. remove the axis line where it crossed air; vectorize (contourpy + polygonize).
- Used only when **Inner Wall Fully Scanned** is checked (sherds by default); Hull Ratio is disabled then. The completion pipeline (box unchecked) is unchanged.
- Noise removal and the handle are respected: triangles touching removed or handle vertices are left out of the cut (cached aligned mesh, `section_mesh()`).
- Step Inspector Step 2 / Grid show the filled section ("Filled section (mesh cut)").
- Results: chalice 2,101–2,375 mm² at 0°/150°/300° (was 355), solid stem to the axis, hollows white; sherd: the fill follows the true surface exactly (the old hull was ~1 mm too wide on each side because of the ±2 mm slab). A large unscanned hole in a wall may stay white (shows where the scan is missing).
- Speed: section ~0.65 s on 1M vertices. Also `outline_polygon()` deduplication now uses an integer cell key instead of `np.unique(axis=0)` (same cells, 1.6 s → 0.2 s) → a full update on the chalice (non-symmetrical) went from ~4 s to ~2 s.
- **Beta frozen:** `pottery_studio_beta.py` now runs the copy in `beta_amit/` (the code inside `PotteryStudioBetaAmit.exe`); this change is in the regular version only.

## 21. Project folders (2026-10-19, user's request: one folder per version, nothing deleted)
| Folder | Contents |
|---|---|
| `studio/` | `pottery_studio.py`, `RunStudio.bat` – the current Pottery Studio |
| `core/` | `pottery_processor.py` – shared calculations (studio + legacy) |
| `beta_amit/` | `pottery_studio_beta.py`, `RunStudioBeta.bat`, frozen copy of `pottery_studio.py` + `pottery_processor.py` (= the code in `PotteryStudioBetaAmit.exe`) |
| `legacy/` | `main.py`, `profile_test.py`, `profile_test2.py` + `RunApp.bat`, `RunProfileTest.bat`, `RunProfileTest2.bat` |
| `docs/` | `studio_plan.md`, `licensing_plan.md`, `handles_plan.md` |
| `media/` | the `.png` images and `.mp4` videos (git-ignored) |
| root | `requirements.txt`, `.gitignore`, `.agents/AGENTS.md` |
- Files moved with `git mv` (history kept); nothing deleted.
- `studio/pottery_studio.py` adds `../core` to `sys.path`; the beta adds its own folder (frozen copy); the legacy launchers set `PYTHONPATH=..\core` and `cd` to their folder – the legacy `.py` files were not changed.
- Each launcher starts its script by full path (`%~dp0`) → works from any working directory (drag-and-drop of an STL). All 5 launchers tested: each program window opens.
- `.gitignore`: `__pycache__/`, `*.pyc`, `media/`. (The one cache file already tracked in git, `__pycache__/pottery_processor.cpython-311.pyc`, was left as is – nothing removed.)
