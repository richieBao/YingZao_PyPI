# -*- coding: utf-8 -*-
"""
FT_TimberBox_Features_UpForwardLeft
最终版（稳定局部坐标系，不跳变）

GhPython 输入（必须设定）:
------------------------------------------------
TimberBrep  : item, type: Brep 或 Box

GhPython 输出：
------------------------------------------------
FaceList        : list[rg.BrepFace]
PointList       : list[rg.Point3d]
EdgeList        : list[rg.Curve]
CenterPoint     : rg.Point3d
CenterAxisLines : list[rg.Line]
EdgeMidPoints   : list[rg.Point3d]
FacePlaneList   : list[rg.Plane]
Corner0Planes   : list[rg.Plane]
LocalAxesPlane  : rg.Plane      （Corner0 原点的局部坐标平面）
AxisX           : rg.Vector3d   （前进方向 Forward）
AxisY           : rg.Vector3d   （左侧方向 Left）
AxisZ           : rg.Vector3d   （向上 Up）
FaceDirTags     : list[str]     （+X/-X/+Y/-Y/+Z/-Z）
EdgeDirTags     : list[str]
Corner0EdgeDirs : list[rg.Vector3d]
Log             : list[str]
"""

import Rhino.Geometry as rg


class FT_TimberBoxFeatures(object):

    def __init__(self):
        self._log = []

    def log(self, msg):
        self._log.append(str(msg))
    @property
    def log_lines(self): return self._log

    def _axis_tag(self, idx, sign):
        return ["+X","-X","+Y","-Y","+Z","-Z"][(idx*2)+(0 if sign>=0 else 1)]

    # ----------------------------------------------------------------------
    # Corner0 = Brep.Vertices[0]（拓扑稳定，不随旋转改变）
    # ----------------------------------------------------------------------
    def _get_corner0(self, brep):
        if brep.Vertices.Count == 0:
            raise ValueError("Brep 无顶点")
        P0 = brep.Vertices[0].Location
        self.log("Corner0 = Brep.Vertices[0]")
        return P0

    # ----------------------------------------------------------------------
    # 获取 Corner0 三条邻边方向
    # ----------------------------------------------------------------------
    def _neighbor_edge_dirs(self, brep, P0, tol=1e-9):
        dirs = []
        for e in brep.Edges:
            pA = e.StartVertex.Location
            pB = e.EndVertex.Location
            if pA.DistanceTo(P0) < tol:
                dirs.append(pB - P0)
            elif pB.DistanceTo(P0) < tol:
                dirs.append(pA - P0)
        if len(dirs) != 3:
            raise ValueError("Corner0 未找到 3 条邻边，找到 {}".format(len(dirs)))
        for i,d in enumerate(dirs):
            self.log("NeighborEdge[{}]={:.3f},{:.3f},{:.3f}".format(i,d.X,d.Y,d.Z))
        return dirs

    # ----------------------------------------------------------------------
    # Up–Forward–Left 局部坐标系（最终版）
    # ----------------------------------------------------------------------
    def _stable_axes(self, dirs):
        worldZ = rg.Vector3d(0,0,1)

        # Step 1：按 abs(Z) 排序区分水平边和竖边
        d_sorted = sorted(dirs, key=lambda v: abs(v.Z))
        H1, H2, V = d_sorted[0], d_sorted[1], d_sorted[2]

        self.log("水平边 H1, H2；竖边 V")

        # 单位化
        H1u = rg.Vector3d(H1); H1u.Unitize()
        H2u = rg.Vector3d(H2); H2u.Unitize()
        Vu  = rg.Vector3d(V);  Vu.Unitize()

        # Step 2：根据左手规则选局部 X（Forward）
        # 若 H1 的左侧是 H2，则 X=H1；否则 X=H2
        # 左侧判定：Cross(H1, H2)·worldZ > 0？
        if rg.Vector3d.Multiply(rg.Vector3d.CrossProduct(H1u, H2u), worldZ) > 0:
            axis_x = H1u
            axis_y = H2u
        else:
            axis_x = H2u
            axis_y = H1u

        # Step 3：校正 Left，使 Cross(X,Y) 与 worldZ 同向（保持左手系）
        if rg.Vector3d.Multiply(rg.Vector3d.CrossProduct(axis_x, axis_y), worldZ) < 0:
            axis_y *= -1

        # Step 4：局部 Z = 竖边方向 V，调整符号使其与 worldZ 同向
        axis_z = Vu
        if rg.Vector3d.Multiply(axis_z, worldZ) < 0:
            axis_z *= -1

        axis_x.Unitize(); axis_y.Unitize(); axis_z.Unitize()

        self.log("AxisX(Forward)=({:.3f},{:.3f},{:.3f})".format(axis_x.X,axis_x.Y,axis_x.Z))
        self.log("AxisY(Left)   =({:.3f},{:.3f},{:.3f})".format(axis_y.X,axis_y.Y,axis_y.Z))
        self.log("AxisZ(Up)     =({:.3f},{:.3f},{:.3f})".format(axis_z.X,axis_z.Y,axis_z.Z))

        return axis_x, axis_y, axis_z

    # ----------------------------------------------------------------------
    # 主函数
    # ----------------------------------------------------------------------
    def extract(self, timber):

        self._log = []
        self.log("== TimberBox Up–Forward–Left 计算开始 ==")

        # 转为 Brep
        if isinstance(timber, rg.Box):
            brep = timber.ToBrep()
            pts = list(timber.GetCorners())
        elif isinstance(timber, rg.Brep):
            brep = timber
            pts = [v.Location for v in brep.Vertices]
        else:
            raise TypeError("输入必须是 Box 或 Brep")

        P0 = self._get_corner0(brep)
        dirs = self._neighbor_edge_dirs(brep, P0)
        axis_x, axis_y, axis_z = self._stable_axes(dirs)

        # LocalAxesPlane
        local_axes_plane = rg.Plane(P0, axis_x, axis_y)

        # CenterPoint
        cx = sum(p.X for p in pts)/len(pts)
        cy = sum(p.Y for p in pts)/len(pts)
        cz = sum(p.Z for p in pts)/len(pts)
        center = rg.Point3d(cx,cy,cz)

        # 半长
        hx=hy=hz=0
        for p in pts:
            v = p-center
            hx=max(hx,abs(rg.Vector3d.Multiply(v,axis_x)))
            hy=max(hy,abs(rg.Vector3d.Multiply(v,axis_y)))
            hz=max(hz,abs(rg.Vector3d.Multiply(v,axis_z)))

        center_axes=[
            rg.Line(center,center+axis_x*hx),
            rg.Line(center,center-axis_x*hx),
            rg.Line(center,center+axis_y*hy),
            rg.Line(center,center-axis_y*hy),
            rg.Line(center,center+axis_z*hz),
            rg.Line(center,center-axis_z*hz),
        ]

        # Edge midpoints
        EdgeList=[e.DuplicateCurve() for e in brep.Edges]
        EdgeMid=[]
        for cr in EdgeList:
            t=cr.Domain.ParameterAt(0.5)
            EdgeMid.append(cr.PointAt(t))

        # Face planes + tags
        FaceList=[f for f in brep.Faces]
        FacePlaneList=[]
        FaceDirTags=[]
        axes=[axis_x,axis_y,axis_z]

        for face in FaceList:
            fb=face.DuplicateFace(True)
            amp=rg.AreaMassProperties.Compute(fb)
            fc=amp.Centroid if amp else fb.GetBoundingBox(True).Center

            udom=face.Domain(0); vdom=face.Domain(1)
            nf=face.NormalAt( (udom.T0+udom.T1)/2, (vdom.T0+vdom.T1)/2 )
            nf.Unitize()

            dots=[rg.Vector3d.Multiply(nf,a) for a in axes]
            absd=[abs(d) for d in dots]
            idx=absd.index(max(absd))
            sign=1 if dots[idx]>=0 else -1

            # 标签
            FaceDirTags.append(self._axis_tag(idx,sign))

            # 余下两个轴为平面 X/Y
            rem=[0,1,2]; rem.remove(idx)
            xax=rg.Vector3d(axes[rem[0]]); xax.Unitize()
            yax=rg.Vector3d(axes[rem[1]]); yax.Unitize()

            pl=rg.Plane(fc,xax,yax)
            if rg.Vector3d.Multiply(pl.ZAxis, axes[idx]*sign)<0: pl.Flip()
            FacePlaneList.append(pl)

        # Edge tags
        EdgeDirTags=[]
        for cr in EdgeList:
            v = cr.PointAtEnd - cr.PointAtStart
            dots=[rg.Vector3d.Multiply(v,a) for a in axes]
            absd=[abs(d) for d in dots]
            idx=absd.index(max(absd))
            sign=1 if dots[idx]>=0 else -1
            EdgeDirTags.append(self._axis_tag(idx,sign))

        # Corner0 planes
        Corner0Planes=[
            rg.Plane(P0,axis_x,axis_y),
            rg.Plane(P0,axis_x,axis_z),
            rg.Plane(P0,axis_y,axis_z),
        ]

        return (FaceList, pts, EdgeList, center, center_axes, EdgeMid,
                FacePlaneList, Corner0Planes, local_axes_plane,
                axis_x,axis_y,axis_z,
                FaceDirTags,EdgeDirTags, dirs)


if __name__=='__main__':
    # =========================================================
    # GH 脚本输出
    # =========================================================

    if TimberBrep is None:
        FaceList=[];PointList=[];EdgeList=[]
        CenterPoint=None;CenterAxisLines=[]
        EdgeMidPoints=[];FacePlaneList=[]
        Corner0Planes=[];LocalAxesPlane=None
        AxisX=None;AxisY=None;AxisZ=None
        FaceDirTags=[];EdgeDirTags=[]
        Corner0EdgeDirs=[];Log=["TimberBrep 输入为空"]
    else:
        fx=FT_TimberBoxFeatures()
        try:
            (FaceList,PointList,EdgeList,CenterPoint,
             CenterAxisLines,EdgeMidPoints,FacePlaneList,
             Corner0Planes,LocalAxesPlane,
             AxisX,AxisY,AxisZ,
             FaceDirTags,EdgeDirTags,Corner0EdgeDirs)=fx.extract(TimberBrep)
            Log=fx.log_lines
        except Exception as e:
            FaceList=[];PointList=[];EdgeList=[]
            CenterPoint=None;CenterAxisLines=[]
            EdgeMidPoints=[];FacePlaneList=[]
            Corner0Planes=[];LocalAxesPlane=None
            AxisX=None;AxisY=None;AxisZ=None
            FaceDirTags=[];EdgeDirTags=[]
            Corner0EdgeDirs=[]
            Log=["错误: {}".format(e)]
