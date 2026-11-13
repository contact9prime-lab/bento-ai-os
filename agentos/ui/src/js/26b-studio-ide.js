/* ================= App Studio's code editor (the IDE) =================

   An app is one HTML file, and the person can now open it, change a line and save it,
   as well as describe a change to the builder. This file is the editor itself: a
   highlighter for HTML with CSS and JavaScript inside it, a textarea under the
   highlighted text (so the browser's own caret, selection, undo, IME and phone keyboard
   all work), line numbers, find, an outline of the file, and a line diff for Versions.
   No editor library is vendored: CodeMirror and Monaco are large, and an app is a file
   of a few hundred lines.

   26-studio.js owns the layout and the server calls; this file owns nothing on the
   server. Every save goes through /api/apps/{id}/source (agentos/appsource.py), which
   refuses a save over a version that moved on.

   GUI and SUI: the same window. TUI: `bento studio pull|push|edit|check` is the same
   source and the same save, with $EDITOR as the editor. A terminal cannot show the
   preview, which is why there is no IDE pane in the TUI itself. */

var IDE_LH=19;                  // line height in px, shared by the gutter, the text and the caret line
var IDE_KW=new Set(('async await break case catch class const continue debugger default delete do else '
  +'export extends finally for from function if import in instanceof let new of return static super '
  +'switch this throw try typeof var void while with yield').split(' '));
var IDE_LIT=new Set(['true','false','null','undefined','NaN','Infinity']);
var IDE_RT=new Set(['appData','appTool','appLLM','appChat','appAgent','appCopilot','appToast','appConfirm',
  'appCelebrate','appIcon','appShare','appFmt','appSurface','APP_ID']);   // the app runtime, so it reads as ours

function ideEsc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

/* One pass over the file: HTML outside, CSS inside <style>, JavaScript inside <script>.
   Returns the highlighted HTML and the mode each line starts in (for comment toggling
   and the status bar). Text is always escaped; nothing the file says becomes markup. */
function ideHighlight(src){
  var out='',i=0,n=src.length,mode='html',modes=['html'],cssDepth=0,lastSig='';
  function emit(cls,t){
    if(!t)return;
    var k=0;for(var j=0;j<t.length;j++)if(t.charCodeAt(j)===10)k++;
    out+=cls?'<span class="'+cls+'">'+ideEsc(t)+'</span>':ideEsc(t);
    for(;k>0;k--)modes.push(mode);
  }
  function until(str,from){var e=src.indexOf(str,from);return e<0?n:e+str.length}
  function lower(at,s){return src.substr(at,s.length).toLowerCase()===s}
  while(i<n){
    var c=src[i];
    if(mode==='html'){
      if(src.startsWith('<!--',i)){var e=until('-->',i+4);emit('t-com',src.slice(i,e));i=e;continue}
      if(c==='<'&&/[a-zA-Z\/!]/.test(src[i+1]||'')){
        var close=src[i+1]==='/';
        emit('t-pun',close?'</':'<');i+=close?2:1;
        var m=/^[!\w:-]+/.exec(src.slice(i,i+40));var tag=m?m[0]:'';
        emit('t-tag',tag);i+=tag.length;
        while(i<n&&src[i]!=='>'){
          var ch=src[i];
          if(ch==='"'||ch==="'"){var q=src.indexOf(ch,i+1);q=q<0?n:q+1;emit('t-str',src.slice(i,q));i=q;continue}
          if(/[\w:@.-]/.test(ch)){var a=/^[\w:@.-]+/.exec(src.slice(i,i+80))[0];emit('t-attr',a);i+=a.length;continue}
          if(ch==='<')break;                       // a broken tag: let the next one start
          emit(ch==='='||ch==='/'?'t-pun':'',ch);i++;
        }
        if(src[i]==='>'){emit('t-pun','>');i++}
        var t=tag.toLowerCase();
        if(!close&&t==='script'){mode='js';lastSig=''}
        else if(!close&&t==='style'){mode='css';cssDepth=0}
        continue;
      }
      var nx=src.indexOf('<',i+1);if(nx<0)nx=n;
      if(c==='<'){emit('',c);i++;continue}
      emit('',src.slice(i,nx));i=nx;continue;
    }
    if(mode==='js'){
      if(c==='<'&&lower(i,'</script')){mode='html';continue}
      if(c==='/'&&src[i+1]==='/'){var e1=src.indexOf('\n',i);e1=e1<0?n:e1;emit('t-com',src.slice(i,e1));i=e1;continue}
      if(c==='/'&&src[i+1]==='*'){var e2=until('*/',i+2);emit('t-com',src.slice(i,e2));i=e2;continue}
      if(c==='"'||c==="'"||c==='`'){
        var j=i+1;
        while(j<n&&src[j]!==c){if(src[j]==='\\')j++;else if(c!=='`'&&src[j]==='\n')break;j++}
        j=Math.min(n,j+1);emit('t-str',src.slice(i,j));i=j;lastSig='a';continue;
      }
      if(c==='/'&&(lastSig===''||/[(,=:\[!&|?{};+\-*%<>~^]/.test(lastSig))){
        // a regex literal, where an operand is expected
        var k2=i+1,inCls=false;
        while(k2<n&&src[k2]!=='\n'){
          if(src[k2]==='\\'){k2+=2;continue}
          if(src[k2]==='[')inCls=true;else if(src[k2]===']')inCls=false;
          else if(src[k2]==='/'&&!inCls)break;
          k2++;
        }
        if(src[k2]==='/'){k2++;while(/[a-z]/.test(src[k2]||''))k2++;emit('t-re',src.slice(i,k2));i=k2;lastSig='a';continue}
      }
      if(/[0-9]/.test(c)||(c==='.'&&/[0-9]/.test(src[i+1]||''))){
        var mn=/^(0x[\da-f]+|\d[\d_]*\.?\d*(e[+-]?\d+)?|\.\d+)/i.exec(src.slice(i,i+40));
        var num=mn?mn[0]:c;emit('t-num',num);i+=num.length;lastSig='a';continue;
      }
      if(/[A-Za-z_$]/.test(c)){
        var w=/^[A-Za-z_$][\w$]*/.exec(src.slice(i,i+80))[0];
        var after=/^\s*\(/.test(src.slice(i+w.length,i+w.length+20));
        var dot=src[i-1]==='.';
        var cls=IDE_KW.has(w)&&!dot?'t-kw':IDE_LIT.has(w)&&!dot?'t-lit':IDE_RT.has(w)&&!dot?'t-rt':after?'t-fn':'';
        emit(cls,w);i+=w.length;lastSig=IDE_KW.has(w)&&w!=='this'&&w!=='super'?'(':'a';continue;
      }
      if(!/\s/.test(c))lastSig=c;
      emit('',c);i++;continue;
    }
    // css
    if(c==='<'&&lower(i,'</style')){mode='html';continue}
    if(c==='/'&&src[i+1]==='*'){var e3=until('*/',i+2);emit('t-com',src.slice(i,e3));i=e3;continue}
    if(c==='"'||c==="'"){var q2=src.indexOf(c,i+1);q2=q2<0?n:q2+1;emit('t-str',src.slice(i,q2));i=q2;continue}
    if(c==='{'){cssDepth++;emit('t-pun',c);i++;continue}
    if(c==='}'){cssDepth=Math.max(0,cssDepth-1);emit('t-pun',c);i++;continue}
    if(/\s|;/.test(c)){emit(c===';'?'t-pun':'',c);i++;continue}
    if(c==='@'){var at=/^@[\w-]+/.exec(src.slice(i,i+40));at=at?at[0]:'@';emit('t-kw',at);i+=at.length;continue}
    // a statement: a selector if '{' comes before ';' or '}', else a declaration
    var end=i;while(end<n&&!'{;}'.includes(src[end])&&!(src[end]==='<'&&lower(end,'</style')))end++;
    if(src[end]==='{'||cssDepth===0){emit('t-sel',src.slice(i,end));i=end;continue}
    var colon=src.indexOf(':',i);
    if(colon>=0&&colon<end){
      emit('t-prop',src.slice(i,colon));emit('t-pun',':');
      var v=src.slice(colon+1,end),re=/(#[\da-f]{3,8}\b|-?\d*\.?\d+(?:px|em|rem|%|vh|vw|s|ms|deg|fr|ch|ex|pt)?\b|"[^"]*"|'[^']*'|var\(--[\w-]+\))/gi,last=0,mm;
      while((mm=re.exec(v))){emit('',v.slice(last,mm.index));emit(mm[0].startsWith('var(')?'t-rt':mm[0][0]==='"'||mm[0][0]==="'"?'t-str':'t-num',mm[0]);last=mm.index+mm[0].length}
      emit('',v.slice(last));i=end;continue;
    }
    emit('',src.slice(i,end));i=end;
  }
  return {html:out,modes:modes};
}

/* The file's landmarks: its style and script blocks, the functions it defines, the ids
   it draws into, and the two surfaces. Clicked in the explorer, each jumps to its line. */
function ideOutline(src){
  var items=[],lines=src.split('\n');
  for(var i=0;i<lines.length&&items.length<160;i++){
    var L=lines[i],m;
    if(/<style\b/i.test(L))items.push({kind:'css',name:'<style>',line:i+1});
    if((m=/<script\b([^>]*)>/i.exec(L)))items.push({kind:'js',name:/\bsrc=/.test(m[1])?'<script src>':'<script>',line:i+1});
    if((m=/\bclass\s*=\s*["'][^"']*\b(widget-only|desktop-only)\b/.exec(L)))items.push({kind:'surface',name:m[1]==='widget-only'?'widget view':'desktop view',line:i+1});
    if((m=/(?:^|[^\w$.])function\s*\*?\s*([A-Za-z_$][\w$]*)\s*\(/.exec(L)))items.push({kind:'fn',name:m[1]+'()',line:i+1});
    else if((m=/(?:^|[;{\s])(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)/.exec(L)))items.push({kind:'fn',name:m[1]+'()',line:i+1});
    if(/appCopilot\s*\.\s*mount/.test(L))items.push({kind:'ai',name:'copilot',line:i+1});
    var re=/\bid\s*=\s*["']([\w-]{1,40})["']/g;
    while((m=re.exec(L))&&items.length<160)items.push({kind:'id',name:'#'+m[1],line:i+1});
  }
  return items;
}

/* A line diff (LCS) for Versions → Compare. Bounded: past ~2,500 lines a side it says so
   instead of freezing the page on a table of six million cells. */
function ideDiff(a,b){
  var A=a.split('\n'),B=b.split('\n');
  // trim the common head and tail, which is most of a file in most edits
  var h=0;while(h<A.length&&h<B.length&&A[h]===B[h])h++;
  var t=0;while(t<A.length-h&&t<B.length-h&&A[A.length-1-t]===B[B.length-1-t])t++;
  var a2=A.slice(h,A.length-t),b2=B.slice(h,B.length-t);
  if(a2.length*b2.length>6e6)return {tooBig:true};
  var n=a2.length,m=b2.length,dp=new Array(n+1);
  for(var i=0;i<=n;i++){dp[i]=new Int32Array(m+1)}
  for(i=n-1;i>=0;i--)for(var j=m-1;j>=0;j--)dp[i][j]=a2[i]===b2[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);
  var rows=[];i=0;j=0;
  while(i<n||j<m){
    if(i<n&&j<m&&a2[i]===b2[j]){rows.push({k:' ',t:a2[i],a:h+i+1,b:h+j+1});i++;j++}
    else if(i<n&&(j>=m||dp[i+1][j]>=dp[i][j+1])){rows.push({k:'-',t:a2[i],a:h+i+1});i++}
    else{rows.push({k:'+',t:b2[j],b:h+j+1});j++}
  }
  return {rows:rows,head:h,tail:t,added:rows.filter(r=>r.k==='+').length,removed:rows.filter(r=>r.k==='-').length};
}

/* ---- the editor widget --------------------------------------------------------- */
function ideEditor(host,o){
  host.innerHTML=`<div class="ide-ed">
      <div class="ide-gut" aria-hidden="true"><div class="ide-gutin"></div></div>
      <div class="ide-code">
        <div class="ide-cur" aria-hidden="true"></div>
        <pre class="ide-hl" aria-hidden="true"><code></code></pre>
        <textarea class="ide-ta" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off" wrap="off" aria-label="App source"></textarea>
      </div>
      <div class="ide-find" hidden>
        <input class="ide-fq" placeholder="Find" aria-label="Find">
        <span class="ide-fn mut"></span>
        <button class="ide-fp" title="Previous (Shift+Enter)">↑</button>
        <button class="ide-fx" title="Next (Enter)">↓</button>
        <button class="ide-fc" title="Close (Esc)">✕</button>
      </div>
    </div>`;
  var ta=host.querySelector('.ide-ta'),hl=host.querySelector('.ide-hl'),code=hl.firstChild,
      gut=host.querySelector('.ide-gutin'),cur=host.querySelector('.ide-cur'),
      find=host.querySelector('.ide-find'),fq=host.querySelector('.ide-fq'),fcount=host.querySelector('.ide-fn');
  var ed={ta:ta,modes:['html'],marks:{},lines:1};
  var raf=0;
  ta.value=o.value||'';
  function paint(){
    raf=0;
    var r=ideHighlight(ta.value);
    code.innerHTML=r.html+'\n ';           // the extra line keeps the last one as tall as the textarea's
    ed.modes=r.modes;
    var n=ta.value.split('\n').length;
    if(n!==ed.lines||ed._marksDirty){
      ed.lines=n;ed._marksDirty=false;
      var g='';
      for(var i=1;i<=n;i++){var mk=ed.marks[i];g+='<div'+(mk?' class="m-'+mk.sev+'" title="'+esc(mk.msg)+'"':'')+'>'+i+'</div>'}
      gut.innerHTML=g;
    }
    sync();
  }
  function later(){if(!raf)raf=requestAnimationFrame(paint)}
  function sync(){
    var x=ta.scrollLeft,y=ta.scrollTop;
    hl.style.transform='translate('+(-x)+'px,'+(-y)+'px)';
    gut.style.transform='translateY('+(-y)+'px)';
    var p=ed.pos();cur.style.transform='translateY('+((p.line-1)*IDE_LH-y)+'px)';
  }
  ed.pos=function(){
    var s=ta.selectionStart,before=ta.value.slice(0,s),line=before.split('\n').length;
    return {line:line,col:s-before.lastIndexOf('\n'),sel:ta.selectionEnd-s};
  };
  ed.mode=function(){return ed.modes[ed.pos().line-1]||'html'};
  ed.get=function(){return ta.value};
  ed.set=function(v,keep){
    var s=ta.selectionStart,y=ta.scrollTop;ta.value=v;
    if(keep){ta.selectionStart=ta.selectionEnd=Math.min(s,v.length);ta.scrollTop=y}
    paint();
  };
  ed.goto=function(line,col){
    var L=ta.value.split('\n'),at=0;line=Math.max(1,Math.min(line,L.length));
    for(var i=0;i<line-1;i++)at+=L[i].length+1;
    at+=Math.max(0,Math.min((col||1)-1,L[line-1].length));
    ta.focus({preventScroll:true});ta.setSelectionRange(at,at);
    ta.scrollTop=Math.max(0,(line-1)*IDE_LH-ta.clientHeight/3);
    sync();o.onCursor&&o.onCursor();
  };
  ed.view=function(){return {s:ta.selectionStart,e:ta.selectionEnd,y:ta.scrollTop,x:ta.scrollLeft}};
  ed.restore=function(v){if(!v)return;ta.setSelectionRange(v.s,v.e);ta.scrollTop=v.y;ta.scrollLeft=v.x;sync()};
  ed.setMarks=function(probs){
    ed.marks={};
    (probs||[]).forEach(function(p){if(!p.line)return;var k=p.severity==='broken'?'err':p.severity==='contract'?'warn':'info';
      var was=ed.marks[p.line];if(!was||(was.sev!=='err'&&k==='err'))ed.marks[p.line]={sev:k,msg:p.message}});
    ed._marksDirty=true;later();
  };
  ed.selection=function(){
    var s=ta.selectionStart,e=ta.selectionEnd;if(e<=s)return null;
    var v=ta.value;return {text:v.slice(s,e),from:v.slice(0,s).split('\n').length,to:v.slice(0,e).split('\n').length};
  };
  ed.focus=function(){ta.focus({preventScroll:true})};

  // Edits go through insertText so the textarea's own undo stack keeps them.
  function put(text,selFrom,selTo){
    if(selFrom!==undefined)ta.setSelectionRange(selFrom,selTo);
    if(!document.execCommand||!document.execCommand('insertText',false,text)){
      var s=ta.selectionStart,e=ta.selectionEnd;ta.setRangeText(text,s,e,'end');
      ta.dispatchEvent(new Event('input'));
    }
  }
  function lineRange(){
    var v=ta.value,s=ta.selectionStart,e=ta.selectionEnd;
    if(e>s&&v[e-1]==='\n')e--;
    var a=v.lastIndexOf('\n',s-1)+1,b=v.indexOf('\n',e);if(b<0)b=v.length;
    return [a,b];
  }
  function indentLines(out){
    var r=lineRange(),block=ta.value.slice(r[0],r[1]);
    var next=block.split('\n').map(function(L){return out?L.replace(/^( {1,2}|\t)/,''):'  '+L}).join('\n');
    put(next,r[0],r[1]);ta.setSelectionRange(r[0],r[0]+next.length);
  }
  function toggleComment(){
    var mode=ed.mode(),r=lineRange(),block=ta.value.slice(r[0],r[1]),L=block.split('\n');
    var next;
    if(mode==='js'){
      var all=L.every(function(x){return !x.trim()||/^\s*\/\//.test(x)});
      next=L.map(function(x){return all?x.replace(/^(\s*)\/\/ ?/,'$1'):(x.trim()?x.replace(/^(\s*)/,'$1// '):x)}).join('\n');
    }else{
      var open=mode==='css'?'/* ':'<!-- ',shut=mode==='css'?' */':' -->';
      var t=block.trim(),lead=block.match(/^\s*/)[0];
      next=t.startsWith(open.trim())&&t.endsWith(shut.trim())
        ?lead+t.slice(open.trim().length,t.length-shut.trim().length).trim()
        :lead+open+t+shut;
    }
    put(next,r[0],r[1]);ta.setSelectionRange(r[0],r[0]+next.length);
  }
  ta.addEventListener('keydown',function(e){
    var mod=e.metaKey||e.ctrlKey;
    if(mod&&e.key.toLowerCase()==='s'){e.preventDefault();o.onSave&&o.onSave();return}
    if(mod&&e.key.toLowerCase()==='f'){e.preventDefault();ed.openFind();return}
    if(mod&&e.key.toLowerCase()==='g'){e.preventDefault();ed.askLine();return}
    if(mod&&e.key==='/'){e.preventDefault();toggleComment();return}
    if(mod&&e.key==='Enter'){e.preventDefault();o.onRun&&o.onRun();return}
    if(e.key==='Escape'&&!find.hidden){e.preventDefault();ed.closeFind();return}
    if(e.key==='Tab'&&!mod&&!e.altKey){
      e.preventDefault();
      if(e.shiftKey||ta.value.slice(ta.selectionStart,ta.selectionEnd).includes('\n'))indentLines(e.shiftKey);
      else put('  ');
      return;
    }
    if(e.key==='Enter'&&!mod&&!e.shiftKey&&!e.isComposing){
      var v=ta.value,s=ta.selectionStart,ls=v.lastIndexOf('\n',s-1)+1,ind=v.slice(ls,s).match(/^[ \t]*/)[0];
      var prev=v.slice(ls,s).trimEnd(),nextCh=v[ta.selectionEnd]||'';
      var opens=/[{([]$/.test(prev)||(/<([a-zA-Z][\w-]*)\b[^>]*>$/.test(prev)&&!/<\/|\/>$/.test(prev)&&!/^<(br|img|input|meta|link|hr)\b/i.test(prev.slice(prev.lastIndexOf('<'))));
      e.preventDefault();
      if(opens&&/[})\]<]/.test(nextCh)){put('\n'+ind+'  \n'+ind);ta.setSelectionRange(s+1+ind.length+2,s+1+ind.length+2)}
      else put('\n'+ind+(opens?'  ':''));
      return;
    }
  });
  ta.addEventListener('input',function(){later();o.onChange&&o.onChange(ta.value)});
  ta.addEventListener('scroll',sync,{passive:true});
  ['keyup','click','select'].forEach(function(t){ta.addEventListener(t,function(){sync();o.onCursor&&o.onCursor()})});

  // find: selects each match in the textarea, so the caret and the selection are the browser's own
  var hits=[],hi=-1;
  function search(){
    var q=fq.value;hits=[];hi=-1;
    if(q){var v=ta.value.toLowerCase(),ql=q.toLowerCase(),at=v.indexOf(ql);
      while(at>=0&&hits.length<5000){hits.push(at);at=v.indexOf(ql,at+Math.max(1,ql.length))}}
    fcount.textContent=q?(hits.length?'':'no results'):'';
  }
  function step(d){
    if(!hits.length){search();if(!hits.length)return}
    var s=ta.selectionStart;
    if(hi<0){hi=d>0?hits.findIndex(function(h){return h>=s}):-1;if(hi<0)hi=d>0?0:hits.length-1}
    else hi=(hi+d+hits.length)%hits.length;
    var at=hits[hi],line=ta.value.slice(0,at).split('\n').length;
    ta.focus({preventScroll:true});ta.setSelectionRange(at,at+fq.value.length);
    ta.scrollTop=Math.max(0,(line-1)*IDE_LH-ta.clientHeight/3);
    fcount.textContent=(hi+1)+' of '+hits.length;sync();fq.focus();
  }
  ed.openFind=function(){
    find.hidden=false;var sel=ta.value.slice(ta.selectionStart,ta.selectionEnd);
    if(sel&&!sel.includes('\n'))fq.value=sel;
    fq.focus();fq.select();search();
  };
  ed.closeFind=function(){find.hidden=true;ta.focus({preventScroll:true})};
  ed.askLine=async function(){
    var v=await osPrompt('Go to line',{value:String(ed.pos().line),confirmText:'Go'});
    var n=parseInt(v,10);if(n>0)ed.goto(n);
  };
  fq.addEventListener('input',function(){search();if(hits.length)step(1)});
  fq.addEventListener('keydown',function(e){
    if(e.key==='Enter'){e.preventDefault();step(e.shiftKey?-1:1)}
    else if(e.key==='Escape'){e.preventDefault();ed.closeFind()}
  });
  host.querySelector('.ide-fx').onclick=function(){step(1)};
  host.querySelector('.ide-fp').onclick=function(){step(-1)};
  host.querySelector('.ide-fc').onclick=ed.closeFind;
  paint();
  return ed;
}
