import type { Attribution } from '@/shared/api/types';

const aboPublisherUrl = 'https://registry.opendata.aws/amazon-berkeley-objects/';
const aboLicenseUrl = 'https://creativecommons.org/licenses/by/4.0/';

/** Recognize the actual dataset source, not a Product ID or a similar hostname. */
export function isAboAttribution(attribution: Attribution): boolean {
  if (attribution.source !== 'Amazon Berkeley Objects (ABO)') return false;
  try {
    const url = new URL(attribution.sourceUrl);
    return url.protocol === 'https:' && (
      url.hostname === 'amazon-berkeley-objects.s3.amazonaws.com' ||
      url.hostname === 'amazon-berkeley-objects.s3.us-east-1.amazonaws.com' ||
      (url.hostname === 'registry.opendata.aws' && url.pathname === '/amazon-berkeley-objects/')
    );
  } catch {
    return false;
  }
}

export function attributionStatusPresentation(status: Attribution['licenseStatus']) {
  return status === 'conflicting-source-records'
    ? { className: 'warning', testId: 'license-conflict' }
    : { className: 'subtle', testId: 'license-status' };
}

/** Publisher information supplements immutable archive metadata; it never edits it. */
export function AttributionLicense({ attribution }: { attribution: Attribution }) {
  const status = attributionStatusPresentation(attribution.licenseStatus);
  if (!isAboAttribution(attribution)) {
    return attribution.licenseNote ? <p className={status.className} data-testid={status.testId}>{attribution.licenseNote}</p> : null;
  }
  return <>
    <p className="subtle" data-testid="publisher-license-current">
      The <a href={aboPublisherUrl} target="_blank" rel="noreferrer noopener">ABO publisher's AWS Registry entry</a> lists{' '}
      <a href={aboLicenseUrl} target="_blank" rel="noreferrer noopener">CC BY 4.0</a> and reports that all asset licenses changed from CC BY-NC to CC BY in 2023. Older publications may show the earlier terms.
    </p>
    <details data-testid="historical-license-records">
      <summary>Historical license metadata</summary>
      <p className="subtle">These archive records are preserved as historical evidence; they do not describe the current publisher entry.</p>
      {attribution.licenseNote ? <p className={status.className} data-testid={status.testId}>{attribution.licenseNote}</p> : null}
      <ul>{attribution.licenseEvidence.map((evidence, i) => <li key={i}>
        <a href={evidence.url} target="_blank" rel="noreferrer noopener">{evidence.label}</a>: Previously recorded: {evidence.recordedLicense}
      </li>)}</ul>
    </details>
  </>;
}
