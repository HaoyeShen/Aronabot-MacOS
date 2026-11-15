"""Native integer strings paginate numerically; indexes are not missing message shards."""
from scripts.import_native_history import page_cursor,is_message_shard

def main():
 assert page_cursor([{'local_id':'999'},{'local_id':'1000'}],0)==1000
 assert page_cursor([{'local_id':'9999'},{'local_id':'10000'}],1000)==10000
 assert page_cursor([],123)==123
 try:page_cursor([{'local_id':'1000'}],1000)
 except RuntimeError:pass
 else:raise AssertionError('nonadvancing page must fail rather than repeat records')
 for name in ['message_0.db','message_12.db']:assert is_message_shard(name)
 for name in ['message_fts.db','message_resource.db','contact.db','message_0.db-wal']:
  assert not is_message_shard(name)
 print('HISTORY PAGINATION AND SHARD INVENTORY TESTS PASSED')
if __name__=='__main__':main()
