import type { Product } from '@/shared/api/types';
import { attributionStatusPresentation } from './DesignPanel';

/** Read-only Catalogue facts, shared by public and captured live Designs. */
export function ProductDisclosures({ products }: { products: ReadonlyArray<Product> }) {
  return <section aria-label="Product sources and availability">
    <h2>Products and sources</h2>
    {products.map((product, index) => <article key={`${product.id}-${index}`}>
      <h3>{product.displayName}</h3>
      <p>{product.purchase.note}{product.purchaseUrl ? <> <a href={product.purchaseUrl} target="_blank" rel="noreferrer noopener">View at the retailer</a></> : ' No verified purchase link.'}</p>
      {product.attribution.licenseNote && <p className={attributionStatusPresentation(product.attribution.licenseStatus).className}>{product.attribution.licenseNote}</p>}
      <p>Mesh from <a href={product.attribution.sourceUrl} target="_blank" rel="noreferrer noopener">{product.attribution.source}</a>, © {product.attribution.holder}. Archive license: <a href={product.attribution.licenseUrl} target="_blank" rel="noreferrer noopener">{product.attribution.license}</a>.</p>
      <details><summary>Mesh source and modifications</summary>
        <p>{product.attribution.modifications}</p><p>{product.attribution.citation}</p>
        <p><a className="break" href={product.attribution.materialUrl} target="_blank" rel="noreferrer noopener">Original source record</a></p>
        <ul>{(product.attribution.licenseEvidence ?? []).map((evidence, i) => <li key={i}><a href={evidence.url} target="_blank" rel="noreferrer noopener">{evidence.label}</a>: {evidence.recordedLicense}</li>)}</ul>
      </details>
    </article>)}
  </section>;
}
