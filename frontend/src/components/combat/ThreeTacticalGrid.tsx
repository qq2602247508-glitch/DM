import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import * as THREE from "three";
import type { Combatant } from "../../api/types";
import { gridDistanceFt, isAimPointInRange, type GridPoint } from "../../ui/gridTargeting";
import type { CombatTargeting } from "./TurnCommandConsole";
import type { VfxEvent } from "../../pages/QuickCombatPage";
import { soundboard } from "../../ui/soundboard";

export type ThreeTacticalGridProps = {
  campaignId: string;
  combatId: string;
  fighters: Combatant[];
  activeFighterId: string | null;
  selectedTargetId: string;
  onTargetSelect: (id: string) => void;
  positions: Record<string, [number, number]>;
  targeting: CombatTargeting | null;
  interactionMode: "move" | "target";
  onInteractionModeChange: (mode: "move" | "target") => void;
  aimPoint: GridPoint | null;
  onAimPointChange: (point: GridPoint | null) => void;
  areaKeys: Set<string>;
  vfxEvents: VfxEvent[];
  onSpawnVfx: (event: Omit<VfxEvent, "id">) => void;
  onMoveToken: (fighter: Combatant, newRow: number, newCol: number, spentFt: number) => void;
  showEnemyThreat: boolean;
  onToggleEnemyThreat: () => void;
};

type CellTerrain = {
  elevationFt: number; // 0, 10, 20
  isWall?: boolean;
  isStairs?: boolean;
  isPillar?: boolean;
};

function getCellTerrain(r: number, c: number): CellTerrain {
  if (r === 4 && (c === 4 || c === 5)) return { elevationFt: 5, isStairs: true };
  if (r === 7 && (c === 4 || c === 5)) return { elevationFt: 5, isStairs: true };

  if (c <= 3 && r >= 2 && r <= 9) return { elevationFt: 10 };
  if (c <= 4 && r >= 3 && r <= 8) return { elevationFt: 10 };

  if (c >= 10 && r >= 2 && r <= 4) return { elevationFt: 15 };

  if ((r === 1 || r === 10) && (c === 1 || c === 12)) return { elevationFt: 8, isPillar: true };
  if (r === 5 && c === 8) return { elevationFt: 6, isPillar: true };
  if (r === 6 && c === 8) return { elevationFt: 6, isPillar: true };

  return { elevationFt: 0 };
}

function combatantElevationFt(fighter: Combatant): number {
  const snap = fighter.snapshot_json as Record<string, unknown> | undefined;
  if (!snap) return 0;
  const pos = snap.grid_position as { elevation_ft?: number } | undefined;
  if (pos && typeof pos.elevation_ft === "number") return pos.elevation_ft;
  if (typeof snap.elevation_ft === "number") return snap.elevation_ft;
  if (typeof snap.elevation === "number") return snap.elevation;
  return 0;
}

function createTokenBadgeTexture(fighter: Combatant, isMeleeThreatened: boolean): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  let ctx: CanvasRenderingContext2D | null = null;
  try {
    ctx = canvas.getContext("2d");
  } catch {
    ctx = null;
  }
  if (!ctx) return new THREE.CanvasTexture(canvas);

  try {
    ctx.clearRect(0, 0, 256, 128);

    ctx.fillStyle = "#0f172a";
    ctx.strokeStyle = fighter.entity_type === "monster" ? "#f43f5e" : "#f59e0b";
    ctx.lineWidth = 4;
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(8, 8, 240, 112, 16);
      ctx.fill();
      ctx.stroke();
    } else {
      ctx.fillRect(8, 8, 240, 112);
      ctx.strokeRect(8, 8, 240, 112);
    }

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 24px sans-serif";
    ctx.textAlign = "center";
    const name = fighter.display_name?.slice(0, 8) ?? "单位";
    ctx.fillText(name, 128, 42);

    const hp = Math.max(0, fighter.hp ?? 0);
    const maxHp = Math.max(1, fighter.max_hp ?? 10);
    const hpPct = Math.max(0, Math.min(1, hp / maxHp));

    ctx.fillStyle = "#334155";
    if (typeof ctx.roundRect === "function") {
      ctx.beginPath();
      ctx.roundRect(24, 54, 208, 20, 10);
      ctx.fill();
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.beginPath();
      ctx.roundRect(24, 54, Math.max(8, 208 * hpPct), 20, 10);
      ctx.fill();
    } else {
      ctx.fillRect(24, 54, 208, 20);
      ctx.fillStyle = hpPct > 0.5 ? "#10b981" : hpPct > 0.2 ? "#f59e0b" : "#ef4444";
      ctx.fillRect(24, 54, Math.max(8, 208 * hpPct), 20);
    }

    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 16px monospace";
    ctx.fillText(`${hp}/${maxHp}`, 128, 70);

    if (isMeleeThreatened && fighter.entity_type === "character") {
      ctx.fillStyle = "#ef4444";
      ctx.font = "bold 18px sans-serif";
      ctx.fillText("⚠️ 借机危险区", 128, 102);
    } else {
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "16px monospace";
      ctx.fillText(`AC ${fighter.armor_class ?? 10}`, 128, 102);
    }
  } catch {
    // Fallback if canvas methods fail in unit tests
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;
  return texture;
}

export function ThreeTacticalGrid({
  fighters,
  activeFighterId,
  selectedTargetId,
  onTargetSelect,
  positions,
  targeting,
  interactionMode,
  onInteractionModeChange,
  aimPoint,
  onAimPointChange,
  areaKeys,
  vfxEvents,
  onSpawnVfx,
  onMoveToken,
  showEnemyThreat,
  onToggleEnemyThreat,
}: ThreeTacticalGridProps): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredCell, setHoveredCell] = useState<{ row: number; col: number } | null>(null);
  const [cameraPreset, setCameraPreset] = useState<"iso" | "top" | "close">("iso");

  const width = 12;
  const height = 10;
  const cellSize = 1.6; // 3D units per 5ft cell
  const cellSizeFt = 5;

  // Current active combatant whose turn it is
  const activeFighter = fighters.find((f) => f.id === activeFighterId) ?? fighters[0] ?? null;
  const activePos = activeFighter ? positions[activeFighter.id] : null;
  const activePosition: GridPoint | null = activePos ? { row: activePos[0], col: activePos[1] } : null;

  // The mover for range calculations is always the active actor (or selected character)
  const targetedCombatant = fighters.find((f) => f.id === selectedTargetId);
  const moverFighter = (targetedCombatant && targetedCombatant.entity_type === "character")
    ? targetedCombatant
    : activeFighter;
  const moverPos = moverFighter ? (positions[moverFighter.id] ?? [3, 3]) : null;
  const moverRemaining = (moverFighter?.movement_remaining_ft !== undefined && moverFighter?.movement_remaining_ft !== null)
    ? moverFighter.movement_remaining_ft
    : (moverFighter?.speed_ft ?? 30);

  // Compute enemy threat maps
  const enemyThreatCells = useMemo(() => {
    if (!showEnemyThreat) {
      return {
        meleeMap: new Map<string, string[]>(),
        rangedMap: new Map<string, string[]>(),
      };
    }
    const meleeMap = new Map<string, string[]>();
    const rangedMap = new Map<string, string[]>();

    const enemies = fighters.filter((f) => f.entity_type === "monster" && (f.hp ?? 0) > 0);
    enemies.forEach((enemy) => {
      const pos = positions[enemy.id];
      if (!pos) return;

      for (let r = 1; r <= height; r++) {
        for (let c = 1; c <= width; c++) {
          const key = `${r}:${c}`;
          const dist = gridDistanceFt({ row: pos[0], col: pos[1] }, { row: r, col: c }, cellSizeFt);
          if (dist <= 5) {
            const list = meleeMap.get(key) ?? [];
            list.push(enemy.display_name);
            meleeMap.set(key, list);
          } else if (dist <= 30) {
            const list = rangedMap.get(key) ?? [];
            list.push(enemy.display_name);
            rangedMap.set(key, list);
          }
        }
      }
    });

    return { meleeMap, rangedMap };
  }, [fighters, positions, showEnemyThreat, height, width, cellSizeFt]);

  // Three.js Scene Refs
  const sceneRef = useRef<THREE.Scene | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const tileMeshesRef = useRef<Map<string, { capMesh: THREE.Mesh; capEdgeLine: THREE.LineSegments; blockMesh: THREE.Mesh }>>(new Map());
  const tokenGroupsRef = useRef<Map<string, THREE.Group>>(new Map());
  const particleGroupRef = useRef<THREE.Group>(new THREE.Group());

  // Orbit controls state
  const isDraggingRef = useRef<boolean>(false);
  const previousMousePositionRef = useRef<{ x: number; y: number }>({ x: 0, y: 0 });
  const sphericalRef = useRef<{ radius: number; theta: number; phi: number }>({
    radius: 24,
    theta: Math.PI / 4,
    phi: Math.PI / 3.4,
  });
  const targetLookAtRef = useRef<THREE.Vector3>(new THREE.Vector3(0, 0, 0));

  // Update camera position from spherical coordinates
  const updateCameraFromSpherical = useCallback(() => {
    if (!cameraRef.current) return;
    const { radius, theta, phi } = sphericalRef.current;
    const x = radius * Math.sin(phi) * Math.sin(theta);
    const y = radius * Math.cos(phi);
    const z = radius * Math.sin(phi) * Math.cos(theta);

    cameraRef.current.position.set(
      targetLookAtRef.current.x + x,
      targetLookAtRef.current.y + y,
      targetLookAtRef.current.z + z,
    );
    cameraRef.current.lookAt(targetLookAtRef.current);
  }, []);

  // Set camera presets
  const applyCameraPreset = useCallback((preset: "iso" | "top" | "close") => {
    setCameraPreset(preset);
    if (preset === "iso") {
      sphericalRef.current = { radius: 24, theta: Math.PI / 4, phi: Math.PI / 3.4 };
    } else if (preset === "top") {
      sphericalRef.current = { radius: 22, theta: 0.001, phi: 0.05 };
    } else if (preset === "close") {
      sphericalRef.current = { radius: 14, theta: Math.PI / 3.8, phi: Math.PI / 2.6 };
    }
    updateCameraFromSpherical();
  }, [updateCameraFromSpherical]);

  // Convert (row, col) to 3D world space (x, y, z)
  const gridToWorld = useCallback((row: number, col: number, manualElevationFt?: number): THREE.Vector3 => {
    const terrain = getCellTerrain(row, col);
    const elevFt = manualElevationFt !== undefined ? manualElevationFt : terrain.elevationFt;
    const x = (col - (width + 1) / 2) * cellSize;
    const z = (row - (height + 1) / 2) * cellSize;
    const y = (elevFt / 5) * 0.45;
    return new THREE.Vector3(x, y, z);
  }, [width, height, cellSize]);

  // Initialize Three.js scene (NO HARSH SHADOWS - Pure Clean Geometric Tabletop)
  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    const scene = new THREE.Scene();
    sceneRef.current = scene;

    scene.background = new THREE.Color(0x0a0e17);

    const camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 0.1, 1000);
    cameraRef.current = camera;
    updateCameraFromSpherical();

    let renderer: THREE.WebGLRenderer | null = null;
    let animationFrameId: number | null = null;

    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.setSize(container.clientWidth || 600, container.clientHeight || 400);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      renderer.shadowMap.enabled = false;
      rendererRef.current = renderer;

      container.innerHTML = "";
      container.appendChild(renderer.domElement);
    } catch {
      return;
    }

    // Clean, Balanced Ambient & Diffuse Lighting
    const ambientLight = new THREE.AmbientLight(0xd1d5db, 1.4);
    scene.add(ambientLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 0.9);
    keyLight.position.set(15, 30, 20);
    scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0x94a3b8, 0.7);
    fillLight.position.set(-20, 20, -15);
    scene.add(fillLight);

    // Base Architectural Ground Board
    const basePlateGeo = new THREE.BoxGeometry(width * cellSize + 3.0, 0.3, height * cellSize + 3.0);
    const basePlateMat = new THREE.MeshLambertMaterial({ color: 0x111827 });
    const basePlateMesh = new THREE.Mesh(basePlateGeo, basePlateMat);
    basePlateMesh.position.y = -0.16;
    scene.add(basePlateMesh);

    const baseEdgesGeo = new THREE.EdgesGeometry(basePlateGeo);
    const baseEdgesMat = new THREE.LineBasicMaterial({ color: 0x334155, linewidth: 2 });
    const baseEdgesLine = new THREE.LineSegments(baseEdgesGeo, baseEdgesMat);
    basePlateMesh.add(baseEdgesLine);

    // Voxel Multi-Level Block Tiles
    const tilesMap = new Map<string, { capMesh: THREE.Mesh; capEdgeLine: THREE.LineSegments; blockMesh: THREE.Mesh }>();

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const terrain = getCellTerrain(r, c);
        const wPos = gridToWorld(r, c, terrain.elevationFt);
        const blockHeight = Math.max(0.15, (terrain.elevationFt / 5) * 0.45 + 0.15);

        // 1. Lower Block Extrusion Body
        const blockGeo = new THREE.BoxGeometry(cellSize * 0.96, blockHeight, cellSize * 0.96);
        const isElevated = terrain.elevationFt > 0;
        const blockMat = new THREE.MeshLambertMaterial({
          color: isElevated ? 0x222d42 : 0x182030,
        });
        const blockMesh = new THREE.Mesh(blockGeo, blockMat);
        blockMesh.position.set(wPos.x, blockHeight / 2 - 0.15, wPos.z);
        scene.add(blockMesh);

        const blockEdgesGeo = new THREE.EdgesGeometry(blockGeo);
        const blockEdgesMat = new THREE.LineBasicMaterial({
          color: isElevated ? 0x64748b : 0x334155,
        });
        const blockEdgesLine = new THREE.LineSegments(blockEdgesGeo, blockEdgesMat);
        blockMesh.add(blockEdgesLine);

        // 2. Interactive Solid 3D Cap Step (for Range Highlights & Clicks)
        const capGeo = new THREE.BoxGeometry(cellSize * 0.92, 0.08, cellSize * 0.92);
        const capMat = new THREE.MeshLambertMaterial({
          color: isElevated ? 0x28354d : (r + c) % 2 === 0 ? 0x1e293b : 0x172033,
        });
        const capMesh = new THREE.Mesh(capGeo, capMat);
        capMesh.position.set(wPos.x, wPos.y + 0.04, wPos.z);
        capMesh.userData = { row: r, col: c, key, elevationFt: terrain.elevationFt };
        scene.add(capMesh);

        // Highlight Edges Line for Cap
        const capEdgeGeo = new THREE.EdgesGeometry(capGeo);
        const capEdgeMat = new THREE.LineBasicMaterial({ color: 0x475569, linewidth: 2 });
        const capEdgeLine = new THREE.LineSegments(capEdgeGeo, capEdgeMat);
        capMesh.add(capEdgeLine);

        // Architectural Props: Pillars
        if (terrain.isPillar) {
          const pillarGeo = new THREE.CylinderGeometry(0.2, 0.25, 1.2, 8);
          const pillarMat = new THREE.MeshLambertMaterial({ color: 0x475569 });
          const pillarMesh = new THREE.Mesh(pillarGeo, pillarMat);
          pillarMesh.position.set(wPos.x, wPos.y + 0.6, wPos.z);
          scene.add(pillarMesh);

          const pillarEdges = new THREE.LineSegments(new THREE.EdgesGeometry(pillarGeo), new THREE.LineBasicMaterial({ color: 0x94a3b8 }));
          pillarMesh.add(pillarEdges);
        }

        tilesMap.set(key, { capMesh, capEdgeLine, blockMesh });
      }
    }
    tileMeshesRef.current = tilesMap;

    // Particle Group
    scene.add(particleGroupRef.current);

    // Animation Loop
    const clock = new THREE.Clock();

    const animate = () => {
      if (!renderer || !camera) return;
      animationFrameId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      // Animate active token gold ring rotation
      tokenGroupsRef.current.forEach((group) => {
        const activeRing = group.getObjectByName("activeRing");
        if (activeRing) {
          activeRing.rotation.z += delta * 2;
        }
        const badge = group.getObjectByName("badgeSprite");
        if (badge && cameraRef.current) {
          badge.quaternion.copy(cameraRef.current.quaternion);
        }
      });

      // Animate particles
      particleGroupRef.current.children.forEach((p) => {
        p.position.y += delta * 0.8;
        if (p instanceof THREE.Mesh && p.material instanceof THREE.Material) {
          p.material.opacity -= delta * 1.2;
        }
      });

      renderer.render(scene, camera);
    };
    animate();

    const handleResize = () => {
      if (!container || !camera || !renderer) return;
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      if (animationFrameId !== null) cancelAnimationFrame(animationFrameId);
      if (renderer) renderer.dispose();
    };
  }, [width, height, cellSize, gridToWorld, updateCameraFromSpherical]);

  // Update Tile Colors based on state (Movement, Spell AoE, Threat Ranges, Hover)
  useEffect(() => {
    const tilesMap = tileMeshesRef.current;
    if (!tilesMap.size) return;

    for (let r = 1; r <= height; r++) {
      for (let c = 1; c <= width; c++) {
        const key = `${r}:${c}`;
        const item = tilesMap.get(key);
        if (!item) continue;

        const terrain = getCellTerrain(r, c);
        const fighter = fighters.find((f) => positions[f.id]?.[0] === r && positions[f.id]?.[1] === c);

        // Movement Range (Calculated from Mover Fighter)
        const distFromMover = moverPos
          ? gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, { row: r, col: c }, cellSizeFt)
          : null;
        const canMoveHere = interactionMode === "move" && moverFighter && !fighter && distFromMover !== null && distFromMover <= moverRemaining && moverRemaining > 0;

        // Spell Range & AoE Coverage
        const inCastRange = targeting && activePosition
          ? isAimPointInRange(activePosition, { row: r, col: c }, targeting.rangeFt, cellSizeFt)
          : false;
        const isAreaAffected = areaKeys.has(key);
        const isHovered = hoveredCell?.row === r && hoveredCell?.col === c;

        // Monster Threat Ranges
        const isMeleeThreat = enemyThreatCells.meleeMap.has(key);
        const isRangedThreat = enemyThreatCells.rangedMap.has(key);

        const capMat = item.capMesh.material as THREE.MeshLambertMaterial;
        const edgeMat = item.capEdgeLine.material as THREE.LineBasicMaterial;

        if (canMoveHere) {
          // 🟢 Brilliant Emerald Green Movement Range
          capMat.color.setHex(isHovered ? 0x10b981 : 0x059669);
          capMat.emissive.setHex(isHovered ? 0x34d399 : 0x10b981);
          capMat.emissiveIntensity = isHovered ? 0.9 : 0.6;
          edgeMat.color.setHex(0x34d399);
        } else if (isAreaAffected && interactionMode === "target") {
          // 🟣 Vivid Fuchsia Spell AoE
          capMat.color.setHex(0xc026d3);
          capMat.emissive.setHex(0xd946ef);
          capMat.emissiveIntensity = 0.9;
          edgeMat.color.setHex(0xf0abfc);
        } else if (inCastRange && interactionMode === "target") {
          // 🔵 Arcane Cyan Spell Range
          capMat.color.setHex(0x0284c7);
          capMat.emissive.setHex(0x38bdf8);
          capMat.emissiveIntensity = 0.6;
          edgeMat.color.setHex(0x38bdf8);
        } else if (isMeleeThreat) {
          // 🔴 Crimson 5ft Melee Threat Danger Zone
          capMat.color.setHex(isHovered ? 0xe11d48 : 0x9f1239);
          capMat.emissive.setHex(0xf43f5e);
          capMat.emissiveIntensity = 0.5;
          edgeMat.color.setHex(0xf43f5e);
        } else if (isRangedThreat) {
          // 🟡 Amber 30ft Ranged Threat Zone
          capMat.color.setHex(isHovered ? 0xd97706 : 0x78350f);
          capMat.emissive.setHex(0xf59e0b);
          capMat.emissiveIntensity = 0.35;
          edgeMat.color.setHex(0xf59e0b);
        } else if (isHovered) {
          capMat.color.setHex(0x475569);
          capMat.emissive.setHex(0x94a3b8);
          capMat.emissiveIntensity = 0.2;
          edgeMat.color.setHex(0x94a3b8);
        } else {
          capMat.color.setHex(terrain.elevationFt > 0 ? 0x28354d : (r + c) % 2 === 0 ? 0x1e293b : 0x172033);
          capMat.emissive.setHex(0x000000);
          capMat.emissiveIntensity = 0;
          edgeMat.color.setHex(0x475569);
        }
      }
    }
  }, [
    fighters,
    positions,
    moverPos,
    moverFighter,
    moverRemaining,
    interactionMode,
    targeting,
    activePosition,
    areaKeys,
    hoveredCell,
    enemyThreatCells,
    height,
    width,
    cellSizeFt,
  ]);

  // Update 3D Tabletop Miniature Chess Tokens (棋子)
  useEffect(() => {
    const scene = sceneRef.current;
    if (!scene) return;

    const currentGroups = tokenGroupsRef.current;
    const existingIds = new Set(fighters.map((f) => f.id));

    // Remove defunct tokens
    currentGroups.forEach((group, id) => {
      if (!existingIds.has(id)) {
        scene.remove(group);
        currentGroups.delete(id);
      }
    });

    // Create or update chess figurine tokens
    fighters.forEach((f) => {
      const pos = positions[f.id] ?? [3, 3];
      const terrain = getCellTerrain(pos[0], pos[1]);
      const manualElev = combatantElevationFt(f);
      const totalElevFt = terrain.elevationFt + manualElev;
      const targetWPos = gridToWorld(pos[0], pos[1], totalElevFt);

      const isPc = f.entity_type === "character";
      const isMonster = f.entity_type === "monster";
      const isActive = f.id === activeFighterId;
      const isSelected = f.id === selectedTargetId;

      let group = currentGroups.get(f.id);

      if (!group) {
        group = new THREE.Group();
        group.userData = { fighterId: f.id };

        // 1. Cylindrical Tabletop Chess Pedestal (棋子圆柱底盘)
        const baseGeo = new THREE.CylinderGeometry(0.48, 0.54, 0.18, 24);
        const baseMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x0284c7 : isMonster ? 0x9f1239 : 0x6d28d9,
        });
        const baseMesh = new THREE.Mesh(baseGeo, baseMat);
        baseMesh.position.y = 0.09;
        group.add(baseMesh);

        // Clean White/Gold Outlines on Chess Base
        const baseEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(baseGeo),
          new THREE.LineBasicMaterial({ color: isPc ? 0x38bdf8 : isMonster ? 0xf43f5e : 0xc084fc, linewidth: 2 }),
        );
        baseMesh.add(baseEdges);

        // 2. Classical Chess Piece Body
        const stemGeo = new THREE.CylinderGeometry(0.24, 0.36, 0.55, 20);
        const stemMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x0369a1 : isMonster ? 0x881337 : 0x581c87,
        });
        const stemMesh = new THREE.Mesh(stemGeo, stemMat);
        stemMesh.position.y = 0.45;
        group.add(stemMesh);

        const stemEdges = new THREE.LineSegments(
          new THREE.EdgesGeometry(stemGeo),
          new THREE.LineBasicMaterial({ color: isPc ? 0x7dd3fc : isMonster ? 0xfb7185 : 0xd8b4fe }),
        );
        stemMesh.add(stemEdges);

        // 3. Chess Piece Head / Crown
        const crownGeo = isPc
          ? new THREE.OctahedronGeometry(0.26)
          : isMonster
            ? new THREE.DodecahedronGeometry(0.26)
            : new THREE.SphereGeometry(0.26, 12, 12);
        const crownMat = new THREE.MeshLambertMaterial({
          color: isPc ? 0x38bdf8 : isMonster ? 0xf43f5e : 0xa855f7,
          emissive: isPc ? 0x0284c7 : isMonster ? 0x881337 : 0x6b21a8,
          emissiveIntensity: 0.3,
        });
        const crownMesh = new THREE.Mesh(crownGeo, crownMat);
        crownMesh.position.y = 0.88;
        group.add(crownMesh);

        // 4. Active Gold Action Ring
        const activeRingGeo = new THREE.RingGeometry(0.62, 0.74, 24);
        const activeRingMat = new THREE.MeshBasicMaterial({
          color: 0xfbbf24,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.95,
        });
        const activeRing = new THREE.Mesh(activeRingGeo, activeRingMat);
        activeRing.rotation.x = -Math.PI / 2;
        activeRing.position.y = 0.02;
        activeRing.name = "activeRing";
        group.add(activeRing);

        // 5. Target Emerald Selection Ring
        const targetRingGeo = new THREE.RingGeometry(0.62, 0.72, 24);
        const targetRingMat = new THREE.MeshBasicMaterial({
          color: 0x10b981,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.95,
        });
        const targetRing = new THREE.Mesh(targetRingGeo, targetRingMat);
        targetRing.rotation.x = -Math.PI / 2;
        targetRing.position.y = 0.02;
        targetRing.name = "targetRing";
        group.add(targetRing);

        // 6. Overhead 3D HUD Badge Sprite
        const badgeTexture = createTokenBadgeTexture(f, false);
        const badgeMat = new THREE.SpriteMaterial({ map: badgeTexture, transparent: true });
        const badgeSprite = new THREE.Sprite(badgeMat);
        badgeSprite.scale.set(2.4, 1.2, 1);
        badgeSprite.position.y = 1.7;
        badgeSprite.name = "badgeSprite";
        group.add(badgeSprite);

        group.position.copy(targetWPos);
        scene.add(group);
        currentGroups.set(f.id, group);
      }

      // Smooth Position Interpolation
      group.position.lerp(targetWPos, 0.25);

      // Ring Visibilities
      const activeRing = group.getObjectByName("activeRing");
      if (activeRing) activeRing.visible = isActive;

      const targetRing = group.getObjectByName("targetRing");
      if (targetRing) targetRing.visible = isSelected && !isActive;

      // Update Sprite Texture
      const isThreatened = enemyThreatCells.meleeMap.has(`${pos[0]}:${pos[1]}`);
      const badge = group.getObjectByName("badgeSprite") as THREE.Sprite | undefined;
      if (badge && badge.material instanceof THREE.SpriteMaterial) {
        badge.material.map?.dispose();
        badge.material.map = createTokenBadgeTexture(f, isThreatened);
        badge.material.needsUpdate = true;
      }
    });
  }, [fighters, positions, activeFighterId, selectedTargetId, gridToWorld, enemyThreatCells]);

  // Spawn 3D VFX
  useEffect(() => {
    if (!vfxEvents.length || !sceneRef.current) return;
    const latest = vfxEvents[vfxEvents.length - 1];
    const terrain = getCellTerrain(latest.row, latest.col);
    const wPos = gridToWorld(latest.row, latest.col, terrain.elevationFt);

    if (latest.type === "slash") {
      const geo = new THREE.TorusGeometry(0.6, 0.08, 8, 20, Math.PI * 1.2);
      const mat = new THREE.MeshBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.95 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, wPos.y + 0.6, wPos.z);
      mesh.rotation.x = Math.PI / 3;
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 500);
    } else if (latest.type === "arcane" || latest.type === "fire") {
      const geo = new THREE.SphereGeometry(0.5, 12, 12);
      const mat = new THREE.MeshBasicMaterial({
        color: latest.type === "fire" ? 0xf97316 : 0xd946ef,
        transparent: true,
        opacity: 0.9,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(wPos.x, wPos.y + 0.8, wPos.z);
      sceneRef.current.add(mesh);
      setTimeout(() => {
        sceneRef.current?.remove(mesh);
      }, 600);
    } else if (latest.type === "dust") {
      for (let i = 0; i < 6; i++) {
        const geo = new THREE.SphereGeometry(0.12, 6, 6);
        const mat = new THREE.MeshBasicMaterial({ color: 0x34d399, transparent: true, opacity: 0.85 });
        const mesh = new THREE.Mesh(geo, mat);
        mesh.position.set(
          wPos.x + (Math.random() - 0.5) * 0.6,
          wPos.y + 0.1 + Math.random() * 0.3,
          wPos.z + (Math.random() - 0.5) * 0.6,
        );
        particleGroupRef.current.add(mesh);
        setTimeout(() => {
          particleGroupRef.current.remove(mesh);
        }, 700);
      }
    }
  }, [vfxEvents, gridToWorld]);

  // Pointer interaction & Raycasting
  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    isDraggingRef.current = false;
    previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const dx = e.clientX - previousMousePositionRef.current.x;
    const dy = e.clientY - previousMousePositionRef.current.y;

    if (e.buttons === 1 || e.buttons === 2) {
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
        isDraggingRef.current = true;
        sphericalRef.current.theta -= dx * 0.006;
        sphericalRef.current.phi = Math.max(0.1, Math.min(Math.PI / 2.05, sphericalRef.current.phi - dy * 0.006));
        updateCameraFromSpherical();
        previousMousePositionRef.current = { x: e.clientX, y: e.clientY };
      }
    } else {
      // Raycasting for Hover Highlights
      if (!rendererRef.current || !cameraRef.current || !sceneRef.current) return;
      const rect = rendererRef.current.domElement.getBoundingClientRect();
      const mouse = new THREE.Vector2(
        ((e.clientX - rect.left) / rect.width) * 2 - 1,
        -((e.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const raycaster = new THREE.Raycaster();
      raycaster.setFromCamera(mouse, cameraRef.current);

      const capMeshes = Array.from(tileMeshesRef.current.values()).map((v) => v.capMesh);
      const intersects = raycaster.intersectObjects(capMeshes);

      if (intersects.length > 0) {
        const hit = intersects[0].object.userData as { row: number; col: number };
        if (hit.row !== hoveredCell?.row || hit.col !== hoveredCell?.col) {
          setHoveredCell({ row: hit.row, col: hit.col });
        }
      } else if (hoveredCell !== null) {
        setHoveredCell(null);
      }
    }
  };

  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    sphericalRef.current.radius = Math.max(8, Math.min(45, sphericalRef.current.radius + e.deltaY * 0.03));
    updateCameraFromSpherical();
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDraggingRef.current) return;
    if (!rendererRef.current || !cameraRef.current) return;

    const rect = rendererRef.current.domElement.getBoundingClientRect();
    const mouse = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(mouse, cameraRef.current);

    // 1. Check for token hits
    const tokenMeshes: THREE.Object3D[] = [];
    tokenGroupsRef.current.forEach((grp) => tokenMeshes.push(...grp.children));
    const tokenHits = raycaster.intersectObjects(tokenMeshes);

    if (tokenHits.length > 0) {
      let cur: THREE.Object3D | null = tokenHits[0].object;
      while (cur && !cur.userData?.fighterId) {
        cur = cur.parent;
      }
      if (cur?.userData?.fighterId) {
        onTargetSelect(cur.userData.fighterId);
        soundboard.playDiceRoll();
        return;
      }
    }

    // 2. Check for tile hits
    const capMeshes = Array.from(tileMeshesRef.current.values()).map((v) => v.capMesh);
    const tileHits = raycaster.intersectObjects(capMeshes);

    if (tileHits.length > 0) {
      const hit = tileHits[0].object.userData as { row: number; col: number; elevationFt: number };
      const point = { row: hit.row, col: hit.col };
      const occupant = fighters.find((f) => positions[f.id]?.[0] === hit.row && positions[f.id]?.[1] === hit.col);

      if (occupant) {
        onTargetSelect(occupant.id);
        soundboard.playDiceRoll();
      } else if (interactionMode === "move" && moverFighter && moverPos) {
        const dist = gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, point, cellSizeFt);
        if (dist <= moverRemaining && moverRemaining > 0) {
          onMoveToken(moverFighter, hit.row, hit.col, dist);
        }
      } else if (interactionMode === "target") {
        onAimPointChange(point);
      }
    }
  };

  return (
    <div className="relative flex flex-col justify-between rounded-2xl border border-sky-500/30 bg-[#090d16] p-3 shadow-2xl">
      {/* 3D Viewport Top Controls */}
      <div className="z-20 mb-2 flex flex-wrap items-center justify-between gap-2 text-2xs">
        <div className="flex items-center gap-2">
          {/* Interaction Mode Switch */}
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5 shadow-lg">
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${
                interactionMode === "move"
                  ? "bg-emerald-600 text-emerald-950 shadow ring-1 ring-emerald-400"
                  : "text-stone-300 hover:text-white"
              }`}
              onClick={() => onInteractionModeChange("move")}
              type="button"
            >
              🏃 移动走位 ({moverRemaining}尺)
            </button>
            <button
              className={`rounded-lg px-3 py-1 font-bold transition ${
                interactionMode === "target"
                  ? "bg-fuchsia-600 text-fuchsia-950 shadow ring-1 ring-fuchsia-400"
                  : "text-stone-300 hover:text-white"
              }`}
              onClick={() => onInteractionModeChange("target")}
              type="button"
            >
              🔮 施法瞄准 {targeting ? `(${targeting.rangeFt}尺)` : ""}
            </button>
          </div>

          {/* Camera Angles Presets */}
          <div className="flex rounded-xl border border-ink-700 bg-ink-900/90 p-0.5 shadow-lg">
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "iso" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("iso")}
              type="button"
            >
              📐 45° 战术
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "top" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("top")}
              type="button"
            >
              🦅 顶视
            </button>
            <button
              className={`rounded-lg px-2.5 py-1 transition ${
                cameraPreset === "close" ? "bg-amber-600 font-bold text-amber-950 shadow" : "text-stone-400 hover:text-stone-200"
              }`}
              onClick={() => applyCameraPreset("close")}
              type="button"
            >
              ⚔️ 特写
            </button>
          </div>
        </div>

        {/* Threat Range Switcher */}
        <div className="flex items-center gap-1.5">
          <button
            className={`rounded-xl border px-2.5 py-1 text-2xs font-bold transition flex items-center gap-1.5 shadow-lg ${
              showEnemyThreat
                ? "border-rose-500 bg-rose-950/80 text-rose-200 shadow-[0_0_10px_rgba(244,63,94,0.4)]"
                : "border-ink-700 bg-ink-900 text-stone-400 hover:text-stone-200"
            }`}
            onClick={onToggleEnemyThreat}
            title="切换显示怪物近战 5尺 威胁区与远程 30尺 射程"
            type="button"
          >
            <span>👹 怪物攻击范围: {showEnemyThreat ? "开" : "关"}</span>
            {showEnemyThreat ? (
              <span className="flex items-center gap-1 text-[9px] text-stone-300">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-500 inline-block" /> 近战5尺
                <span className="h-1.5 w-1.5 rounded-full bg-amber-500 inline-block ml-0.5" /> 远程30尺
              </span>
            ) : null}
          </button>
        </div>
      </div>

      {/* Three.js 3D WebGL Canvas Viewport (Clean Architectural & Chess Figurine Scene) */}
      <div
        className="relative h-[380px] w-full cursor-grab active:cursor-grabbing overflow-hidden rounded-xl border border-slate-800 bg-[#080d1a]"
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onWheel={handleWheel}
        ref={containerRef}
      />

      {/* Bottom Floating Legend Bar */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-emerald-500 inline-block" /> 绿色: 可移动范围 ({moverRemaining}尺)
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-sky-500 inline-block" /> 蓝色: 施法射程
          </span>
          <span className="flex items-center gap-1">
            <span className="h-2 w-2 rounded bg-fuchsia-500 inline-block" /> 紫色: 3D法术范围
          </span>
        </div>
        {hoveredCell ? (
          <div className="rounded-lg bg-ink-950 px-2 py-0.5 border border-ink-800 font-mono text-amber-300">
            坐标: ({hoveredCell.row}, {hoveredCell.col}) · 高度: {getCellTerrain(hoveredCell.row, hoveredCell.col).elevationFt} 尺
            {moverPos
              ? ` · 距离 ${gridDistanceFt({ row: moverPos[0], col: moverPos[1] }, hoveredCell, cellSizeFt)} 尺`
              : ""}
          </div>
        ) : null}
      </div>
    </div>
  );
}
