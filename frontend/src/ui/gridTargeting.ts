import type { SceneGrid } from "../api/types";

export type GridPoint = { row: number; col: number };
export type TargetShape = "single" | "circle" | "cone" | "line" | "cube" | "cylinder";

export type TargetingTemplate = {
  shape: TargetShape;
  /** Maximum distance from caster to the selected aim point. */
  rangeFt: number;
  /** Circle radius, cone length, or line length. Defaults to rangeFt. */
  sizeFt?: number;
  /** Line width in feet. Defaults to one grid cell. */
  widthFt?: number;
  /** Vertical height of a cylinder or explicit 3-D area, in feet. */
  heightFt?: number;
  /** Height of the selected area anchor, in feet. */
  anchorHeightFt?: number;
  /**
   * An advanced monster area has to fail closed when its vertical geometry is
   * not recorded.  Ordinary legacy spell previews leave this off so their
   * established two-dimensional behaviour is unchanged.
   */
  requiresElevation?: boolean;
  /** Area is centered on the caster; no remote aim point is required. */
  originSelf?: boolean;
};

export type TargetingElevationResult = {
  applies: boolean;
  valid: boolean;
  status:
    | "not_applicable"
    | "within_volume"
    | "outside_volume"
    | "missing_height"
    | "missing_size"
    | "missing_target_elevation"
    | "missing_origin_elevation";
};

type TargetingGrid = Pick<SceneGrid, "width" | "height" | "cell_size_ft">
  & { cells?: Array<{ row: number; col: number; kind: string; blocks_sight?: boolean; sight_transparency?: string }> };

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function positiveNumber(value: unknown): number | null {
  const parsed = finiteNumber(value);
  return parsed !== null && parsed > 0 ? parsed : null;
}

/**
 * Read only an explicitly saved combat elevation.  In particular, this does
 * not silently turn a missing value into ground level: callers that need a
 * three-dimensional confirmation can then fail closed instead of selecting a
 * flying or otherwise unmeasured target by mistake.
 */
export function explicitElevationFt(gridPosition: unknown): number | null {
  if (!gridPosition || typeof gridPosition !== "object" || Array.isArray(gridPosition)) {
    return null;
  }
  return finiteNumber((gridPosition as Record<string, unknown>).elevation_ft);
}

/** Always expose ground plus every saved combatant height as selectable map layers. */
export function availableElevationLayers(gridPositions: Iterable<unknown>): number[] {
  return [...new Set([
    0,
    ...Array.from(gridPositions)
      .map(explicitElevationFt)
      .filter((elevation): elevation is number => elevation !== null),
  ])].sort((left, right) => left - right);
}

function verticalTargetingApplies(template: TargetingTemplate): boolean {
  return template.requiresElevation === true
    || template.shape === "cylinder"
    || finiteNumber(template.heightFt) !== null
    || finiteNumber(template.anchorHeightFt) !== null;
}

function elevationResult(
  valid: boolean,
  status: Exclude<TargetingElevationResult["status"], "not_applicable">,
): TargetingElevationResult {
  return { applies: true, valid, status };
}

/**
 * Mirrors the vertical component of the server's authoritative area checks.
 * Horizontal shape membership remains the responsibility of getTargetingCells;
 * this helper deliberately only answers whether one elevation can occupy the
 * already selected horizontal point.
 */
export function evaluateTargetingElevation(
  grid: Pick<SceneGrid, "cell_size_ft">,
  origin: GridPoint,
  aim: GridPoint,
  point: GridPoint,
  template: TargetingTemplate,
  originElevationFt: number | null,
  targetElevationFt: number | null,
): TargetingElevationResult {
  if (!verticalTargetingApplies(template)) {
    return { applies: false, valid: true, status: "not_applicable" };
  }
  if (targetElevationFt === null) {
    return elevationResult(false, "missing_target_elevation");
  }

  const cellSizeFt = grid.cell_size_ft;
  const anchorHeightFt = finiteNumber(template.anchorHeightFt) ?? 0;
  const sizeFt = positiveNumber(template.sizeFt);
  if (template.shape === "cylinder") {
    const heightFt = positiveNumber(template.heightFt);
    if (heightFt === null) return elevationResult(false, "missing_height");
    return elevationResult(
      targetElevationFt >= anchorHeightFt && targetElevationFt < anchorHeightFt + heightFt,
      targetElevationFt >= anchorHeightFt && targetElevationFt < anchorHeightFt + heightFt
        ? "within_volume"
        : "outside_volume",
    );
  }

  if (template.shape === "cube") {
    const heightFt = positiveNumber(template.heightFt) ?? sizeFt;
    if (heightFt === null) return elevationResult(false, "missing_size");
    return elevationResult(
      targetElevationFt >= anchorHeightFt && targetElevationFt < anchorHeightFt + heightFt,
      targetElevationFt >= anchorHeightFt && targetElevationFt < anchorHeightFt + heightFt
        ? "within_volume"
        : "outside_volume",
    );
  }

  if (template.shape === "circle") {
    if (sizeFt === null) return elevationResult(false, "missing_size");
    // Sphere/circle membership is Euclidean in the authoritative backend.
    // Keep this separate from movement/range distance (which uses the 5e
    // one-square diagonal rule), otherwise the preview can select a corner
    // target that the server correctly rejects as outside the volume.
    const horizontalFt = Math.hypot(
      (point.row - aim.row) * cellSizeFt,
      (point.col - aim.col) * cellSizeFt,
    );
    const inVolume = Math.hypot(horizontalFt, targetElevationFt - anchorHeightFt) <= sizeFt + 0.01;
    return elevationResult(inVolume, inVolume ? "within_volume" : "outside_volume");
  }

  if (originElevationFt === null) {
    return elevationResult(false, "missing_origin_elevation");
  }

  if (template.shape === "line") {
    const halfWidthFt = (positiveNumber(template.widthFt) ?? cellSizeFt) / 2;
    const inVolume = Math.abs(targetElevationFt - originElevationFt) <= halfWidthFt + 0.01;
    return elevationResult(inVolume, inVolume ? "within_volume" : "outside_volume");
  }

  if (template.shape === "cone") {
    const directionRow = aim.row - origin.row;
    const directionCol = aim.col - origin.col;
    const directionLength = Math.hypot(directionRow, directionCol);
    if (directionLength === 0) {
      const inVolume = targetElevationFt === originElevationFt;
      return elevationResult(inVolume, inVolume ? "within_volume" : "outside_volume");
    }
    const forwardFt = (
      ((point.row - origin.row) * directionRow + (point.col - origin.col) * directionCol)
      / directionLength
    ) * cellSizeFt;
    const inVolume = Math.abs(targetElevationFt - originElevationFt) <= forwardFt + 0.01;
    return elevationResult(inVolume, inVolume ? "within_volume" : "outside_volume");
  }

  const heightFt = positiveNumber(template.heightFt);
  if (heightFt === null) return elevationResult(false, "missing_height");
  const inVolume = targetElevationFt >= anchorHeightFt && targetElevationFt < anchorHeightFt + heightFt;
  return elevationResult(inVolume, inVolume ? "within_volume" : "outside_volume");
}

function cellsForGrid(grid: Pick<SceneGrid, "width" | "height">): GridPoint[] {
  return Array.from({ length: grid.height }, (_, row) => (
    Array.from({ length: grid.width }, (_, col) => ({ row: row + 1, col: col + 1 }))
  )).flat();
}

export function gridDistanceFt(
  from: GridPoint,
  to: GridPoint,
  cellSizeFt = 5,
): number {
  // 5e treats diagonal movement as one square unless the optional alternating
  // diagonal rule is enabled, so Chebyshev distance is the useful UI default.
  return Math.max(Math.abs(to.row - from.row), Math.abs(to.col - from.col)) * cellSizeFt;
}

export function isAimPointInRange(
  origin: GridPoint,
  aim: GridPoint,
  rangeFt: number,
  cellSizeFt = 5,
): boolean {
  return gridDistanceFt(origin, aim, cellSizeFt) <= rangeFt;
}

function vector(from: GridPoint, to: GridPoint): [number, number] {
  return [to.col - from.col, to.row - from.row];
}

function distanceToSegment(point: GridPoint, start: GridPoint, end: GridPoint): number {
  const [segmentX, segmentY] = vector(start, end);
  const [pointX, pointY] = vector(start, point);
  const lengthSquared = segmentX * segmentX + segmentY * segmentY;
  if (lengthSquared === 0) return Math.hypot(pointX, pointY);
  const projection = Math.max(0, Math.min(1, (pointX * segmentX + pointY * segmentY) / lengthSquared));
  return Math.hypot(pointX - projection * segmentX, pointY - projection * segmentY);
}

export function getTargetingCells(
  grid: TargetingGrid,
  origin: GridPoint,
  aim: GridPoint,
  template: TargetingTemplate,
): GridPoint[] {
  const cellSizeFt = grid.cell_size_ft;
  const aimRangeFt = template.originSelf
    ? Math.max(template.rangeFt, template.sizeFt ?? 0)
    : template.rangeFt;
  if (!isAimPointInRange(origin, aim, aimRangeFt, cellSizeFt)) return [];
  if (!hasLineOfSight(grid, origin, aim)) return [];
  if (template.shape === "single") return [aim];

  const cells = cellsForGrid(grid);
  const sizeCells = Math.max(0, (template.sizeFt ?? template.rangeFt) / cellSizeFt);
  if (template.shape === "circle" || template.shape === "cylinder") {
    const radiusFt = template.sizeFt ?? template.rangeFt;
    return cells.filter((cell) => (
      Math.hypot(
        (cell.row - aim.row) * cellSizeFt,
        (cell.col - aim.col) * cellSizeFt,
      ) <= radiusFt + 0.01
      && hasLineOfSight(grid, aim, cell)
    ));
  }

  if (template.shape === "cube") {
    const halfSizeCells = Math.max(0.5, sizeCells / 2);
    if (template.originSelf && (aim.row !== origin.row || aim.col !== origin.col)) {
      const directionRow = aim.row - origin.row;
      const directionCol = aim.col - origin.col;
      const directionLength = Math.hypot(directionRow, directionCol);
      return cells.filter((cell) => {
        const relativeRow = cell.row - origin.row;
        const relativeCol = cell.col - origin.col;
        const forward = (relativeRow * directionRow + relativeCol * directionCol) / directionLength;
        const lateral = Math.abs(relativeRow * directionCol - relativeCol * directionRow) / directionLength;
        return forward >= -0.01
          && forward <= sizeCells + 0.01
          && lateral <= halfSizeCells + 0.01
          && hasLineOfSight(grid, origin, cell);
      });
    }
    const center = template.originSelf ? origin : aim;
    return cells.filter((cell) => (
      Math.max(Math.abs(cell.row - center.row), Math.abs(cell.col - center.col))
        <= halfSizeCells + 0.01
      && hasLineOfSight(grid, center, cell)
    ));
  }

  const [directionX, directionY] = vector(origin, aim);
  const directionLength = Math.hypot(directionX, directionY);
  if (directionLength === 0) return [origin];
  const normalizedX = directionX / directionLength;
  const normalizedY = directionY / directionLength;
  const end: GridPoint = {
    row: origin.row + normalizedY * sizeCells,
    col: origin.col + normalizedX * sizeCells,
  };

  if (template.shape === "line") {
    const halfWidthCells = Math.max(0.5, (template.widthFt ?? cellSizeFt) / cellSizeFt / 2);
    return cells.filter((cell) => {
      const [cellX, cellY] = vector(origin, cell);
      const forward = cellX * normalizedX + cellY * normalizedY;
      return forward >= 0 && forward <= sizeCells + 0.01
        && distanceToSegment(cell, origin, end) <= halfWidthCells + 0.01
        && hasLineOfSight(grid, origin, cell);
    });
  }

  // A 5e cone is as wide as the distance from its origin. This is equivalent
  // to a 90-degree sector (45 degrees on either side of the chosen direction).
  return cells.filter((cell) => {
    const [cellX, cellY] = vector(origin, cell);
    const distance = Math.hypot(cellX, cellY);
    if (distance > sizeCells + 0.01) return false;
    if (distance === 0) return true;
    const forward = cellX * normalizedX + cellY * normalizedY;
    return forward >= 0
      && forward / distance >= Math.SQRT1_2 - 0.01
      && hasLineOfSight(grid, origin, cell);
  });
}

export function hasLineOfSight(
  grid: {
    cells?: Array<{
      row: number;
      col: number;
      kind: string;
      blocks_sight?: boolean;
      sight_transparency?: string;
    }>;
  },
  start: GridPoint,
  end: GridPoint,
): boolean {
  const sightBehavior = (cell: {
    kind: string;
    blocks_sight?: boolean;
    sight_transparency?: string;
  }): "transparent" | "translucent" | "opaque" => {
    if (cell.blocks_sight === false) return "transparent";
    const raw = cell.sight_transparency?.trim().toLowerCase();
    if (raw === "transparent" || raw === "clear" || raw === "透明") return "transparent";
    if (raw === "translucent" || raw === "semi_transparent" || raw === "半透明") return "translucent";
    if (raw === "opaque" || raw === "不透明") return "opaque";
    return cell.kind === "wall" || cell.blocks_sight === true ? "opaque" : "transparent";
  };
  const blockers = new Set(
    (grid.cells ?? [])
      .filter((cell) => sightBehavior(cell) === "opaque")
      .map((cell) => `${cell.row}:${cell.col}`),
  );
  let row = start.row;
  let col = start.col;
  const rowDelta = Math.abs(end.row - row);
  const colDelta = Math.abs(end.col - col);
  const rowStep = row < end.row ? 1 : -1;
  const colStep = col < end.col ? 1 : -1;
  let error = rowDelta - colDelta;
  while (row !== end.row || col !== end.col) {
    if ((row !== start.row || col !== start.col) && blockers.has(`${row}:${col}`)) {
      return false;
    }
    const doubled = 2 * error;
    if (doubled > -colDelta) {
      error -= colDelta;
      row += rowStep;
    }
    if (doubled < rowDelta) {
      error += rowDelta;
      col += colStep;
    }
  }
  return true;
}

export function isBlockedCell(grid: SceneGrid, point: GridPoint): boolean {
  return grid.cells.some(
    (cell) => cell.row === point.row && cell.col === point.col && cell.kind === "wall",
  );
}
