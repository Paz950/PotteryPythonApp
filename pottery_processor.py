import numpy as np
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull

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

def extract_profile(points, xc, yc, angle_deg, thickness=2.0):
    """
    Extracts a 2D profile by slicing the point cloud with a vertical plane.
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
    # Return only the positive side (the side the angle points to)
    return profile_2d[profile_2d[:, 0] >= 0]
