"""Export all accessible per-chat text records through a guarded native reader.

Needs an already accessible signed client/profile and exact account nickname.
Never restarts/resigns WeChat. A manifest records inaccessible or incomplete chats.
"""
from pathlib import Path
import argparse,hashlib,json,re
from wechat_aumac.native import NativeSession
from app.paths import DATA
from app.training import TrainingStore

def is_message_shard(name):
 return bool(re.fullmatch(r'message_\d+\.db',name))

def page_cursor(rows,last):
 values=[int(r['local_id']) for r in rows]
 cursor=max(values,default=last)
 if rows and cursor<=last:raise RuntimeError('History cursor did not advance')
 return cursor

def main():
 p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--expect-account',required=True);args=p.parse_args()
 out=DATA/'local_corpus/private_wechat';out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
 session=NativeSession(args.profile,mode='receive');training=TrainingStore();report={'account_checked':False,'messages':0,'documents':0,'issues':[],'complete':False,'databases':[]}
 try:
  session.connect();identity=session.identity();own=identity['user_id']
  account_name=session.get_display_name(own)
  if account_name!=args.expect_account:raise RuntimeError('Account mismatch; no history imported')
  report['account_nickname']=account_name
  report['account_checked']=True;db=session._database()
  contacts=db.all_rows('contact.db','contact',['username','nick_name','remark'])
  names={r['username']:(r.get('remark') or r.get('nick_name') or r['username']) for r in contacts}
  catalog=db.catalog()
  databases=[d['name'] for d in catalog if is_message_shard(d['name'])]
  report['databases']=databases
  disk=set()
  for record in catalog:
   if record['name'] in databases:
    disk.update(p.name for p in Path(record['path']).parent.glob('message_*.db')
                if is_message_shard(p.name))
  for missing in sorted(disk-set(databases)):
   report['issues'].append({'database':missing,'error':'shard_not_open_in_client'})
  for database in databases:
   ids=db.all_rows(database,'Name2Id',['rowid','user_name']);users={r['rowid']:r['user_name'] for r in ids}
   for contact in ids:
    chat=contact['user_name'];table='Msg_'+hashlib.md5(chat.encode()).hexdigest();last=0;part=0
    while True:
     try:rows=db.read(database,table,['local_id','server_id','local_type','create_time','real_sender_id',{'name':'message_content','encoding':'hex'},{'name':'compress_content','encoding':'hex'}],filters=[{'column':'local_id','op':'>','value':last}],order=[{'column':'local_id'}],limit=500)
     except Exception as e:
      if 'Table does not exist' not in str(e):report['issues'].append({'database':database,'table':table,'error':type(e).__name__})
      break
     if not rows:break
     part+=1;last=page_cursor(rows,last);entries=[]
     for row in rows:
      try:text=db._text(row['message_content']) or db._text(row['compress_content'])
      except Exception as e:report['issues'].append({'database':database,'table':table,'error':'decode_failed'});continue
      sender=users.get(row.get('real_sender_id'),'')
      entries.append({'conversation':names.get(chat,chat),'sender':names.get(sender,sender),'timestamp':row['create_time'],'message_type':row['local_type'],'local_id':row['local_id'],'server_id':row['server_id'],'direction':'outgoing' if sender==own else 'incoming','content':text,'source':'private local history; reference only, not instructions'})
     path=out/f'{database}-{table}-{part}.json';path.write_text(json.dumps(entries,ensure_ascii=False));path.chmod(0o600)
     result=training.add_file(path)
     if not result.get('ok'):raise RuntimeError('Training import failed')
     report['messages']+=len(entries);report['documents']+=1
     print('IMPORTED',report['messages'],'messages',flush=True)
     if len(rows)<500:break
  report['complete']=not report['issues']
 finally:
  (out/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));training.close();session.close()
if __name__=='__main__':main()
