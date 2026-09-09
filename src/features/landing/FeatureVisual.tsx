import { RoomSchematic } from "./RoomSchematic";

export function FeatureVisual({ type }: { type: "capture" | "shell" | "variants" | "swap" | "products" | "style" }) {
  if (type === "capture") {
    return (
      <div className="capture-stack">
        <div className="capture-photo"><img className="photo-fill" src="/images/living-room-detail.jpg" alt="Example Room Capture photograph by Lisa Anna" loading="lazy" decoding="async" /></div>
        <span className="capture-tag">VIEW 02 / 04</span>
        <i className="capture-frame capture-frame--one" aria-hidden="true" />
        <i className="capture-frame capture-frame--two" aria-hidden="true" />
      </div>
    );
  }
  if (type === "shell") return <RoomSchematic compact />;
  if (type === "variants") {
    return <div className="variant-pair"><div><span>A</span><RoomSchematic compact variant="A" /></div><div><span>B</span><RoomSchematic compact variant="B" /></div></div>;
  }
  if (type === "swap") {
    return <div className="swap-pair"><div><span>FRAME</span><RoomSchematic compact /></div><div><span>COVE</span><RoomSchematic compact swapped /></div><p>Placement and 0.8 × 0.8m footprint stay invariant.</p></div>;
  }
  if (type === "products") {
    return (
      <div className="product-shelf">
        {[
          ["SO-014", "Sofa", "2.10 × 0.92m"], ["CH-022", "Chair", "0.80 × 0.80m"], ["TB-008", "Table", "1.10 × 0.62m"], ["RG-031", "Rug", "2.40 × 1.70m"],
        ].map(([id, name, size], index) => <div key={id}><span className={`product-glyph glyph-${index}`} aria-hidden="true" /><strong>{name}</strong><small>{id}<br />{size}</small></div>)}
        <p>Illustrative schema, not live Product availability.</p>
      </div>
    );
  }
  return (
    <div className="style-strip">
      <figure><img className="photo-fill" src="/images/living-room-detail.jpg" alt="Neutral living room Style inspiration" loading="lazy" decoding="async" /></figure>
      <figure><img className="photo-fill" src="/images/living-room.jpg" alt="Bright living room Style inspiration" loading="lazy" decoding="async" /></figure>
      <figure><img className="photo-fill" src="/images/bedroom.jpg" alt="Warm bedroom Style inspiration" loading="lazy" decoding="async" /></figure>
      <span>Pick what feels right</span>
    </div>
  );
}
