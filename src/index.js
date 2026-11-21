const JSON_HEADERS = {"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"};
const SESSION_COOKIE="__Host-mb_admin", SESSION_SECONDS=8*60*60, MAX_BODY_BYTES=1024*1024;
function json(data,status=200,headers={}){return new Response(JSON.stringify(data),{status,headers:{...JSON_HEADERS,...headers}})}
function error(message,status=400){return json({error:message},status)}
function getCookie(request,name){for(const part of (request.headers.get("Cookie")||"").split(";")){const i=part.indexOf("=");if(i>=0&&part.slice(0,i).trim()===name)return part.slice(i+1).trim()}return ""}
function b64(bytes){let s="";for(const b of bytes)s+=String.fromCharCode(b);return btoa(s).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"")}
function unb64(s){const p=s.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-s.length%4)%4);return Uint8Array.from(atob(p),c=>c.charCodeAt(0))}
async function sign(secret,value){const key=await crypto.subtle.importKey("raw",new TextEncoder().encode(secret),{name:"HMAC",hash:"SHA-256"},false,["sign"]);return new Uint8Array(await crypto.subtle.sign("HMAC",key,new TextEncoder().encode(value)))}
async function createSession(env){const payload=b64(new TextEncoder().encode(JSON.stringify({exp:Math.floor(Date.now()/1000)+SESSION_SECONDS,nonce:b64(crypto.getRandomValues(new Uint8Array(18)))})));return payload+"."+b64(await sign(env.SESSION_SECRET,payload))}
async function verifySession(request,env){const parts=getCookie(request,SESSION_COOKIE).split(".");if(parts.length!==2||!env.SESSION_SECRET)return false;try{const expected=await sign(env.SESSION_SECRET,parts[0]),actual=unb64(parts[1]);if(actual.length!==expected.length)return false;let diff=0;for(let i=0;i<expected.length;i++)diff|=expected[i]^actual[i];if(diff)return false;const p=JSON.parse(new TextDecoder().decode(unb64(parts[0])));return Number.isInteger(p.exp)&&p.exp>Math.floor(Date.now()/1000)}catch{return false}}
function cookie(v,age=SESSION_SECONDS){return SESSION_COOKIE+"="+v+"; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age="+age}
function sameOrigin(req){const origin=req.headers.get("Origin");if(!origin)return false;try{return new URL(origin).origin===new URL(req.url).origin}catch{return false}}
async function readJson(req,limit=MAX_BODY_BYTES){if(Number(req.headers.get("Content-Length")||0)>limit)throw Error("Request body is too large.");const t=await req.text();if(t.length>limit)throw Error("Request body is too large.");return JSON.parse(t||"{}")}
function clean(v,n=5000){return String(v??"").trim().slice(0,n)}
function validUrl(v){try{const u=new URL(v);return ["https:","http:"].includes(u.protocol)&&!!u.hostname}catch{return false}}
async function requireAdmin(req,env){return await verifySession(req,env)?null:error("Authentication required.",401)}
async function publicBriefing(env){const r=await env.DB.prepare("SELECT id,title,summary,source,category,region,url,published_at AS published,updated_at,filing_type FROM articles WHERE status='published' ORDER BY COALESCE(published_at,updated_at) DESC LIMIT 30").all();return json({articles:r.results||[]})}
async function publicEconomic(env){const r=await env.DB.prepare("SELECT name,country,value,unit,period,source,series_id,description,updated_at FROM economic_indicators ORDER BY country,name").all();return json({indicators:r.results||[]})}
async function ingest(req,env){
 if(!env.INGEST_SECRET)return error("Ingestion is not configured.",503);
 const auth=req.headers.get("Authorization")||"", supplied=auth.startsWith("Bearer ")?auth.slice(7):"";
 if(!supplied||supplied!==env.INGEST_SECRET)return error("Invalid ingestion credentials.",401);
 let p;try{p=await readJson(req)}catch(e){return error(e.message||"Invalid JSON.")}
 if(!Array.isArray(p.articles)||!Array.isArray(p.economic_data))return error("Payload must contain articles and economic_data arrays.");
 if(p.articles.length>250||p.economic_data.length>100)return error("Payload contains too many records.");
 const now=new Date().toISOString(), stmts=[];let ac=0,ec=0;
 for(const a of p.articles){const title=clean(a.title,500),url=clean(a.url,2000);if(!title||!validUrl(url))continue;const d=clean(a.published,50),published=Number.isNaN(Date.parse(d))?null:new Date(d).toISOString();
 stmts.push(env.DB.prepare("INSERT INTO articles(title,summary,source,category,region,url,published_at,status,filing_type,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'draft',?,?,?) ON CONFLICT(url) DO UPDATE SET title=excluded.title,summary=excluded.summary,source=excluded.source,category=excluded.category,region=excluded.region,published_at=excluded.published_at,filing_type=excluded.filing_type,updated_at=excluded.updated_at WHERE articles.status='draft'").bind(title,clean(a.summary),clean(a.source,200),clean(a.category,120),clean(a.region,120),url,published,clean(a.filing_type,20)||null,now,now));ac++}
 for(const a of p.economic_data){const id=clean(a.series_id,80),name=clean(a.name,200);if(!id||!name)continue;stmts.push(env.DB.prepare("INSERT INTO economic_indicators(series_id,name,country,value,unit,period,source,description,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(series_id) DO UPDATE SET name=excluded.name,country=excluded.country,value=excluded.value,unit=excluded.unit,period=excluded.period,source=excluded.source,description=excluded.description,updated_at=excluded.updated_at").bind(id,name,clean(a.country,100),clean(a.value,80),clean(a.unit,80),clean(a.period,80),clean(a.source,200),clean(a.description,1000),now));ec++}
 for(let i=0;i<stmts.length;i+=50)await env.DB.batch(stmts.slice(i,i+50));
 await env.DB.prepare("INSERT INTO system_events(event_type,details,created_at) VALUES('collector_ingest',?,?)").bind(JSON.stringify({article_records_received:ac,indicator_records_received:ec}),now).run();
 return json({ok:true,articles_received:ac,indicators_received:ec,collected_at:now});
}
async function overview(env){const c=await env.DB.prepare("SELECT SUM(CASE WHEN status='draft' THEN 1 ELSE 0 END) drafts,SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) published,SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) rejected FROM articles").first();const e=await env.DB.prepare("SELECT COUNT(*) count,MAX(updated_at) updated_at FROM economic_indicators").first();const l=await env.DB.prepare("SELECT MAX(created_at) last_ingest FROM system_events WHERE event_type='collector_ingest'").first();return json({counts:{drafts:c?.drafts||0,published:c?.published||0,rejected:c?.rejected||0},economic:e||{count:0,updated_at:null},last_ingest:l?.last_ingest||null})}
async function adminArticles(url,env){const s=url.searchParams.get("status")||"draft",allowed=["draft","published","rejected","all"];if(!allowed.includes(s))return error("Invalid status filter.");const r=s==="all"?await env.DB.prepare("SELECT * FROM articles ORDER BY updated_at DESC LIMIT 300").all():await env.DB.prepare("SELECT * FROM articles WHERE status=? ORDER BY updated_at DESC LIMIT 300").bind(s).all();return json({articles:r.results||[]})}
async function updateArticle(req,id,env){let d;try{d=await readJson(req)}catch(e){return error(e.message||"Invalid JSON.")}const title=clean(d.title,500),summary=clean(d.summary),category=clean(d.category,120),region=clean(d.region,120),url=clean(d.url,2000);if(!title||!summary||!validUrl(url))return error("A title, summary, and valid source URL are required.");const r=await env.DB.prepare("UPDATE articles SET title=?,summary=?,category=?,region=?,url=?,updated_at=? WHERE id=?").bind(title,summary,category,region,url,new Date().toISOString(),id).run();return r.meta?.changes?json({ok:true}):error("Article not found.",404)}
async function actionArticle(id,action,env){const status={approve:"published",reject:"rejected",restore:"draft"}[action];if(!status)return error("Unknown article action.",404);const now=new Date().toISOString();const r=await env.DB.prepare("UPDATE articles SET status=?,published_at=CASE WHEN ?='published' THEN COALESCE(published_at,?) ELSE published_at END,updated_at=? WHERE id=?").bind(status,status,now,now,id).run();if(!r.meta?.changes)return error("Article not found.",404);await env.DB.prepare("INSERT INTO system_events(event_type,details,created_at) VALUES(?,?,?)").bind("article_"+action,JSON.stringify({article_id:id}),now).run();return json({ok:true,status})}
async function route(req,env){
 const u=new URL(req.url),p=u.pathname;
 if(p==="/api/health"&&req.method==="GET")return json({ok:true,service:"The Market Brief API",database:true});
 if(p==="/api/public/briefing"&&req.method==="GET")return publicBriefing(env);
 if(p==="/api/public/economic"&&req.method==="GET")return publicEconomic(env);
 if(p==="/api/ingest"&&req.method==="POST")return ingest(req,env);
 if(p==="/api/admin/login"&&req.method==="POST"){if(!sameOrigin(req))return error("Request origin rejected.",403);if(!env.ADMIN_PASSWORD||!env.SESSION_SECRET)return error("Admin authentication is not configured.",503);let d;try{d=await readJson(req,4096)}catch{return error("Invalid request.")}const pass=String(d.password||"");if(pass.length>256)return error("Incorrect password.",401);
 const ip=req.headers.get("CF-Connecting-IP")||"unknown";
 const digest=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(ip));
 const ipHash=Array.from(new Uint8Array(digest)).map(b=>b.toString(16).padStart(2,"0")).join("");
 const nowMs=Date.now(),nowIso=new Date(nowMs).toISOString();
 const attempt=await env.DB.prepare("SELECT attempts,window_started_at,locked_until FROM login_attempts WHERE ip_hash=?").bind(ipHash).first();
 if(attempt?.locked_until&&Date.parse(attempt.locked_until)>nowMs)return error("Too many attempts. Try again in 15 minutes.",429);
 if(pass!==env.ADMIN_PASSWORD){
   const windowValid=attempt?.window_started_at&&nowMs-Date.parse(attempt.window_started_at)<15*60*1000;
   const count=windowValid?(attempt.attempts||0)+1:1;
   const locked=count>=5?new Date(nowMs+15*60*1000).toISOString():null;
   await env.DB.prepare("INSERT INTO login_attempts(ip_hash,attempts,window_started_at,locked_until,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(ip_hash) DO UPDATE SET attempts=excluded.attempts,window_started_at=excluded.window_started_at,locked_until=excluded.locked_until,updated_at=excluded.updated_at").bind(ipHash,count,windowValid?attempt.window_started_at:nowIso,locked,nowIso).run();
   return error(locked?"Too many attempts. Try again in 15 minutes.":"Incorrect password.",locked?429:401);
 }
 await env.DB.prepare("DELETE FROM login_attempts WHERE ip_hash=?").bind(ipHash).run();
 return json({ok:true,expires_in:SESSION_SECONDS},200,{"Set-Cookie":cookie(await createSession(env))})}
 if(p==="/api/admin/logout"&&req.method==="POST"){if(!sameOrigin(req))return error("Request origin rejected.",403);return json({ok:true},200,{"Set-Cookie":cookie("",0)})}
 if(p.startsWith("/api/admin/")){const auth=await requireAdmin(req,env);if(auth)return auth;if(p==="/api/admin/me"&&req.method==="GET")return json({authenticated:true});if(p==="/api/admin/overview"&&req.method==="GET")return overview(env);if(p==="/api/admin/articles"&&req.method==="GET")return adminArticles(u,env);const m=p.match(/^\/api\/admin\/articles\/(\d+)(?:\/(approve|reject|restore))?$/);if(m){const id=Number(m[1]),action=m[2];if(!Number.isSafeInteger(id)||id<1)return error("Invalid article ID.");if(req.method==="PATCH"&&!action)return updateArticle(req,id,env);if(req.method==="POST"&&action)return actionArticle(id,action,env);if(req.method==="DELETE"&&!action){const r=await env.DB.prepare("DELETE FROM articles WHERE id=?").bind(id).run();return r.meta?.changes?json({ok:true}):error("Article not found.",404)}}return error("Admin endpoint not found.",404)}
 if(p==="/admin"||p==="/admin/")return env.ASSETS.fetch(new Request(new URL("/admin/index.html",req.url),req));
 return env.ASSETS.fetch(req);
}
export default {async fetch(req,env){try{if(!env.DB||!env.ASSETS)return error("Service configuration incomplete.",503);return await route(req,env)}catch(e){console.error("Worker request failed:",e);return error("An unexpected server error occurred.",500)}}};
