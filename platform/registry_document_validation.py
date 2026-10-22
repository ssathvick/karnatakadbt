"""Custom document filename, byte-size and MIME validation."""
import json
from pathlib import Path
import filetype
from registry_metadata_store import RegistryError

def validate_document(data,filename,bucket,client_type=None):
    profiles=json.loads(Path(__file__).with_name('registry_upload_profiles.json').read_text())
    if bucket not in profiles:raise RegistryError('REQ-VAL-000','Invalid document bucket')
    profile=profiles[bucket]
    if profile is None:return client_type or 'application/octet-stream'
    def fail(name,message):
        rule=json.loads(Path(__file__).with_name('registry_error_contract.json').read_text())[name]
        raise RegistryError(rule['code'],message)
    if not filename or not filename.strip():fail('INVALID_FILE_NAME','Filename is required.')
    name=filename.strip()
    if any(char in name for char in ['\0','/','\\']):fail('INVALID_FILE_NAME','Filename contains invalid characters.')
    if name.startswith('.') or name.endswith('.'):fail('INVALID_FILE_NAME','Filename must have a valid extension.')
    extension=next((ext for ext in sorted(profile['allowed_extensions'],key=len,reverse=True) if name.lower().endswith('.'+ext) and len(name)>len(ext)+1),None)
    if extension is None:fail('INVALID_FILE_TYPE',f"File extension is not allowed for '{name}'. Allowed: {', '.join(sorted(profile['allowed_extensions']))}.")
    if '.' in name[:-(len(extension)+1)]:fail('INVALID_FILE_NAME','Filename must contain exactly one allowlisted extension (multiple extensions are not allowed).')
    if not data:fail('INVALID_FILE_CONTENT','File content is empty.')
    size=len(data)
    if size>profile['max_bytes']:fail('FILE_TOO_LARGE',f"File size ({size} bytes) exceeds maximum of {profile['max_bytes']} bytes.")
    if profile['content_mode']=='text':
        try:data.decode('utf-8')
        except UnicodeDecodeError:fail('INVALID_FILE_CONTENT','Content must be valid UTF-8 text.')
        mime='application/json' if extension=='json' else 'text/plain'
    else:
        kind=filetype.guess(data)
        # A document extension alone is not evidence of PDF/image content.
        if kind is None:fail('INVALID_FILE_CONTENT','File content could not be identified as an allowed type.')
        mime=kind.mime.lower()
    if mime not in profile['allowed_mime_types']:fail('INVALID_FILE_TYPE',f"Detected file type '{mime}' is not allowed. Allowed MIME types: {', '.join(sorted(profile['allowed_mime_types']))}.")
    limit=profile['max_bytes_by_mime'].get(mime,profile['max_bytes'])
    if size>limit:fail('FILE_TOO_LARGE',f"File size ({size} bytes) exceeds maximum of {limit} bytes for MIME type '{mime}'.")
    return mime
