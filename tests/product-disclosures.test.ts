import {createElement} from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {expect,it} from 'vitest';
import {ProductDisclosures} from '../src/features/design/ProductDisclosures';
import {DesignPanel} from '../src/features/design/DesignPanel';
import type {FitResult, Product, RoomShell} from '../src/shared/api/types';

const historicalNote='The ABO download page and archive contain CC BY 4.0 terms, while the AWS Registry and CVPR paper state CC BY-NC 4.0. Commercial rights are unresolved.';
const aboProduct={id:'controlled-abo-disclosure',displayName:'Controlled ABO Product',category:'chair',roomTypes:['bedroom'],brand:'Fixture',colour:'Fixture',dimensionsM:{widthM:1,heightM:1,depthM:1},frontAxis:'+Z',placementClass:'floor-standing',accessRegions:[],mesh:{normalization:{originRule:'floor-centre',upAxis:'+Y'},lods:[],sharedTextureUrls:[],totalCompressedBytes:100},purchaseUrl:'',purchase:{note:'Purchase availability was not verified.'},attribution:{source:'Amazon Berkeley Objects (ABO)',holder:'Amazon.com, Inc.',sourceUrl:'https://amazon-berkeley-objects.s3.amazonaws.com/index.html',license:'CC BY 4.0',licenseUrl:'https://creativecommons.org/licenses/by/4.0/',materialUrl:'https://amazon-berkeley-objects.s3.amazonaws.com/fixture.glb',licenseStatus:'conflicting-source-records',licenseNote:historicalNote,modifications:'Normalized for this fixture.',citation:'Fixture citation',licenseEvidence:[{label:'AWS Registry of Open Data entry',url:'https://registry.opendata.aws/amazon-berkeley-objects/',recordedLicense:'CC BY-NC 4.0'}]}} as unknown as Product;

function expectCurrentAndHistorical(html:string) {
  const current=html.slice(0,html.indexOf('<details'));
  expect(current).toContain('data-testid="publisher-license-current"');
  expect(current).toContain('https://registry.opendata.aws/amazon-berkeley-objects/');
  expect(current).toContain('CC BY 4.0');
  expect(current).toContain('all asset licenses changed from CC BY-NC to CC BY in 2023');
  expect(current).not.toContain('Commercial rights are unresolved');
  expect(html).toContain('<summary>Historical license metadata</summary>');
  expect(html).toContain(historicalNote);
  expect(html).toContain('Previously recorded: CC BY-NC 4.0');
}

it('distinguishes current ABO publisher information from preserved historical metadata in generated/restored disclosures',()=>{
  const before=JSON.stringify(aboProduct);
  const html=renderToStaticMarkup(createElement(ProductDisclosures,{products:[aboProduct]}));
  expectCurrentAndHistorical(html);
  expect(html).toContain('Meshes are approximate representations of Products.');
  expect(html).toContain('Purchase availability was not verified.');
  expect(html).toContain('No verified purchase link.');
  expect(html).toContain('Fixture citation');
  expect(JSON.stringify(aboProduct)).toBe(before);
});

it('uses the same current/historical disclosure in the detailed Product panel',()=>{
  const html=renderToStaticMarkup(createElement(DesignPanel,{product:aboProduct,room:{walls:[]} as unknown as RoomShell,fit:{status:'does-not-fit',reason:'controlled',detail:'Controlled fixture'} as unknown as FitResult}));
  expectCurrentAndHistorical(html);
});

it('does not reinterpret another source or a lookalike URL as ABO publisher evidence',()=>{
  for(const attribution of [
    {...aboProduct.attribution,source:'Another archive'},
    {...aboProduct.attribution,sourceUrl:'https://amazon-berkeley-objects.s3.amazonaws.com.example.invalid/'},
  ]) {
    const html=renderToStaticMarkup(createElement(ProductDisclosures,{products:[{...aboProduct,attribution}]}));
    expect(html).toContain(historicalNote);
    expect(html).not.toContain('publisher-license-current');
    expect(html).not.toContain('Historical license metadata');
  }
});

it('shows approximate Mesh scope visibly alongside unchanged source and unknown availability',()=>{
  const product={id:'controlled-disclosure-fixture',displayName:'Controlled Product',purchaseUrl:'',purchase:{note:'Purchase availability was not verified.'},attribution:{source:'Fixture source',holder:'Fixture holder',sourceUrl:'https://example.invalid/source',license:'Fixture license',licenseUrl:'https://example.invalid/license',materialUrl:'https://example.invalid/mesh',licenseStatus:'unknown',licenseNote:'No authoritative license evidence is currently available.',modifications:'Normalized for this fixture.',citation:'Fixture citation',licenseEvidence:[]}} as unknown as Product;
  const html=renderToStaticMarkup(createElement(ProductDisclosures,{products:[product]}));
  expect(html).toContain('aria-label="Product sources and availability"');
  expect(html).toContain('Meshes are approximate representations of Products. Materials, colours and details may differ from the real Product.');
  expect(html.indexOf('Meshes are approximate')).toBeLessThan(html.indexOf('<details>'));
  expect(html).toContain('Purchase availability was not verified.');expect(html).toContain('No verified purchase link.');
  expect(html).toContain('href="https://example.invalid/source"');expect(html).toContain('No authoritative license evidence');
});
