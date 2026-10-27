/** Deliberate legacy UI fixture adapter. Real stream sequencing has a separate local-server suite. */
export function resultStream(result: any, room?: any): string {
  const generationId = result.generationId;
  const events: any[] = [];
  if (result.status === 'solved') {
    events.push({ type:'shell',generationId,room:result.design.room },
      { type:'variant',generationId,variant:'A',signature:'a'.repeat(64),result },
      { type:'complete',generationId,status:'partial',available:['A'],reason:'duplicate-exhausted',providerCalls:result.providerCalls,usage:result.usage });
  } else {
    if (room) events.push({type:'shell',generationId,room});
    events.push({type:'error',generationId,code:result.code,detail:result.detail,invalidated:false,failure:result},
      {type:'complete',generationId,status:'failed',available:[],reason:'generation-failed',providerCalls:result.providerCalls,usage:result.usage});
  }
  return events.map(e=>JSON.stringify(e)+'\n').join('');
}
