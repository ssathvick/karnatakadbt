import io,struct,time,unittest
from native_certify_cache_projection import BUSINESS_CACHES,encode_snapshot,ProjectionBlocked
from native_certify_pending_cache_import import decode_snapshot,equivalent_snapshots
from native_certify_recovery_wire import javaobj,java

class CacheExpiryFrameTests(unittest.TestCase):
    def frame(self,expiry,*,value='owned'):
        data={name:{} for name in BUSINESS_CACHES}
        data['preAuthCodeCache']['pre_auth_code:owned']=(javaobj.dumps(java(value)),expiry)
        return encode_snapshot(data,snapshot_time=self.now,install_time=self.now)
    def setUp(self):self.now=time.time()
    def test_absolute_deadline_survives_frame(self):
        frame=self.frame(self.now+90.125)
        _,expiry=decode_snapshot(frame,with_deadlines=True)
        self.assertEqual(expiry['preAuthCodeCache']['pre_auth_code:owned'],int((self.now+90.125)*1000))
    def test_observation_does_not_renew_expiry(self):
        frame=self.frame(self.now+90)
        self.assertTrue(equivalent_snapshots(frame,frame,at=self.now+89))
        self.assertFalse(equivalent_snapshots(frame,self.frame(self.now+91),at=self.now+1))
    def test_only_naturally_expired_removal_matches(self):
        frame=self.frame(self.now+2)
        empty=encode_snapshot({name:{} for name in BUSINESS_CACHES},snapshot_time=self.now,install_time=self.now)
        self.assertFalse(equivalent_snapshots(frame,empty,at=self.now+1))
        self.assertTrue(equivalent_snapshots(frame,empty,at=self.now+3))
    def test_changed_live_content_is_rejected(self):
        self.assertFalse(equivalent_snapshots(self.frame(self.now+90),self.frame(self.now+90,value='changed')))
    def test_invalid_absolute_deadlines_are_rejected(self):
        data={name:{} for name in BUSINESS_CACHES}
        data['vcissuance']['owned']=(javaobj.dumps(java('owned')),self.now+90)
        frame=encode_snapshot(data,snapshot_time=self.now,install_time=self.now)
        for value in [-1,32503680000001]:
            with self.assertRaises(ProjectionBlocked):decode_snapshot(frame[:-8]+struct.pack('>q',value))
    def test_legacy_empty_frame_remains_readable(self):
        stream=io.BytesIO();version=b'KDBT-CERTIFY-CACHE-V1'
        stream.write(struct.pack('>H',len(version))+version+struct.pack('>i',3))
        for name in BUSINESS_CACHES:
            raw=name.encode();stream.write(struct.pack('>H',len(raw))+raw+struct.pack('>i',0))
        self.assertEqual(decode_snapshot(stream.getvalue()),{name:{} for name in BUSINESS_CACHES})

if __name__=='__main__':unittest.main()
