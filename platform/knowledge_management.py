"""Versioned, plain-text knowledge guidance; permissions remain native."""
import json,re,datetime,unicodedata,math
from urllib.parse import urlencode
from pathlib import Path
from flask import Blueprint,g,request,abort,redirect
from localization import language,tr,LANGUAGES
SEED=json.loads(Path(__file__).with_name('knowledge-seed.json').read_text(encoding='utf-8'))
FIELDS=['module','stage','audience','title','purpose','steps','requirements','next_step','issues']
AUDIENCES=['all','citizen','officer','verifier','supervisor']
MODULES={m['id']:m['name'] for m in SEED['modules']}
def reference_metadata(item):
 from urllib.parse import urlparse
 sources=[]
 for source in item.get('sources',[]):
  url=source.get('url','');parsed=urlparse(url)
  if parsed.scheme=='https' and (parsed.hostname in ['docs.opeka2p.org','localhost:8443'] or parsed.hostname=='github.com' and parsed.path.startswith('/KarnatakaDBT/opeka2p-documentation/')):
   sources.append({'title':str(source.get('title','Reference'))[:160],'url':url[:1200]})
 result={'sources':sources[:8]} if sources else {}
 if item.get('scope') in ['upstream_reference','local_workflow']:result['scope']=item['scope']
 if re.fullmatch(r'\d{4}-\d{2}-\d{2}',item.get('sources_checked_on','')):result['sources_checked_on']=item['sources_checked_on']
 return result
def install(r):
 import localization
 localization.install(r)
 bp=Blueprint('knowledge',__name__)
 with r.db() as c:
  c.executescript("""CREATE TABLE IF NOT EXISTS km_articles(id INTEGER PRIMARY KEY,slug TEXT UNIQUE NOT NULL,module TEXT NOT NULL,stage TEXT NOT NULL,audience TEXT NOT NULL,draft TEXT NOT NULL,version INTEGER NOT NULL,status TEXT NOT NULL,author TEXT NOT NULL,reviewer TEXT,published TEXT,published_version INTEGER,updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS km_history(id INTEGER PRIMARY KEY,article INTEGER NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,actor TEXT NOT NULL,at TEXT NOT NULL,content TEXT NOT NULL);""")
  for table,column in [('km_articles','review_note'),('km_history','note')]:
   if column not in {row[1] for row in c.execute('PRAGMA table_info('+table+')')}:c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+" TEXT DEFAULT ''")
  kannada=json.loads(Path(__file__).with_name('knowledge-kn.json').read_text(encoding='utf-8'))
  for item in SEED['articles']+kannada['articles']:
   content=json.dumps({**{k:item[k] for k in FIELDS},**reference_metadata(item),'language':item.get('language','en'),'translation_of':item.get('translation_of','')},ensure_ascii=False);now=r.stamp();actor='system:documentation-import' if item.get('origin')=='system:documentation-import' else 'system:initial-guidance'
   cur=c.execute("INSERT OR IGNORE INTO km_articles(slug,module,stage,audience,draft,version,status,author,reviewer,published,published_version,updated) VALUES(?,?,?,?,?,1,'published',?,?,?,1,?)",(item['slug'],item['module'],item['stage'],item['audience'],content,actor,actor,content,now))
   if cur.rowcount:c.execute("INSERT INTO km_history(article,version,action,actor,at,content) VALUES(?,1,?,?,?,?)",(cur.lastrowid,'documentation_import' if actor=='system:documentation-import' else 'initial_guidance',actor,now,content))
 def permissions():
  roles=[role.replace('iqs-','kdbt-',1) for role in g.user.get('roles',[])] if g.user else [];staff=g.session.get('mode')=='staff'
  return {'edit':staff and (g.staff or any(role in roles for role in ['kdbt-registration-officer','kdbt-verification-officer','kdbt-programme-supervisor'])),'review':staff and (g.staff or 'kdbt-verification-officer' in roles),'publish':staff and (g.staff or 'kdbt-programme-supervisor' in roles)}
 def require(action):
  r.require_user()
  if not permissions()[action]:abort(403,'Your account cannot perform this knowledge action.')
 def history(c,a,action,note=''):c.execute('INSERT INTO km_history(article,version,action,actor,at,content,note) VALUES(?,?,?,?,?,?,?)',(a['id'],a['version'],action,g.user['sub'],r.stamp(),a['draft'],note))
 def readable(content):
  if content.get('visibility','public')=='public':return True
  if not g.user or g.session.get('mode')!='staff':return False
  roles={role.replace('iqs-','kdbt-',1) for role in g.user.get('roles',[])}
  if 'kdbt-intake-reviewer' in roles:return True
  required={'officer':'kdbt-registration-officer','verifier':'kdbt-verification-officer','supervisor':'kdbt-programme-supervisor'}
  audience=content.get('audience','all')
  return bool(roles.intersection(required.values())) if audience in ('all','citizen') else required.get(audience) in roles
 def governance(form,previous=None):
  previous=previous or {};visibility=form.get('visibility',previous.get('visibility','public'));due=form.get('review_due',previous.get('review_due','')).strip()
  if visibility not in ('public','staff'):abort(400,'Choose public or staff-only visibility.')
  if due:
   try:datetime.date.fromisoformat(due)
   except ValueError:abort(400,'Use a valid review date.')
  article_language=form.get('language',previous.get('language','en'))
  if article_language not in LANGUAGES:abort(400,'Choose a supported article language.')
  return {'visibility':visibility,'review_due':due,'language':article_language,'translation_of':previous.get('translation_of','')}
 def normalized(value):
  return unicodedata.normalize('NFC',value.casefold())
 def matches(article,query):
  words=normalized(query).split();text=normalized(' '.join(str(article[k]) for k in FIELDS))
  return all(word in text for word in words)
 def published(select_language=True):
  result=[]
  for row in r.rows("SELECT * FROM km_articles WHERE published IS NOT NULL AND status!='archived' ORDER BY module,stage,audience"):
   content=json.loads(row['published'])
   if readable(content):result.append({'id':row['id'],'slug':row['slug'],'version':row['published_version'],'language':'en',**content})
  if not select_language:return result
  preferred=language();translations={a.get('translation_of'):a for a in result if a.get('translation_of') and a['language']==preferred}
  original_slugs={a['slug'] for a in result if a['language']!=preferred}
  chosen=[]
  for a in result:
   if a.get('translation_of') and a['translation_of'] in original_slugs and a['language']==preferred:continue
   if a['language']==preferred:chosen.append(a)
   elif a['slug'] in translations:chosen.append(translations[a['slug']])
   elif preferred=='kn' and a['language']=='en':chosen.append({**a,'language_fallback':True})
  return chosen
 @bp.get(r.PREFIX+'/api/knowledge')
 def public_api():
  articles=published();module=request.args.get('module');audience=request.args.get('audience','all')
  if module and module not in MODULES:abort(400,'Unknown service')
  if module:articles=[a for a in articles if a['module']==module]
  if audience not in AUDIENCES:abort(400,'Unknown audience')
  if request.args.get('include_roles')!='1':articles=[a for a in articles if a['audience'] in ['all',audience]]
  query=request.args.get('q','').strip()
  if len(query)>160:abort(400,'Keep searches under 160 characters.')
  if query:articles=[a for a in articles if matches(a,query)]
  response=r.app.make_response({'articles':articles,'modules':[{**m,'name':tr(m['name'])} for m in SEED['modules']],'audiences':AUDIENCES,'language':language(),'languages':LANGUAGES,'notice':'Public guidance is open; staff-only guidance requires an authorised staff session. Audience filters do not grant permissions.'})
  origin=request.headers.get('Origin','');host=origin.removeprefix('https://')
  if origin.startswith('https://') and (host=='localhost:8443' or re.fullmatch(r'[a-z0-9-]+\.karnatakadbt\.com',host)):response.headers['Access-Control-Allow-Origin']=origin;response.headers['Vary']='Origin'
  response.headers['Cache-Control']='private, no-store'
  response.headers['Vary']='Cookie, Origin'
  return response
 @bp.get(r.PREFIX+'/knowledge')
 def library():
  articles=published();total_published=len(articles);source_guides=sum(bool(a.get('sources')) for a in articles);q=request.args.get('q','').strip().lower();module=request.args.get('module','');audience=request.args.get('audience','all')
  if module:articles=[a for a in articles if a['module']==module]
  if audience not in AUDIENCES:abort(400)
  if len(q)>160 or module and module not in MODULES:abort(400,'Choose a service and a search of at most 160 characters.')
  articles=[a for a in articles if a['audience'] in ['all',audience] and matches(a,q)]
  if audience!='all':
   choices={}
   for a in articles:
    key=(a['module'],a['stage'])
    if key not in choices or a['audience']==audience:choices[key]=a
   articles=list(choices.values())
  if q and hasattr(r,'analytics_search'):r.analytics_search(module,len(articles))
  if q:articles.sort(key=lambda a:sum(normalized(a['title']).count(w)*3 for w in normalized(q).split()),reverse=True)
  total_matches=len(articles)
  try:page_number=int(request.args.get('page','1'))
  except ValueError:abort(400,'Use a valid page number.')
  pages=max(1,math.ceil(total_matches/12))
  if not 1<=page_number<=pages:abort(400,'This result page does not exist.')
  articles=articles[(page_number-1)*12:page_number*12]
  def page_url(n):return r.PREFIX+'/knowledge?'+urlencode({'q':request.args.get('q',''),'module':module,'audience':audience,'page':n,'lang':language()})
  return r.page('knowledge-library.html',articles=articles,modules=MODULES,audiences=AUDIENCES,perms=permissions(),total_published=total_published,source_guides=source_guides,q=request.args.get('q',''),module=module,audience=audience,total_matches=total_matches,page_number=page_number,pages=pages,previous_url=page_url(page_number-1) if page_number>1 else None,next_url=page_url(page_number+1) if page_number<pages else None)
 @bp.get(r.PREFIX+'/knowledge/<int:aid>')
 def article_page(aid):
  item=next((a for a in published(False) if a['id']==aid),None)
  if not item:abort(404)
  return r.page('knowledge-article.html',article=item,modules=MODULES)
 @bp.get(r.PREFIX+'/knowledge/<int:aid>/export')
 def export(aid):
  item=next((a for a in published(False) if a['id']==aid),None)
  if not item:abort(404)
  headings={'purpose':'Purpose','steps':'What to do','requirements':'What you need','next_step':'Next step','issues':'Common issues'}
  body=item['title']+'\n'+tr('Published version')+' '+str(item['version'])+'\n\n'+'\n\n'.join(tr(headings[k])+'\n'+item[k] for k in FIELDS if k not in ('title','module','audience','stage'))
  response=r.app.make_response(body);response.headers['Content-Type']='text/plain; charset=utf-8';response.headers['Content-Disposition']='attachment; filename="knowledge-'+str(aid)+'-v'+str(item['version'])+'.txt"';response.headers['Cache-Control']='private, no-store';return response
 @bp.get(r.PREFIX+'/knowledge/admin')
 def admin():
  if not g.user:return redirect(r.PREFIX+'/login?mode=staff&knowledge=1')
  require('edit');items=r.rows('SELECT * FROM km_articles ORDER BY updated DESC')
  for a in items:a['content']=json.loads(a['draft'])
  return r.page('knowledge-admin.html',items=items,perms=permissions())
 @bp.get(r.PREFIX+'/knowledge/admin/new')
 @bp.get(r.PREFIX+'/knowledge/admin/<int:aid>')
 def editor(aid=None):
  require('edit');a=r.one('SELECT * FROM km_articles WHERE id=?',(aid,)) if aid else None
  if aid and not a:abort(404)
  return r.page('knowledge-editor.html',article=a,content=json.loads(a['draft']) if a else {},modules=MODULES,audiences=AUDIENCES,perms=permissions(),history=r.rows('SELECT id,version,action,actor,at,note FROM km_history WHERE article=? ORDER BY id DESC',(aid,)) if aid else [])
 @bp.post(r.PREFIX+'/knowledge/admin/save')
 def save():
  require('edit');aid=request.form.get('id');data={k:request.form.get(k,'').strip() for k in FIELDS}
  if data['module'] not in MODULES or data['audience'] not in AUDIENCES:abort(400,'Choose a valid module and audience.')
  if any(not data[k] for k in FIELDS) or any(len(v)>6000 for v in data.values()) or len(data['title'])>160 or len(data['stage'])>160:abort(400,'Complete every field; keep guidance concise (maximum 6000 characters per field).')
  actor=g.user['sub'];now=r.stamp();content=json.dumps({**data,**governance(request.form)})
  with r.db() as c:
   c.execute('BEGIN IMMEDIATE')
   if aid:
    a=c.execute('SELECT * FROM km_articles WHERE id=?',(aid,)).fetchone()
    if not a:abort(404)
    if request.form.get('version')!=str(a['version']):abort(409,'Guidance changed. Reload before saving.')
    previous=json.loads(a['draft']);content=json.dumps({**data,**reference_metadata(previous),**governance(request.form,previous)});version=a['version']+1;c.execute("UPDATE km_articles SET module=?,stage=?,audience=?,draft=?,version=?,status='draft',author=?,reviewer=NULL,review_note='',updated=? WHERE id=?",(data['module'],data['stage'],data['audience'],content,version,actor,now,aid))
   else:
    import secrets
    slug=re.sub('[^a-z0-9]+','-',data['title'].lower()).strip('-')+'-'+secrets.token_hex(4)
    aid=c.execute("INSERT INTO km_articles(slug,module,stage,audience,draft,version,status,author,updated) VALUES(?,?,?,?,?,1,'draft',?,?)",(slug,data['module'],data['stage'],data['audience'],content,actor,now)).lastrowid
   a=dict(c.execute('SELECT * FROM km_articles WHERE id=?',(aid,)).fetchone());history(c,a,'saved')
  return redirect(r.PREFIX+'/knowledge/admin/'+str(aid))
 @bp.post(r.PREFIX+'/knowledge/admin/<int:aid>/<action>')
 def transition(aid,action):
  if action not in ['submit','review','return','publish','archive','restore']:abort(404)
  require('review' if action in ['review','return'] else 'publish' if action in ['publish','archive','restore'] else 'edit')
  note=request.form.get('reason','').strip()
  if len(note)>2000 or (action=='return' and len(note)<10):abort(400,'Provide a useful return reason (10–2000 characters).')
  with r.db() as c:
   c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM km_articles WHERE id=?',(aid,)).fetchone()
   if not row:abort(404)
   a=dict(row);actor=g.user['sub']
   if request.form.get('version')!=str(a['version']):abort(409,'Guidance changed. Reload before continuing.')
   allowed={'submit':['draft'],'review':['in_review'],'return':['in_review'],'publish':['reviewed'],'archive':['published','draft','in_review','reviewed'],'restore':['archived']}
   if a['status'] not in allowed[action]:abort(409,'This action is not available in the current status.')
   if action in ['review','return'] and a['author']==actor:abort(403,'A different staff member must review your guidance.')
   if action=='publish' and (not a['reviewer'] or a['reviewer']==a['author']):abort(403,'An independent review is required before publication.')
   if action=='publish':c.execute("UPDATE km_articles SET published=draft,published_version=version,status='published',updated=? WHERE id=?",(r.stamp(),aid))
   else:
    status={'submit':'in_review','review':'reviewed','return':'draft','archive':'archived','restore':'draft'}[action]
    c.execute('UPDATE km_articles SET status=?,reviewer=?,updated=? WHERE id=?',(status,actor if action=='review' else None,r.stamp(),aid))
    if action=='restore':c.execute('UPDATE km_articles SET published=NULL,published_version=NULL WHERE id=?',(aid,))
   if action in ['review','return']:c.execute('UPDATE km_articles SET review_note=? WHERE id=?',(note,aid))
   history(c,a,action,note)
  return redirect(r.PREFIX+'/knowledge/admin/'+str(aid))
 @bp.get(r.PREFIX+'/knowledge/admin/<int:aid>/history/<int:hid>')
 def revision(aid,hid):
  require('edit');row=r.one('SELECT * FROM km_history WHERE article=? AND id=?',(aid,hid))
  if not row:abort(404)
  return r.page('knowledge-revision.html',revision=row,content=json.loads(row['content']),article=r.one('SELECT * FROM km_articles WHERE id=?',(aid,)),perms=permissions())
 @bp.post(r.PREFIX+'/knowledge/admin/<int:aid>/restore-version/<int:hid>')
 def restore_version(aid,hid):
  require('edit')
  with r.db() as c:
   c.execute('BEGIN IMMEDIATE');a=c.execute('SELECT * FROM km_articles WHERE id=?',(aid,)).fetchone();old=c.execute('SELECT * FROM km_history WHERE article=? AND id=?',(aid,hid)).fetchone()
   if not a or not old:abort(404)
   if request.form.get('version')!=str(a['version']):abort(409,'Guidance changed. Reload before restoring.')
   content=json.loads(old['content']);c.execute("UPDATE km_articles SET module=?,stage=?,audience=?,draft=?,version=version+1,status='draft',author=?,reviewer=NULL,review_note='',updated=? WHERE id=?",(content['module'],content['stage'],content['audience'],old['content'],g.user['sub'],r.stamp(),aid))
   if a['status']=='archived':c.execute('UPDATE km_articles SET published=NULL,published_version=NULL WHERE id=?',(aid,))
   history(c,dict(c.execute('SELECT * FROM km_articles WHERE id=?',(aid,)).fetchone()),'restore_version')
  return redirect(r.PREFIX+'/knowledge/admin/'+str(aid))
 r.knowledge_readable=readable
 r.knowledge_published=published
 r.app.register_blueprint(bp)
