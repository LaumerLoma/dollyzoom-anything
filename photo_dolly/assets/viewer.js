import * as THREE from 'three';
import {SparkRenderer,SplatMesh} from '@sparkjsdev/spark';

const job=await fetch('/job.json').then(r=>r.json()),options=job.options;
const stage=document.querySelector('#stage');
stage.style.aspectRatio=`${job.video_size[0]}/${job.video_size[1]}`;
const scene=new THREE.Scene();scene.background=new THREE.Color('#061123');
const camera=new THREE.PerspectiveCamera(job.image.vertical_fov_degrees,job.image.image_width/job.image.image_height,.001,1e8);
const renderer=new THREE.WebGLRenderer({antialias:false,preserveDrawingBuffer:true});
let captureMode=false;
function fitStage(){if(captureMode)return;const ratio=job.video_size[0]/job.video_size[1],width=Math.max(100,Math.min(innerWidth-34,(innerHeight-175)*ratio));stage.style.boxSizing='content-box';stage.style.width=`${width}px`;stage.style.height=`${width/ratio}px`;renderer.setSize(stage.clientWidth,stage.clientHeight)}
renderer.setPixelRatio(Math.min(devicePixelRatio,2));fitStage();stage.prepend(renderer.domElement);
scene.add(new SparkRenderer({renderer,accumExtSplats:true}));
const mesh=new SplatMesh({url:'/scene.ply',extSplats:true});mesh.quaternion.set(1,0,0,0);scene.add(mesh);
const anchor=new THREE.Vector3(...job.anchor.world),baseTangent=Math.tan(THREE.MathUtils.degToRad(job.image.vertical_fov_degrees)/2);
const rect=job.crop_rect;
camera.setViewOffset(job.image.image_width,job.image.image_height,...rect);
let phase=0,progress=0,playing=true,lastTime=null,cycles=0;
// Easing returns the fraction of (strength-1) applied at a phase. 'bouncy' uses the same
// back-ease snap/overshoot/settle on both legs: out settles at HIGH after overshooting to 1,
// back settles at LOW after overshooting to 0. It never goes below 0 (no wider-than-original
// view) or above 1 (no unassessed move), and the loop closes at LOW.
const C1=1.70158,C3=C1+1,backOut=u=>1+C3*(u-1)**3+C1*(u-1)**2,smooth=u=>u*u*(3-2*u);
const BACK_PEAK=(()=>{let m=1;for(let i=0;i<=10000;i++)m=Math.max(m,backOut(i/10000));return m})();
const RANGE=1/(2*BACK_PEAK-1),LOW=(BACK_PEAK-1)*RANGE,HIGH=LOW+RANGE;
function lensAmount(t){
 const bounce=options.motion==='bounce';
 if(options.easing!=='bouncy')return smooth(bounce?(t<=.5?2*t:2*(1-t)):t);
 if(!bounce)return Math.max(0,backOut(t)/BACK_PEAK);
 const amount=t<=.5?LOW+RANGE*backOut(2*t):HIGH-RANGE*backOut(2*t-1);
 return Math.min(1,Math.max(0,amount));
}
function pose(t){
 phase=Math.max(0,Math.min(1,t));progress=options.motion==='bounce'?(phase<=.5?2*phase:2*(1-phase)):phase;
 const ratio=1+(options.strength-1)*lensAmount(phase);
 camera.position.set(0,0,job.anchor.depth*(ratio-1));camera.quaternion.identity();
 camera.fov=THREE.MathUtils.radToDeg(2*Math.atan(baseTangent/ratio));camera.updateProjectionMatrix();camera.updateMatrixWorld(true);
 document.querySelector('#timeline').value=String(phase);document.querySelector('#time').textContent=`${(phase*(job.loop_seconds||job.duration_seconds)).toFixed(2)} s`;
 const uv=anchor.clone().project(camera);const marker=document.querySelector('#marker');marker.style.left=`${(uv.x+1)*50}%`;marker.style.top=`${(1-uv.y)*50}%`;
 return ratio;
}
function pause(){playing=false;document.querySelector('#play').textContent='Play'}
document.querySelector('#play').onclick=()=>{if(options.motion==='forward'&&phase>=1)pose(0);playing=!playing;lastTime=null;document.querySelector('#play').textContent=playing?'Pause':'Play'};
document.querySelector('#restart').onclick=()=>{pose(0);cycles=0;playing=true;lastTime=null;document.querySelector('#play').textContent='Pause'};
document.querySelector('#timeline').oninput=event=>{pause();pose(Number(event.target.value))};
document.querySelector('#anchor').onclick=()=>{const marker=document.querySelector('#marker');const show=marker.style.display!=='block';marker.style.display=show?'block':'none';document.querySelector('#anchor').textContent=show?'Hide anchor':'Show anchor'};
addEventListener('resize',()=>{fitStage();pose(phase)});
pose(0);await mesh.initialized;
document.querySelector('#loading').remove();document.querySelector('#title').textContent=job.anchor.label;
document.querySelector('#status').textContent=`${options.bpm?options.bpm+' BPM · ':''}${job.duration_seconds} seconds · ${options.fps} fps`;
document.querySelector('#assessment').textContent=`Suitability: ${job.assessment.rating}`;
function span(depth){return Math.abs(new THREE.Vector3(.2,0,-depth).project(camera).x-new THREE.Vector3(-.2,0,-depth).project(camera).x)/2}
function measure(){const point=anchor.clone().project(camera);return {phase,progress,cycles,
 lens_ratio:1+(options.strength-1)*lensAmount(phase),camera_z:camera.position.z,
 anchor_uv:[(point.x+1)/2,(1-point.y)/2],anchor_span:span(job.anchor.depth),background_span:span(job.background_depth)}}
window.photoDolly={ready:true,job,mesh,renderer,camera,scene,measure,
 setPhase(t){pause();pose(t)},
 setCaptureSize(width,height){captureMode=true;renderer.setPixelRatio(1);renderer.setSize(width,height);stage.style.boxSizing='content-box';stage.style.width=`${width}px`;stage.style.height=`${height}px`;stage.style.maxWidth='none';pose(phase)},
 async captureAt(t){pause();pose(t);await new Promise(r=>setTimeout(r,65));renderer.render(scene,camera);return {image:renderer.domElement.toDataURL('image/png'),measurement:measure()}}
};
lastTime=null;
renderer.setAnimationLoop(time=>{if(lastTime===null)lastTime=time;const dt=Math.min((time-lastTime)/1000,.1);lastTime=time;
 if(playing){let next=phase+dt/(job.loop_seconds||job.duration_seconds);if(next>=1){if(options.motion==='bounce'){cycles++;next%=1}else{next=1;pause()}}pose(next)}
 renderer.render(scene,camera)
});
