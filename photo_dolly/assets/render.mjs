// Actual Gaussian rendering, geometric validation, and portable video export.
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {execFileSync} from 'node:child_process';

const request=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const {runtime,config:job}=request,out=request.run,options=job.options;
const {chromium}=await import(pathToFileURL(path.join(runtime.node_modules,'playwright-core/index.mjs')).href);
const frames=path.join(out,'frames');await fs.mkdir(frames,{recursive:true});
const args=['--enable-webgl','--ignore-gpu-blocklist'];
if(process.platform==='darwin')args.push('--use-angle=metal');
if((process.env.DOLLYZOOM_NO_SANDBOX||process.env.PHOTO_DOLLY_NO_SANDBOX)==='1')args.push('--no-sandbox');
const browser=await chromium.launch({executablePath:runtime.browser,headless:true,args});
const errors=[],samples=[];
try{
 const page=await browser.newPage({viewport:{width:1280,height:1100},deviceScaleFactor:1});
 page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 await page.goto(request.url,{waitUntil:'networkidle'});
 await page.waitForFunction(()=>window.photoDolly?.ready,undefined,{timeout:180000});
 const loaded=await page.evaluate(()=>window.photoDolly.mesh.splats.getNumSplats());
 if(loaded!==job.gaussian_count)throw Error(`Expected ${job.gaussian_count} Gaussians, loaded ${loaded}`);
 await page.evaluate(size=>{window.photoDolly.setCaptureSize(...size);window.photoDolly.setPhase(0)},job.capture_size);
 await page.waitForTimeout(1000);
 const count=job.frame_count;
 // Save peak separately so short/odd frame-count exports still have an exact reference.
 for(const [phase,name] of [[0,'start.png'],[options.motion==='bounce'?.5:1,'peak.png']]){
  const result=await page.evaluate(t=>window.photoDolly.captureAt(t),phase);
  await fs.writeFile(path.join(out,name),Buffer.from(result.image.split(',')[1],'base64'));
 }
 for(let i=0;i<count;i++){
  // Bounce phase is taken from real time, so multi-loop (BPM) clips stay on tempo without drift.
  const phase=options.motion==='bounce'?((i/options.fps)/(job.loop_seconds||job.duration_seconds))%1:i/(count-1);
  const result=await page.evaluate(t=>window.photoDolly.captureAt(t),phase);
  await fs.writeFile(path.join(frames,`frame_${String(i).padStart(5,'0')}.png`),Buffer.from(result.image.split(',')[1],'base64'));
  samples.push(result.measurement);
  if(i===count-1)await fs.writeFile(path.join(out,'loop_end.png'),Buffer.from(result.image.split(',')[1],'base64'));
  if(i%Math.max(1,Math.round(options.fps))===0)console.log(`Rendered ${i}/${count}`);
 }
 const start=samples[0],maxDrift=Math.max(...samples.map(s=>Math.hypot((s.anchor_uv[0]-start.anchor_uv[0])*job.capture_size[0],(s.anchor_uv[1]-start.anchor_uv[1])*job.capture_size[1])));
 const sizeDrift=Math.max(...samples.map(s=>Math.abs(s.anchor_span/start.anchor_span-1)));
 if(errors.length||maxDrift>1e-5||sizeDrift>1e-6)throw Error(JSON.stringify({errors,maxDrift,sizeDrift}));
 const peak=await page.evaluate(async phase=>(await window.photoDolly.captureAt(phase)).measurement,options.motion==='bounce'?.5:1);
 const closure=await page.evaluate(async()=>(await window.photoDolly.captureAt(1)).measurement);
 const exactLoopClosed=Math.abs(closure.camera_z-start.camera_z)<1e-10&&Math.abs(closure.lens_ratio-start.lens_ratio)<1e-10;
 if(options.motion==='bounce'&&!exactLoopClosed)throw Error('The camera loop does not close.');
 const graphics=await page.evaluate(()=>{const gl=window.photoDolly.renderer.getContext(),ext=gl.getExtension('WEBGL_debug_renderer_info');return ext?gl.getParameter(ext.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)});
 const report={frame_count:count,fps:options.fps,duration_seconds:job.duration_seconds,loaded_gaussians:loaded,
   max_anchor_drift_pixels:maxDrift,max_anchor_size_drift_fraction:sizeDrift,exact_loop_closed:exactLoopClosed,
   background_growth_factor:peak.background_span/start.background_span,capture_size:job.capture_size,
   browser_version:browser.version(),graphics,start,peak,loop_end:samples.at(-1),browser_errors:errors,samples};
 await fs.writeFile(path.join(out,'render_report.json'),JSON.stringify(report,null,2)+'\n');
 console.log(`Anchor checked across all ${count} frames; drift ${maxDrift.toExponential(2)} px.`);
}catch(error){
 await fs.writeFile(path.join(out,'render_failed.json'),JSON.stringify({errors,error:String(error)},null,2)+'\n');throw error;
}finally{await browser.close()}

const base=['-hide_banner','-loglevel','error','-y'];
execFileSync(runtime.ffmpeg,[...base,'-framerate',String(options.fps),'-start_number','0','-i',path.join(frames,'frame_%05d.png'),
 '-frames:v',String(job.frame_count),'-vf',`scale=${job.video_size[0]}:${job.video_size[1]}:flags=lanczos`,
 '-c:v','libx264','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart','-fflags','+bitexact','-flags:v','+bitexact',
 '-map_metadata','-1','-metadata','encoder=','-metadata:s:v:0','encoder=','-an',path.join(out,'dolly_zoom.mp4')]);
const gifWidth=Math.min(job.video_size[0],job.video_size[0]>job.video_size[1]?480:360);
const gifHeight=Math.max(2,Math.round(gifWidth*job.video_size[1]/job.video_size[0]/2)*2);
execFileSync(runtime.ffmpeg,[...base,'-i',path.join(out,'dolly_zoom.mp4'),'-filter_complex',
 `fps=${Math.min(24,options.fps)},scale=${gifWidth}:${gifHeight}:flags=lanczos,split[a][b];[a]palettegen=max_colors=256:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3`,
 '-loop',options.motion==='bounce'?'0':'-1','-map_metadata','-1','-fflags','+bitexact',path.join(out,'dolly_zoom.gif')]);
const video=JSON.parse(execFileSync(runtime.ffprobe,['-v','error','-show_streams','-show_format','-of','json',path.join(out,'dolly_zoom.mp4')],{encoding:'utf8'}));
await fs.writeFile(path.join(out,'video_report.json'),JSON.stringify(video,null,2)+'\n');
console.log('Video encoded and ready for final image/metadata validation.');
