import type { CapturePhoto, CaptureView } from '@/shared/api/types';
export const walls = ['wall-north','wall-east','wall-south','wall-west'] as const;
export function CapturePhotos({capture,pending,analysisAvailable,upload,action}:{capture:CaptureView;pending:boolean;analysisAvailable:boolean;
  upload:(file:File,wall:string)=>void;action:(id:string,action:'analyze'|'remove'|'associate',wall?:string)=>void}) {
  return <section><h2>Capture all four walls</h2><p>Choose one physical wall as A, then label B, C and D clockwise. Add an accepted photo for each wall, up to eight JPEG/PNG photos. Labels stay fixed when photos are reordered.</p>
    <div className="wall-upload-grid">{walls.map((wall,index)=><label key={wall}>Wall {'ABCD'[index]} photo
      <input aria-label={`Wall ${'ABCD'[index]} photo`} type="file" accept="image/jpeg,image/png" disabled={pending||(capture.photos?.length??0)>=8}
        onChange={event=>{const file=event.target.files?.[0]; if(file)upload(file,wall);event.target.value='';}}/></label>)}</div>
    <ul className="photo-list">{capture.photos?.map((photo:CapturePhoto)=><li key={photo.id}>
      <strong>Photo · Wall {'ABCD'[walls.indexOf(photo.primaryWallId)]} · {photo.state}</strong>
      <label>Photo wall association <select aria-label={`Photo wall association ${photo.id}`} value={photo.primaryWallId} disabled={pending}
        onChange={event=>action(photo.id,'associate',event.target.value)}>{walls.map((wall,index)=><option key={wall} value={wall}>Wall {'ABCD'[index]}</option>)}</select></label>
      <div><button disabled={pending||photo.state!=='accepted'||!analysisAvailable} onClick={()=>action(photo.id,'analyze')}>Analyze this photo</button>
        <button disabled={pending} onClick={()=>action(photo.id,'remove')}>Remove photo</button></div>
      <span>{photo.analysisStatus==='complete'?'Semantic proposals available for review.':photo.analysisStatus==='failed'?'Analysis failed. Retry explicitly or review required observations.':'Opening observations need review.'}</span>
    </li>)}</ul>
    {!analysisAvailable?<p className="capture-warning">Live photo analysis is unavailable in this runtime. No synthetic observations are supplied.</p>:null}
  </section>;
}
