/**
 * Ambient decoration for the login screen — an abstract wallet / money-flow
 * graph (nodes + travelling-dash edges), spanning the whole
 * backdrop. Purely decorative, aria-hidden; motion is CSS-driven and disabled
 * under prefers-reduced-motion.
 */

const NODES: { x: number; y: number; r: number }[] = [
  { x: 70, y: 130, r: 5 }, { x: 190, y: 80, r: 3 }, { x: 150, y: 250, r: 6 },
  { x: 300, y: 170, r: 4 }, { x: 280, y: 330, r: 5 }, { x: 110, y: 410, r: 4 },
  { x: 250, y: 470, r: 6 }, { x: 430, y: 110, r: 3 }, { x: 460, y: 290, r: 5 },
  { x: 410, y: 450, r: 4 }, { x: 360, y: 610, r: 5 }, { x: 560, y: 190, r: 4 },
  { x: 600, y: 380, r: 6 }, { x: 560, y: 560, r: 4 }, { x: 720, y: 120, r: 3 },
  { x: 760, y: 300, r: 5 }, { x: 720, y: 490, r: 4 }, { x: 890, y: 200, r: 5 },
  { x: 910, y: 410, r: 6 }, { x: 860, y: 600, r: 4 }, { x: 1050, y: 300, r: 5 },
  { x: 1070, y: 510, r: 4 }, { x: 1000, y: 140, r: 3 },
];

const EDGES: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 3], [2, 4], [2, 5], [4, 6], [5, 6], [3, 7],
  [3, 8], [4, 8], [8, 9], [6, 9], [9, 10], [8, 11], [11, 12], [12, 13],
  [9, 13], [11, 14], [12, 15], [15, 16], [14, 17], [15, 17], [15, 18],
  [16, 18], [18, 19], [17, 20], [18, 20], [20, 21], [18, 21], [14, 22], [17, 22],
];

export function LoginGraph({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 1140 700"
      fill="none"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
    >
      {EDGES.map(([a, b], i) => {
        const s = NODES[a];
        const t = NODES[b];
        return (
          <g key={`e${i}`}>
            <line
              x1={s.x} y1={s.y} x2={t.x} y2={t.y}
              stroke="rgba(255, 255, 255,0.09)"
              strokeWidth={1}
            />
            <line
              x1={s.x} y1={s.y} x2={t.x} y2={t.y}
              stroke="rgba(52,211,153,0.5)"
              strokeWidth={1.25}
              className="login-flow"
              style={{ animationDelay: `${(i % 7) * 0.35}s` }}
            />
          </g>
        );
      })}
      {NODES.map((n, i) => (
        <g key={`n${i}`}>
          <circle cx={n.x} cy={n.y} r={n.r} fill="rgba(255, 255, 255,0.13)" />
          <circle
            cx={n.x} cy={n.y} r={n.r}
            fill="none"
            stroke="rgba(52,211,153,0.55)"
            strokeWidth={1}
            className="login-node"
            style={{ animationDelay: `${(i % 5) * 0.7}s` }}
          />
        </g>
      ))}
    </svg>
  );
}
