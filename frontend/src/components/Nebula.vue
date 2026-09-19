<script setup>
import {ref,onMounted,onUnmounted} from 'vue'
const element=ref(null)
let cleanup=()=>{}
onMounted(()=>{
    const canvas=element.value;
    if(!canvas||!canvas.getContext)return;
    const context=canvas.getContext('2d');
    if(!context)return;
    const reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)');
    const palette={white:'62, 104, 140',cyan:'22, 133, 178'}, lerp=(a,b,t)=>a+(b-a)*t;
    const seeded=(seed)=>{let s=seed>>>0;return()=>{s+=0x6d2b79f5;let v=s;v=Math.imul(v^(v>>>15),v|1);v^=v+Math.imul(v^(v>>>7),v|61);return((v^(v>>>14))>>>0)/4294967296;}};
    const sprite=(rgb)=>{const c=document.createElement('canvas'),size=64,r=size/2;c.width=size;c.height=size;const x=c.getContext('2d'),g=x.createRadialGradient(r,r,0,r,r,r);g.addColorStop(0,`rgba(${rgb},1)`);g.addColorStop(.18,`rgba(${rgb},.94)`);g.addColorStop(.42,`rgba(${rgb},.48)`);g.addColorStop(.72,`rgba(${rgb},.12)`);g.addColorStop(1,`rgba(${rgb},0)`);x.fillStyle=g;x.fillRect(0,0,size,size);return c;};
    const sprites={white:sprite(palette.white),cyan:sprite(palette.cyan)};
    const pointer={active:false,targetX:0,targetY:0,x:0,y:0};let width=0,height=0,stars=[],animationId=0,lastTime=0,isVisible=!document.hidden;
    const countFor=(w)=>w<=430?74:w<=744?108:w<=1180?146:184;
    const build=()=>{const random=seeded((width*73856093)^(height*19349663));stars=Array.from({length:countFor(width)},()=>{const depth=random(),orbit=lerp(.08,.58,Math.pow(random(),.7));return{angle:random()*Math.PI*2,color:random()<.24?'cyan':'white',depth,orbitRadiusX:width*orbit,orbitRadiusY:height*orbit*lerp(.76,1.08,random()),orbitSpeed:lerp(.08,.24,random()),pulsePhase:random()*Math.PI*2,pulseSpeed:lerp(1.8,5.2,random()),size:lerp(.82,1.5,random())*lerp(.78,1.2,depth),sparkle:random()>.94};});};
    const resize=()=>{width=canvas.clientWidth;height=canvas.clientHeight;const ratio=Math.min(window.devicePixelRatio||1,2);canvas.width=Math.max(1,Math.floor(width*ratio));canvas.height=Math.max(1,Math.floor(height*ratio));context.setTransform(ratio,0,0,ratio,0,0);build();};
    const draw=(time,staticFrame=false)=>{const elapsed=staticFrame?0:time*.001,cx=width*.56,cy=height*.5;context.clearRect(0,0,width,height);context.save();context.globalCompositeOperation='screen';const cloud=context.createRadialGradient(width*.74,height*.19,0,width*.74,height*.19,Math.max(width,height)*.58);cloud.addColorStop(0,'rgba(83,201,235,.20)');cloud.addColorStop(.32,'rgba(52,164,211,.10)');cloud.addColorStop(1,'rgba(52,164,211,0)');context.fillStyle=cloud;context.fillRect(0,0,width,height);const cloud2=context.createRadialGradient(width*.22,height*.76,0,width*.22,height*.76,Math.max(width,height)*.48);cloud2.addColorStop(0,'rgba(112,180,238,.12)');cloud2.addColorStop(.36,'rgba(69,142,204,.06)');cloud2.addColorStop(1,'rgba(69,142,204,0)');context.fillStyle=cloud2;context.fillRect(0,0,width,height);context.globalCompositeOperation='lighter';pointer.x=lerp(pointer.x,pointer.active?pointer.targetX:0,.035);pointer.y=lerp(pointer.y,pointer.active?pointer.targetY:0,.035);stars.forEach(star=>{const angle=star.angle-elapsed*star.orbitSpeed,parallax=lerp(3,16,star.depth),x=cx+Math.cos(angle)*star.orbitRadiusX+pointer.x*parallax,y=cy+Math.sin(angle)*star.orbitRadiusY+pointer.y*parallax;if(x<-30||x>width+30||y<-30||y>height+30)return;const pulse=staticFrame?.62:.5+.5*Math.sin(elapsed*star.pulseSpeed+star.pulsePhase),brightness=lerp(.32,1,pulse),core=star.size*lerp(.86,1.3,brightness),halo=core*lerp(7.5,11,star.depth),rgb=palette[star.color];context.globalAlpha=brightness*lerp(.48,.78,star.depth);context.drawImage(sprites[star.color],x-halo/2,y-halo/2,halo,halo);context.globalAlpha=brightness*lerp(.72,1,star.depth);context.fillStyle=`rgb(${rgb})`;context.beginPath();context.arc(x,y,core,0,Math.PI*2);context.fill();if(star.sparkle&&brightness>.7){const ray=core*4.5;context.globalAlpha=(brightness-.7)*.72;context.strokeStyle=`rgb(${rgb})`;context.lineWidth=.55;context.beginPath();context.moveTo(x-ray,y);context.lineTo(x+ray,y);context.moveTo(x,y-ray);context.lineTo(x,y+ray);context.stroke();}});context.restore();};
    const animate=(time)=>{if(!isVisible||reduceMotion.matches)return;if(!lastTime||time-lastTime>=(width<=744?32:16)){draw(time);lastTime=time;}animationId=requestAnimationFrame(animate);};
    const restart=()=>{cancelAnimationFrame(animationId);lastTime=0;resize();draw(0,true);if(isVisible&&!reduceMotion.matches)animationId=requestAnimationFrame(animate);};
    const handlePointerMove=(event)=>{pointer.targetX=event.clientX/Math.max(width,1)-.5;pointer.targetY=event.clientY/Math.max(height,1)-.5;pointer.active=true;};
    const handlePointerOut=(event)=>{if(!event.relatedTarget)pointer.active=false;};
    const handleVisibility=()=>{isVisible=!document.hidden;restart();};
    const observer=new ResizeObserver(restart);observer.observe(canvas);reduceMotion.addEventListener('change',restart);document.addEventListener('visibilitychange',handleVisibility);window.addEventListener('pointermove',handlePointerMove,{passive:true});window.addEventListener('pointerout',handlePointerOut);restart();
    cleanup=()=>{cancelAnimationFrame(animationId);observer.disconnect();reduceMotion.removeEventListener('change',restart);document.removeEventListener('visibilitychange',handleVisibility);window.removeEventListener('pointermove',handlePointerMove);window.removeEventListener('pointerout',handlePointerOut);};
})
onUnmounted(()=>cleanup())
</script>
<template><canvas ref="element" class="nebula-canvas" aria-hidden="true"></canvas></template>

