'use client';

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { BrainLink, BrainNode, BrainNodeType } from '@/fixtures/brain';

interface ForceGraphProps {
  id: string;
  nodes: BrainNode[];
  links: BrainLink[];
  focusedNodeId: string | null;
  highlightedNodeIds: string[];
  onNodeClick: (node: BrainNode) => void;
  onBackgroundClick?: () => void;
}

interface SimNode extends SimulationNodeDatum {
  id: string;
  type: BrainNodeType;
  label: string;
  meta: string;
}

interface SimLink extends SimulationLinkDatum<SimNode> {
  kind: BrainLink['kind'];
}

const WIDTH = 680;
const HEIGHT = 380;
const PAD_X = 36;
const PAD_TOP = 28;
const PAD_BOTTOM = 28;

const NODE_RADIUS: Record<BrainNodeType, number> = {
  role: 14,
  interviewer: 11,
  signal: 9,
};

const NODE_FILL: Record<BrainNodeType, string> = {
  role: '#7A6BD9',
  interviewer: '#ECEAE6',
  signal: '#FFFBEB',
};

const NODE_STROKE: Record<BrainNodeType, string> = {
  role: '#5E4FAE',
  interviewer: '#555555',
  signal: '#B45309',
};

const NODE_LABEL_COLOR: Record<BrainNodeType, string> = {
  role: '#FFFFFF',
  interviewer: '#111111',
  signal: '#111111',
};

const LINK_COLOR: Record<BrainLink['kind'], string> = {
  panel: 'currentColor',
  overload: 'rgba(180,83,9,0.55)',
  drift: 'rgba(180,83,9,0.55)',
  risk: 'rgba(220,38,38,0.55)',
};

const LINK_OPACITY: Record<BrainLink['kind'], number> = {
  panel: 0.32,
  overload: 1,
  drift: 1,
  risk: 1,
};

export function ForceGraph({
  id,
  nodes,
  links,
  focusedNodeId,
  highlightedNodeIds,
  onNodeClick,
  onBackgroundClick,
}: ForceGraphProps) {
  /* SimNodes are kept stable across re-renders so d3-force can mutate `x`/`y`
     in place. Re-creating the array would discard layout state every tick. */
  const simNodesRef = useRef<SimNode[]>([]);
  const simLinksRef = useRef<SimLink[]>([]);

  const desiredNodes = useMemo(() => nodes, [nodes]);
  const desiredLinks = useMemo(() => links, [links]);

  const [, setSnapshot] = useState(0);
  const rafRef = useRef<number | null>(null);
  const simRef = useRef<Simulation<SimNode, SimLink> | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<{
    node: SimNode;
    originX: number;
    originY: number;
    didDrag: boolean;
    pointerId: number;
  } | null>(null);

  useEffect(() => {
    /* Reuse existing positions for stable nodes; seed new nodes on a circle.
       This way switching tabs / time ranges doesn't blow up the layout.   */
    const existing = new Map<string, SimNode>();
    simNodesRef.current.forEach((n) => existing.set(n.id, n));

    const newSimNodes: SimNode[] = desiredNodes.map((n, idx) => {
      const prev = existing.get(n.id);
      if (prev) {
        prev.type = n.type;
        prev.label = n.label;
        prev.meta = n.meta;
        return prev;
      }
      return {
        id: n.id,
        type: n.type,
        label: n.label,
        meta: n.meta,
        x: WIDTH / 2 + Math.cos((idx / desiredNodes.length) * Math.PI * 2) * 140,
        y: HEIGHT / 2 + Math.sin((idx / desiredNodes.length) * Math.PI * 2) * 100,
      };
    });
    simNodesRef.current = newSimNodes;

    const nodeMap = new Map(newSimNodes.map((n) => [n.id, n]));
    const newSimLinks: SimLink[] = desiredLinks
      .filter((l) => nodeMap.has(l.source) && nodeMap.has(l.target))
      .map((l) => ({ source: l.source, target: l.target, kind: l.kind }));
    simLinksRef.current = newSimLinks;

    if (simRef.current) simRef.current.stop();

    const sim = forceSimulation<SimNode>(newSimNodes)
      .force(
        'link',
        forceLink<SimNode, SimLink>(newSimLinks)
          .id((d) => d.id)
          .distance(82)
          .strength(0.55),
      )
      .force('charge', forceManyBody<SimNode>().strength(-180))
      .force('center', forceCenter<SimNode>(WIDTH / 2, HEIGHT / 2))
      .force('collide', forceCollide<SimNode>().radius((d) => NODE_RADIUS[d.type] + 10))
      /* x/y forces gently pull every node toward center — without this, the
         charge force can fling outliers off-canvas and they never recover. */
      .force('x', forceX<SimNode>(WIDTH / 2).strength(0.05))
      .force('y', forceY<SimNode>(HEIGHT / 2).strength(0.06))
      .alpha(0.9)
      .alphaDecay(0.02)
      .velocityDecay(0.4);

    simRef.current = sim;

    sim.on('tick', () => {
      /* Clamp every node back into the visible area on every tick. d3-force
         can blow nodes outside the canvas during the high-alpha settle
         phase; this is what keeps the graph "in the box".                  */
      for (const n of newSimNodes) {
        const r = NODE_RADIUS[n.type];
        if (typeof n.x === 'number') {
          n.x = Math.max(PAD_X + r, Math.min(WIDTH - PAD_X - r, n.x));
        }
        if (typeof n.y === 'number') {
          n.y = Math.max(PAD_TOP + r, Math.min(HEIGHT - PAD_BOTTOM - r, n.y));
        }
      }
      if (rafRef.current !== null) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = null;
        setSnapshot((v) => v + 1);
      });
    });

    return () => {
      sim.stop();
      sim.on('tick', null);
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [desiredNodes, desiredLinks]);

  /* Convert client coords to SVG viewBox coords. The canvas uses
     `preserveAspectRatio="xMidYMid meet"` so we account for letterboxing by
     using the actual painted area derived from the SVG's bounding rect.  */
  const clientToSvg = useCallback((clientX: number, clientY: number): { x: number; y: number } => {
    const svg = svgRef.current;
    if (!svg) return { x: WIDTH / 2, y: HEIGHT / 2 };
    const rect = svg.getBoundingClientRect();
    const aspect = WIDTH / HEIGHT;
    const containerAspect = rect.width / rect.height;
    let paintedW = rect.width;
    let paintedH = rect.height;
    let offsetX = 0;
    let offsetY = 0;
    if (containerAspect > aspect) {
      paintedW = rect.height * aspect;
      offsetX = (rect.width - paintedW) / 2;
    } else {
      paintedH = rect.width / aspect;
      offsetY = (rect.height - paintedH) / 2;
    }
    return {
      x: ((clientX - rect.left - offsetX) / paintedW) * WIDTH,
      y: ((clientY - rect.top - offsetY) / paintedH) * HEIGHT,
    };
  }, []);

  /* Document-level move/up handlers attached on pointerdown. This is the
     pattern that makes drag survive the cursor leaving the SVG, hovering
     over child <text>/<title> elements, or moving over a popup overlay.   */
  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || e.pointerId !== drag.pointerId) return;
      const { x, y } = clientToSvg(e.clientX, e.clientY);
      const dx = Math.abs(x - drag.originX);
      const dy = Math.abs(y - drag.originY);
      if (dx > 3 || dy > 3) drag.didDrag = true;
      const r = NODE_RADIUS[drag.node.type];
      drag.node.fx = Math.max(PAD_X + r, Math.min(WIDTH - PAD_X - r, x));
      drag.node.fy = Math.max(PAD_TOP + r, Math.min(HEIGHT - PAD_BOTTOM - r, y));
      simRef.current?.alphaTarget(0.18).restart();
    };
    const onUp = (e: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag || e.pointerId !== drag.pointerId) return;
      drag.node.fx = null;
      drag.node.fy = null;
      simRef.current?.alphaTarget(0);
      const wasClick = !drag.didDrag;
      const node = drag.node;
      dragRef.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      if (wasClick) {
        onNodeClick(nodeFromSim(node));
      }
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
    document.addEventListener('pointercancel', onUp);
    return () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
      document.removeEventListener('pointercancel', onUp);
    };
  }, [clientToSvg, onNodeClick]);

  const onNodePointerDown = useCallback(
    (e: React.PointerEvent, node: SimNode) => {
      e.stopPropagation();
      e.preventDefault();
      dragRef.current = {
        node,
        originX: node.x ?? 0,
        originY: node.y ?? 0,
        didDrag: false,
        pointerId: e.pointerId,
      };
      node.fx = node.x ?? null;
      node.fy = node.y ?? null;
      simRef.current?.alphaTarget(0.2).restart();
      document.body.style.cursor = 'grabbing';
      document.body.style.userSelect = 'none';
    },
    [],
  );

  const onSvgClick = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      if (e.target === e.currentTarget && onBackgroundClick) {
        onBackgroundClick();
      }
    },
    [onBackgroundClick],
  );

  const highlightSet = useMemo(() => new Set(highlightedNodeIds), [highlightedNodeIds]);
  const hasHighlight = highlightSet.size > 0 || focusedNodeId !== null;
  const activeId = dragRef.current?.node.id ?? null;

  const renderNodes = simNodesRef.current;
  const renderLinks = simLinksRef.current;

  return (
    <svg
      id={id}
      ref={svgRef}
      role="img"
      aria-label="Brain force-directed graph — drag a node to reposition"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      preserveAspectRatio="xMidYMid meet"
      className="block h-full w-full select-none text-text-primary"
      onClick={onSvgClick}
    >
      <defs>
        <radialGradient id={`${id}-glow`} cx="50%" cy="50%" r="55%">
          <stop offset="0%" stopColor="rgba(122,107,217,0.07)" />
          <stop offset="100%" stopColor="rgba(122,107,217,0)" />
        </radialGradient>
      </defs>
      <rect id={`${id}-bg`} x="0" y="0" width={WIDTH} height={HEIGHT} fill={`url(#${id}-glow)`} />
      <g id={`${id}-grid`} stroke="currentColor" strokeOpacity={0.06} strokeWidth={1}>
        {Array.from({ length: 12 }).map((_, i) => (
          <line
            // biome-ignore lint/suspicious/noArrayIndexKey: grid lines are static
            key={`v${i}`}
            id={`${id}-grid-v-${i}`}
            x1={(i * WIDTH) / 12}
            x2={(i * WIDTH) / 12}
            y1={0}
            y2={HEIGHT}
          />
        ))}
        {Array.from({ length: 7 }).map((_, i) => (
          <line
            // biome-ignore lint/suspicious/noArrayIndexKey: grid lines are static
            key={`h${i}`}
            id={`${id}-grid-h-${i}`}
            x1={0}
            x2={WIDTH}
            y1={(i * HEIGHT) / 7}
            y2={(i * HEIGHT) / 7}
          />
        ))}
      </g>
      <g id={`${id}-links`}>
        {renderLinks.map((link, idx) => {
          const source = link.source as SimNode;
          const target = link.target as SimNode;
          if (!source || !target || source.x == null || target.x == null) return null;
          const linkActive =
            highlightSet.has(source.id) ||
            highlightSet.has(target.id) ||
            focusedNodeId === source.id ||
            focusedNodeId === target.id;
          const dim = hasHighlight && !linkActive;
          return (
            <line
              // biome-ignore lint/suspicious/noArrayIndexKey: link index is stable per render
              key={idx}
              id={`${id}-link-${idx}`}
              x1={source.x}
              y1={source.y ?? 0}
              x2={target.x}
              y2={target.y ?? 0}
              stroke={LINK_COLOR[link.kind]}
              strokeWidth={linkActive ? 1.6 : 0.9}
              opacity={dim ? 0.18 : LINK_OPACITY[link.kind]}
              style={{ transition: 'opacity 150ms ease-out, stroke-width 150ms ease-out' }}
            />
          );
        })}
      </g>
      <g id={`${id}-nodes`}>
        {renderNodes.map((n) => {
          const cx = n.x ?? WIDTH / 2;
          const cy = n.y ?? HEIGHT / 2;
          const r = NODE_RADIUS[n.type];
          const isFocused = focusedNodeId === n.id;
          const isHighlighted = highlightSet.has(n.id);
          const isActive = isFocused || isHighlighted;
          const dim = hasHighlight && !isActive;
          const isDragging = activeId === n.id;
          return (
            // biome-ignore lint/a11y/useSemanticElements: SVG group needs role=button for keyboard interactivity
            <g
              key={n.id}
              id={`${id}-node-${n.id}`}
              role="button"
              tabIndex={0}
              aria-label={`${n.label} · ${n.meta} — drag to reposition`}
              transform={`translate(${cx}, ${cy})`}
              style={{
                cursor: isDragging ? 'grabbing' : 'grab',
                opacity: dim ? 0.32 : 1,
                transition: dim ? 'opacity 150ms ease-out' : undefined,
              }}
              onPointerDown={(e) => onNodePointerDown(e, n)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onNodeClick(nodeFromSim(n));
                }
              }}
            >
              <title>{`${n.label} · ${n.meta}`}</title>
              {/* Transparent hit area — much bigger than the visible circle so
                  drag/click still works in the gap between circle + label. */}
              <circle id={`${id}-node-${n.id}-hit`} r={r + 12} fill="transparent" />
              {isActive && (
                <circle
                  id={`${id}-node-${n.id}-pulse`}
                  r={r + 8}
                  fill={NODE_FILL[n.type]}
                  opacity={0.2}
                  style={{ pointerEvents: 'none' }}
                >
                  <animate
                    attributeName="r"
                    values={`${r + 4};${r + 14};${r + 4}`}
                    dur="2.6s"
                    repeatCount="indefinite"
                  />
                  <animate
                    attributeName="opacity"
                    values="0.3;0.05;0.3"
                    dur="2.6s"
                    repeatCount="indefinite"
                  />
                </circle>
              )}
              <circle
                id={`${id}-node-${n.id}-core`}
                r={r}
                fill={NODE_FILL[n.type]}
                stroke={NODE_STROKE[n.type]}
                strokeWidth={1.25}
                style={{ pointerEvents: 'none' }}
              />
              <text
                id={`${id}-node-${n.id}-initial`}
                y="4"
                textAnchor="middle"
                fontFamily="var(--font-mono)"
                fontSize={n.type === 'role' ? 11 : 10}
                fontWeight={500}
                fill={NODE_LABEL_COLOR[n.type]}
                style={{ pointerEvents: 'none' }}
              >
                {initialsFor(n.label)}
              </text>
              <text
                id={`${id}-node-${n.id}-label`}
                y={r + 14}
                textAnchor="middle"
                fontFamily="var(--font-sans)"
                fontSize={11}
                fontWeight={isActive ? 500 : 400}
                fill="currentColor"
                style={{ pointerEvents: 'none' }}
              >
                {n.label}
              </text>
            </g>
          );
        })}
      </g>
    </svg>
  );
}

function initialsFor(label: string): string {
  const parts = label.replace(/·/g, ' ').split(/\s+/).filter(Boolean).slice(0, 2);
  return parts
    .map((p) => {
      const ch = p[0];
      return ch ? ch.toUpperCase() : '';
    })
    .join('');
}

function nodeFromSim(sim: SimNode): BrainNode {
  return {
    id: sim.id,
    type: sim.type,
    label: sim.label,
    meta: sim.meta,
  };
}
