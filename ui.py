"""The Beam web interface: one page, no framework, no build step.

Laid out for a phone first. At 900px the actions move into a sidebar and the
file rows gain columns, which is the only structural difference between the
phone and a Mac or Windows desktop - everything else is the same markup.
"""

import json

STYLE = r"""
:root{
  color-scheme:light dark;
  --bg:#f4f5f7; --panel:#fff; --panel2:#f9fafb;
  --line:#e4e7ec; --soft:#eef0f4;
  --ink:#101319; --ink2:#59616f; --ink3:#8a92a2;
  --accent:#1a6dff; --accent-soft:rgba(26,109,255,.10);
  --danger:#d92d20; --ok:#0f9d58;
  --r:14px; --r2:10px;
  --shadow:0 1px 2px rgba(16,24,40,.04), 0 4px 14px rgba(16,24,40,.05);
  --glass:rgba(244,245,247,.78);
}
@media (prefers-color-scheme:dark){:root{
  --bg:#0b0c0f; --panel:#14161b; --panel2:#191c22;
  --line:#252932; --soft:#1e222a;
  --ink:#e9ecf2; --ink2:#a3abb9; --ink3:#6e7684;
  --accent:#4d94ff; --accent-soft:rgba(77,148,255,.14);
  --danger:#ff6a5e; --ok:#3ecf8e;
  --shadow:0 1px 2px rgba(0,0,0,.3), 0 6px 18px rgba(0,0,0,.28);
  --glass:rgba(11,12,15,.72);
}}
*,*::before,*::after{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI Variable Text",
       "Segoe UI",Roboto,Inter,system-ui,sans-serif;
  -webkit-font-smoothing:antialiased;-webkit-tap-highlight-color:transparent;
  overscroll-behavior-y:none}
a{color:inherit;text-decoration:none}
input,button,select,textarea{font:inherit;color:inherit}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:6px}
svg symbol{overflow:visible}
svg use{fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;
  stroke-linejoin:round}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
@media (min-width:900px){
  ::-webkit-scrollbar{width:11px;height:11px}
  ::-webkit-scrollbar-thumb{background:var(--line);border-radius:7px;border:3px solid var(--bg)}
  ::-webkit-scrollbar-track{background:transparent}
}

/* shell */
.shell{display:grid;grid-template-columns:1fr;min-height:100%}
@media (min-width:900px){.shell{grid-template-columns:274px minmax(0,1fr)}}
main{min-width:0;padding-bottom:calc(96px + env(safe-area-inset-bottom))}
@media (min-width:900px){main{padding-bottom:40px}}
.inner{max-width:1120px;margin:0 auto;padding:16px}
@media (min-width:900px){.inner{padding:20px 30px}}

/* sidebar */
.side{display:none}
@media (min-width:900px){.side{
  display:flex;flex-direction:column;gap:16px;padding:24px 20px;
  background:var(--panel);border-right:1px solid var(--line);
  position:sticky;top:0;height:100vh;overflow:auto}}
.brand{display:flex;align-items:baseline;gap:2px;font-size:21px;font-weight:650;
  letter-spacing:-.02em}
.brand b{font-weight:650}
.brand i{color:var(--accent);font-style:normal}
.brand em{font-style:normal;font-size:12.5px;color:var(--ink3);margin-left:auto;
  font-weight:450;letter-spacing:0}
.side .brand{display:block}
.side .brand em{display:block;margin:3px 0 0;font-size:12.5px}
.qrcard{background:var(--panel2);border:1px solid var(--line);border-radius:var(--r);
  padding:14px;text-align:center}
.qrcard img{width:100%;max-width:190px;image-rendering:pixelated;border-radius:8px;
  background:#fff;padding:6px}
.qrcard p{margin:10px 2px 0;font-size:12.5px;color:var(--ink2);line-height:1.4}
.creds{margin-top:11px;padding-top:11px;border-top:1px solid var(--line);
  display:flex;flex-direction:column;gap:7px}
.creds div{display:flex;align-items:baseline;gap:8px;justify-content:center}
.creds b{font-weight:500;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink3)}
.creds code{font:inherit;font-size:14px;color:var(--ink);font-variant-numeric:tabular-nums;
  user-select:all}
.creds code.pin{font-size:19px;font-weight:650;letter-spacing:.16em}
.meter b{display:block;font-size:12.5px;color:var(--ink2);font-weight:500;margin-bottom:7px}
.meter .track{height:6px;border-radius:4px;background:var(--soft);overflow:hidden}
.meter .track i{display:block;height:100%;background:var(--accent);border-radius:4px}
.keys{margin-top:auto;font-size:12px;color:var(--ink3);line-height:1.9}
.keys kbd{font:inherit;font-size:11px;background:var(--soft);border:1px solid var(--line);
  border-radius:5px;padding:1px 5px;color:var(--ink2)}

/* top bar */
.top{position:sticky;top:0;z-index:20;background:var(--glass);
  -webkit-backdrop-filter:saturate(180%) blur(16px);
  backdrop-filter:saturate(180%) blur(16px);border-bottom:1px solid var(--line)}
.mrow{display:flex;align-items:center;gap:10px;padding:11px 16px 0}
@media (min-width:900px){.mrow{display:none}}
.mrow .free{margin-left:auto;font-size:12.5px;color:var(--ink3)}
.trow{display:flex;align-items:center;gap:9px;padding:11px 16px}
@media (min-width:900px){.trow{padding:15px 30px}}
.crumbs{display:flex;align-items:center;gap:5px;min-width:0;font-size:13.5px;
  color:var(--ink3);overflow:hidden;white-space:nowrap}
.crumbs a{color:var(--ink2);border-radius:6px;padding:2px 5px}
.crumbs a:hover{background:var(--soft);color:var(--ink)}
.crumbs a:last-child{color:var(--ink);font-weight:550}
.crumbs span{opacity:.5}
.tools{display:flex;align-items:center;gap:8px;margin-left:auto;min-width:0}
.search{position:relative;flex:1;min-width:0;max-width:300px}
.search svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);
  width:16px;height:16px;color:var(--ink3);pointer-events:none}
.search input{width:100%;padding:8px 30px 8px 32px;border:1px solid var(--line);
  background:var(--panel);border-radius:999px;font-size:14px;min-width:0}
.search input::placeholder{color:var(--ink3)}
.search .clr{position:absolute;right:4px;top:50%;transform:translateY(-50%);
  border:0;background:none;color:var(--ink3);cursor:pointer;padding:5px;display:none}
.search.has .clr{display:block}
select.sort{border:1px solid var(--line);background:var(--panel);border-radius:999px;
  padding:8px 10px;font-size:13.5px;color:var(--ink2);cursor:pointer}
@media (max-width:520px){select.sort{display:none}}
.seg{display:flex;background:var(--soft);border-radius:999px;padding:3px;gap:2px}
.seg button{border:0;background:none;width:32px;height:28px;border-radius:999px;
  display:grid;place-items:center;color:var(--ink3);cursor:pointer}
.seg button.on{background:var(--panel);color:var(--ink);box-shadow:var(--shadow)}
@media (max-width:380px){.seg{display:none}}

/* buttons */
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  border:1px solid var(--line);background:var(--panel);border-radius:var(--r2);
  padding:11px 14px;font-size:14.5px;font-weight:500;cursor:pointer;
  transition:background .12s,transform .06s}
.btn:hover{background:var(--panel2)}
.btn:active{transform:scale(.985)}
.btn.primary{background:var(--accent);color:#fff;border-color:transparent;font-weight:600}
.btn.primary:hover{filter:brightness(1.07)}
.btn.block{width:100%}
.btn svg{width:18px;height:18px;flex:none}
.ib{border:0;background:transparent;color:var(--ink3);width:34px;height:34px;
  border-radius:9px;display:grid;place-items:center;cursor:pointer;flex:none;
  transition:background .12s,color .12s}
.ib:hover{background:var(--soft);color:var(--ink)}
.ib.armed{background:color-mix(in srgb,var(--danger) 14%,transparent);color:var(--danger);
  width:auto;padding:0 11px;font-size:12.5px;font-weight:600}
.ib.lit{color:var(--accent)}
.card .acts .ib.lit{color:#7db4ff}

/* panels */
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);margin-bottom:16px;overflow:hidden}
.panel.pad{padding:14px}
.hide{display:none!important}
h2{font-size:12px;font-weight:600;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink3);margin:20px 2px 9px}
h2:first-child{margin-top:4px}
textarea{width:100%;border:1px solid var(--line);background:var(--panel2);
  border-radius:var(--r2);padding:12px;font-size:15px;resize:vertical;min-height:96px}

/* rows */
.rows{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);
  box-shadow:var(--shadow);overflow:hidden}
.row{display:flex;align-items:center;gap:12px;padding:9px 11px;
  border-bottom:1px solid var(--soft)}
.row:last-child{border-bottom:0}
@media (hover:hover){.row:hover{background:var(--panel2)}}
.pv{width:58px;height:40px;border-radius:8px;flex:none;background:var(--soft);
  display:grid;place-items:center;overflow:hidden;color:var(--ink3);position:relative}
.pv img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;
  opacity:0;transition:opacity .22s ease-out}
.pv img.on{opacity:1}
.pv svg{width:19px;height:19px}
.pv.folder{background:var(--accent-soft);color:var(--accent)}
.meta{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px}
.nm{font-size:14.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sub{font-size:12.5px;color:var(--ink3);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.col{font-size:13px;color:var(--ink3);flex:none;text-align:right;display:none}
@media (min-width:900px){
  .col{display:block}
  .col.size{width:86px}
  .col.when{width:118px}
  .row .sub{display:none}
}
.acts{display:flex;gap:2px;flex:none}
@media (hover:hover) and (min-width:900px){
  .acts{opacity:0;transition:opacity .12s}
  .row:hover .acts,.row:focus-within .acts,.acts:has(.armed){opacity:1}
}

/* grid */
.grid{display:grid;gap:13px;grid-template-columns:repeat(auto-fill,minmax(158px,1fr))}
@media (min-width:900px){.grid{gap:16px;grid-template-columns:repeat(auto-fill,minmax(208px,1fr))}}
.card{position:relative;background:var(--panel);border:1px solid var(--line);
  border-radius:var(--r);box-shadow:var(--shadow);overflow:hidden;display:flex;
  flex-direction:column;transition:transform .12s,box-shadow .12s}
@media (hover:hover){.card:hover{transform:translateY(-2px);
  box-shadow:0 2px 4px rgba(16,24,40,.06),0 10px 26px rgba(16,24,40,.10)}}
.card .pv{width:100%;height:auto;aspect-ratio:16/10;border-radius:0}
.card .pv svg{width:26px;height:26px}
.card .body{padding:10px 11px;min-width:0}
.card .meta{gap:2px}
/* the actions sit on the preview, so the name gets the whole width */
.card .acts{position:absolute;top:7px;right:7px;opacity:1;gap:1px;padding:2px;
  border-radius:999px;background:rgba(10,12,16,.5);
  -webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
.card .acts .ib{color:#fff;width:30px;height:30px}
.card .acts .ib:hover{background:rgba(255,255,255,.2)}
.card .acts .ib.armed{background:var(--danger);color:#fff}

.empty{padding:56px 20px;text-align:center;color:var(--ink3)}
.empty svg{width:34px;height:34px;margin-bottom:12px;opacity:.5}
.empty b{display:block;color:var(--ink2);font-weight:550;font-size:15px;margin-bottom:4px}

/* uploads */
.upitem{padding:11px 13px;border-bottom:1px solid var(--soft)}
.upitem:last-child{border-bottom:0}
.uphead{display:flex;align-items:center;gap:10px;font-size:13.5px}
.uphead b{font-weight:450;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.uphead span{color:var(--ink3);font-size:12.5px;flex:none;
  font-variant-numeric:tabular-nums}
.track{height:5px;border-radius:3px;background:var(--soft);overflow:hidden;margin-top:8px}
.track i{display:block;height:100%;width:0;background:var(--accent);border-radius:3px;
  position:relative;overflow:hidden;transition:width .18s cubic-bezier(.3,.8,.4,1)}
.upitem.done .track i{background:var(--ok)}
.upitem.fail .track i{background:var(--danger)}
.netbar{position:fixed;top:0;left:0;height:2px;background:var(--accent);z-index:80;
  width:0;transition:width .2s linear;opacity:0}
.netbar.on{opacity:1}

/* dock, veil, toasts */
.dock{position:fixed;left:0;right:0;bottom:0;z-index:30;display:flex;gap:9px;
  padding:10px 16px calc(10px + env(safe-area-inset-bottom));background:var(--glass);
  -webkit-backdrop-filter:saturate(180%) blur(16px);
  backdrop-filter:saturate(180%) blur(16px);border-top:1px solid var(--line)}
@media (min-width:900px){.dock{display:none}}
.dock .btn.primary{flex:1}
.dock .btn:not(.primary){width:48px;padding:0}
.veil{position:fixed;inset:0;z-index:60;display:none;place-items:center;
  background:rgba(8,10,14,.6);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}
.veil.on{display:grid}
.veil div{color:#fff;font-size:19px;font-weight:600;display:flex;flex-direction:column;
  align-items:center;gap:14px;border:2px dashed rgba(255,255,255,.55);border-radius:20px;
  padding:44px 60px}
.veil svg{width:36px;height:36px}
.toasts{position:fixed;left:50%;transform:translateX(-50%);z-index:70;display:flex;
  flex-direction:column;gap:8px;align-items:center;pointer-events:none;
  bottom:calc(86px + env(safe-area-inset-bottom))}
@media (min-width:900px){.toasts{bottom:26px}}
.toast{background:#14161bef;color:#fff;padding:10px 16px;border-radius:999px;
  font-size:13.5px;box-shadow:0 8px 26px rgba(0,0,0,.3);animation:pop .18s ease-out;
  max-width:82vw;text-align:center}
@media (prefers-color-scheme:dark){.toast{background:#2a2e37f2}}
.toast.bad{background:var(--danger)}
@keyframes pop{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
@keyframes slidein{from{opacity:0;transform:translateY(-9px)}to{opacity:1;transform:none}}
@keyframes shimmer{from{background-position:-150% 0}to{background-position:250% 0}}
@keyframes shake{15%{transform:translateX(-3px)}45%{transform:translateX(3px)}
  75%{transform:translateX(-2px)}100%{transform:none}}
@keyframes veilin{from{opacity:0}to{opacity:1}}
@keyframes veilcard{from{opacity:0;transform:scale(.93)}to{opacity:1;transform:none}}
@keyframes stamp{from{opacity:0;transform:scale(.4)}60%{transform:scale(1.12)}
  to{opacity:1;transform:scale(1)}}
@keyframes collapse{to{opacity:0;transform:translateX(-18px);max-height:0;
  padding-top:0;padding-bottom:0;border-width:0}}
/* a new file rises into place; everything already on screen stays put */
.row.fresh,.card.fresh{animation:rise .34s cubic-bezier(.2,.7,.3,1) backwards}
.row.going,.card.going{animation:collapse .22s ease-in forwards;overflow:hidden}
.pv img{transform:scale(1.03)}
.pv img.on{transform:none;transition:opacity .25s ease-out,transform .5s ease-out}
.upitem{animation:slidein .24s cubic-bezier(.2,.7,.3,1)}
.upitem.busy .track i::after{content:"";position:absolute;inset:0;
  background:linear-gradient(100deg,transparent 25%,rgba(255,255,255,.55) 50%,transparent 75%);
  background-size:200% 100%;animation:shimmer 1.15s linear infinite}
.upitem.fail{animation:shake .38s ease-out}
.upitem .stamp{animation:stamp .34s cubic-bezier(.2,.8,.3,1.4);color:var(--ok);
  display:grid;place-items:center;width:34px;height:34px;flex:none}
.veil{animation:veilin .16s ease-out}
.veil div{animation:veilcard .24s cubic-bezier(.2,.8,.3,1.3)}
.netbar{box-shadow:0 0 10px var(--accent)}
/* the shape of the list, drawn before the list itself arrives */
.sk{display:flex;align-items:center;gap:12px;padding:9px 11px;border-bottom:1px solid var(--soft)}
.sk:last-child{border-bottom:0}
.sk i,.sk u{display:block;border-radius:7px;text-decoration:none;
  background:linear-gradient(100deg,var(--soft) 30%,var(--panel2) 50%,var(--soft) 70%);
  background-size:220% 100%;animation:shimmer 1.4s linear infinite}
.sk i{width:58px;height:40px;flex:none}
.sk u:first-of-type{height:11px;width:46%;margin-bottom:7px}
.sk u:last-of-type{height:9px;width:26%}
.sk div{flex:1}

/* share modal */
.modal{position:fixed;inset:0;z-index:65;display:none;place-items:center;padding:20px;
  background:rgba(8,10,14,.6);-webkit-backdrop-filter:blur(4px);backdrop-filter:blur(4px)}
.modal.on{display:grid;animation:veilin .16s ease-out}
.sheet{width:min(430px,100%);background:var(--panel);border:1px solid var(--line);
  border-radius:var(--r);box-shadow:var(--shadow);padding:20px;
  animation:veilcard .22s cubic-bezier(.2,.8,.3,1.3)}
.sheet h3{margin:0 0 4px;font-size:17px;display:flex;align-items:center;gap:8px}
.sheet h3 svg{width:19px;height:19px;color:var(--accent)}
.sheet .who{font-size:13.5px;color:var(--ink2);margin:0 0 16px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sheet .who b{font-weight:600;color:var(--ink)}
.linkrow{display:flex;gap:8px;margin-bottom:14px}
.linkrow input{flex:1;min-width:0;padding:10px 12px;border:1px solid var(--line);
  background:var(--panel2);border-radius:var(--r2);font-size:13.5px;color:var(--ink2);
  font-variant-numeric:tabular-nums}
.exprow{display:flex;align-items:center;justify-content:space-between;gap:10px;
  font-size:13.5px;color:var(--ink2);margin-bottom:8px}
.exprow select{border:1px solid var(--line);background:var(--panel);border-radius:999px;
  padding:7px 10px;font-size:13.5px;color:var(--ink);cursor:pointer}
.note-ro{font-size:12.5px;color:var(--ink3);line-height:1.5;margin:0 0 18px;
  display:flex;gap:7px;align-items:flex-start}
.note-ro svg{width:15px;height:15px;flex:none;margin-top:1px;color:var(--ok)}
.modacts{display:flex;gap:8px}
.modacts .btn{flex:1}
.btn.ghost{color:var(--danger);border-color:transparent;background:transparent}
.btn.ghost:hover{background:color-mix(in srgb,var(--danger) 12%,transparent)}
.pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
  letter-spacing:.04em;text-transform:uppercase;color:var(--ok);
  background:color-mix(in srgb,var(--ok) 14%,transparent);border-radius:999px;
  padding:3px 9px}
.pill svg{width:13px;height:13px}
.side .rochip{margin-top:2px}

/* guest view: hide every way to write */
html.guest #sendbtn,html.guest #folderbtn,html.guest #textbtn,html.guest .qrcard,
html.guest .keys,html.guest .dock,html.guest #textbox,html.guest #qrbox,
html.guest #veil{display:none!important}
html.guest main{padding-bottom:40px}
"""

ICONS = """<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-folder" viewBox="0 0 24 24"><path d="M3 7.5A2 2 0 0 1 5 5.5h3.6l1.8 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></symbol>
<symbol id="i-film" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M7.5 4.5v15M16.5 4.5v15M3 9.5h4.5M3 14.5h4.5M16.5 9.5H21M16.5 14.5H21"/></symbol>
<symbol id="i-image" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/><circle cx="8.8" cy="9.6" r="1.5"/><path d="M20.6 16.4l-4.2-4.2L11 17.6l-2.2-2.2L3.4 19"/></symbol>
<symbol id="i-music" viewBox="0 0 24 24"><path d="M9 17.5V5.8l10-2v11.4"/><circle cx="6.8" cy="17.5" r="2.2"/><circle cx="16.8" cy="15.2" r="2.2"/></symbol>
<symbol id="i-doc" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M8.6 13h6.8M8.6 16.5h4.6"/></symbol>
<symbol id="i-text" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M8.6 12.5h6.8M8.6 16h4.6"/></symbol>
<symbol id="i-archive" viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/><path d="M3 9.5h18M12 9.5v10M10.2 13.2h3.6"/></symbol>
<symbol id="i-file" viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></symbol>
<symbol id="i-down" viewBox="0 0 24 24"><path d="M12 4v11M8 11.5l4 4 4-4M5 19.5h14"/></symbol>
<symbol id="i-up" viewBox="0 0 24 24"><path d="M12 19.5V8.5M8 12.5l4-4 4 4M5 4.5h14"/></symbol>
<symbol id="i-trash" viewBox="0 0 24 24"><path d="M4.5 6.8h15M9.5 6.8V4.9h5v1.9M6.6 6.8l.9 12.3h9l.9-12.3"/></symbol>
<symbol id="i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.6"/><path d="M20 20l-3.8-3.8"/></symbol>
<symbol id="i-x" viewBox="0 0 24 24"><path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/></symbol>
<symbol id="i-list" viewBox="0 0 24 24"><path d="M9 6.5h11M9 12h11M9 17.5h11M4.6 6.5h.01M4.6 12h.01M4.6 17.5h.01"/></symbol>
<symbol id="i-grid" viewBox="0 0 24 24"><rect x="4" y="4" width="6.6" height="6.6" rx="1.6"/><rect x="13.4" y="4" width="6.6" height="6.6" rx="1.6"/><rect x="4" y="13.4" width="6.6" height="6.6" rx="1.6"/><rect x="13.4" y="13.4" width="6.6" height="6.6" rx="1.6"/></symbol>
<symbol id="i-qr" viewBox="0 0 24 24"><rect x="4" y="4" width="6" height="6" rx="1.4"/><rect x="14" y="4" width="6" height="6" rx="1.4"/><rect x="4" y="14" width="6" height="6" rx="1.4"/><path d="M14 14.5h2.5M14 19.5h2M18.5 17h1.5M19.5 14v1.5M17 17v3"/></symbol>
<symbol id="i-text-add" viewBox="0 0 24 24"><path d="M5 6.5h14M5 11.5h14M5 16.5h8"/></symbol>
<symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.6 4.6L19 7.7"/></symbol>
<symbol id="i-back" viewBox="0 0 24 24"><path d="M14.5 5.5L8 12l6.5 6.5"/></symbol>
<symbol id="i-inbox" viewBox="0 0 24 24"><path d="M3.5 13.5h4l1.5 3h6l1.5-3h4"/><path d="M5.6 5.5h12.8l2.1 8v5a2 2 0 0 1-2 2H5.5a2 2 0 0 1-2-2v-5z"/></symbol>
<symbol id="i-link" viewBox="0 0 24 24"><path d="M10 13.5a3.5 3.5 0 0 0 5 0l2.5-2.5a3.5 3.5 0 0 0-5-5l-1.2 1.2"/><path d="M14 10.5a3.5 3.5 0 0 0-5 0L6.5 13a3.5 3.5 0 0 0 5 5l1.2-1.2"/></symbol>
<symbol id="i-copy" viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15H4.5A1.5 1.5 0 0 1 3 13.5V5A2 2 0 0 1 5 3h8.5A1.5 1.5 0 0 1 15 4.5V5"/></symbol>
</svg>"""

LOGIN = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#f4f5f7" media="(prefers-color-scheme:light)">
<meta name=theme-color content="#0b0c0f" media="(prefers-color-scheme:dark)">
<title>Beam</title><style>__STYLE__
.gate{min-height:100%;display:grid;place-items:center;padding:24px}
.gate form{width:min(340px,100%);text-align:center}
.gate .brand{justify-content:center;font-size:30px;margin-bottom:6px}
.gate p{color:var(--ink2);font-size:14.5px;margin:0 0 22px}
.gate input{width:100%;font-size:30px;text-align:center;letter-spacing:.42em;
  text-indent:.42em;padding:16px;border:1px solid var(--line);border-radius:var(--r);
  background:var(--panel);box-shadow:var(--shadow);margin-bottom:12px;
  font-variant-numeric:tabular-nums}
.gate .msg{min-height:22px;color:var(--danger);font-size:13.5px;margin-top:14px}
</style>
<div class=gate><form method=get action="/">
  <div class=brand><b>Beam</b><i>.</i></div>
  <p>The PIN is under the QR code in the Beam window on the Mac.</p>
  <input name=k inputmode=numeric pattern="[0-9]*" autocomplete=off maxlength=6
         autofocus placeholder="0000" aria-label="PIN">
  <button class="btn primary block" type=submit>Unlock</button>
  <div class=msg>{{msg}}</div>
</form></div>""".replace("__STYLE__", STYLE)

GONE = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#f4f5f7" media="(prefers-color-scheme:light)">
<meta name=theme-color content="#0b0c0f" media="(prefers-color-scheme:dark)">
<title>Beam</title><style>__STYLE__
.gate{min-height:100%;display:grid;place-items:center;padding:24px}
.gate div{width:min(360px,100%);text-align:center}
.gate .brand{justify-content:center;font-size:30px;margin-bottom:14px}
.gate h1{font-size:19px;margin:0 0 8px}
.gate p{color:var(--ink2);font-size:14.5px;margin:0}
</style>
<div class=gate><div>
  <div class=brand><b>Beam</b><i>.</i></div>
  <h1>This link is no longer active</h1>
  <p>Whoever shared it may have stopped the share, or it has expired. Ask them
     for a fresh link.</p>
</div></div>""".replace("__STYLE__", STYLE)

PAGE = r"""<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name=theme-color content="#f4f5f7" media="(prefers-color-scheme:light)">
<meta name=theme-color content="#0b0c0f" media="(prefers-color-scheme:dark)">
<meta name=apple-mobile-web-app-capable content=yes>
<title>Beam</title><style>__STYLE__</style>
__ICONS__
<div class=netbar id=netbar></div>
<div class=shell>

  <aside class=side>
    <div class=brand><b>Beam</b><i>.</i><em id=host></em>
      <span class="pill rochip hide" id=rochip><svg><use href="#i-link"/></svg>Read-only</span></div>
    <label class="btn primary block" id=sendbtn><svg><use href="#i-up"/></svg>Send files
      <input type=file id=picker multiple hidden></label>
    <label class="btn block hide" id=folderbtn><svg><use href="#i-folder"/></svg>Send a folder
      <input type=file id=folderpick webkitdirectory directory multiple hidden></label>
    <button class="btn block" id=textbtn><svg><use href="#i-text-add"/></svg>Send text</button>
    <div class=qrcard><img src="/qr.png" alt="QR code for this page">
      <p>Point another phone's camera here</p>
      <div class="creds hide" id=creds>
        <div><b>Address</b><code id=credurl></code></div>
        <div><b>PIN</b><code class=pin id=credpin></code></div>
      </div></div>
    <div class=meter><b id=meterlabel>&nbsp;</b><div class=track><i id=meterfill></i></div></div>
    <div class=keys>
      <div><kbd>/</kbd> search &nbsp; <kbd>v</kbd> view &nbsp; <kbd>esc</kbd> clear</div>
      <div><kbd>⌘V</kbd> paste a file straight in</div>
    </div>
  </aside>

  <main>
    <div class=top>
      <div class=mrow>
        <div class=brand><b>Beam</b><i>.</i></div>
        <div class=free id=mfree></div>
      </div>
      <div class=trow>
        <nav class=crumbs id=crumbs aria-label=Breadcrumb></nav>
        <div class=tools>
          <div class=search id=searchwrap>
            <svg><use href="#i-search"/></svg>
            <input id=search placeholder="Search" aria-label="Search this folder">
            <button class=clr id=clr aria-label="Clear search">
              <svg width=15 height=15><use href="#i-x"/></svg></button>
          </div>
          <select class=sort id=sort aria-label="Sort by">
            <option value=new>Newest</option><option value=old>Oldest</option>
            <option value=name>Name</option><option value=big>Largest</option>
          </select>
          <div class=seg id=viewseg role=group aria-label="View">
            <button data-view=list aria-label="List view"><svg width=17 height=17><use href="#i-list"/></svg></button>
            <button data-view=grid aria-label="Grid view"><svg width=17 height=17><use href="#i-grid"/></svg></button>
          </div>
        </div>
      </div>
    </div>

    <div class=inner>
      <div class="panel pad hide" id=textbox>
        <textarea id=note placeholder="Paste a link, a password, an address..."></textarea>
        <button class="btn primary block" style="margin-top:10px" id=notesend>Save as a text file</button>
      </div>
      <div class="panel pad hide" id=qrbox style="text-align:center">
        <img src="/qr.png" alt="QR code" style="width:210px;max-width:64vw;background:#fff;padding:8px;border-radius:10px">
        <p style="color:var(--ink2);font-size:13px;margin:10px 0 0">Point another phone's camera here</p>
      </div>
      <div class="panel hide" id=queue></div>
      <h2 id=head>Files</h2>
      <div id=files></div>
    </div>
  </main>
</div>

<div class=dock>
  <label class="btn primary"><svg><use href="#i-up"/></svg>Send files
    <input type=file id=picker2 multiple hidden></label>
  <button class=btn id=textbtn2 aria-label="Send text"><svg><use href="#i-text-add"/></svg></button>
  <button class=btn id=qrbtn2 aria-label="Show QR code"><svg><use href="#i-qr"/></svg></button>
</div>

<div class=veil id=veil><div><svg><use href="#i-up"/></svg>Drop to send</div></div>

<div class=modal id=sharebox>
  <div class=sheet role=dialog aria-modal=true aria-label="Share link">
    <h3><svg><use href="#i-link"/></svg>Share link</h3>
    <p class=who id=sharewho></p>
    <div class=linkrow>
      <input id=sharelink readonly aria-label="Share link" value="Creating link...">
      <button class="btn" id=sharecopy><svg><use href="#i-copy"/></svg>Copy</button>
    </div>
    <div class=exprow><span>Stops working after</span>
      <select id=shareexp aria-label="Expiry">
        <option value=never>Never</option>
        <option value=1h>1 hour</option>
        <option value=24h>24 hours</option>
        <option value=7d>7 days</option>
      </select></div>
    <p class=note-ro><svg><use href="#i-check"/></svg>
      Anyone on your WiFi with this link can download this, and nothing else.
      They cannot upload, delete, or see the rest of your files.</p>
    <div class=modacts>
      <button class="btn ghost" id=sharestop>Stop sharing</button>
      <button class="btn primary" id=shareclose>Done</button>
    </div>
  </div>
</div>

<div class=toasts id=toasts aria-live=polite></div>

<script>
const REL = __REL__;
const GUEST = __GUEST__;       // a read-only visitor on a share link
const LABEL = __LABEL__;       // what this share is called
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const qs = p => p ? '?p=' + encodeURIComponent(p) : '';
const fpath = p => p.split('/').map(encodeURIComponent).join('/');
const ICON = {video:'i-film', image:'i-image', audio:'i-music', archive:'i-archive',
              doc:'i-doc', text:'i-text', file:'i-file'};
const store = {
  get(k, d) { try { return localStorage.getItem('beam.' + k) ?? d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('beam.' + k, v); } catch (e) {} }
};
const state = {dirs: [], files: [], q: '', sort: store.get('sort', 'new'),
               view: store.get('view', 'list'), sig: '', shares: []};
const seen = new Set();      // paths already on screen, so only new ones animate

/* rendering */
function human(n) {
  const u = ['B','KB','MB','GB','TB']; let i = 0;
  while (n >= 1024 && i < 4) { n /= 1024; i++; }
  return (i === 0 || n >= 100 ? n.toFixed(0) : n.toFixed(1)) + ' ' + u[i];
}
function preview(f, cls) {
  const ico = '<svg><use href="#' + (ICON[f.kind] || 'i-file') + '"/></svg>';
  if (!f.thumb) return '<div class="pv ' + cls + '">' + ico + '</div>';
  // native lazy loading: the browser fetches these as they near the viewport
  return '<div class="pv ' + cls + '">' + ico +
         '<img alt="" loading="lazy" onload="this.classList.add(\'on\')" ' +
         'src="/thumb/' + fpath(f.path) + '?v=' + Math.round(f.mtime) + '">' + '</div>';
}
function actions(f, isDir) {
  const dl = isDir ? '' : '<a class=ib href="/f/' + fpath(f.path) + '?download=1" download ' +
                  'aria-label="Download"><svg width=18 height=18><use href="#i-down"/></svg></a>';
  if (GUEST) return '<div class=acts>' + dl + '</div>';   // a guest only downloads
  const shared = state.shares.some(s => s.target === f.path);
  return '<div class=acts>' + dl +
    '<button class="ib' + (shared ? ' lit' : '') + '" data-share="' + esc(f.path) + '" ' +
    'data-name="' + esc(f.name) + '" aria-label="Share link">' +
    '<svg width=17 height=17><use href="#i-link"/></svg></button>' +
    '<button class=ib data-del="' + esc(f.path) + '" aria-label="Delete">' +
    '<svg width=17 height=17><use href="#i-trash"/></svg></button></div>';
}
function render(animateAll) {
  const q = state.q.toLowerCase();
  const hit = x => !q || x.name.toLowerCase().includes(q);
  const dirs = state.dirs.filter(hit);
  let files = state.files.filter(hit);
  const by = {new: (a,b) => b.mtime - a.mtime, old: (a,b) => a.mtime - b.mtime,
              name: (a,b) => a.name.localeCompare(b.name, undefined, {numeric: true}),
              big: (a,b) => b.size - a.size};
  files.sort(by[state.sort] || by.new);

  const n = dirs.length + files.length;
  $('#head').textContent = state.q ? n + (n === 1 ? ' match' : ' matches')
                                   : 'Files' + (n ? ' · ' + n : '');
  if (!n) {
    $('#files').innerHTML = '<div class="rows"><div class=empty>' +
      '<svg><use href="#i-inbox"/></svg>' +
      (state.q ? '<b>Nothing matches "' + esc(state.q) + '"</b>'
               : GUEST ? '<b>Nothing here</b>This shared folder is empty.'
               : '<b>This folder is empty</b>Send something from this device, ' +
                 'or drop a file into ~/Drop on the Mac.') + '</div></div>';
    return;
  }
  const grid = state.view === 'grid';
  const out = [];
  let nth = 0;
  const enter = item => {                  // a short, capped stagger
    const isNew = animateAll || !seen.has(item.path);
    seen.add(item.path);
    if (!isNew) return '';
    return ' fresh" style="animation-delay:' + Math.min(nth++ * 24, 260) + 'ms';
  };
  if (REL && !state.q) {
    const up = REL.split('/').slice(0, -1).join('/');
    out.push(grid ? '' : '<a class=row href="/' + qs(up) + '">' +
      '<div class="pv folder"><svg><use href="#i-back"/></svg></div>' +
      '<div class=meta><span class=nm>Back</span></div></a>');
  }
  for (const d of dirs) {
    if (grid) out.push('<div class="card' + enter(d) + '"><a href="/' + qs(d.path) + '">' +
      '<div class="pv folder"><svg><use href="#i-folder"/></svg></div></a>' +
      actions(d, true) +
      '<div class=body><a class=meta href="/' + qs(d.path) + '"><span class=nm>' +
      esc(d.name) + '</span><span class=sub>Folder</span></a></div></div>');
    else out.push('<div class="row' + enter(d) + '"><a class="pv folder" href="/' + qs(d.path) + '">' +
      '<svg><use href="#i-folder"/></svg></a>' +
      '<a class=meta href="/' + qs(d.path) + '"><span class=nm>' + esc(d.name) +
      '</span><span class=sub>Folder</span></a>' +
      '<div class="col size">-</div><div class="col when">' + esc(d.when) + '</div>' +
      actions(d, true) + '</div>');
  }
  for (const f of files) {
    const u = '/f/' + fpath(f.path);
    if (grid) out.push('<div class="card' + enter(f) + '"><a href="' + u + '" target=_blank rel=noopener>' +
      preview(f, '') + '</a>' + actions(f, false) +
      '<div class=body><a class=meta href="' + u + '" target=_blank rel=noopener>' +
      '<span class=nm>' + esc(f.name) + '</span><span class=sub>' + f.human + ' · ' +
      esc(f.when) + '</span></a></div></div>');
    else out.push('<div class="row' + enter(f) + '"><a href="' + u + '" target=_blank rel=noopener>' +
      preview(f, '') + '</a><a class=meta href="' + u + '" target=_blank rel=noopener>' +
      '<span class=nm>' + esc(f.name) + '</span><span class=sub>' + f.human + ' · ' +
      esc(f.when) + '</span></a><div class="col size">' + f.human + '</div>' +
      '<div class="col when">' + esc(f.when) + '</div>' + actions(f, false) + '</div>');
  }
  $('#files').innerHTML = grid ? '<div class=grid>' + out.join('') + '</div>'
                               : '<div class=rows>' + out.join('') + '</div>';
}

/* data */
async function load() {
  let d;
  try {
    const r = await fetch('/api/list' + qs(REL), {cache: 'no-store'});
    if (r.status === 401) { location.reload(); return; }
    d = await r.json();
  } catch (e) { return; }

  const pct = d.total_bytes ? (d.used_bytes / d.total_bytes) * 100 : 0;
  $('#meterfill').style.width = pct.toFixed(1) + '%';
  $('#meterlabel').textContent = d.free + ' free of ' + human(d.total_bytes);
  $('#mfree').textContent = d.free + ' free';

  // the server sends these to loopback only, so they show in the Mac's own
  // window and never on a phone
  if (d.pin !== undefined) {
    $('#credurl').textContent = (d.url || '').replace(/^https?:\/\//, '').replace(/\/$/, '');
    $('#credpin').textContent = d.pin || 'none';
    $('#creds').classList.remove('hide');
  }

  const parts = REL ? REL.split('/') : [];
  let acc = '', crumb = '<a href="/">' + (GUEST ? esc(LABEL || 'Shared') : 'Drop') + '</a>';
  for (const p of parts) {
    acc = acc ? acc + '/' + p : p;
    crumb += '<span>/</span><a href="/' + qs(acc) + '">' + esc(p) + '</a>';
  }
  $('#crumbs').innerHTML = crumb;

  state.shares = d.shares || [];
  const sig = JSON.stringify([d.dirs.map(x => x.name),
                              d.files.map(x => [x.name, x.size, x.mtime]),
                              state.shares.map(s => s.target)]);
  if (sig === state.sig) return;              // nothing changed, keep the DOM
  state.sig = sig; state.dirs = d.dirs; state.files = d.files;
  render();
}

/* uploads */
const queue = [];
const running = new Set();
const PARALLEL = 3;      // one stream rarely fills a WiFi link on its own

function enqueue(files) {
  if (GUEST) return;            // a guest link is read-only; nothing goes up
  for (const file of files) {
    // a folder drop gives every file a path; keep the shape it arrived in
    const rel = (file.webkitRelativePath || '').split('/').slice(0, -1).join('/');
    const el = document.createElement('div');
    el.className = 'upitem';
    el.innerHTML = '<div class=uphead><b>' +
      (rel ? '<span style="color:var(--ink3)">' + esc(rel) + '/</span>' : '') +
      esc(file.name) + '</b><span>waiting</span>' +
      '<button class=ib aria-label=Cancel><svg width=15 height=15><use href="#i-x"/></svg>' +
      '</button></div><div class=track><i></i></div>';
    const job = {file, el, rel, loaded: 0, xhr: null};
    el.querySelector('button').onclick = () => cancel(job);
    $('#queue').appendChild(el);
    $('#queue').classList.remove('hide');
    queue.push(job);
  }
  pump();
}

function cancel(job) {
  const i = queue.indexOf(job);
  if (i >= 0) queue.splice(i, 1);
  if (job.xhr) job.xhr.abort();        // the server throws its .part file away
  running.delete(job);
  job.el.remove();
  if (!$('#queue').children.length) $('#queue').classList.add('hide');
  toast('Upload cancelled');
  pump();
}

function netTick() {
  const jobs = [...running, ...queue];
  const bar = $('#netbar');
  const total = jobs.reduce((a, j) => a + j.file.size, 0);
  const done = jobs.reduce((a, j) => a + j.loaded, 0);
  bar.classList.toggle('on', jobs.length > 0);
  bar.style.width = (jobs.length && total ? (done / total) * 100 : 0).toFixed(1) + '%';
}

function pump() {
  while (running.size < PARALLEL && queue.length) send(queue.shift());
  netTick();
}

function settle(job) {
  job.loaded = job.file.size;
  running.delete(job);
  job.el.classList.remove('busy');
  state.sig = '';
  load();
  pump();
}

function send(job) {
  running.add(job);
  const {file, el, rel} = job;
  el.classList.add('busy');
  const bar = el.querySelector('i'), lab = el.querySelector('span');
  const x = new XMLHttpRequest();
  job.xhr = x;
  const t0 = Date.now();
  x.open('PUT', '/up/' + encodeURIComponent(file.name) + qs(REL) +
         (rel ? (REL ? '&' : '?') + 'd=' + encodeURIComponent(rel) : ''));
  x.upload.onprogress = ev => {
    if (!ev.lengthComputable) return;
    job.loaded = ev.loaded;
    bar.style.width = (ev.loaded / ev.total * 100).toFixed(1) + '%';
    const rate = ev.loaded / Math.max((Date.now() - t0) / 1000, .001);
    const left = Math.ceil((ev.total - ev.loaded) / Math.max(rate, 1));
    lab.textContent = human(rate) + '/s · ' + (left > 1 ? left + 's left' : 'finishing');
    netTick();
  };
  x.onload = () => {
    const ok = x.status === 200;
    settle(job);
    el.classList.add(ok ? 'done' : 'fail');
    bar.style.width = '100%';
    const btn = el.querySelector('button');
    if (ok && btn) btn.outerHTML =
      '<div class=stamp><svg width=19 height=19><use href="#i-check"/></svg></div>';
    else if (btn) btn.remove();
    lab.textContent = ok
      ? 'sent · ' + human(file.size / Math.max((Date.now() - t0) / 1000, .001)) + '/s'
      : (x.responseText || 'failed');
    if (!ok) toast(x.responseText || 'Upload failed', 'bad');
    if (ok) setTimeout(() => {
      el.remove();
      if (!$('#queue').children.length) $('#queue').classList.add('hide');
    }, 3600);
  };
  x.onerror = () => {
    settle(job);
    el.classList.add('fail');
    const btn = el.querySelector('button');
    if (btn) btn.remove();
    lab.textContent = 'connection lost';
    toast('Connection lost - is the Mac still awake?', 'bad');
  };
  x.onabort = () => { running.delete(job); pump(); };
  x.send(file);
}

/* bits and pieces */
function toast(msg, kind) {
  const t = document.createElement('div');
  t.className = 'toast' + (kind ? ' ' + kind : '');
  t.textContent = msg;
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), 3400);
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-del]');
  document.querySelectorAll('.ib.armed').forEach(x => {
    if (x !== b) { x.classList.remove('armed'); x.innerHTML = TRASH; }
  });
  if (!b) return;
  e.preventDefault();
  if (!b.classList.contains('armed')) {       // two taps, never a modal
    b.classList.add('armed'); b.textContent = 'Delete?';
    setTimeout(() => { if (b.isConnected && b.classList.contains('armed')) {
      b.classList.remove('armed'); b.innerHTML = TRASH; } }, 4000);
    return;
  }
  const r = await fetch('/api/delete', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Beam': '1'},
    body: JSON.stringify({path: b.dataset.del})});
  if (!r.ok) { toast('Could not delete that', 'bad'); return; }
  const row = b.closest('.row,.card');          // let it collapse before redrawing
  if (row) row.classList.add('going');
  seen.delete(b.dataset.del);
  toast('Deleted');
  setTimeout(() => { state.sig = ''; load(); }, 210);
});
const TRASH = '<svg width=17 height=17><use href="#i-trash"/></svg>';

/* sharing a file or folder as a read-only link */
let shareCtx = null;      // {path, name, token}

async function makeShare(path, expires) {
  const r = await fetch('/api/share', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Beam': '1'},
    body: JSON.stringify({path, expires})});
  if (!r.ok) { toast('Could not create a link', 'bad'); return null; }
  return r.json();
}
async function dropShare(token) {
  await fetch('/api/unshare', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Beam': '1'}, body: JSON.stringify({token})});
}
function openShare(path, name) {
  shareCtx = {path, name, token: null};
  $('#sharewho').innerHTML = 'Sharing <b>' + esc(name) + '</b>';
  $('#sharelink').value = 'Creating link...';
  $('#shareexp').value = 'never';
  $('#sharebox').classList.add('on');
  const existing = state.shares.find(s => s.target === path);
  const first = existing
    ? Promise.resolve(existing)
    : makeShare(path, 'never');
  first.then(s => {
    if (!s) { $('#sharebox').classList.remove('on'); return; }
    shareCtx.token = s.token;
    $('#sharelink').value = s.url;
    $('#sharelink').focus(); $('#sharelink').select();
    state.sig = ''; load();          // light up the row's share icon
  });
}
async function reissue(expires) {         // change of expiry = a fresh link
  if (!shareCtx) return;
  if (shareCtx.token) await dropShare(shareCtx.token);
  $('#sharelink').value = 'Creating link...';
  const s = await makeShare(shareCtx.path, expires);
  if (!s) return;
  shareCtx.token = s.token;
  $('#sharelink').value = s.url;
  $('#sharelink').select();
  state.sig = ''; load();
}
function closeShare() { $('#sharebox').classList.remove('on'); shareCtx = null; }

if (!GUEST) {
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-share]');
    if (!b) return;
    e.preventDefault();
    openShare(b.dataset.share, b.dataset.name);
  });
  $('#shareexp').onchange = e => reissue(e.target.value);
  $('#shareclose').onclick = closeShare;
  $('#sharebox').onclick = e => { if (e.target === $('#sharebox')) closeShare(); };
  $('#sharestop').onclick = async () => {
    if (shareCtx && shareCtx.token) { await dropShare(shareCtx.token); toast('Sharing stopped'); }
    closeShare(); state.sig = ''; load();
  };
  $('#sharecopy').onclick = async () => {
    const link = $('#sharelink').value;
    if (!link || link === 'Creating link...') return;
    try { await navigator.clipboard.writeText(link); }
    catch (e) { $('#sharelink').select(); document.execCommand('copy'); }
    toast('Link copied');
  };
}

$('#picker').onchange = $('#picker2').onchange = e => {
  enqueue(e.target.files); e.target.value = '';
};
$('#search').oninput = e => {
  state.q = e.target.value;
  $('#searchwrap').classList.toggle('has', !!state.q);
  render();
};
$('#clr').onclick = () => { $('#search').value = ''; $('#search').dispatchEvent(new Event('input')); };
$('#sort').value = state.sort;
$('#sort').onchange = e => { state.sort = e.target.value; store.set('sort', state.sort); render(); };
$('#viewseg').onclick = e => {
  const b = e.target.closest('[data-view]');
  if (!b || b.dataset.view === state.view) return;
  state.view = b.dataset.view; store.set('view', state.view); setView(); render(true);
};
function setView() {
  document.querySelectorAll('#viewseg button').forEach(
    b => b.classList.toggle('on', b.dataset.view === state.view));
}
setView();
const toggle = id => () => {
  const el = $(id); const wasHidden = el.classList.contains('hide');
  $('#textbox').classList.add('hide'); $('#qrbox').classList.add('hide');
  el.classList.toggle('hide', !wasHidden);
  if (wasHidden && id === '#textbox') $('#note').focus();
};
$('#textbtn').onclick = $('#textbtn2').onclick = toggle('#textbox');
$('#qrbtn2').onclick = toggle('#qrbox');
$('#notesend').onclick = async () => {
  const text = $('#note').value;
  if (!text.trim()) return;
  const r = await fetch('/api/note', {method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Beam': '1'}, body: JSON.stringify({text, p: REL})});
  if (r.ok) { $('#note').value = ''; $('#textbox').classList.add('hide');
              toast('Saved as a text file'); state.sig = ''; load(); }
};

let veils = 0;
window.addEventListener('dragenter', e => {
  if (!e.dataTransfer || ![...e.dataTransfer.types].includes('Files')) return;
  e.preventDefault(); veils++; $('#veil').classList.add('on');
});
window.addEventListener('dragover', e => e.preventDefault());
window.addEventListener('dragleave', e => {
  e.preventDefault(); if (--veils <= 0) { veils = 0; $('#veil').classList.remove('on'); }
});
window.addEventListener('drop', e => {
  e.preventDefault(); veils = 0; $('#veil').classList.remove('on');
  if (e.dataTransfer.files.length) enqueue(e.dataTransfer.files);
});
window.addEventListener('paste', e => {
  const files = [...(e.clipboardData?.files || [])];
  if (files.length) enqueue(files);
});
window.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === '/' && !typing) { e.preventDefault(); $('#search').focus(); }
  else if (e.key === 'v' && !typing) {
    state.view = state.view === 'list' ? 'grid' : 'list';
    store.set('view', state.view); setView(); render(true);
  } else if (e.key === 'Escape') {
    if (state.q) { $('#clr').click(); }
    document.querySelectorAll('.ib.armed').forEach(x => {
      x.classList.remove('armed'); x.innerHTML = TRASH; });
    $('#textbox').classList.add('hide'); $('#qrbox').classList.add('hide');
  }
});
$('#host').textContent = location.host;
if (GUEST) {
  document.documentElement.classList.add('guest');
  $('#host').textContent = LABEL || 'Shared';
  $('#rochip').classList.remove('hide');
  document.title = (LABEL ? LABEL + ' · ' : '') + 'Beam';
}
// the shape of the list, drawn while the first response is still in flight
$('#files').innerHTML = '<div class=rows>' +
  '<div class=sk><i></i><div><u></u><u></u></div></div>'.repeat(4) + '</div>';
if ('webkitdirectory' in document.createElement('input') &&
    matchMedia('(min-width:900px)').matches) $('#folderbtn').classList.remove('hide');
$('#folderpick').onchange = e => { enqueue(e.target.files); e.target.value = ''; };
load();
setInterval(() => { if (!running.size) load(); }, 5000);
</script>"""


def js(value):
    """A value embedded in a <script> safely - `</script>` and friends neutered.

    json.dumps leaves `<`, `>` and `&` untouched, so a folder literally named
    `</script>...` would otherwise close the tag and run as markup.
    """
    return (json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def page(rel, guest=False, label=""):
    return (PAGE.replace("__STYLE__", STYLE)
                .replace("__ICONS__", ICONS)
                .replace("__REL__", js(rel))
                .replace("__GUEST__", "true" if guest else "false")
                .replace("__LABEL__", js(label)))


def gone():
    return (GONE.replace("__STYLE__", STYLE))
