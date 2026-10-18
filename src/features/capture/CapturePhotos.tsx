import type { CapturePhoto, CaptureView } from '@/shared/api/types';
import { activeWalls, rectangleWalls, wallLabel } from './capture-topology';
export const walls = rectangleWalls;
export function CapturePhotos({ capture, topology, pending, analysisAvailable, upload, action }: { capture: CaptureView; topology?: string; pending: boolean; analysisAvailable: boolean;
  upload: (file: File, wall: string) => void; action: (id: string, action: 'analyze' | 'remove' | 'associate', wall?: string, observed?: ReadonlyArray<string>) => void }) {
  const active = activeWalls(topology);
  return <section><h2>Capture all {active.length === 6 ? 'six' : 'four'} walls</h2><p>Align your physical walls to the labelled diagram and its start/end arrows. Add a distinct accepted primary photo for every active wall, up to eight JPEG/PNG photos. Secondary observations do not replace primary coverage.</p>
    <div className="wall-upload-grid">{active.map(wall => <label key={wall}>{wallLabel(topology, wall)} photo<input aria-label={`${wallLabel(topology, wall)} photo`} type="file" accept="image/jpeg,image/png" disabled={pending || (capture.photos?.length ?? 0) >= 8} onChange={event => { const file = event.target.files?.[0]; if (file) upload(file, wall); event.target.value = ''; }} /></label>)}</div>
    <ul className="photo-list">{capture.photos?.map((photo: CapturePhoto) => {
      const associated = (active as readonly string[]).includes(photo.primaryWallId);
      return <li key={photo.id}><strong>Photo · {wallLabel(topology, photo.primaryWallId)} · {photo.state}</strong>
        {!associated ? <p className="capture-warning">This primary wall is inactive. Reassociate this photo or remove it before confirmation. Its bytes are preserved.</p> : null}
        <label>Photo wall association <select aria-label={`Photo wall association ${photo.id}`} value={photo.primaryWallId} disabled={pending} onChange={event => action(photo.id, 'associate', event.target.value, photo.observedWallIds?.filter(wall => (active as readonly string[]).includes(wall)))}>
          {!associated ? <option value={photo.primaryWallId}>Inactive primary wall — choose again</option> : null}{active.map(wall => <option key={wall} value={wall}>{wallLabel(topology, wall)}</option>)}</select></label>
        <fieldset disabled={pending || !associated}><legend>Secondary walls visible in this photo</legend>{active.map(wall => <label key={wall}><input type="checkbox" aria-label={`Photo ${photo.id} observes ${wallLabel(topology, wall)}`} checked={photo.observedWallIds?.includes(wall) ?? false}
          onChange={event => action(photo.id, 'associate', photo.primaryWallId, event.target.checked ? [...(photo.observedWallIds ?? []), wall] : (photo.observedWallIds ?? []).filter(id => id !== wall))} />{wallLabel(topology, wall)}</label>)}</fieldset>
        <div><button disabled={pending || !associated || photo.state !== 'accepted' || !analysisAvailable} onClick={() => action(photo.id, 'analyze')}>Analyze this photo</button><button disabled={pending} onClick={() => action(photo.id, 'remove')}>Remove photo</button></div>
        <span>{photo.analysisStatus === 'complete' ? 'Semantic proposals available for review.' : photo.analysisStatus === 'failed' ? 'Analysis failed. Retry explicitly or review required observations.' : 'Opening observations need review.'}</span>
      </li>;
    })}</ul>
    {!analysisAvailable ? <p className="capture-warning">Live photo analysis is unavailable in this runtime. No synthetic observations are supplied.</p> : null}
  </section>;
}

