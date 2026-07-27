import Link from "next/link";
import { notFound } from "next/navigation";

import { fetchItems } from "@/modules/catalogue";
import { Planner } from "@/modules/plan";
import { fetchUnit } from "@/modules/units";

import styles from "./page.module.css";

export default async function UnitPage({ params }: PageProps<"/unit/[slug]">) {
  const { slug } = await params;
  // The catalogue does not depend on which unit this is, so neither request waits.
  const [unit, items] = await Promise.all([fetchUnit(slug), fetchItems()]);

  if (!unit) notFound();

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Link className={styles.back} href="/">
            ← All layouts
          </Link>
          <h1 className={styles.title}>{unit.name}</h1>
          <p className={styles.subtitle}>{unit.building}</p>
        </div>
        <dl className={styles.facts}>
          <div>
            <dt>Floor area</dt>
            <dd>{unit.area_m2.toFixed(1)} m²</dd>
          </div>
          <div>
            <dt>Bedrooms</dt>
            <dd>{unit.bedrooms}</dd>
          </div>
          <div>
            <dt>Ceiling</dt>
            <dd>{unit.ceiling_height_m.toFixed(2)} m</dd>
          </div>
        </dl>
      </header>

      <div className={styles.body}>
        <Planner unit={unit} catalogue={items} />
      </div>

      <p className={styles.hint}>
        Left-drag furniture to move it · right-drag to orbit · scroll to zoom
      </p>
    </main>
  );
}
