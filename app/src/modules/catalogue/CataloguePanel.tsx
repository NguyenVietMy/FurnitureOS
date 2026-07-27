"use client";

import { useMemo, useState } from "react";

import { ALL_CATEGORIES, categoriesOf, filterItems } from "./filter";
import type { Item } from "./types";
import styles from "./CataloguePanel.module.css";

/**
 * What a drag from the catalogue carries: just the item id.
 *
 * A custom MIME type rather than `text/plain`, so a stray drag of selected text from
 * somewhere else on the page cannot be mistaken for a sofa.
 */
export const CATALOGUE_ITEM_MIME = "application/x-furnitureos-item";

/**
 * The catalogue panel: category chips, a search box, and a draggable card per item.
 *
 * Built for around a hundred items even though v1 seeds twenty — hence the scrolling
 * list and the client-side filter rather than a grid that assumes it can show
 * everything at once.
 *
 * No prices here. Prices are carried on every item and are not shown until issue 06
 * introduces `lib/money`; formatting VND in two places would be one place too many.
 */
export function CataloguePanel({
  items,
  onAdd,
}: {
  items: readonly Item[];
  /** Place an item without dragging — the keyboard path, and a faster mouse path. */
  onAdd: (item: Item) => void;
}) {
  const [category, setCategory] = useState(ALL_CATEGORIES);
  const [query, setQuery] = useState("");

  const categories = useMemo(() => categoriesOf(items), [items]);
  const visible = useMemo(
    () => filterItems(items, { category, query }),
    [items, category, query],
  );

  return (
    <aside className={styles.panel} aria-label="Catalogue">
      <div className={styles.controls}>
        <input
          className={styles.search}
          type="search"
          value={query}
          placeholder="Search furniture"
          aria-label="Search furniture"
          onChange={(event) => setQuery(event.target.value)}
        />

        <div className={styles.chips} role="group" aria-label="Categories">
          <Chip
            label="All"
            active={category === ALL_CATEGORIES}
            onClick={() => setCategory(ALL_CATEGORIES)}
          />
          {categories.map((name) => (
            <Chip
              key={name}
              label={name}
              active={category === name}
              onClick={() => setCategory(name)}
            />
          ))}
        </div>
      </div>

      <ul className={styles.list}>
        {visible.map((item) => (
          <ItemCard key={item.id} item={item} onAdd={onAdd} />
        ))}
      </ul>

      {visible.length === 0 && (
        <p className={styles.empty}>Nothing matches. Try another word, or clear the filter.</p>
      )}
    </aside>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      className={styles.chip}
      aria-pressed={active}
      data-active={active || undefined}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function ItemCard({ item, onAdd }: { item: Item; onAdd: (item: Item) => void }) {
  return (
    <li>
      <button
        type="button"
        className={styles.card}
        draggable
        onDragStart={(event) => {
          event.dataTransfer.setData(CATALOGUE_ITEM_MIME, item.id);
          event.dataTransfer.effectAllowed = "copy";
        }}
        onClick={() => onAdd(item)}
        title={`Drag into the room, or click to place ${item.name}`}
      >
        <Footprint item={item} />
        <span className={styles.details}>
          <span className={styles.name}>{item.name}</span>
          <span className={styles.size}>
            {formatMetres(item.width_m)} × {formatMetres(item.depth_m)} ×{" "}
            {formatMetres(item.height_m)} m
          </span>
        </span>
      </button>
    </li>
  );
}

/**
 * A rectangle at the item's true plan proportions.
 *
 * Standing in for issue 13's product photography, and doing something the photograph
 * will not: showing at a glance that a wardrobe is deep and a bookcase is not.
 */
function Footprint({ item }: { item: Item }) {
  const longest = Math.max(item.width_m, item.depth_m);

  return (
    <span className={styles.thumb} aria-hidden>
      <span
        className={styles.footprint}
        style={{
          width: `${(item.width_m / longest) * 100}%`,
          height: `${(item.depth_m / longest) * 100}%`,
        }}
      />
    </span>
  );
}

/** Metres to two decimals, trailing zeroes and all: 0.90 reads as a measurement. */
function formatMetres(value: number): string {
  return value.toFixed(2);
}
