import { Link } from "react-router";
import { FeatureVisual } from "./FeatureVisual";
import "./landing.css";
import { useEffect, useRef, useState } from "react";
import { RoomSchematic } from "./RoomSchematic";

type RoomType = "living" | "bedroom";
type Variant = "A" | "B" | "C";

const productTabs = [
  { id: "capture", label: "Capture", icon: "⌗", summary: "Photos establish the real Room." },
  { id: "shell", label: "Room Shell", icon: "⌞", summary: "Confirmed dimensions establish scale." },
  { id: "variants", label: "Variants", icon: "⋮", summary: "Distinct arrangements share one Room Shell." },
  { id: "swap", label: "Swap", icon: "↔", summary: "A new furnishing keeps the same Placement." },
] as const;

const features = [
  {
    id: "capture",
    title: "Start with the Room you already have",
    body: "A Capture of roughly four views gives FurnitureOS the wall, Opening and furniture context it needs. You confirm the Room shape and dimensions.",
    visual: "capture",
  },
  {
    id: "room-shell",
    title: "Keep the measurements honest",
    body: "FurnitureOS reads doors and windows. You choose the Room shape and confirm the numbers, so your measurements stay in charge.",
    visual: "shell",
  },
  {
    id: "variants",
    title: "Compare real spatial choices",
    body: "Variants rethink the arrangement inside one Room Shell, so the alternatives are meaningful instead of being unrelated room pictures.",
    visual: "variants",
  },
  {
    id: "swap",
    title: "Swap a Product, keep its place",
    body: "A Swap changes one furnishing only when the replacement is the same size. It keeps the same position, so nothing else moves.",
    visual: "swap",
  },
  {
    id: "products",
    title: "A direction built around real Products",
    body: "FurnitureOS is designed to assemble Designs from a finite Catalogue with dimensions and purchase metadata—not furniture invented by an image model.",
    visual: "products",
  },
  {
    id: "style",
    title: "Choose Style by pointing, not naming",
    body: "Pick the rooms that feel right. Visual references carry more nuance than forcing your taste into a single style label.",
    visual: "style",
  },
] as const;

const faqs = [
  ["Is this a working room generator?", "Not yet. This page presents the FurnitureOS product direction and an interactive concept preview. It does not generate a live Design."],
  ["Where do the room dimensions come from?", "You confirm them. A vision model can read walls, doors and windows from a Capture, but typed dimensions remain the source of truth for scale."],
  ["Does a Swap move the furniture?", "No. A Swap keeps the existing Placement and only accepts a replacement whose footprint fits the same slot."],
  ["Are the inspiration photos generated Designs?", "No. They are credited room photographs used only to communicate Style and Capture direction."],
  ["Can I buy the illustrated furnishings?", "No. The schematic furnishings in this sample are illustrative and are not presented as available Products."],
] as const;

function Wordmark() {
  return <span className="wordmark" aria-label="FurnitureOS">FURNITURE<span>OS</span></span>;
}

function ArrowIcon() {
  return <span aria-hidden="true">↗</span>;
}

export function LandingPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [roomType, setRoomType] = useState<RoomType>("living");
  const [variant, setVariant] = useState<Variant>("A");
  const [swapped, setSwapped] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  const openSample = (event: React.MouseEvent<HTMLButtonElement>) => {
    triggerRef.current = event.currentTarget;
    dialogRef.current?.showModal();
  };

  const closeSample = () => {
    dialogRef.current?.close();
    triggerRef.current?.focus();
  };

  const selectTab = (index: number) => {
    setActiveTab(index);
    tabRefs.current[index]?.focus();
  };

  const onTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % productTabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + productTabs.length) % productTabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = productTabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(next);
  };

  const closeMenu = () => setMenuOpen(false);

  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <div className="announcement">
        <a href="#sample" onClick={closeMenu}>A clearer way to plan a real Room is taking shape <ArrowIcon /></a>
      </div>

      <header className="site-header">
        <div className="header-main">
          <a href="#top" className="brand-link" aria-label="FurnitureOS home"><Wordmark /></a>
          <nav className="desktop-nav" aria-label="Primary navigation">
            <a href="#product">Product</a>
            <a href="#how-it-works">How it works</a>
            <a href="#features">Features</a>
            <a href="#gallery">Examples</a>
            <a href="#faq">FAQ</a>
            <Link className="room-preview-link" to="/design">Room preview</Link>
          </nav>
          <button className="nav-cta" type="button" onClick={openSample}>EXPLORE SAMPLE</button>
        </div>
        <div className="mobile-nav-row">
          <button
            className="mobile-nav-trigger"
            type="button"
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            Product · How it works · FAQ <span aria-hidden="true">{menuOpen ? "×" : "+"}</span>
          </button>
          <nav id="mobile-menu" className="mobile-menu" aria-label="Mobile navigation" hidden={!menuOpen}>
            <a href="#product" onClick={closeMenu}>Product</a>
            <a href="#how-it-works" onClick={closeMenu}>How it works</a>
            <a href="#features" onClick={closeMenu}>Features</a>
            <a href="#gallery" onClick={closeMenu}>Examples</a>
            <a href="#faq" onClick={closeMenu}>FAQ</a>
            <Link to="/design" onClick={closeMenu}>Room preview</Link>
          </nav>
        </div>
      </header>

      <main id="main">
        <section className="hero framed-grid" id="top" aria-labelledby="hero-title">
          <span className="corner corner--tl" aria-hidden="true" />
          <span className="corner corner--tr" aria-hidden="true" />
          <span className="corner corner--bl" aria-hidden="true" />
          <span className="corner corner--br" aria-hidden="true" />
          <div className="hero-copy">
            <h1 id="hero-title">AI powered room design<br />built for real life</h1>
            <p>FurnitureOS is being built to turn photos of your Room into a furnished Design made to fit real life.</p>
            <div className="hero-control" id="sample">
              <label>
                <span>Room Type</span>
                <select value={roomType} onChange={(event) => setRoomType(event.target.value as RoomType)}>
                  <option value="living">Living room</option>
                  <option value="bedroom">Bedroom</option>
                </select>
              </label>
              <button type="button" className="dither-button" onClick={openSample}>
                <span className="cta-long">Explore a sample Design</span>
                <span className="cta-short">Explore sample</span>
              </button>
            </div>
          </div>
        </section>

        <section className="product-frame" id="product" aria-labelledby="product-heading">
          <h2 id="product-heading" className="sr-only">FurnitureOS product preview</h2>
          <div className="product-tabs" role="tablist" aria-label="Product preview">
            {productTabs.map((tab, index) => (
              <button
                key={tab.id}
                ref={(node) => { tabRefs.current[index] = node; }}
                id={`tab-${tab.id}`}
                type="button"
                role="tab"
                aria-selected={activeTab === index}
                aria-controls={`panel-${tab.id}`}
                tabIndex={activeTab === index ? 0 : -1}
                onClick={() => setActiveTab(index)}
                onKeyDown={(event) => onTabKeyDown(event, index)}
              >
                <span aria-hidden="true">{tab.icon}</span>{tab.label}
              </button>
            ))}
          </div>
          <div className="preview-surround framed-grid">
            {productTabs.map((tab, index) => (
              <div
                key={tab.id}
                id={`panel-${tab.id}`}
                role="tabpanel"
                aria-labelledby={`tab-${tab.id}`}
                hidden={activeTab !== index}
                className="product-panel"
              >
                <div className="app-window">
                  <div className="app-toolbar">
                    <span className="app-dots" aria-hidden="true"><i /><i /><i /></span>
                    <Wordmark />
                    <span className="concept-badge">CONCEPT PREVIEW</span>
                  </div>
                  <div className="app-body">
                    <aside className="app-sidebar">
                      <span className="mono-label">{tab.label}</span>
                      <h3>{tab.summary}</h3>
                      <p>{index === 0 ? "Use four connected views, then confirm the shape." : index === 1 ? "A 4.0 × 3.0m shell with a door swing and window." : index === 2 ? "Variant B shifts the arrangement, not the room." : "Frame chair and Cove chair share one 0.8 × 0.8m slot."}</p>
                      <div className="sidebar-steps" aria-hidden="true">
                        <span className={index >= 0 ? "is-on" : ""}>Capture</span>
                        <span className={index >= 1 ? "is-on" : ""}>Confirm</span>
                        <span className={index >= 2 ? "is-on" : ""}>Compare</span>
                        <span className={index >= 3 ? "is-on" : ""}>Refine</span>
                      </div>
                    </aside>
                    <div className="app-canvas">
                      {index === 0 ? (
                        <div className="capture-preview">
                          <img className="photo-fill" src="/images/living-room-detail.jpg" alt="Living room Capture example, photographed by Lisa Anna" loading="eager" decoding="async" fetchPriority="high" />
                          <span>Capture view 02 / 04</span>
                        </div>
                      ) : (
                        <RoomSchematic roomType={roomType} variant={index === 2 ? "B" : "A"} swapped={index === 3} />
                      )}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <p className="truth-note">Interactive concept preview. Illustrative furnishings; no live Catalogue or room generation.</p>
        </section>

        <section className="concept-stats" aria-label="FurnitureOS concept facts">
          {[
            ["≈4", "Capture views"], ["2", "Room Types"], ["3", "Design Variants"], ["1", "fixed Placement per Swap"],
          ].map(([value, label]) => (
            <div key={label}><strong>{value}</strong><span>{label}</span></div>
          ))}
        </section>

        <section className="catalogue-wall" aria-labelledby="catalogue-title">
          <div className="section-intro">
            <h2 id="catalogue-title">A Design language made of things that fit</h2>
            <p>FurnitureOS is being shaped around a finite Catalogue: real dimensions first, visual character second.</p>
          </div>
          <div className="catalogue-grid" aria-label="Illustrative Product categories">
            {[
              ["▰", "Beds"], ["▱", "Sofas"], ["◒", "Chairs"], ["▭", "Tables"],
              ["⌑", "Storage"], ["◯", "Lighting"], ["▧", "Rugs"], ["⌂", "Room Shells"],
              ["↔", "Swap fits"], ["⌁", "Openings"], ["⊞", "Zones"], ["◇", "Style cues"],
            ].map(([icon, label]) => <div key={label}><span aria-hidden="true">{icon}</span>{label}</div>)}
          </div>
        </section>

        <section className="dark-cta patterned-band" aria-labelledby="dark-cta-title">
          <div>
            <span className="mono-label">ROOM → DESIGN</span>
            <h2 id="dark-cta-title">See one room become a place to live</h2>
          </div>
          <button type="button" className="dither-button" onClick={openSample}>Explore a sample Design</button>
        </section>

        <section id="features" className="features" aria-labelledby="features-title">
          <div className="section-intro section-intro--wide">
            <h2 id="features-title">Every decision starts with the actual Room</h2>
            <p>No imagined floor plan. No furniture painted into a photograph. A deliberate path from Capture to valid Placement.</p>
          </div>
          {features.map((feature) => (
            <article className="feature-row" id={feature.id} key={feature.id}>
              <div className="feature-copy">
                <h3>{feature.title}</h3>
                <p>{feature.body}</p>
              </div>
              <div className={`feature-visual feature-visual--${feature.visual}`}>
                <FeatureVisual type={feature.visual} />
              </div>
            </article>
          ))}
        </section>

        <section className="blue-band patterned-band" aria-labelledby="blue-title">
          <div className="blue-copy">
            <span className="mono-label">TASTE MEETS GEOMETRY</span>
            <h2 id="blue-title">The model chooses.<br />The solver places.</h2>
            <p>Your taste guides the choice. Confirmed measurements keep every furnishing in bounds.</p>
          </div>
          <div className="intent-console" aria-label="Illustrative Placement Intent">
            <div><span>01</span><code>Room · 4.0 × 3.0m</code></div>
            <div><span>02</span><code>Chair · 0.8 × 0.8m</code></div>
            <div><span>03</span><code>Same size · same position</code></div>
            <div className="console-result"><span>✓</span><code>Fits the confirmed Room</code></div>
          </div>
        </section>

        <section id="how-it-works" className="workflow" aria-labelledby="workflow-title">
          <div className="section-intro">
            <h2 id="workflow-title">From four walls to one clear choice</h2>
            <p>Each step has a different job. Keeping those jobs separate is how a Design stays both useful and believable.</p>
          </div>
          <div className="workflow-grid">
            {[
              ["Capture", "FurnitureOS reads", "Walls, doors, windows and visible context from connected room views."],
              ["Confirm", "You decide", "Room Type, shape and measured dimensions establish the truth."],
              ["Compose", "FurnitureOS plans", "Style guides the Product choices; measurements keep the arrangement in bounds."],
              ["Refine", "You control", "Compare Variants, Swap compatible footprints, and choose."],
            ].map(([title, owner, body], index) => (
              <article key={title}>
                <span className="workflow-number">0{index + 1}</span>
                <h3>{title}</h3>
                <strong>{owner}</strong>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section id="gallery" className="gallery" aria-labelledby="gallery-title">
          <div className="section-intro section-intro--wide">
            <h2 id="gallery-title">Point to the feeling you want</h2>
            <p>These credited photographs are Style inspiration only—not generated Designs or evidence of Product availability.</p>
          </div>
          <div className="gallery-grid">
            <figure className="gallery-main">
              <img className="photo-fill" src="/images/living-room-detail.jpg" alt="Neutral living room Style inspiration photographed by Lisa Anna" loading="lazy" decoding="async" />
              <figcaption><span>Quiet structure</span><small>Style inspiration · Lisa Anna</small></figcaption>
            </figure>
            <figure>
              <img className="photo-fill" src="/images/living-room.jpg" alt="Bright living room Style inspiration photographed by Bailey Alexander" loading="lazy" decoding="async" />
              <figcaption><span>Light and open</span><small>Style inspiration · Bailey Alexander</small></figcaption>
            </figure>
            <figure>
              <img className="photo-fill" src="/images/bedroom.jpg" alt="Warm bedroom Style inspiration photographed by Erik Mclean" loading="lazy" decoding="async" />
              <figcaption><span>Soft and warm</span><small>Style inspiration · Erik Mclean</small></figcaption>
            </figure>
          </div>
        </section>

        <section id="faq" className="faq" aria-labelledby="faq-title">
          <div className="faq-heading">
            <span className="mono-label">THE HONEST VERSION</span>
            <h2 id="faq-title">Questions before you explore</h2>
          </div>
          <div className="faq-list">
            {faqs.map(([question, answer]) => (
              <details key={question}>
                <summary>{question}<span aria-hidden="true">+</span></summary>
                <p>{answer}</p>
              </details>
            ))}
          </div>
        </section>

        <section className="final-cta patterned-band" aria-labelledby="final-title">
          <span className="mono-label">A ROOM, RESOLVED</span>
          <h2 id="final-title">See the next furniture decision in the Room</h2>
          <p>Explore the interaction model behind FurnitureOS.</p>
          <button type="button" className="dither-button" onClick={openSample}>Explore a sample Design</button>
        </section>
      </main>

      <footer>
        <div className="footer-top">
          <Wordmark />
          <div>
            <strong>Product</strong>
            <Link to="/design">Room preview</Link><a href="#product">Concept preview</a><a href="#features">Features</a><a href="#gallery">Style</a>
          </div>
          <div>
            <strong>Learn</strong>
            <a href="#how-it-works">How it works</a><a href="#faq">FAQ</a><a href="#sample">Try the sample</a>
          </div>
        </div>
        <div className="footer-wordmark" aria-hidden="true">FURNITUREOS</div>
        <p className="footer-note">Product concept · no live Catalogue, generation, purchase flow or claimed customer traction.</p>
      </footer>

      <dialog ref={dialogRef} className="sample-dialog" aria-labelledby="dialog-title" onClose={() => triggerRef.current?.focus()}>
        <div className="dialog-header">
          <div><span className="mono-label">INTERACTIVE CONCEPT</span><h2 id="dialog-title">Sample Design</h2></div>
          <button type="button" className="icon-button" onClick={closeSample} aria-label="Close sample">×</button>
        </div>
        <p className="dialog-disclosure">Interactive concept preview. Illustrative furnishings; no live Catalogue or room generation.</p>
        <p className="dialog-preview-link"><Link to="/design">Open the real Room preview ↗</Link></p>
        <div className="dialog-controls">
          <label>Room Type
            <select value={roomType} onChange={(event) => setRoomType(event.target.value as RoomType)}>
              <option value="living">Living room</option><option value="bedroom">Bedroom</option>
            </select>
          </label>
          <fieldset>
            <legend>Variant</legend>
            {(["A", "B", "C"] as Variant[]).map((value) => (
              <button key={value} type="button" aria-pressed={variant === value} onClick={() => setVariant(value)}>{value}</button>
            ))}
          </fieldset>
        </div>
        <RoomSchematic roomType={roomType} variant={variant} swapped={swapped} />
        <div className="swap-control">
          <div><span className="mono-label">SAME 0.8 × 0.8M FOOTPRINT</span><strong>{swapped ? "Cove chair" : "Frame chair"}</strong><small>Placement x412 · y184 · rotation 0°</small></div>
          <button type="button" onClick={() => setSwapped((value) => !value)}>Swap to {swapped ? "Frame" : "Cove"} chair</button>
        </div>
      </dialog>
    </>
  );
}
