import Link from "next/link";

import { fetchUnits, UnitThumbnail } from "@/modules/units";

import styles from "./page.module.css";

/**
 * The public gallery: the front door of the funnel.
 *
 * Deliberately unauthenticated — no code, no unit-number lookup, no verification. A
 * buyer arrives from a flyer or a QR code and picks their layout out of a grid, so
 * anything standing between the landing and the 3D scene is a step to lose them on.
 */
export default async function GalleryPage() {
  const units = await fetchUnits();

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>FurnitureOS</h1>
        <p className={styles.lede}>
          Furnish your apartment before you move in. Pick your layout to begin.
        </p>
      </header>

      {units.length === 0 ? (
        <p className={styles.empty}>No layouts published yet.</p>
      ) : (
        <ul className={styles.grid}>
          {units.map((unit) => (
            <li key={unit.slug}>
              <Link className={styles.card} href={`/unit/${unit.slug}`}>
                <span className={styles.frame}>
                  <UnitThumbnail unit={unit} />
                </span>
                <span className={styles.body}>
                  <span className={styles.name}>{unit.name}</span>
                  <span className={styles.building}>{unit.building}</span>
                  <span className={styles.facts}>
                    {bedroomLabel(unit.bedrooms)} · {unit.area_m2.toFixed(1)} m²
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function bedroomLabel(bedrooms: number): string {
  return bedrooms === 1 ? "1 bedroom" : `${bedrooms} bedrooms`;
}
