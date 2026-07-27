import { deriveThumbnail } from "./thumbnail";
import styles from "./UnitThumbnail.module.css";
import type { UnitSummary } from "./types";

/**
 * A top-down floorplan of a unit, sized by its container.
 *
 * All the geometry lives in `thumbnail.ts`; this decides only how it looks. A server
 * component — it is one `<svg>` with no state and nothing to hydrate.
 */
export function UnitThumbnail({ unit }: { unit: UnitSummary }) {
  const thumbnail = deriveThumbnail(unit);

  return (
    <svg
      className={styles.thumbnail}
      viewBox={thumbnail.viewBox}
      // The card already names the unit in text; announcing the drawing too would just
      // read the same thing twice.
      aria-hidden="true"
      focusable="false"
    >
      {thumbnail.rooms.map((room) => (
        <path key={room.key} className={styles.room} data-room-type={room.type} d={room.d} />
      ))}
      <path className={styles.outline} d={thumbnail.outline} />
    </svg>
  );
}
