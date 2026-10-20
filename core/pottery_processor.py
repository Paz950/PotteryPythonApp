import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull

from shapely.geometry import Point, LineString, Polygon, MultiPoint, box
from shapely import concave_hull
from shapely.validation import make_valid


def generate_whole_vessel_profile(points_2d, gap_threshold=15.0, fallback_thickness=None):
    """
    Generates a solid vessel profile polygon from a 2D right-side profile slice.
    Implements the full 6-step pipeline:
      1. Handle Rejection via Z-Binning & Gap Detection
      2. Profile Boundary Extraction via Concave Hull
      3. Outer/Inner Wall Splitting
      4. Automatic Perpendicular Thickness Measurement
      5. Robust Inner Wall Offset
      6. Flat Base Closure & Topology Resolution

    Args:
        points_2d: Nx2 numpy array (X, Z) of right-side profile points.
        gap_threshold: X-gap in mm to detect handles (default 15mm).
        fallback_thickness: Manual override thickness (from slider) used when
                           auto-measurement gives a value below 3mm (scan noise).

    Returns:
        (shape, thickness, error_msg):
          - shape: shapely Polygon or None on failure
          - thickness: the wall thickness used (auto or fallback)
          - error_msg: string describing failure, or None on success
    """
    if points_2d is None or len(points_2d) < 10:
        return None, 0.0, "Not enough profile points (need >= 10)"

    z_min, z_max = np.min(points_2d[:, 1]), np.max(points_2d[:, 1])

    # ---------------------------------------------------------
    # STEP 1: Handle Rejection (Body Tracking)
    # ---------------------------------------------------------
    try:
        bins = np.arange(z_min, z_max + 2.0, 2.0)
        cleaned_points = []
        for i in range(len(bins) - 1):
            mask = (points_2d[:, 1] >= bins[i]) & (points_2d[:, 1] < bins[i + 1])
            pts = points_2d[mask]
            if len(pts) == 0:
                continue
            pts = pts[np.argsort(pts[:, 0])]
            gaps = np.diff(pts[:, 0])
            gap_indices = np.where(gaps > gap_threshold)[0]
            if len(gap_indices) > 0:
                pts = pts[:gap_indices[0] + 1]
            cleaned_points.append(pts)

        if len(cleaned_points) == 0:
            return None, 0.0, "Step 1 failed: all Z-bins were empty after handle rejection"

        cleaned_points = np.vstack(cleaned_points)

        if len(cleaned_points) < 10:
            return None, 0.0, f"Step 1 failed: only {len(cleaned_points)} points remain after handle rejection"
    except Exception as e:
        return None, 0.0, f"Step 1 exception (Handle Rejection): {e}"

    # ---------------------------------------------------------
    # STEP 2: Extract Outer and Inner Boundary via Concave Hull
    # ---------------------------------------------------------
    try:
        mp = MultiPoint(cleaned_points)
        hull = make_valid(concave_hull(mp, ratio=0.15, allow_holes=False))

        if hull.geom_type == 'MultiPolygon':
            hull = max(hull.geoms, key=lambda a: a.area)

        if hull.geom_type != 'Polygon' or hull.is_empty:
            return None, 0.0, f"Step 2 failed: concave_hull produced {hull.geom_type} instead of Polygon"

        coords = np.array(hull.exterior.coords)
    except Exception as e:
        return None, 0.0, f"Step 2 exception (Concave Hull): {e}"

    # ---------------------------------------------------------
    # STEP 3: Outer/Inner Wall Splitting
    # ---------------------------------------------------------
    try:
        # Find the Rim Peak (highest point)
        rim_idx = np.argmax(coords[:, 1])
        rim_z = coords[rim_idx, 1]

        # Find the Bottom Center point (innermost point near the base)
        z_mid = (rim_z + z_min) / 2.0
        bottom_indices = np.where(coords[:, 1] < z_mid)[0]
        if len(bottom_indices) == 0:
            return None, 0.0, "Step 3 failed: no hull vertices found below Z midpoint"
        bottom_center_idx = bottom_indices[np.argmin(coords[bottom_indices, 0])]

        # Split the hull exterior loop into two distinct paths
        idx1, idx2 = rim_idx, bottom_center_idx
        if idx1 < idx2:
            path1 = coords[idx1:idx2 + 1]
            path2 = np.vstack((coords[idx2:], coords[:idx1 + 1]))
        else:
            path1 = coords[idx2:idx1 + 1]
            path2 = np.vstack((coords[idx1:], coords[:idx2 + 1]))

        # The path with the larger average X is the outer wall
        if np.mean(path1[:, 0]) > np.mean(path2[:, 0]):
            outer_coords, inner_coords = path1, path2
        else:
            outer_coords, inner_coords = path2, path1

        # Ensure outer_coords flows geometrically upwards: Bottom to Rim
        if abs(outer_coords[0, 1] - rim_z) < abs(outer_coords[-1, 1] - rim_z):
            outer_coords = outer_coords[::-1]

        # Ensure inner_coords flows downwards: Rim to Base
        if abs(inner_coords[-1, 1] - rim_z) < abs(inner_coords[0, 1] - rim_z):
            inner_coords = inner_coords[::-1]

        outer_line = LineString(outer_coords)
    except Exception as e:
        return None, 0.0, f"Step 3 exception (Wall Splitting): {e}"

    # ---------------------------------------------------------
    # STEP 4: Automatic Perpendicular Thickness Measurement
    # ---------------------------------------------------------
    try:
        inner_pts = [p for p in inner_coords if p[1] > rim_z - 20.0]
        if len(inner_pts) < 5:
            inner_pts = [p for p in inner_coords if p[1] > rim_z - 10.0]

        distances = [Point(p).distance(outer_line) for p in inner_pts]
        auto_thickness = np.median(distances) if distances else 0.0

        # If auto-measurement is below 3mm (scan noise), use fallback
        MIN_WALL_THICKNESS = 3.0
        if auto_thickness < MIN_WALL_THICKNESS:
            if fallback_thickness is not None and fallback_thickness >= MIN_WALL_THICKNESS:
                thickness = fallback_thickness
                print(f"[Thickness] Auto={auto_thickness:.1f}mm (too thin, scan noise). Using slider fallback={thickness:.1f}mm")
            else:
                thickness = 5.0  # Reasonable ceramic default
                print(f"[Thickness] Auto={auto_thickness:.1f}mm (too thin). Using default={thickness:.1f}mm")
        else:
            thickness = auto_thickness
            print(f"[Thickness] Auto-measured={thickness:.1f}mm from {len(inner_pts)} rim points")
    except Exception as e:
        thickness = fallback_thickness if fallback_thickness and fallback_thickness >= 3.0 else 5.0
        print(f"[Thickness] Measurement failed ({e}). Using fallback={thickness:.1f}mm")

    # ---------------------------------------------------------
    # STEP 5: Synthetic Inner Wall Offset
    # ---------------------------------------------------------
    try:
        # offset_curve default side='left' pushes towards X=0 for a Bottom->Up line
        synthetic_inner = outer_line.offset_curve(thickness, join_style=1)

        if synthetic_inner.is_empty:
            return None, thickness, f"Step 5 failed: offset_curve produced empty geometry (thickness={thickness:.1f}mm)"

        # Handle MultiLineString from offset_curve (swallowtails)
        if synthetic_inner.geom_type == 'MultiLineString':
            synthetic_inner = max(synthetic_inner.geoms, key=lambda geom: geom.length)
    except Exception as e:
        return None, thickness, f"Step 5 exception (Offset Curve, thickness={thickness:.1f}mm): {e}"

    # ---------------------------------------------------------
    # STEP 6: Base Closure (The Foot)
    # ---------------------------------------------------------
    try:
        inner_base_z = z_min + thickness
        clip_box = box(-1000, inner_base_z, 1000, rim_z + 1000)
        clipped_inner = synthetic_inner.intersection(clip_box)

        if clipped_inner.is_empty:
            # Try without clipping as fallback
            print("[Base Closure] Clipping produced empty result, using unclipped inner wall")
            clipped_inner = synthetic_inner

        if clipped_inner.geom_type == 'MultiLineString':
            clipped_inner = max(clipped_inner.geoms, key=lambda geom: geom.length)

        if clipped_inner.geom_type == 'GeometryCollection':
            lines = [g for g in clipped_inner.geoms if g.geom_type == 'LineString']
            if lines:
                clipped_inner = max(lines, key=lambda geom: geom.length)
            else:
                return None, thickness, "Step 6 failed: clipping produced no usable LineString"

        inner_offset_coords = np.array(clipped_inner.coords)

        # Ensure the inner offset coordinates flow downwards from Rim to Base
        if inner_offset_coords[0, 1] < inner_offset_coords[-1, 1]:
            inner_offset_coords = inner_offset_coords[::-1]

        # Topology Assembly
        ring = []
        p_bottom_center = outer_coords[0]
        ring.append([0, p_bottom_center[1]])
        ring.append([p_bottom_center[0], p_bottom_center[1]])
        ring.extend(outer_coords.tolist())
        ring.extend(inner_offset_coords.tolist())
        p_inner_bottom = inner_offset_coords[-1]
        ring.append([0, p_inner_bottom[1]])
        ring.append([0, p_bottom_center[1]])

        final_shape = make_valid(Polygon(ring).buffer(0))

        if final_shape.is_empty:
            return None, thickness, "Step 6 failed: final polygon is empty after buffer(0)"

        return final_shape, thickness, None

    except Exception as e:
        return None, thickness, f"Step 6 exception (Base Closure): {e}"


def generate_sherd_profile(points_2d):
    """
    Generates a filled polygon for a sherd profile using Concave Hull
    with Delaunay triangulation (allows holes for double-wall sherds).

    Args:
        points_2d: Nx2 numpy array (X, Z) of right-side profile points.

    Returns:
        A shapely Polygon/MultiPolygon, or None on failure.
    """
    if points_2d is None or len(points_2d) < 10:
        return None

    try:
        rp_rounded = np.round(points_2d * 2) / 2
        rp_unique = np.unique(rp_rounded, axis=0)
        if len(rp_unique) < 4:
            return None
        mp = MultiPoint(rp_unique)
        shape = make_valid(concave_hull(mp, ratio=0.1, allow_holes=True))
        return shape
    except Exception as e:
        print("Sherd profile generation error:", e)
        return None

def align_by_3_points(points, p1, p2, p3):
    """
    Aligns the point cloud so that the plane defined by p1, p2, p3 is horizontal (aligned to Z-axis).
    points: Nx3 numpy array
    """
    # Calculate plane normal
    v1 = p2 - p1
    v2 = p3 - p1
    normal = np.cross(v1, v2)
    norm = np.linalg.norm(normal)
    if norm == 0:
        return points # Invalid points
    normal = normal / norm
    
    # Target normal is Z-axis
    target = np.array([0, 0, 1])
    if np.dot(normal, target) < 0:
        normal = -normal # Ensure normal points "up"
        
    axis = np.cross(normal, target)
    axis_len = np.linalg.norm(axis)
    
    if axis_len < 1e-6:
        return points # Already aligned
        
    axis = axis / axis_len
    angle = np.arccos(np.clip(np.dot(normal, target), -1.0, 1.0))
    
    # Create rotation matrix (Rodrigues' rotation formula)
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * np.dot(K, K)
    
    # Rotate around the mean of the 3 points
    center = np.mean([p1, p2, p3], axis=0)
    aligned_points = np.dot(points - center, R.T) + center
    return aligned_points

def extract_top_layer(points, top_percent=0.05):
    """Extracts the top points based on Z coordinate."""
    z_min = np.min(points[:, 2])
    z_max = np.max(points[:, 2])
    threshold = z_max - (z_max - z_min) * top_percent
    return points[points[:, 2] >= threshold]

def extract_bottom_layer(points, bottom_percent=0.05):
    """Extracts the bottom points based on Z coordinate."""
    z_min = np.min(points[:, 2])
    z_max = np.max(points[:, 2])
    threshold = z_min + (z_max - z_min) * bottom_percent
    return points[points[:, 2] <= threshold]

def fit_circle_2d(points_2d):
    """
    Fits a circle to 2D points using least squares.
    Returns (xc, yc, R)
    """
    def calc_R(xc, yc):
        return np.sqrt((points_2d[:, 0] - xc)**2 + (points_2d[:, 1] - yc)**2)
    
    def f_2(c):
        Ri = calc_R(*c)
        return Ri - Ri.mean()
    
    center_estimate = np.mean(points_2d[:, 0]), np.mean(points_2d[:, 1])
    center = least_squares(f_2, center_estimate).x
    xc, yc = center
    Ri = calc_R(xc, yc)
    R = Ri.mean()
    return xc, yc, R

def extract_profile(points, xc, yc, angle_deg, thickness=2.0, side='right'):
    """
    Extracts a 2D profile by slicing the point cloud with a vertical plane.
    side can be 'right', 'left', or 'both'.
    """
    angle_rad = np.radians(angle_deg)
    
    # Plane normal (perpendicular to the slice direction)
    nx = -np.sin(angle_rad)
    ny = np.cos(angle_rad)
    normal = np.array([nx, ny, 0])
    
    # A point on the plane is the center (xc, yc, 0)
    p0 = np.array([xc, yc, 0])
    
    # Distance from points to plane
    dist = np.abs(np.dot(points - p0, normal))
    
    profile_pts_3d = points[dist < thickness]
    
    # Project profile points to 2D: distance from center along the angle, and Z
    dir_vec = np.array([np.cos(angle_rad), np.sin(angle_rad)])
    
    xy_points = profile_pts_3d[:, :2] - np.array([xc, yc])
    # Dot product gives signed distance along the slice direction
    x_proj = np.dot(xy_points, dir_vec)
    z_proj = profile_pts_3d[:, 2]
    
    profile_2d = np.column_stack((x_proj, z_proj))
    if side == 'right':
        return profile_2d[profile_2d[:, 0] >= 0]
    elif side == 'left':
        return profile_2d[profile_2d[:, 0] <= 0]
    else:
        return profile_2d

def extract_facade_projection(points, xc, yc, angle_deg):
    """
    Extracts a thick projection of the left half of the vessel.
    """
    angle_rad = np.radians(angle_deg)
    dir_vec = np.array([np.cos(angle_rad), np.sin(angle_rad)])
    
    xy_points = points[:, :2] - np.array([xc, yc])
    x_proj = np.dot(xy_points, dir_vec)
    z_proj = points[:, 2]
    
    # Facade is usually on the left (negative x_proj)
    left_mask = x_proj <= 0
    return np.column_stack((x_proj[left_mask], z_proj[left_mask]))

def extract_horizontal_slice(points, z_height, thickness=2.0):
    """
    Extracts a horizontal slice (cross-section) of the vessel at a specific Z height.
    """
    dist = np.abs(points[:, 2] - z_height)
    slice_pts = points[dist < thickness]
    return slice_pts

def circle_from_3_points_3d(p1, p2, p3):
    """
    Computes the 3D circumcircle (center, radius, normal vector) for three 3D points.
    Returns: center_3d, radius, normal_vec
    """
    # Vectors
    v1 = p2 - p1
    v2 = p3 - p1
    
    # Normal of the plane
    normal = np.cross(v1, v2)
    norm_len = np.linalg.norm(normal)
    if norm_len < 1e-6:
        raise ValueError("Points are collinear")
    normal = normal / norm_len
    
    # Calculate circumcenter (equidistant from p1, p2, p3)
    axb = np.cross(v1, v2)
    center = p1 + np.cross(np.dot(v1, v1) * v2 - np.dot(v2, v2) * v1, axb) / (2 * norm_len**2)
    radius = np.linalg.norm(center - p1)
    
    # Ensure normal points "upwards" (positive Z)
    if normal[2] < 0:
        normal = -normal
        
    return center, radius, normal


def format_points_data(stl_path="", profile_angle=0, base_points=None,
                       rim_points=None, rim_fit=None, vessel_type="Sherd",
                       is_flipped=False, wall_thickness=5.0, cutoff_z=10):
    """
    Formats the picked points (Base and Rim) and profile parameters into a clean text format.
    """
    lines = []
    lines.append("# Pottery Sherd Analysis - Picked Points & Parameters")
    lines.append(f"STL_FILE: {stl_path}")
    lines.append(f"PROFILE_ANGLE: {profile_angle}")
    lines.append(f"VESSEL_TYPE: {vessel_type}")
    lines.append(f"IS_FLIPPED: {is_flipped}")
    lines.append(f"WALL_THICKNESS: {wall_thickness:.2f}")
    lines.append(f"CUTOFF_Z: {cutoff_z}")
    lines.append("")
    
    lines.append("[BASE_POINTS]")
    if base_points is not None and len(base_points) > 0:
        lines.append("# X, Y, Z (Points picked on Base for alignment)")
        for p in base_points:
            lines.append(f"{p[0]:.6f}, {p[1]:.6f}, {p[2]:.6f}")
    else:
        lines.append("# None picked")
    lines.append("")
    
    lines.append("[RIM_POINTS]")
    if rim_points is not None and len(rim_points) > 0:
        lines.append("# X, Y, Z (Points picked on Rim for circle fit)")
        for p in rim_points:
            lines.append(f"{p[0]:.6f}, {p[1]:.6f}, {p[2]:.6f}")
    else:
        lines.append("# None picked")
    lines.append("")
    
    lines.append("[RIM_FIT]")
    if rim_fit is not None:
        c = rim_fit.get('center', [0.0, 0.0, 0.0])
        r = rim_fit.get('radius', 0.0)
        n = rim_fit.get('normal', [0.0, 0.0, 1.0])
        lines.append(f"CENTER: {c[0]:.6f}, {c[1]:.6f}, {c[2]:.6f}")
        lines.append(f"RADIUS: {r:.6f}")
        lines.append(f"DIAMETER_CM: {(r * 2.0 / 10.0):.2f}")
        lines.append(f"NORMAL: {n[0]:.6f}, {n[1]:.6f}, {n[2]:.6f}")
    else:
        lines.append("# None calculated")
    lines.append("")
    
    return "\n".join(lines)


def parse_points_data(text_content):
    """
    Parses points data from text content (supports both custom text format and JSON).
    Returns a dict with keys:
      'stl_path', 'profile_angle', 'base_points', 'rim_points', 
      'rim_fit', 'vessel_type', 'is_flipped', 'wall_thickness', 'cutoff_z'
    """
    import json
    trimmed = text_content.strip()
    if trimmed.startswith("{") and trimmed.endswith("}"):
        try:
            data = json.loads(trimmed)
            return {
                'stl_path': data.get('stl_path', ''),
                'profile_angle': int(data.get('profile_angle', 0)),
                'base_points': np.array(data['base_points']) if data.get('base_points') else None,
                'rim_points': np.array(data['rim_points']) if data.get('rim_points') else None,
                'rim_fit': data.get('rim_fit', None),
                'vessel_type': data.get('vessel_type', 'Sherd'),
                'is_flipped': bool(data.get('is_flipped', False)),
                'wall_thickness': float(data.get('wall_thickness', 5.0)),
                'cutoff_z': int(data.get('cutoff_z', 10)),
            }
        except Exception:
            pass

    result = {
        'stl_path': '',
        'profile_angle': 0,
        'base_points': None,
        'rim_points': None,
        'rim_fit': None,
        'vessel_type': 'Sherd',
        'is_flipped': False,
        'wall_thickness': 5.0,
        'cutoff_z': 10,
    }
    
    current_section = None
    base_pts = []
    rim_pts = []
    rim_fit_dict = {}

    for line in text_content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
            
        if line.startswith("[") and line.endswith("]"):
            current_section = line[1:-1].strip().upper()
            continue
            
        if current_section is None:
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().upper()
                val = val.strip()
                if key == "STL_FILE":
                    result['stl_path'] = val
                elif key == "PROFILE_ANGLE":
                    try: result['profile_angle'] = int(float(val))
                    except: pass
                elif key == "VESSEL_TYPE":
                    result['vessel_type'] = val
                elif key == "IS_FLIPPED":
                    result['is_flipped'] = (val.lower() in ('true', '1', 'yes'))
                elif key == "WALL_THICKNESS":
                    try: result['wall_thickness'] = float(val)
                    except: pass
                elif key == "CUTOFF_Z":
                    try: result['cutoff_z'] = int(float(val))
                    except: pass
        elif current_section == "BASE_POINTS":
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                try:
                    base_pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                except: pass
        elif current_section == "RIM_POINTS":
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 3:
                try:
                    rim_pts.append([float(parts[0]), float(parts[1]), float(parts[2])])
                except: pass
        elif current_section == "RIM_FIT":
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().upper()
                val = val.strip()
                if key == "CENTER":
                    parts = [float(p.strip()) for p in val.split(",")]
                    rim_fit_dict['center'] = parts
                elif key == "RADIUS":
                    rim_fit_dict['radius'] = float(val)
                elif key == "NORMAL":
                    parts = [float(p.strip()) for p in val.split(",")]
                    rim_fit_dict['normal'] = parts

    if len(base_pts) > 0:
        result['base_points'] = np.array(base_pts)
    if len(rim_pts) > 0:
        result['rim_points'] = np.array(rim_pts)
    if rim_fit_dict:
        result['rim_fit'] = rim_fit_dict

    return result


# =====================================================================
# Pottery Studio geometry (see studio_plan.md)
#
# Coordinate systems used below:
#   * aligned 3D  - the cloud after alignment_transform(): the chosen
#                   alignment plane (rim or base) is horizontal, +Z is up.
#   * uv (axis)   - 2D coordinates inside the slicing plane:
#                   u = distance from the symmetry axis (right side u >= 0),
#                   v = distance along the symmetry axis.
#                   The axis is always the line u = 0, so the 6-step pipeline
#                   and mirroring (u -> -u) work unchanged even when the axis
#                   is tilted.
#   * drawing     - 2D scheme coordinates: aligned +Z is up. uv maps to the
#                   drawing by a pure rotation (true shape is preserved), so a
#                   tilted axis appears tilted in the scheme.
# =====================================================================

import shapely
from shapely import affinity


def rotation_between(v_from, v_to):
    """Rotation matrix that turns direction v_from onto direction v_to."""
    a = np.asarray(v_from, dtype=float)
    b = np.asarray(v_to, dtype=float)
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    axis = np.cross(a, b)
    s = np.linalg.norm(axis)
    c = np.dot(a, b)
    if s < 1e-9:
        if c > 0:
            return np.eye(3)
        # 180 degrees: rotate around any axis perpendicular to a
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-6:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        perp = perp / np.linalg.norm(perp)
        return 2.0 * np.outer(perp, perp) - np.eye(3)
    axis = axis / s
    K = np.array([
        [0, -axis[2], axis[1]],
        [axis[2], 0, -axis[0]],
        [-axis[1], axis[0], 0]
    ])
    angle = np.arctan2(s, c)
    return np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * np.dot(K, K)


def alignment_transform(p1, p2, p3, points=None, plane='base'):
    """
    Rotation that makes the plane through p1, p2, p3 horizontal (normal -> +Z).
    If `points` is given, the normal's direction is chosen so that the vessel
    body ends up above a base plane or below a rim plane (no manual flip).
    Returns (R, center); apply it with apply_alignment().
    """
    p1, p2, p3 = (np.asarray(p, dtype=float) for p in (p1, p2, p3))
    normal = np.cross(p2 - p1, p3 - p1)
    norm = np.linalg.norm(normal)
    if norm < 1e-9:
        raise ValueError("The 3 points are collinear")
    normal = normal / norm
    center = (p1 + p2 + p3) / 3.0

    if points is not None and len(points) > 0:
        side = np.median(np.dot(np.asarray(points) - center, normal))
        if (plane == 'base' and side < 0) or (plane == 'rim' and side > 0):
            normal = -normal
    elif normal[2] < 0:
        normal = -normal

    return rotation_between(normal, [0.0, 0.0, 1.0]), center


def apply_alignment(points, R, center):
    """Applies a rotation from alignment_transform() to Nx3 points (or one point)."""
    pts = np.asarray(points, dtype=float)
    return np.dot(pts - center, R.T) + center


def circle_through_3_points(p1, p2, p3):
    """
    Circle through three 3D points (circumcircle).
    Returns (center_3d, radius, normal) with the normal pointing up (+Z side).
    """
    p1, p2, p3 = (np.asarray(p, dtype=float) for p in (p1, p2, p3))
    a = p1 - p3
    b = p2 - p3
    axb = np.cross(a, b)
    denom = 2.0 * np.dot(axb, axb)
    if denom < 1e-12:
        raise ValueError("Points are collinear")
    center = p3 + np.cross(np.dot(a, a) * b - np.dot(b, b) * a, axb) / denom
    radius = np.linalg.norm(center - p1)
    normal = axb / np.linalg.norm(axb)
    if normal[2] < 0:
        normal = -normal
    return center, radius, normal


def build_symmetry_axis(mode, rim_circle=None, base_circle=None):
    """
    Builds the symmetry axis in aligned coordinates.

    mode: 'rim'     - perpendicular to the rim plane, through the rim center
          'base'    - perpendicular to the base plane, through the base center
          'centers' - through the base center and the rim center
    rim_circle / base_circle: (center, radius, normal) as returned by
          circle_through_3_points() on aligned points.
    Returns (axis_point, axis_dir) with axis_dir pointing up (+Z side).
    """
    if mode == 'rim':
        if rim_circle is None:
            raise ValueError("Rim plane is not set")
        pt, d = rim_circle[0], rim_circle[2]
    elif mode == 'base':
        if base_circle is None:
            raise ValueError("Base plane is not set")
        pt, d = base_circle[0], base_circle[2]
    elif mode == 'centers':
        if rim_circle is None or base_circle is None:
            raise ValueError("Both rim and base planes must be set")
        pt = base_circle[0]
        d = np.asarray(rim_circle[0], dtype=float) - np.asarray(base_circle[0], dtype=float)
    else:
        raise ValueError(f"Unknown axis mode: {mode}")

    pt = np.asarray(pt, dtype=float)
    d = np.asarray(d, dtype=float)
    length = np.linalg.norm(d)
    if length < 1e-9:
        raise ValueError("Axis direction is undefined (rim and base centers coincide)")
    d = d / length
    if d[2] < 0:
        d = -d
    return pt, d


def slice_frame(axis_point, axis_dir, angle_deg):
    """
    Builds the slicing frame: a half-plane that contains the symmetry axis,
    rotated by angle_deg around it.
    For a vertical axis this matches extract_profile() (angle 0 = +X direction).
    """
    a = np.asarray(axis_dir, dtype=float)
    a = a / np.linalg.norm(a)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(np.dot(ref, a)) > 0.95:
        ref = np.array([0.0, 1.0, 0.0])
    e0 = ref - np.dot(ref, a) * a
    e0 = e0 / np.linalg.norm(e0)
    e90 = np.cross(a, e0)

    t = np.radians(angle_deg)
    e = np.cos(t) * e0 + np.sin(t) * e90   # in-plane direction away from the axis (right side)
    n = np.cross(a, e)                     # slicing plane normal

    # Drawing "up" = aligned +Z as seen inside the slicing plane
    z = np.array([0.0, 0.0, 1.0])
    up_uv = np.array([np.dot(z, e), np.dot(z, a)])
    up_len = np.linalg.norm(up_uv)
    up_uv = up_uv / up_len if up_len > 1e-9 else np.array([0.0, 1.0])
    right_uv = np.array([up_uv[1], -up_uv[0]])

    return {
        'origin': np.asarray(axis_point, dtype=float),
        'a': a, 'e': e, 'n': n,
        'up_uv': up_uv, 'right_uv': right_uv,
        'angle_deg': angle_deg,
    }


def points_to_uv(points, frame):
    """
    Projects aligned 3D points into the slicing frame.
    Returns (uv, w): uv is Nx2 (u = from axis, v = along axis),
    w is the signed distance from the slicing plane.
    """
    rel = np.asarray(points, dtype=float) - frame['origin']
    u = np.dot(rel, frame['e'])
    v = np.dot(rel, frame['a'])
    w = np.dot(rel, frame['n'])
    return np.column_stack((u, v)), w


def uv_to_3d(uv, frame):
    """Maps uv coordinates (Nx2 or a single pair) back to aligned 3D points."""
    uv = np.atleast_2d(np.asarray(uv, dtype=float))
    return frame['origin'] + np.outer(uv[:, 0], frame['e']) + np.outer(uv[:, 1], frame['a'])


def uv_to_drawing(uv, frame):
    """Maps uv coordinates (Nx2) to drawing coordinates (aligned Z is up)."""
    uv = np.atleast_2d(np.asarray(uv, dtype=float))
    x = np.dot(uv, frame['right_uv'])
    y = np.dot(uv, frame['up_uv']) + frame['origin'][2]
    return np.column_stack((x, y))


def drawing_to_uv(xy, frame):
    """Inverse of uv_to_drawing()."""
    xy = np.atleast_2d(np.asarray(xy, dtype=float))
    x = xy[:, 0]
    y = xy[:, 1] - frame['origin'][2]
    return np.outer(x, frame['right_uv']) + np.outer(y, frame['up_uv'])


def geometry_uv_to_drawing(geom, frame):
    """Maps a shapely geometry from uv to drawing coordinates."""
    r, up = frame['right_uv'], frame['up_uv']
    return affinity.affine_transform(geom, [r[0], r[1], up[0], up[1], 0.0, frame['origin'][2]])


def mirror_uv(data):
    """Mirrors across the symmetry axis (u -> -u). Accepts Nx2 arrays or shapely geometries."""
    if hasattr(data, 'geom_type'):
        return affinity.scale(data, xfact=-1.0, yfact=1.0, origin=(0.0, 0.0))
    arr = np.array(data, dtype=float)
    arr[:, 0] = -arr[:, 0]
    return arr


def reflect_across_line_2d(pts, line_pt, line_dir):
    """Reflects Nx2 points across the 2D line through line_pt with direction line_dir."""
    pts = np.atleast_2d(np.asarray(pts, dtype=float))
    d = np.asarray(line_dir, dtype=float)
    d = d / np.linalg.norm(d)
    rel = pts - np.asarray(line_pt, dtype=float)
    along = np.outer(np.dot(rel, d), d)
    return np.asarray(line_pt, dtype=float) + 2.0 * along - rel


def extract_axis_profile(points, frame, thickness=2.0):
    """
    Right-side profile: points within `thickness` of the slicing plane with u >= 0.
    Returns Nx2 uv points (the input of run_6step_pipeline).
    """
    uv, w = points_to_uv(points, frame)
    mask = (np.abs(w) < thickness) & (uv[:, 0] >= 0)
    return uv[mask]


def extract_axis_half(points, frame, side='left'):
    """
    Projection of one half of the vessel onto the slicing plane (external view).
    side='left' returns u <= 0, side='right' returns u >= 0. Returns Nx2 uv points.
    """
    uv, _ = points_to_uv(points, frame)
    if side == 'left':
        return uv[uv[:, 0] <= 0]
    return uv[uv[:, 0] >= 0]


def outline_polygon(points_2d, ratio=0.1, resolution=1.0, allow_holes=True):
    """
    Outline (concave hull) of a 2D point cloud, downsampled to `resolution` mm
    so large clouds stay fast. Keeps inner voids (e.g. handle holes) when
    allow_holes is True. Returns the largest Polygon, or None.
    """
    if points_2d is None or len(points_2d) < 4:
        return None
    try:
        # One point per grid cell. A single integer key per cell is ~8x faster than
        # np.unique(axis=0) on large clouds (same result).
        cells = np.round(np.asarray(points_2d) / resolution).astype(np.int64)
        cells -= cells.min(axis=0)
        key = cells[:, 0] * (int(cells[:, 1].max()) + 1) + cells[:, 1]
        _, first = np.unique(key, return_index=True)
        rounded = cells[first].astype(float) * resolution + np.round(np.min(points_2d, axis=0) / resolution) * resolution
        if len(rounded) < 4:
            return None
        hull = make_valid(concave_hull(MultiPoint(rounded), ratio=ratio, allow_holes=allow_holes))
        if hull.geom_type == 'Polygon':
            return None if hull.is_empty else hull
        polys = [g for g in getattr(hull, 'geoms', []) if g.geom_type == 'Polygon']
        return max(polys, key=lambda g: g.area) if polys else None
    except Exception as e:
        print("Outline error:", e)
        return None


def _line_parts(geom):
    """LineStrings contained in a shapely geometry (for clipping results)."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'LineString':
        return [geom]
    if geom.geom_type == 'LinearRing':
        return [LineString(geom.coords)]
    parts = []
    for g in getattr(geom, 'geoms', []):
        parts.extend(_line_parts(g))
    return parts


def outer_wall_coords(poly):
    """
    Outer wall of a profile polygon (uv): the part of its outline between the lowest
    and the highest point that lies farther from the axis. Ordered bottom -> top.
    """
    coords = np.array(poly.exterior.coords)[:-1]
    top = int(np.argmax(coords[:, 1]))
    bottom = int(np.argmin(coords[:, 1]))
    n = len(coords)
    path1 = coords[[(top + i) % n for i in range((bottom - top) % n + 1)]]
    path2 = coords[[(bottom + i) % n for i in range((top - bottom) % n + 1)]]
    outer = path1 if np.mean(path1[:, 0]) > np.mean(path2[:, 0]) else path2
    if outer[0, 1] > outer[-1, 1]:
        outer = outer[::-1]
    return outer


def rim_line_v(rim_left_uv, rim_right_uv):
    """Height (v) of the rim line at a given u, as a function; None if undefined."""
    if rim_left_uv is None or rim_right_uv is None:
        return None
    (u0, v0), (u1, v1) = rim_left_uv, rim_right_uv
    if abs(u1 - u0) < 1e-9:
        return lambda u: max(v0, v1)
    return lambda u: v0 + (u - u0) * (v1 - v0) / (u1 - u0)


def half_view_outline(points, frame, rim_v=None, ratio=0.1, resolution=1.0):
    """
    External view of the left half of the vessel (u <= 0) as outline lines in uv:
    the concave hull of the half's projection (holes kept, e.g. a handle opening),
    clipped at the axis and at the rim line (rim_v: function u -> v, optional).
    Returns a list of LineStrings.
    """
    left = extract_axis_half(points, frame, 'left')
    poly = outline_polygon(left, ratio=ratio, resolution=resolution, allow_holes=True)
    if poly is None:
        return []
    u_min = left[:, 0].min() - 10.0
    v_min = left[:, 1].min() - 10.0
    if rim_v is not None:
        top_left, top_axis = rim_v(u_min), rim_v(-0.1)
    else:
        top_left = top_axis = left[:, 1].max() + 10.0
    top_left, top_axis = max(top_left, v_min + 1.0), max(top_axis, v_min + 1.0)
    clip = Polygon([(u_min, v_min), (-0.1, v_min), (-0.1, top_axis), (u_min, top_left)])
    lines = []
    for ring in [poly.exterior, *poly.interiors]:
        lines.extend(_line_parts(LineString(ring.coords).intersection(clip)))
    return lines


def lasso_point_mask(points, frame, lasso_uv, side='right', slab=None):
    """
    Boolean mask of 3D points whose projection (uv) falls inside a lasso polygon.
    side: 'right' (u >= 0), 'left' (u <= 0) or 'both'.
    slab: if given, only points within this distance of the slicing plane (the profile slice).
    """
    uv, w = points_to_uv(points, frame)
    mask = points_in_polygon(uv, lasso_uv)
    if side == 'right':
        mask &= uv[:, 0] >= 0
    elif side == 'left':
        mask &= uv[:, 0] <= 0
    if slab is not None:
        mask &= np.abs(w) < slab
    return mask


def handle_outline(points, frame, lasso_uv, ratio=0.1, resolution=1.0):
    """
    External view of a handle on the right side: outline (uv Polygon, holes kept) of the
    right-half points whose projection falls inside the handle lasso. None if too few points.
    """
    mask = lasso_point_mask(points, frame, lasso_uv, side='right')
    if np.sum(mask) < 4:
        return None
    uv, _ = points_to_uv(np.asarray(points)[mask], frame)
    return outline_polygon(uv, ratio=ratio, resolution=resolution, allow_holes=True)


def handle_free_angle(handle_points, axis_point, axis_dir, handle_angle, slab=2.0, margin=5.0):
    """
    Nearest profile angle (degrees, 0-359) whose slice misses the handle: the handle's angular
    extent around the axis (widened by the slab half-width at each point's radius) plus a margin,
    on whichever side of the handle is closer.
    """
    pts = np.asarray(handle_points, dtype=float)
    if len(pts) == 0:
        return int(round(handle_angle)) % 360
    fr0 = slice_frame(axis_point, axis_dir, 0.0)
    rel = pts - fr0['origin']
    x = np.dot(rel, fr0['e'])
    y = np.dot(rel, np.cross(fr0['a'], fr0['e']))
    r = np.hypot(x, y)
    keep = r > 1e-6
    offset = (np.degrees(np.arctan2(y[keep], x[keep])) - handle_angle + 180.0) % 360.0 - 180.0
    half_width = np.degrees(np.arcsin(np.clip(slab / r[keep], 0.0, 1.0)))
    after = handle_angle + np.max(offset + half_width) + margin
    before = handle_angle + np.min(offset - half_width) - margin
    best = after if abs(after - handle_angle) <= abs(before - handle_angle) else before
    return int(round(best)) % 360


def points_in_polygon(points_2d, polygon_vertices):
    """Boolean mask of the Nx2 points that lie inside the polygon (e.g. a lasso)."""
    pts = np.asarray(points_2d, dtype=float)
    if len(pts) == 0 or polygon_vertices is None or len(polygon_vertices) < 3:
        return np.zeros(len(pts), dtype=bool)
    poly = make_valid(Polygon(polygon_vertices))
    return shapely.contains_xy(poly, pts[:, 0], pts[:, 1])


def circle_slice_intersections(center, radius, normal, frame):
    """
    Where a 3D circle (e.g. the rim) crosses the slicing plane.
    Returns a 2x2 uv array sorted by u (left point first), or None if the
    circle does not cross the plane.
    Used for the rim line of the scheme, which may be tilted.
    """
    c = np.asarray(center, dtype=float)
    nrm = np.asarray(normal, dtype=float)
    nrm = nrm / np.linalg.norm(nrm)
    ref = np.array([1.0, 0.0, 0.0]) if abs(nrm[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    b1 = np.cross(nrm, ref)
    b1 = b1 / np.linalg.norm(b1)
    b2 = np.cross(nrm, b1)

    # (c + r*(cos(f) b1 + sin(f) b2) - o) . n = 0   ->   A cos f + B sin f = C
    n = frame['n']
    A = radius * np.dot(b1, n)
    B = radius * np.dot(b2, n)
    C = -np.dot(c - frame['origin'], n)
    amp = np.hypot(A, B)
    if amp < 1e-9 or abs(C) > amp:
        return None
    phi0 = np.arctan2(B, A)
    delta = np.arccos(np.clip(C / amp, -1.0, 1.0))
    pts3d = np.array([c + radius * (np.cos(f) * b1 + np.sin(f) * b2)
                      for f in (phi0 - delta, phi0 + delta)])
    uv, _ = points_to_uv(pts3d, frame)
    return uv[np.argsort(uv[:, 0])]


def handle_section(points, frame, lasso_uv, line_uv, slab=1.5, n_bins=72):
    """
    Handle cross-section along a line the user drew across the handle.

    The drawn line (in uv) and the viewing direction (the slicing plane normal)
    define a 3D cutting plane perpendicular to the handle. Handle points
    (right half, inside the lasso) within `slab` mm of that plane are projected
    onto it and filled (filled_section_polygon).

    Returns a dict or None:
      'polygon'     - filled section in local coordinates: t along the drawn line
                      (0 = the line's midpoint), s = depth toward the viewer
                      (0 = the section's own center)
      'mid_uv'      - midpoint of the drawn line (uv)
      'line_dir_uv' - unit direction of the drawn line (uv)
      'n_points'    - number of points used
    """
    line_uv = np.asarray(line_uv, dtype=float)
    d_uv = line_uv[1] - line_uv[0]
    length = np.linalg.norm(d_uv)
    if length < 1e-6:
        return None
    d_uv = d_uv / length
    mid_uv = line_uv.mean(axis=0)

    uv, _ = points_to_uv(points, frame)
    handle_mask = (uv[:, 0] >= 0) & points_in_polygon(uv, lasso_uv)
    handle_pts = np.asarray(points)[handle_mask]
    if len(handle_pts) < 4:
        return None

    p0 = uv_to_3d(mid_uv, frame)[0]
    d3 = d_uv[0] * frame['e'] + d_uv[1] * frame['a']
    m = np.cross(d3, frame['n'])           # cutting plane normal (along the handle)
    rel = handle_pts - p0
    t = np.dot(rel, d3)
    s = np.dot(rel, frame['n'])
    dist = np.dot(rel, m)
    sel = (np.abs(dist) < slab) & (np.abs(t) <= length / 2.0 + slab)
    if np.sum(sel) < 4:
        return None

    section_pts = np.column_stack((t[sel], s[sel]))
    poly = filled_section_polygon(section_pts, n_bins=n_bins)
    if poly is None:
        return None
    # Center the depth axis on the section itself (t stays aligned with the drawn line)
    poly = affinity.translate(poly, yoff=-poly.centroid.y)
    return {'polygon': poly, 'mid_uv': mid_uv, 'line_dir_uv': d_uv, 'n_points': int(np.sum(sel))}


def filled_section_polygon(points_2d, n_bins=72, smooth=0.8):
    """
    Solid outline of a cut through a scanned surface. A scan has points only on
    the surface, so a cut gives a ring of points; this keeps the farthest point
    from the centroid in each angular bin and joins them into a filled polygon.
    Suitable for star-shaped sections (round, oval, strap handles).
    """
    pts = np.asarray(points_2d, dtype=float)
    if len(pts) < 4:
        return None
    c = pts.mean(axis=0)
    rel = pts - c
    ang = np.arctan2(rel[:, 1], rel[:, 0])
    rad = np.hypot(rel[:, 0], rel[:, 1])
    bins = np.floor((ang + np.pi) / (2 * np.pi) * n_bins).astype(int) % n_bins
    ring = []
    for b in range(n_bins):
        idx = np.where(bins == b)[0]
        if len(idx) > 0:
            ring.append(pts[idx[np.argmax(rad[idx])]])
    if len(ring) < 3:
        return None
    # Morphological closing smooths the notches left by scan noise
    poly = make_valid(Polygon(ring)).buffer(smooth).buffer(-smooth)
    if poly.geom_type != 'Polygon':
        polys = [g for g in getattr(poly, 'geoms', []) if g.geom_type == 'Polygon']
        poly = max(polys, key=lambda g: g.area) if polys else None
    return poly if poly is not None and not poly.is_empty else None


def scanned_section(mesh, frame, axis_top_v=None, res=0.2, close_px=2):
    """
    Cross-section of a vessel whose walls were scanned on both sides ("Inner Wall Fully Scanned").

    The scan is a shell: points only on the surfaces, none inside the clay. So the section is
    found by "painting the air":
      1. cut the mesh with the slicing plane (exact section lines) and keep the right side (u >= 0);
      2. add the symmetry axis as a line (from the bottom up to axis_top_v) - it closes the
         right half on the axis side (e.g. a solid stem or base that reaches the axis);
      3. draw the lines on a fine grid (res mm per pixel), closing tiny scan gaps (close_px);
      4. paint everything reachable from the image border (the air, including open hollows such
         as the inside of a bowl or of a hollow foot); what is left is clay;
      5. remove the axis line again where it crossed air, and turn the clay back into a polygon.

    mesh: trimesh.Trimesh in aligned coordinates. Returns (polygon_uv or None, raw_uv_points).
    """
    from scipy import ndimage
    import contourpy
    import trimesh

    segs = trimesh.intersections.mesh_plane(mesh, plane_normal=frame['n'], plane_origin=frame['origin'])
    if len(segs) == 0:
        return None, np.empty((0, 2))
    uv0, _ = points_to_uv(segs[:, 0], frame)
    uv1, _ = points_to_uv(segs[:, 1], frame)

    # Keep the right side; segments crossing the axis are cut at u = 0
    left0, left1 = uv0[:, 0] < 0, uv1[:, 0] < 0
    keep = ~(left0 & left1)
    uv0, uv1, left0, left1 = uv0[keep], uv1[keep], left0[keep], left1[keep]
    crossing = left0 ^ left1
    if np.any(crossing):
        a, b = uv0[crossing], uv1[crossing]
        t = (a[:, 0] / (a[:, 0] - b[:, 0]))[:, None]
        cut = a + t * (b - a)
        a = np.where(left0[crossing][:, None], cut, a)
        b = np.where(left1[crossing][:, None], cut, b)
        uv0[crossing], uv1[crossing] = a, b
    if len(uv0) == 0:
        return None, np.empty((0, 2))
    raw = np.vstack([uv0, uv1])

    # Axis line from the lowest point up to the rim line (or the top of the section)
    v_bottom = raw[:, 1].min()
    v_top = raw[:, 1].max() if axis_top_v is None else max(min(axis_top_v, raw[:, 1].max()), v_bottom)
    axis0 = np.array([[0.0, v_bottom]])
    axis1 = np.array([[0.0, v_top]])
    seg0 = np.vstack([uv0, axis0])
    seg1 = np.vstack([uv1, axis1])

    # Raster: rows = v, columns = u (u starts exactly at the axis, column 0)
    margin = (close_px + 3) * res
    lo = np.array([0.0, raw[:, 1].min() - margin])
    hi = np.array([raw[:, 0].max() + margin, raw[:, 1].max() + margin])
    n_cols, n_rows = (np.ceil((hi - lo) / res).astype(int) + 1)
    lines = np.zeros((n_rows, n_cols), dtype=bool)
    length = np.hypot(*(seg1 - seg0).T)
    steps = np.maximum(np.ceil(length / (res / 2)).astype(int), 1)
    t = np.concatenate([np.linspace(0.0, 1.0, k + 1) for k in steps])
    idx = np.repeat(np.arange(len(steps)), steps + 1)
    pts = seg0[idx] + t[:, None] * (seg1[idx] - seg0[idx])
    ij = np.clip(np.floor((pts - lo) / res).astype(int), 0, [n_cols - 1, n_rows - 1])
    lines[ij[:, 1], ij[:, 0]] = True
    axis_col = np.zeros_like(lines)
    a0 = int(np.floor((v_bottom - lo[1]) / res))
    a1 = int(np.floor((v_top - lo[1]) / res))
    axis_col[a0:a1 + 1, 0] = True

    # The image's left edge is the axis itself: pad on the left with "air" so the border is outside
    walls = ndimage.binary_dilation(lines, iterations=close_px)
    walls[:, 0] |= axis_col[:, 0]
    walls = np.pad(walls, ((1, 1), (1, 1)), constant_values=False)
    clay = ndimage.binary_fill_holes(walls)
    clay = ndimage.binary_erosion(clay, iterations=close_px, border_value=0)
    clay = clay[1:-1, 1:-1] | (lines & ~axis_col)
    # Remove the axis line where it crossed air: keep axis pixels only next to clay
    clay[:, 0] &= clay[:, min(close_px + 1, n_cols - 1)] if n_cols > 1 else clay[:, 0]

    if not clay.any():
        return None, raw
    gen = contourpy.contour_generator(z=np.pad(clay, 1).astype(float), name='serial')
    rings = [lo + (np.asarray(l) - 1.0) * res for l in gen.lines(0.5)]
    rings = [r for r in rings if len(r) >= 4]
    faces = shapely.get_parts(shapely.polygonize([LineString(r) for r in rings]))
    keep_faces = []
    for f in faces:
        p = f.representative_point()
        j, i = int((p.x - lo[0]) / res), int((p.y - lo[1]) / res)
        if 0 <= i < n_rows and 0 <= j < n_cols and clay[i, j]:
            keep_faces.append(f)
    if not keep_faces:
        return None, raw
    poly = make_valid(shapely.unary_union(keep_faces).simplify(res / 2))
    return poly, raw


def run_scanned_profile(mesh, frame, axis_top_v=None):
    """
    Profile for "Inner Wall Fully Scanned": the section painted from the mesh cut
    (scanned_section). Returns (solid_poly, diag, error_msg) like run_6step_pipeline,
    with Steps 3-5 marked as not needed.
    """
    diag = {'skipped_steps': True, 'filled_section': True}
    try:
        poly, raw = scanned_section(mesh, frame, axis_top_v=axis_top_v)
    except Exception as e:
        return None, diag, f"Section error: {e}"
    diag['raw_points'] = raw
    diag['cleaned_points'] = raw
    diag['rejected_points'] = np.empty((0, 2))
    if len(raw):
        diag['z_min'], diag['z_max'] = raw[:, 1].min(), raw[:, 1].max()
    if poly is None or poly.is_empty:
        return None, diag, "The slice misses the vessel at this angle – rotate the angle."
    parts = [g for g in shapely.get_parts(poly) if g.geom_type == 'Polygon']
    if not parts:
        return None, diag, "The section could not be filled."
    main = max(parts, key=lambda g: g.area)
    diag['hull'] = poly
    diag['coords'] = np.array(main.exterior.coords)
    diag['solid_poly'] = poly
    return poly, diag, None


def run_6step_pipeline(points_2d, handle_mask=None, hull_ratio=0.03, complete_inner_wall=True):
    """
    The 6-step profile pipeline from profile_test2.py (run_6step_pipeline_v2).
    Input is the right-side profile in uv coordinates (axis at u = 0).
      - Handle points are ONLY rejected if specified by user via handle_mask (Lasso).
      - Stray mid-height points right on the axis are filtered to prevent false central neck snapping.
      - Bottom center is strictly searched in the true bottom zone (lowest 15% of vessel).
      - Concave hull ratio defaults to 0.03 to preserve rounded rim curvature.
    complete_inner_wall=False (sherds: both walls are scanned) stops after Step 2 and
    uses the concave hull itself as the profile; Steps 3-6 are skipped.
    Returns (solid_poly, diag, error_msg).
    """
    diag = {}
    if points_2d is None or len(points_2d) < 10:
        return None, diag, "Error: Not enough points in 2D profile (need >= 10 points)."

    diag['raw_points'] = points_2d.copy()
    z_min, z_max = np.min(points_2d[:, 1]), np.max(points_2d[:, 1])
    diag['z_min'] = z_min
    diag['z_max'] = z_max

    # STEP 1: Handle Filtering & Mid-Axis Noise Cleanup
    if handle_mask is not None and len(handle_mask) == len(points_2d) and np.any(handle_mask):
        cleaned_points = points_2d[~handle_mask]
        rejected_points = points_2d[handle_mask]
    else:
        cleaned_points = points_2d.copy()
        rejected_points = np.empty((0, 2))

    # Prevent opposite-wall bleed: filter points right on the axis that are above the base zone
    axis_spill_mask = (cleaned_points[:, 0] < 0.8) & (cleaned_points[:, 1] > z_min + 30.0)
    cleaned_points = cleaned_points[~axis_spill_mask]

    diag['cleaned_points'] = cleaned_points
    diag['rejected_points'] = rejected_points

    if len(cleaned_points) < 10:
        return None, diag, f"Step 1 Error: Only {len(cleaned_points)} points remain after filtering."

    # STEP 2: Profile Boundary via Concave Hull
    try:
        hull = make_valid(concave_hull(MultiPoint(cleaned_points), ratio=hull_ratio, allow_holes=False))
        if hull.geom_type in ('MultiPolygon', 'GeometryCollection'):
            polys = [g for g in hull.geoms if g.geom_type == 'Polygon']
            hull = max(polys, key=lambda a: a.area) if polys else hull
        if hull.geom_type != 'Polygon' or hull.is_empty:
            return None, diag, f"Step 2 Error: concave_hull returned {hull.geom_type} instead of Polygon."
        coords = np.array(hull.exterior.coords)
        diag['hull'] = hull
        diag['coords'] = coords
    except Exception as e:
        return None, diag, f"Step 2 Exception (Concave Hull): {e}"

    if not complete_inner_wall:
        # Both walls were scanned: the outline of the slice is the true section
        diag['skipped_steps'] = True
        diag['solid_poly'] = hull
        return hull, diag, None

    # STEP 3: Outer/Inner Wall Splitting
    try:
        rim_idx = np.argmax(coords[:, 1])
        rim_z = coords[rim_idx, 1]
        rim_x = coords[rim_idx, 0]
        diag['rim_peak'] = (rim_x, rim_z)

        # Search for true bottom center strictly in the lowest 15% of the vessel
        z_bottom_zone = z_min + 0.15 * (rim_z - z_min)
        bottom_indices = np.where(coords[:, 1] < z_bottom_zone)[0]
        if len(bottom_indices) == 0:
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

        # outer flows upwards (bottom -> rim), inner flows downwards (rim -> base)
        if abs(outer_coords[0, 1] - rim_z) < abs(outer_coords[-1, 1] - rim_z):
            outer_coords = outer_coords[::-1]
        if abs(inner_coords[-1, 1] - rim_z) < abs(inner_coords[0, 1] - rim_z):
            inner_coords = inner_coords[::-1]

        outer_line = LineString(outer_coords)
        diag['outer_coords'] = outer_coords
        diag['inner_coords'] = inner_coords
        diag['outer_line'] = outer_line
    except Exception as e:
        return None, diag, f"Step 3 Exception (Wall Splitting): {e}"

    # STEP 4: Automatic Perpendicular Thickness Measurement (scanned inner wall, 1.5-20 mm below the rim)
    # - The inner wall is resampled every 0.5 mm: hull vertices crowd on the rounded lip, where
    #   inner and outer walls meet (distance ~0), and would pull the median far too low.
    # - Where the inside was not scanned (e.g. a narrow neck), the hull's "inner" side runs along
    #   the outer wall; samples closer than 1 mm to the outer wall are not a real inner wall.
    try:
        inner_line = LineString(inner_coords)
        n_samples = max(int(inner_line.length / 0.5), 2)
        resampled = np.array([inner_line.interpolate(d).coords[0]
                              for d in np.linspace(0, inner_line.length, n_samples)])
        near_rim = [p for p in resampled if rim_z - 20.0 < p[1] < rim_z - 1.5]
        near_rim_dist = [Point(p).distance(outer_line) for p in near_rim]
        inner_pts = [p for p, dist in zip(near_rim, near_rim_dist) if dist > 1.0]
        distances = [dist for dist in near_rim_dist if dist > 1.0]
        if len(distances) < 3:
            inner_pts, distances = near_rim, near_rim_dist
        thickness = float(np.median(distances)) if len(distances) > 0 else 5.0
        diag['inner_sampled_pts'] = np.array(inner_pts) if len(inner_pts) > 0 else np.empty((0, 2))
        diag['distances'] = distances
        diag['measured_thickness'] = thickness
    except Exception as e:
        return None, diag, f"Step 4 Exception (Thickness Measurement): {e}"

    # STEP 5: Synthetic Inner Wall Offset
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
        if inner_offset_coords[0, 1] < inner_offset_coords[-1, 1]:
            inner_offset_coords = inner_offset_coords[::-1]
        diag['inner_offset_coords'] = inner_offset_coords
    except Exception as e:
        return None, diag, f"Step 5 Exception (Inner Wall Offset): {e}"

    # STEP 6: Base Closure & Topology Resolution
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


