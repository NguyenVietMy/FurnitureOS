"use client";

import { useId } from "react";

type RoomSchematicProps = {
  roomType?: "living" | "bedroom";
  variant?: "A" | "B" | "C";
  swapped?: boolean;
  compact?: boolean;
};

export function RoomSchematic({
  roomType = "living",
  variant = "A",
  swapped = false,
  compact = false,
}: RoomSchematicProps) {
  const titleId = useId();
  const variantOffset = variant === "B" ? 28 : variant === "C" ? -24 : 0;
  const isBedroom = roomType === "bedroom";
  const bedroomBedX = variant === "A" ? 185 : variant === "B" ? 155 : 195;
  const fixtureName = swapped ? "Cove chair" : "Frame chair";

  return (
    <figure className={`room-schematic${compact ? " room-schematic--compact" : ""}`}>
      <svg viewBox="0 0 640 390" role="img" aria-labelledby={titleId}>
        <title id={titleId}>{`Illustrative ${roomType === "living" ? "living room" : "bedroom"} concept, Variant ${variant}, with ${fixtureName}`}</title>
        <rect className="room-floor" x="58" y="44" width="524" height="292" />
        <path className="room-wall" d="M58 336V44h524v292H394m-84 0H58" />
        <path className="room-opening" d="M310 336a84 84 0 0 1 84-84v84" />
        <path className="room-window" d="M198 44v-11h174v11m-174 8h174" />

        {isBedroom ? (
          <>
            <g className="furnishing furnishing--primary furnishing--bed" transform={`translate(${bedroomBedX} 88)`}>
              <rect width="214" height="146" rx="3" />
              <rect className="furnishing-detail" x="15" y="14" width="84" height="34" rx="5" />
              <rect className="furnishing-detail" x="115" y="14" width="84" height="34" rx="5" />
              <path className="furnishing-line" d="M14 64h186M107 64v68" />
            </g>
            <g className="furnishing furnishing--secondary" transform="translate(78 76)">
              <rect width="72" height="68" rx="3" />
              <circle className="furnishing-detail" cx="36" cy="34" r="9" />
            </g>
            <g className="furnishing furnishing--secondary" transform="translate(454 76)">
              <rect width="72" height="68" rx="3" />
              <circle className="furnishing-detail" cx="36" cy="34" r="9" />
            </g>
            <g className="furnishing furnishing--rug" transform={`translate(${164 - variantOffset / 2} 246)`}>
              <rect width="260" height="66" rx="32" />
            </g>
          </>
        ) : (
          <>
            <g className="furnishing furnishing--rug" transform="translate(126 182)">
              <rect width="262" height="126" rx="8" />
            </g>
            <g className="furnishing furnishing--primary" transform={`translate(${110 + variantOffset} 82)`}>
              <rect width="222" height="72" rx="12" />
              <path className="furnishing-line" d="M12 40h198M76 12v48m70-48v48" />
            </g>
            <g className="furnishing furnishing--secondary" transform={`translate(${192 - variantOffset} 216)`}>
              <rect width="150" height="76" rx="38" />
              <ellipse className="furnishing-detail" cx="75" cy="38" rx="48" ry="20" />
            </g>
          </>
        )}

        <g
          className={`swap-fixture ${swapped ? "swap-fixture--cove" : "swap-fixture--frame"}`}
          transform="translate(412 184) rotate(0)"
          data-testid="swap-fixture"
          data-footprint="0.8x0.8"
          data-placement="x:412;y:184;rotation:0"
        >
          <rect className="fixture-footprint" x="0" y="0" width="64" height="64" />
          {swapped ? (
            <>
              <circle cx="32" cy="31" r="28" />
              <path d="M7 36c10-16 39-20 50-3M14 54l-5 10m41-10 5 10" />
            </>
          ) : (
            <>
              <rect x="4" y="4" width="56" height="54" rx="4" />
              <path d="M4 42h56M12 58l-3 6m43-6 3 6M14 12v28m36-28v28" />
            </>
          )}
        </g>

        <g className="dimension dimension--x">
          <path d="M412 286v18m64-18v18M412 297h64" />
          <text x="444" y="321" textAnchor="middle">0.8m</text>
        </g>
        <g className="dimension dimension--y">
          <path d="M493 184h18m-18 64h18m7-64v64" />
          <text x="526" y="220" transform="rotate(90 526 220)" textAnchor="middle">0.8m</text>
        </g>
        <text className="room-caption" x="78" y="322">4.0 × 3.0m Room Shell · Variant {variant}</text>
      </svg>
      <figcaption>
        <span>{fixtureName}</span>
        <span>0.8 × 0.8m · fixed Placement</span>
      </figcaption>
    </figure>
  );
}
