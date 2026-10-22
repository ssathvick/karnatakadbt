"""Own Kafka publisher/consumer; commit offsets only after durable effects."""
import asyncio,base64,json
from native_audit_models import AuditEvent

class NativeAuditRuntime:
    def __init__(self,store,settings):
        self.store,self.settings=store,settings;self.producer=self.consumer=None;self.tasks=[];self.ready=False
    async def start(self):
        from aiokafka import AIOKafkaProducer,AIOKafkaConsumer
        config=self.settings['audit_manager'];kafka=config['kafka']
        self.store.initialize();self.store.maintain(pre_create_months=config['database']['partition_pre_create_months'],retention_months=config['database']['partition_retention_months'])
        self.producer=AIOKafkaProducer(bootstrap_servers=kafka['bootstrap_servers'],client_id=kafka.get('client_id','karnatakadbt-audit'),acks='all',compression_type='gzip')
        try:
            await self.producer.start()
            self.consumer=AIOKafkaConsumer(kafka['topic'],bootstrap_servers=kafka['bootstrap_servers'],group_id=kafka['consumer_group'],client_id=kafka.get('client_id','karnatakadbt-audit'),enable_auto_commit=False,auto_offset_reset=kafka.get('consumer',{}).get('auto_offset_reset','earliest'))
            await self.consumer.start()
        except Exception:
            if self.consumer:await self.consumer.stop()
            await self.producer.stop();raise
        self.ready=True;self.tasks=[asyncio.create_task(fn()) for fn in [self.publish,self.consume,self.maintain]]
    async def stop(self):
        self.ready=False
        for task in self.tasks:task.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True)
        if self.consumer:await self.consumer.stop()
        if self.producer:await self.producer.stop()
    async def _send(self,event):
        kafka=self.settings['audit_manager']['kafka']
        key=event.get('subject') or event['data']['actor']['id']
        await self.producer.send_and_wait(kafka['topic'],json.dumps(event,separators=(',',':')).encode(),key=key.encode())
    async def publish(self):
        while True:
            try:count=await self.store.publish_once(self._send)
            except Exception:count=0
            if not count:await asyncio.sleep(.25)
    async def consume_once(self,records):
        if not records:return 0
        events=[];bad=[]
        for partition,messages in records.items():
            for message in messages:
                try:events.append(AuditEvent.model_validate_json(message.value))
                except Exception:bad.append((partition,message))
        try:
            self.store.persist(events)
            for partition,message in bad:
                payload={'error_code':'INVALID_AUDIT_EVENT','topic':partition.topic,'partition':partition.partition,'offset':message.offset,'raw_base64':base64.b64encode(message.value).decode()}
                await self.producer.send_and_wait(self.settings['audit_manager']['kafka']['dlq_topic'],json.dumps(payload).encode())
            await self.consumer.commit({partition:messages[-1].offset+1 for partition,messages in records.items() if messages})
        except Exception:
            # getmany advances in-process positions even when commits fail.
            # Rewind every fetched partition so the next poll really retries.
            for partition,messages in records.items():
                if messages:self.consumer.seek(partition,messages[0].offset)
            raise
        return len(events)
    async def consume(self):
        maximum=self.settings['audit_manager']['kafka'].get('consumer',{}).get('batch_max_records',500)
        while True:
            try:
                records=await self.consumer.getmany(timeout_ms=1000,max_records=maximum)
                await self.consume_once(records)
            except Exception:await asyncio.sleep(1)
    async def maintain(self):
        config=self.settings['audit_manager']['database']
        while True:
            await asyncio.sleep(config.get('partition_check_interval_seconds',3600))
            try:self.store.maintain(pre_create_months=config['partition_pre_create_months'],retention_months=config['partition_retention_months'])
            except Exception:pass
