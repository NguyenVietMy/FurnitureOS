"""User-authored planar calibration. No semantic model supplies pixel correspondences."""
from __future__ import annotations
from math import hypot, isfinite
from typing import Literal
from pydantic import Field
from .models import ContractModel, Vec2
from .capture_models import CaptureId, DimensionField

from .capture_models import ReferenceRequest, ReferenceEstimate, ReferenceResult

def _solve(rows: list[list[float]], values: list[float]) -> list[float]:
    matrix = [row[:] + [value] for row, value in zip(rows, values, strict=True)]
    pivots = []
    for col in range(8):
        pivot = max(range(col, 8), key=lambda row: abs(matrix[row][col]))
        value = abs(matrix[pivot][col])
        if value < 1e-10:
            raise ValueError("degenerate-reference")
        pivots.append(value)
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        divisor = matrix[col][col]
        matrix[col] = [v / divisor for v in matrix[col]]
        for row in range(8):
            if row != col:
                factor = matrix[row][col]
                matrix[row] = [a - factor * b for a, b in zip(matrix[row], matrix[col], strict=True)]
    if max(pivots) / min(pivots) > 1e8:
        raise ValueError("unstable-calibration")
    return [row[-1] for row in matrix]

def _length(corners, start, end, request, width, height):
    points = (*corners, start, end)
    if any(not (0 <= x <= width and 0 <= y <= height) for x, y in points):
        raise ValueError("marks-outside-image")
    crosses = []
    for i in range(4):
        a, b, c = corners[i], corners[(i+1)%4], corners[(i+2)%4]
        if hypot(b[0]-a[0], b[1]-a[1]) < 20:
            raise ValueError("tiny-reference")
        crosses.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
    if any(v == 0 or v * crosses[0] <= 0 for v in crosses):
        raise ValueError("degenerate-reference")
    area = abs(sum(corners[i][0]*corners[(i+1)%4][1]-corners[(i+1)%4][0]*corners[i][1] for i in range(4))) / 2
    if area < 1000:
        raise ValueError("tiny-reference")
    cx = sum(x for x, _ in corners)/4
    cy = sum(y for _, y in corners)/4
    image_diag = max(hypot(corners[i][0]-corners[j][0], corners[i][1]-corners[j][1]) for i in range(4) for j in range(4))
    if any(hypot(x-cx, y-cy) > 20*image_diag for x,y in (start,end)):
        raise ValueError("far-reference")
    scale = max(width,height)
    metric_scale = hypot(request.referenceWidthM, request.referenceHeightM)
    targets = ((0,0),(request.referenceWidthM/metric_scale,0),
               (request.referenceWidthM/metric_scale,request.referenceHeightM/metric_scale),
               (0,request.referenceHeightM/metric_scale))
    rows, values = [], []
    for (px,py),(mx,my) in zip(corners,targets,strict=True):
        x,y = (px-width/2)/scale,(py-height/2)/scale
        rows.extend(([x,y,1,0,0,0,-mx*x,-mx*y],[0,0,0,x,y,1,-my*x,-my*y]))
        values.extend((mx,my))
    h = _solve(rows,values)
    transformed, signs = [], []
    den_norm = hypot(h[6],h[7])+1
    for px,py in (start,end):
        x,y = (px-width/2)/scale,(py-height/2)/scale
        den = h[6]*x+h[7]*y+1
        if abs(den)/den_norm < 1e-4:
            raise ValueError("horizon-crossing")
        signs.append(den)
        mx,my = (h[0]*x+h[1]*y+h[2])/den*metric_scale,(h[3]*x+h[4]*y+h[5])/den*metric_scale
        if hypot(mx-request.referenceWidthM/2,my-request.referenceHeightM/2) > 20*metric_scale:
            raise ValueError("far-reference")
        transformed.append((mx,my))
    if signs[0]*signs[1] <= 0:
        raise ValueError("horizon-crossing")
    value = hypot(transformed[0][0]-transformed[1][0],transformed[0][1]-transformed[1][1])
    if not isfinite(value) or not 0 < value <= 1000:
        raise ValueError("unsupported-dimension")
    return value

def calibrate(request: ReferenceRequest, width: int, height: int) -> ReferenceResult:
    def fallback(reason):
        return ReferenceResult(status="typed-input-required",reason=reason,photoId=request.photoId,photoHash=request.photoHash)
    if not request.perspective1x:
        return fallback("unsupported-projection")
    if not request.coplanar or not request.visible or not request.dimensionsReviewed or not request.marksReviewed:
        return fallback("unconfirmed-plane-or-marks")
    if request.referenceType == "a4" and (abs(request.referenceWidthM-.210)>1e-9 or abs(request.referenceHeightM-.297)>1e-9):
        return fallback("reference-size-mismatch")
    if any((segment.field == "heightM") != (request.plane == "wall") for segment in request.segments):
        return fallback("noncoplanar-target")
    estimates = []
    try:
        for segment in request.segments:
            base = _length(request.corners,segment.start,segment.end,request,width,height)
            variation = 0.
            coordinates = [list(p) for p in (*request.corners,segment.start,segment.end)]
            for scalar in range(12):
                for delta in (-2,2):
                    probe = [p[:] for p in coordinates]
                    probe[scalar//2][scalar%2] += delta
                    value = _length(probe[:4],probe[4],probe[5],request,width,height)
                    variation = max(variation,abs(value-base)/base)
            if variation > .05:
                return fallback("unstable-calibration")
            estimates.append(ReferenceEstimate(field=segment.field,valueM=base,sensitivity=variation))
    except ValueError as error:
        return fallback(str(error))
    return ReferenceResult(status="provisional",reason="Review each estimate against the real Room; sensitivity is not metric confidence.",
                           estimates=tuple(estimates),photoId=request.photoId,photoHash=request.photoHash)
