import { describe, expect, it } from 'vitest';
import { readVariantStream } from '../src/shared/api/variant-stream';
import { acceptVariantEvent, emptyVariants, installVariantDesign, type VariantState } from '../src/features/design/variant-state';
import type { SolvedDesign, VariantStreamEvent } from '../src/shared/api/types';

const room = { id: 'controlled', floorPolygon: [[-4,-4],[4,-4],[4,4],[-4,4]], walls: [] };
const shell: any = { type: 'shell', generationId: 'batch-one', room };
const variant = (label: 'A'|'B'|'C', session = label): any => ({ type: 'variant', generationId: 'batch-one', variant: label,
  signature: ({ A:'a',B:'b',C:'c' }[label]).repeat(64), result: { status:'solved', design: {
    status:'solved', room, placements:[{ instanceId:'anchor',productId:'original',position:[0,0,0],yaw:0 }], products:[{id:'original'}], intents:[{id:'anchor'}],
    swap:{status:'available',sessionId:session,version:1,catalogueVersion:'controlled',clearanceWidthM:.6} } } });
const complete: any = { type:'complete',generationId:'batch-one',status:'complete',available:['A','B','C'],reason:'complete',providerCalls:3,usage:{known:false} };
const response = (lines: unknown[]) => new Response(lines.map(e=>JSON.stringify(e)+'\n').join(''),{headers:{'content-type':'application/x-ndjson'}});
const started = (): VariantState => ({ ...emptyVariants(1), status:'running' as const });

describe('Variant state ownership', () => {
  it('keeps the selected mutated A while B/C arrive and each session has its own version', () => {
    let state = acceptVariantEvent(started(),1,shell,0);
    state = acceptVariantEvent(state,1,variant('A'),10);
    const changed = { ...state.variants.A!.result.design, swap:{status:'available',sessionId:'A',version:2,catalogueVersion:'controlled',clearanceWidthM:.6}, products:[{...state.variants.A!.result.design.products[0]!,id:'changed'}] } as SolvedDesign;
    state = installVariantDesign(state,1,changed);
    state = acceptVariantEvent(state,1,variant('B'),20);
    state = acceptVariantEvent(state,1,variant('C'),30);
    expect(state.selected).toBe('A');
    expect(state.variants.A!.result.design).toBe(changed);
    expect(state.variants.B!.result.design.swap).toMatchObject({sessionId:'B',version:1});
    expect(state.variants.C!.result.design.swap).toMatchObject({sessionId:'C',version:1});
    expect(state.variants.A!.signature).toBe('a'.repeat(64));
    state = {...state,selected:'B',visit:1};
    const b = {...state.variants.B!.result.design,swap:{status:'available',sessionId:'B',version:2,catalogueVersion:'controlled',clearanceWidthM:.6}} as SolvedDesign;
    state = installVariantDesign(state,1,b);
    expect(state.variants.B!.result.design).toBe(b);
    expect(state.variants.A!.result.design).toBe(changed);
    expect(state.variants.C!.result.design.swap).toMatchObject({sessionId:'C',version:1});
  });
  it('rejects superseded streams, other sessions and old versions across visits', () => {
    let state = acceptVariantEvent(started(),1,shell,0);
    state = acceptVariantEvent(state,1,variant('A'),10);
    expect(acceptVariantEvent(state,0,variant('B'),20)).toBe(state);
    expect(acceptVariantEvent(state,1,{...variant('B'),generationId:'old'},20)).toBe(state);
    expect(installVariantDesign(state,1,variant('B').result.design)).toBe(state);
    const old = {...state.variants.A!.result.design,swap:{status:'available',sessionId:'A',version:0}} as SolvedDesign;
    expect(installVariantDesign(state,1,old)).toBe(state);
    state = {...state,visit:2};
    expect(installVariantDesign(state,0,state.variants.A!.result.design)).toBe(state);
  });
  it('records an accepted A commit during B and preserves it on the next A visit', () => {
    let state=acceptVariantEvent(started(),1,shell,0);
    state=acceptVariantEvent(state,1,variant('A'),10);
    state=acceptVariantEvent(state,1,variant('B'),20);
    const b=state.variants.B;
    const a={...state.variants.A!.result.design,swap:{...state.variants.A!.result.design.swap,version:2}} as SolvedDesign;
    state={...state,selected:'B',visit:1};
    state=installVariantDesign(state,1,a);
    expect(state.selected).toBe('B');expect(state.variants.B).toBe(b);
    state={...state,selected:'A',visit:2};
    expect(state.variants.A!.result.design).toBe(a);
    const later={...a,swap:{...a.swap,version:3}} as SolvedDesign;
    state=installVariantDesign(state,1,later);
    expect(state.variants.A!.result.design).toBe(later);
    expect(installVariantDesign(state,1,a)).toBe(state);
  });
  it('preserves A after later failure, but private invalidation clears every private result', () => {
    let state = acceptVariantEvent(started(),1,shell,0);
    state = acceptVariantEvent(state,1,variant('A'),10);
    state = acceptVariantEvent(state,1,{type:'error',generationId:'batch-one',code:'timeout',detail:'Timed out',invalidated:false},20);
    expect(state.variants.A).toBeDefined();
    state = acceptVariantEvent(state,1,{type:'error',generationId:'batch-one',code:'access',detail:'Expired',invalidated:true},20);
    expect(state.variants).toEqual({});expect(state.shell).toBeNull();
  });
});

describe('bounded NDJSON delivery', () => {
  it('delivers shell and usable A before the rest of a real readable stream is released', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>;
    const body = new ReadableStream<Uint8Array>({ start(c) { controller=c; } });
    const received: VariantStreamEvent[]=[];
    const pending = readVariantStream(new Response(body,{headers:{'content-type':'application/x-ndjson'}}),event=>received.push(event));
    const write=(value:unknown)=>controller.enqueue(new TextEncoder().encode(JSON.stringify(value)+'\n'));
    write(shell);write(variant('A'));
    await new Promise(resolve=>setTimeout(resolve,0));
    expect(received.map(e=>e.type)).toEqual(['shell','variant']);
    write(variant('B'));write(variant('C'));write(complete);controller.close();await pending;
    expect(received.map(e=>e.type)).toEqual(['shell','variant','variant','variant','complete']);
  });
  it('retains delivered A on truncation and never treats EOF as success', async () => {
    let state=started();
    await expect(readVariantStream(response([shell,variant('A')]),event=>{state=acceptVariantEvent(state,1,event,0);})).rejects.toThrow('interrupted');
    expect(state.variants.A).toBeDefined();
  });
  it.each([
    [shell,{...variant('A'),generationId:'another'}],
    [shell,variant('B')],
    [shell,variant('A'),{...variant('B'),signature:'a'.repeat(64)}],
    [shell,variant('A'),complete],
    [shell,{...variant('A'),result:{status:'solved',design:{}}}],
    [shell,{...complete,status:'failed',available:[]},shell],
  ])('rejects malformed or misowned event sequence %#',async (...events)=>{
    await expect(readVariantStream(response(events),()=>{})).rejects.toThrow();
  });
  it('enforces byte bounds and cancellation before invoking callbacks', async () => {
    await expect(readVariantStream(new Response('x'.repeat(524_289),{headers:{'content-type':'application/x-ndjson'}}),()=>{})).rejects.toThrow('byte limit');
    const abort=new AbortController();abort.abort();let calls=0;
    await expect(readVariantStream(response([shell]),()=>calls++,abort.signal)).rejects.toThrow();
    expect(calls).toBe(0);
  });
});
