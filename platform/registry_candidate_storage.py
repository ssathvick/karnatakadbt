"""Real S3 storage constrained to an isolated migration-canary bucket."""
import datetime,hashlib,uuid
from minio import Minio

class CandidateS3Storage:
    def __init__(self,settings,namespace='candidate'):
        self.bucket=settings['bucket']
        if not self.bucket.startswith('kdbt-registry-canary-') or namespace not in {'candidate','reference'}:
            raise ValueError('Only the isolated migration object namespace is allowed')
        self.namespace=namespace
        self.client=Minio(settings['endpoint'],access_key=settings['access_key'],secret_key=settings['secret_key'],secure=False,region='us-east-1')
        self.public=Minio(settings.get('public_endpoint','minio-api.localhost:8443'),access_key=settings['access_key'],secret_key=settings['secret_key'],secure=True,region='us-east-1')
    def key(self,store_id,bucket):
        bucket=getattr(bucket,'value',bucket)
        if bucket not in {'default','templates','documents','data_import_files','export-files'}:raise ValueError('Unknown logical bucket')
        return self.namespace+'/'+bucket+'/'+hashlib.sha256(store_id.encode()).hexdigest()
    def upload(self,data,length,bucket,content_type):
        store_id=str(uuid.uuid4());self.put_object(store_id,data,length,bucket,content_type)
        return store_id
    def put_object(self,store_id,data,length,bucket,content_type):
        self.client.put_object(self.bucket,self.key(store_id,bucket),data,length,content_type=content_type)
    def delete(self,store_id,bucket):self.client.remove_object(self.bucket,self.key(store_id,bucket))
    def get_url(self,store_id,bucket,expires=datetime.timedelta(hours=1)):
        headers={'response-content-disposition':'attachment'} if getattr(bucket,'value',bucket)=='data_import_files' else None
        return self.public.presigned_get_object(self.bucket,self.key(store_id,bucket),expires=expires,response_headers=headers)
    def get_bytes(self,store_id,bucket):
        result=self.client.get_object(self.bucket,self.key(store_id,bucket))
        try:return result.read()
        finally:result.close();result.release_conn()
