import type { FitResult, Product, RoomShell } from '@/shared/api/types';

/**
 * The written half of the Design: what the Product is, where it ended up, what
 * the Mesh costs and where it came from. The API-backed SPA keeps these facts
 * outside the canvas so a reader with WebGL disabled can still access them.
 */

const metres = (value: number) => `${value.toFixed(2)} m`;
const centimetres = (value: number) => `${Math.round(value * 100)} cm`;
const kilobytes = (bytes: number) => `${(bytes / 1024).toFixed(0)} kB`;
const megabytes = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

export function attributionStatusPresentation(status: Product['attribution']['licenseStatus']) {
  return status === 'conflicting-source-records'
    ? { className: 'warning', testId: 'license-conflict' }
    : { className: 'subtle', testId: 'license-status' };
}

function WallLabel({ room, wallId }: { room: RoomShell; wallId: string }) {
  const wall = room.walls.find((candidate) => candidate.id === wallId);
  return <>{wall ? wall.label.toLowerCase() : wallId}</>;
}

function placementVerb(intentKind?: string) {
  if (intentKind === 'centred_on') return 'Centred on';
  if (intentKind === 'in_corner') return 'Placed in the corner at';
  return 'Placed against';
}

export function DesignPanel({
  room,
  product,
  fit,
  intentKind,
}: {
  room: RoomShell;
  product: Product;
  fit: FitResult;
  intentKind?: string;
}) {
  const { widthM, heightM, depthM } = product.dimensionsM;
  const budgetLimit = 5_000_000;
  const attributionStatus = attributionStatusPresentation(product.attribution.licenseStatus);

  return (
    <div className="product-facts" data-testid={`product-facts-${product.id}`}>
      <header className="panel-head">
        <p className="eyebrow">{product.category} · {product.roomTypes.join(', ')}</p>
        <h2>{product.displayName}</h2>
        <p className="subtle">
          {product.brand} · {product.colour}
        </p>
      </header>

      <section>
        <h3>Dimensions</h3>
        <p className="subtle">Measured from the normalized Mesh, not from listing text.</p>
        <dl className="rows" data-testid="dimensions">
          <div>
            <dt>Width</dt>
            <dd>{metres(widthM)} <span className="subtle">({centimetres(widthM)})</span></dd>
          </div>
          <div>
            <dt>Height</dt>
            <dd>{metres(heightM)} <span className="subtle">({centimetres(heightM)})</span></dd>
          </div>
          <div>
            <dt>Depth</dt>
            <dd>{metres(depthM)} <span className="subtle">({centimetres(depthM)})</span></dd>
          </div>
          <div>
            <dt>Origin</dt>
            <dd>{product.mesh.normalization.originRule}, {product.mesh.normalization.upAxis} up, front {product.frontAxis}</dd>
          </div>
        </dl>
      </section>

      <section>
        <h3>Placement</h3>
        {fit.status === 'fits' ? (
          <>
            <p data-testid="fit-status" data-fit="fits">
              {placementVerb(intentKind)} the{' '}
              <WallLabel room={room} wallId={fit.placement.wallContact?.wallId ?? ''} /> in this{' '}
              {room.ceilingHeightM.toFixed(1)} m-high room.
            </p>
            <dl className="rows">
              <div>
                <dt>Position</dt>
                <dd>
                  x {fit.placement.position[0].toFixed(2)}, z {fit.placement.position[2].toFixed(2)}
                </dd>
              </div>
              <div>
                <dt>Yaw</dt>
                <dd>{((fit.placement.yaw * 180) / Math.PI).toFixed(0)}°</dd>
              </div>
              <div>
                <dt>Wall gap</dt>
                <dd>
                  {fit.measurements.wallGapM === null
                    ? '—'
                    : `${(fit.measurements.wallGapM * 1000).toFixed(0)} mm`}
                </dd>
              </div>
              <div>
                <dt>Nearest wall</dt>
                <dd>{metres(fit.measurements.clearanceM)} of clearance</dd>
              </div>
            </dl>
          </>
        ) : (
          <p data-testid="fit-status" data-fit={fit.reason} className="warning">
            {fit.detail}
          </p>
        )}
        <p className="subtle">
          Access kept clear:{' '}
          {product.accessRegions
            .map((region) => `${centimetres(region.depthM)} at the ${region.face}`)
            .join(', ')}
          .
        </p>
      </section>

      <section>
        <h3>Mesh</h3>
        <table className="lods" data-testid="lod-table">
          <thead>
            <tr>
              <th>Level</th>
              <th>Triangles</th>
              <th>Geometry</th>
            </tr>
          </thead>
          <tbody>
            {product.mesh.lods.map((lod) => (
              <tr key={lod.level}>
                <td>LOD {lod.level}</td>
                <td>{lod.triangles.toLocaleString('en-GB')}</td>
                <td>{kilobytes(lod.exclusiveBytes)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="subtle" data-testid="asset-budget">
          {product.mesh.sharedTextureUrls.length} KTX2 textures shared across all levels ·{' '}
          {megabytes(product.mesh.totalCompressedBytes)} total, counted once, against a{' '}
          {megabytes(budgetLimit)} budget.
        </p>
      </section>

      <section>
        <h3>Availability</h3>
        {product.purchaseUrl ? (
          <p data-testid="purchase">
            <a href={product.purchaseUrl} rel="noreferrer noopener" target="_blank">
              View this Product at the retailer
            </a>
          </p>
        ) : (
          <p data-testid="purchase" className="warning">
            No purchase link. {product.purchase.note}
          </p>
        )}
      </section>

      <section>
        <h3>Attribution</h3>
        <p className="subtle" data-testid="attribution">
          Mesh from{' '}
          <a
            data-testid="attribution-source"
            href={product.attribution.sourceUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            {product.attribution.source}
          </a>
          , © {product.attribution.holder}. The archive records{' '}
          <a
            data-testid="attribution-license"
            href={product.attribution.licenseUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            {product.attribution.license}
          </a>
          . {product.attribution.modifications}
        </p>
        <p
          className={attributionStatus.className}
          data-testid={attributionStatus.testId}
        >
          {product.attribution.licenseNote}
        </p>
        <p className="subtle">
          Source file:{' '}
          <a
            className="break"
            data-testid="attribution-material"
            href={product.attribution.materialUrl}
            rel="noreferrer noopener"
            target="_blank"
          >
            {product.attribution.materialUrl}
          </a>
        </p>
        <p className="subtle" data-testid="attribution-citation">
          {product.attribution.citation}
        </p>
      </section>
    </div>
  );
}
