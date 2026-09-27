precision highp float;
uniform vec2 uResolution;
uniform vec2 uPointer;
uniform float uTime;
uniform float uMode;
mat2 rotation(float a){float c=cos(a),s=sin(a);return mat2(c,-s,s,c);}
float surface(vec3 p){
  p.xz=rotation(uTime*.085+uPointer.x*.22)*p.xz;
  p.xy=rotation(-.3+uPointer.y*.18)*p.xy;
  float fold=sin(p.x*3.3+uTime*.18)*sin(p.y*3.8-.5)*sin(p.z*3.4+.8);
  float fine=sin(p.x*9.0+p.y*3.0)*sin(p.y*8.0-p.z*2.0)*sin(p.z*8.0+p.x*2.0);
  float pulse=sin(uTime*1.6)*.008*(1.+uMode);
  return length(p)-1.02-fold*.11-fine*.018-pulse;
}
vec3 normalAt(vec3 p){vec2 e=vec2(.002,0.);return normalize(vec3(surface(p+e.xyy)-surface(p-e.xyy),surface(p+e.yxy)-surface(p-e.yxy),surface(p+e.yyx)-surface(p-e.yyx)));}
vec3 environment(vec3 r){
  vec3 color=vec3(.10,.16,.17);
  color+=vec3(.72,.84,.66)*pow(max(0.,dot(r,normalize(vec3(-.7,1.1,1.2)))),4.0)*1.3;
  color+=vec3(.86,.62,.40)*pow(max(0.,dot(r,normalize(vec3(1.2,-.35,.7)))),7.0)*1.4;
  color+=vec3(.30,.38,.72)*pow(max(0.,dot(r,normalize(vec3(-.6,-.7,.4)))),4.0)*.75;
  color+=vec3(.9,1.,.86)*pow(max(0.,dot(r,normalize(vec3(-1.,1.,.25)))),38.0)*2.5;
  return color;
}
void main(){
  vec2 uv=(2.*gl_FragCoord.xy-uResolution)/min(uResolution.x,uResolution.y);
  uv.y-=.06;
  vec3 ro=vec3(uPointer.x*.09,uPointer.y*.06,4.6);
  vec3 rd=normalize(vec3(uv*1.22,-3.0));
  float t=2.8;float dist=1.;bool hit=false;
  for(int i=0;i<72;i++){vec3 p=ro+rd*t;dist=surface(p);if(dist<.0025){hit=true;break;}t+=dist*.82;if(t>6.5)break;}
  vec3 color=vec3(.3,.43,.3);float alpha=exp(-dot(uv,uv)*2.4)*.045;
  if(hit){
    vec3 p=ro+rd*t;vec3 n=normalAt(p);vec3 refl=reflect(rd,n);
    float diffuse=max(dot(n,normalize(vec3(-.6,.9,1.))),0.);
    float fresnel=pow(1.-max(dot(n,-rd),0.),3.);
    vec3 tint=mix(vec3(.58,.70,.60),vec3(.63,.54,.81),clamp(uMode,0.,1.));
    tint=mix(tint,vec3(.42,.74,.72),max(uMode-1.,0.));
    float grain=.98+.02*sin(p.y*160.+sin(p.x*19.)*4.);
    vec3 env=environment(refl);
    color=(tint*(.09+diffuse*.21)+env*(.72+fresnel*.22))*grain;
    color+=vec3(.73,.88,.66)*fresnel*.14;
    color=pow(1.-exp(-color*1.2),vec3(.85));alpha=1.;
  }
  vec3 ringNormal=normalize(vec3(.28,.76,.52));
  float denom=dot(rd,ringNormal);
  float planeT=-dot(ro,ringNormal)/denom;
  if(planeT>0.&&(!hit||planeT<t)){
    vec3 rp=ro+rd*planeT;float ringDist=abs(length(rp)-1.46);
    float light=exp(-ringDist*520.)*.65+exp(-ringDist*80.)*.12;
    float angle=atan(rp.z,rp.x);light*=.55+.45*sin(angle+uTime*.12);
    color=mix(color,vec3(.71,.82,.63),clamp(light,0.,1.));alpha=max(alpha,clamp(light,0.,1.));
  }
  vec3 axis=normalize(cross(ringNormal,vec3(0.,0.,1.)));vec3 axis2=cross(ringNormal,axis);
  for(int j=0;j<6;j++){
    float a=float(j)*1.0472+uTime*(.085+uMode*.035);
    vec3 dotPos=(axis*cos(a)+axis2*sin(a))*1.46;
    float dt=dot(dotPos-ro,rd);float d=length(ro+rd*dt-dotPos);
    if(dt>0.&&(!hit||dt<t)){
      float intensity=exp(-d*350.)*.95+exp(-d*80.)*.12;
      color=mix(color,vec3(.85,.94,.75),clamp(intensity,0.,1.));alpha=max(alpha,intensity);
    }
  }
  gl_FragColor=vec4(color,clamp(alpha,0.,1.));
}
