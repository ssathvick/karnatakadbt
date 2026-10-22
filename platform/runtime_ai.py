"""A source-grounded fallback when the optional local language model is offline."""
import json
import requests
def configure(module):
 original=module.generate
 def generate(messages,schema):
  try:
   status=requests.get(module.ENDPOINT+'/api/tags',timeout=1)
   if status.ok and any(x.get('name')==module.MODEL for x in status.json().get('models',[])):
    result=original(messages,schema);result['_mode']='local_model';return result
  except (requests.RequestException,ValueError):pass
  payload=json.loads(messages[-1]['content']);guides=payload.get('published_guidance',[])
  if isinstance(guides,str):guides=json.loads(guides)
  if 'answer' in schema.get('properties',{}):
   if not guides:return {'answer':'No published guidance matches. Ask an authorised staff member.','source_ids':[],'_mode':'retrieval'}
   kn=payload.get('response_language')=='kn'
   lead=('ಪ್ರಕಟಿತ ಮಾರ್ಗದರ್ಶನದಿಂದ ಪಡೆದ ಮಾಹಿತಿ (ಐಚ್ಛಿಕ ಸ್ಥಳೀಯ ಭಾಷಾ ಮಾದರಿ ಲಭ್ಯವಿಲ್ಲ).' if kn else 'Published guidance retrieval (the optional local language model is offline).')+'\n\n'
   answer='\n\n'.join(g['title']+'\n'+g.get('purpose','')+'\n'+g.get('steps','')+('\nಮುಂದಿನ ಹಂತ: ' if kn else '\nNext step: ')+g.get('next_step','') for g in guides[:2])
   return {'answer':lead+answer,'source_ids':[g['id'] for g in guides[:2]],'_mode':'retrieval'}
  if payload.get('response_language')=='kn':return {'title':'ಸಿಬ್ಬಂದಿಯ ದೃಢೀಕರಣಕ್ಕಾಗಿ KarnatakaDBT ಕರಡು','purpose':'[ಸಿಬ್ಬಂದಿ ದೃಢೀಕರಿಸಬೇಕು] '+payload.get('instructions','')[:500],'steps':'ಸಂಬಂಧಿತ ಪ್ರಕಟಿತ ಮಾರ್ಗದರ್ಶನ ಪರಿಶೀಲಿಸಿ.\nಕಾರ್ಯವಿಧಾನ ಮತ್ತು ಅನುಮತಿಗಳನ್ನು ದೃಢೀಕರಿಸಿ.\nಸ್ವತಂತ್ರ ಪರಿಶೀಲನೆಗೆ ಈ ಕರಡನ್ನು ಸಲ್ಲಿಸಿ.','requirements':'[ಸಿಬ್ಬಂದಿ ದೃಢೀಕರಿಸಬೇಕು] ಅಗತ್ಯ ದಾಖಲೆಗಳು ಮತ್ತು ನಿಯೋಜಿತ ಪಾತ್ರ.','next_step':'ಉಳಿಸುವ ಮೊದಲು ಪ್ರತಿ ಕ್ಷೇತ್ರ ಪರಿಶೀಲಿಸಿ. ಈ ಮಾದರಿಯನ್ನು ಭಾಷಾ ಮಾದರಿಯಿಲ್ಲದೆ ಸಿದ್ಧಪಡಿಸಲಾಗಿದೆ.','issues':'[ಸಿಬ್ಬಂದಿ ದೃಢೀಕರಿಸಬೇಕು] ಪ್ರಕಟಿಸುವ ಮೊದಲು ತಿಳಿಯದ ಸಂಗತಿಗಳನ್ನು ದೃಢೀಕರಿಸಬೇಕು.'}
  return {'title':'KarnatakaDBT draft for staff confirmation','purpose':'[Staff to confirm] '+payload.get('instructions','')[:500],'steps':'1. Review the related published guidance.\n2. Confirm the target workflow and permissions.\n3. Submit this draft for independent review.','requirements':'[Staff to confirm] Required documents and assigned role.','next_step':'Review every field before saving. This template was prepared without a language model.','issues':'[Staff to confirm] Missing facts must be confirmed before publication.'}
 module.generate=generate
