import Rhino.Geometry as rg
import scriptcontext as sc
import numpy as np

def get_real_geometry(guid):
    """从 GUID 获取真实几何对象"""
    obj = sc.doc.Objects.FindId(guid)
    if obj is None:
        raise ValueError("Invalid GUID")
    geo = obj.Geometry
    if isinstance(geo, rg.Mesh):
        return geo
    elif isinstance(geo, rg.Brep):
        return geo
    elif isinstance(geo, rg.Extrusion):
        return geo.ToBrep()
    elif isinstance(geo, rg.Curve):
        return geo
    elif isinstance(geo, rg.Surface):
        return geo
    elif isinstance(geo, rg.SubD):
        return rg.Mesh.CreateFromSubD(geo)
    else:
        raise TypeError(f"Unsupported geometry type: {type(geo)}")

def get_vertices(geometry):
    """统一提取顶点"""
    pts = []
    if isinstance(geometry, rg.Mesh):
        pts = [geometry.Vertices[i] for i in range(geometry.Vertices.Count)]
    elif isinstance(geometry, rg.Brep):
        mesh = rg.Mesh.CreateFromBrep(geometry, rg.MeshingParameters.Default)
        if mesh and len(mesh) > 0:
            combined = rg.Mesh()
            for m in mesh:
                combined.Append(m)
            pts = [combined.Vertices[i] for i in range(combined.Vertices.Count)]
    elif isinstance(geometry, rg.Curve):
        pts = [geometry.PointAt(t) for t in geometry.DivideByCount(100, True)]
    elif isinstance(geometry, rg.Surface):
        mesh = rg.Mesh.CreateFromSurface(geometry)
        if mesh:
            pts = [mesh.Vertices[i] for i in range(mesh.Vertices.Count)]
    elif isinstance(geometry, rg.SubD):
        mesh = rg.Mesh.CreateFromSubD(geometry)
        pts = [mesh.Vertices[i] for i in range(mesh.Vertices.Count)]
    else:
        raise TypeError(f"Cannot extract vertices from: {type(geometry)}")
    return pts

def get_min_oriented_bounding_box(guid):
    geometry = get_real_geometry(guid)
    pts = get_vertices(geometry)

    # 转 numpy
    pts = np.array([[p.X, p.Y, p.Z] for p in pts])

    # PCA
    mean = np.mean(pts, axis=0)
    pts_centered = pts - mean
    cov = np.cov(pts_centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)

    R = eigvecs.T
    pts_rot = pts_centered @ R.T

    min_coords = pts_rot.min(axis=0)
    max_coords = pts_rot.max(axis=0)
    size = max_coords - min_coords
    center = (min_coords + max_coords) / 2

    center_world = mean + center @ R
    xform = rg.Transform.Identity
    for i in range(3):
        for j in range(3):
            xform[i, j] = R[j, i]
    xform[0, 3] = center_world[0]
    xform[1, 3] = center_world[1]
    xform[2, 3] = center_world[2]

    # 从 xform 中提取 plane
    origin = rg.Point3d(xform[0, 3], xform[1, 3], xform[2, 3])
    x_axis = rg.Vector3d(xform[0, 0], xform[1, 0], xform[2, 0])
    y_axis = rg.Vector3d(xform[0, 1], xform[1, 1], xform[2, 1])
    plane = rg.Plane(origin, x_axis, y_axis)

    # 构造 box
    box = rg.Box(plane,
                rg.Interval(-size[0]/2, size[0]/2),
                rg.Interval(-size[1]/2, size[1]/2),
                rg.Interval(-size[2]/2, size[2]/2))

    return box, plane


if __name__ == "__main__":
    # 输入：g 是 GUID（Grasshopper 的 geometry）
    box, plane = get_min_oriented_bounding_box(G)
