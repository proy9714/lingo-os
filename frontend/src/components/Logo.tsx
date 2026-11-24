import { LOGO_TILES } from "./logoPaths";

/** The Lingo OS logo: four scripts on four tiles (docs/brand/logo.svg). `mark` = the tiles without the dark square. */
export function Logo({ size = 36, mark = false, className }: { size?: number; mark?: boolean; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox={mark ? "86 86 340 340" : "0 0 512 512"}
      role="img"
      aria-label="Lingo OS"
      className={className}
    >
      {!mark && (
        <>
          <defs>
            <linearGradient id="lingo-logo-bg" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#1b2236" />
              <stop offset="1" stopColor="#0a0e1a" />
            </linearGradient>
          </defs>
          <rect width="512" height="512" rx="116" fill="url(#lingo-logo-bg)" />
        </>
      )}
      {LOGO_TILES.map((tile) => (
        <g key={tile.x * 1000 + tile.y}>
          <rect x={tile.x} y={tile.y} width="158" height="158" rx="40" fill={tile.fill} />
          <path d={tile.d} fill={tile.ink} />
        </g>
      ))}
    </svg>
  );
}
