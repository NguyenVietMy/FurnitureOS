import { describe, expect, it } from 'vitest';
import { attributionStatusPresentation } from '../src/features/design/DesignPanel';

describe('attribution status presentation', () => {
  it('labels only conflicting source records as a conflict warning', () => {
    expect(attributionStatusPresentation('conflicting-source-records')).toEqual({
      className: 'warning',
      testId: 'license-conflict',
    });
    expect(attributionStatusPresentation('verified')).toEqual({
      className: 'subtle',
      testId: 'license-status',
    });
    expect(attributionStatusPresentation('unknown')).toEqual({
      className: 'subtle',
      testId: 'license-status',
    });
  });
});
