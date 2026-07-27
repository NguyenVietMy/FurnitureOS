import Link from "next/link";

import styles from "./page.module.css";

/**
 * Placeholder home page.
 *
 * The public gallery of layouts is issue 02 and needs a list endpoint that does not
 * exist yet. Until then this is a signpost to the one seeded unit, so the walking
 * skeleton has a front door.
 */
export default function Home() {
  return (
    <main className={styles.page}>
      <h1 className={styles.title}>FurnitureOS</h1>
      <p className={styles.lede}>Furnish your apartment before you move in.</p>
      <Link className={styles.link} href="/unit/sunrise-b">
        View Sunrise Tower, Type B →
      </Link>
    </main>
  );
}
